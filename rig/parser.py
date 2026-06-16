import re


def parse_files(response: str) -> list[dict]:

    # let it be in comment, it cause bugs, removing it will be hard to diagnose why that bug is there when this might solve an edge case
    # Disabled:
    # This corrupts valid Python strings such as:
    # file.write("\\n")
    # by converting escaped newlines into real newline characters.
    # Re-enable only if handling plain text instead of source code.

    # FINAL VERDICT : its useless, remove it
    # response = response.replace("\\n", "\n")

    pattern = r"#\s*filename:\s*(\S+?\.py)(.*?)(?=#\s*filename:|\Z)"
    matches = re.findall(pattern, response, re.DOTALL)

    files = []

    for path, content in matches:
        # Strip ONLY the leading "Language\nRun\n" UI chrome from ChatGPT
        # e.g. "Python\nRun\n" or "JavaScript\nRun\n"
        content = re.sub(r"^\s*[A-Za-z+#]+\s*\nRun\s*\n", "", content)

        # Dedent if everything is over-indented
        lines = content.split("\n")
        non_empty = [l for l in lines if l.strip()]
        if non_empty:
            min_indent = min(len(l) - len(l.lstrip()) for l in non_empty)
            lines = [l[min_indent:] for l in lines]
        content = "\n".join(lines)

        files.append({"path": path.strip(), "content": content.strip()})

    return files
