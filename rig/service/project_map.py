#!/usr/bin/env python3
"""
project_map.py — Rig "Project Map" unit.

Walks a codebase and produces a compact STUB VIEW of every .py file:
class/function signatures + first-line docstrings, with bodies stripped
to `...`. Top-level executable code (if __name__, loose expressions,
with-blocks etc.) is dropped. Constants/imports are kept as-is.

This is deliberately shaped like a .pyi stub file, not a custom JSON
schema — the AI has already seen millions of these during pretraining,
so zero tokens are spent explaining the format. Rig then answers
`#read:path/to/file.py` requests with the real source when the AI
decides the stub isn't enough.

`generate_project_map()` is the pure, reusable core — it takes a root
and returns a string, nothing touches disk. The CLI `main()` below is
just a thin wrapper for standalone/manual use.
"""

import argparse
import ast
import os
import sys
from pathlib import Path

DEFAULT_EXCLUDES = {
    ".git", "__pycache__", "venv", ".venv", "env", "node_modules",
    ".mypy_cache", ".pytest_cache", "build", "dist", ".idea", ".vscode",
}


def is_docstring_expr(stmt) -> bool:
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


MAX_STR_LEN = 400  # literal strings longer than this get truncated, not embedded


def is_safe_leaf(node) -> bool:
    """A single leaf worth keeping verbatim: a literal (below MAX_STR_LEN
    for strings) OR a bare Name/Attribute reference (e.g. `write.run`,
    `coding`). Both cases reveal zero implementation but carry real
    structural signal."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str) and len(node.value) > MAX_STR_LEN:
            return False
        return True
    if isinstance(node, (ast.Name, ast.Attribute)):
        return True
    return False


def is_safe_to_keep(node) -> bool:
    """Recursively true if every leaf in this expression is either a plain
    literal or a bare reference — allowing MIXED structures like:
        PROTOCOLS = {"write": {"kind": "action", "handler": write.run}}
    where literal tags and callable references sit side by side in the
    same dict. Anything with actual computation (calls other than bare
    attribute access, comprehensions, operators, etc.) is rejected."""
    if is_safe_leaf(node):
        return True
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(is_safe_to_keep(e) for e in node.elts)
    if isinstance(node, ast.Dict):
        return all(
            (k is None or is_safe_to_keep(k)) and is_safe_to_keep(v)
            for k, v in zip(node.keys, node.values)
        )
    return False


def placeholder_for(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return ast.Constant(value=f"<{len(node.value)} char string>")
    return ast.Constant(value=Ellipsis)


def strip_func_body(node):
    """Keep decorators + signature + docstring, drop the rest -> `...`"""
    new_body = []
    if node.body and is_docstring_expr(node.body[0]):
        new_body.append(node.body[0])
    new_body.append(ast.Expr(value=ast.Constant(value=Ellipsis)))
    node.body = new_body
    return node


def strip_class_body(node):
    new_body = []
    if node.body and is_docstring_expr(node.body[0]):
        new_body.append(node.body[0])
    for stmt in node.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            new_body.append(strip_func_body(stmt))
        elif isinstance(stmt, ast.ClassDef):
            new_body.append(strip_class_body(stmt))
        elif isinstance(stmt, ast.AnnAssign):
            # class-level typed attribute, e.g. `name: str`
            if stmt.value is not None and not (is_safe_to_keep(stmt.value)):
                stmt.value = placeholder_for(stmt.value)
            new_body.append(stmt)
        elif isinstance(stmt, ast.Assign) and all(
            isinstance(t, ast.Name) for t in stmt.targets
        ):
            if not (is_safe_to_keep(stmt.value)):
                stmt.value = placeholder_for(stmt.value)
            new_body.append(stmt)
        # everything else (loose Expr, If, With, Try, For at class level) dropped
    if not new_body:
        new_body = [ast.Expr(value=ast.Constant(value=Ellipsis))]
    node.body = new_body
    return node


def strip_module(tree: ast.Module) -> ast.Module:
    new_body = []
    # module docstring
    if tree.body and is_docstring_expr(tree.body[0]):
        new_body.append(tree.body[0])
        rest = tree.body[1:]
    else:
        rest = tree.body
    for stmt in rest:
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            new_body.append(stmt)
        elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            new_body.append(strip_func_body(stmt))
        elif isinstance(stmt, ast.ClassDef):
            new_body.append(strip_class_body(stmt))
        elif isinstance(stmt, ast.AnnAssign):
            if stmt.value is not None and not (is_safe_to_keep(stmt.value)):
                stmt.value = placeholder_for(stmt.value)
            new_body.append(stmt)
        elif isinstance(stmt, ast.Assign) and all(
            isinstance(t, ast.Name) for t in stmt.targets
        ):
            if not (is_safe_to_keep(stmt.value)):
                stmt.value = placeholder_for(stmt.value)
            new_body.append(stmt)
        # drop: bare Expr calls, if __name__ blocks, with/try/for at module level
    tree.body = new_body
    return tree


def stub_source(source: str) -> str:
    tree = ast.parse(source)
    tree = strip_module(tree)
    ast.fix_missing_locations(tree)
    return ast.unparse(tree)


def find_py_files(root: Path, excludes: set[str]):
    if root.is_file():
        if root.suffix == ".py":
            yield root
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in excludes and not d.startswith(".")]
        for fname in filenames:
            if fname.endswith(".py"):
                yield Path(dirpath) / fname


def build_tree_view(files, root: Path) -> str:
    rels = sorted(str(f.relative_to(root)) for f in files)
    return "\n".join(f"  {r}" for r in rels)


def generate_project_map(root: Path, excludes: set[str] = None) -> str:
    """
    Pure core: walks `root`, returns the full stub-view string.
    No disk writes, no argparse, no stdout — just the string, so callers
    (the CLI, or the #projectmap: / /projectmap protocol handler) can do
    whatever they want with it in memory.
    """
    root = Path(root).resolve()
    excludes = set(DEFAULT_EXCLUDES) | (excludes or set())

    files = list(find_py_files(root, excludes))

    if not files:
        return f"No .py files found under {root}"

    base = root if root.is_dir() else root.parent

    out_chunks = []
    out_chunks.append("=== PROJECT STRUCTURE ===")
    out_chunks.append(build_tree_view(files, base))
    out_chunks.append("")

    for f in sorted(files):
        try:
            source = f.read_text(encoding="utf-8")
        except Exception as e:
            out_chunks.append(f"=== FILE STUBS: {f.relative_to(base)} ===\n# could not read: {e}\n")
            continue
        try:
            stub = stub_source(source)
        except SyntaxError as e:
            out_chunks.append(f"=== FILE STUBS: {f.relative_to(base)} ===\n# syntax error, skipped: {e}\n")
            continue

        out_chunks.append(f"=== FILE STUBS: {f.relative_to(base)} ===")
        out_chunks.append(stub)
        out_chunks.append("")

    return "\n".join(out_chunks)


def main():
    parser = argparse.ArgumentParser(description="Generate AST-based stub project map")
    parser.add_argument("path", help="File or directory to map")
    parser.add_argument("--out", default=None, help="Output file (default: stdout)")
    parser.add_argument("--exclude", default="", help="Comma-separated extra dir names to exclude")
    args = parser.parse_args()

    extra_excludes = {e.strip() for e in args.exclude.split(",") if e.strip()} if args.exclude else set()

    result = generate_project_map(args.path, excludes=extra_excludes)

    if args.out:
        Path(args.out).write_text(result, encoding="utf-8")
        print(f"Written to {args.out}", file=sys.stderr)
    else:
        print(result)


if __name__ == "__main__":
    main()
