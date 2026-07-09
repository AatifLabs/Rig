from pathlib import Path

IGNORE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    ".idea",
    ".vscode",
}


def add_all(
    attached_files: list[str],
):
    project_root = Path.cwd()

    added = []

    for file in project_root.rglob("*"):
        if not file.is_file():
            continue

        if any(part in IGNORE_DIRS for part in file.parts):
            continue

        rel_path = str(file.relative_to(project_root))

        if rel_path not in attached_files:
            attached_files.append(rel_path)
            added.append(rel_path)

    return added


def add_file(
    filename: str,
):
    project_root = Path.cwd()

    matches = [match for match in project_root.rglob(filename) if match.is_file()]

    return matches


def attach_file(
    path: Path,
    attached_files: list[str],
):
    project_root = Path.cwd()

    resolved_path = str(path.relative_to(project_root))

    if resolved_path not in attached_files:
        attached_files.append(resolved_path)
        return resolved_path

    return None
