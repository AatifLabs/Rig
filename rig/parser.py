import re


def parse_files(response: str) -> list[dict]:
    # Pure regex scissors. No language stripping needed because the payload is pure code.
    pattern = r"#\s*filename:\s*(\S+?\.py)(.*?)(?=#\s*filename:|\Z)"
    matches = re.findall(pattern, response, re.DOTALL)

    files = []

    for path, content in matches:
        # Dedent if everything is over-indented
        lines = content.split("\n")
        non_empty = [l for l in lines if l.strip()]
        if non_empty:
            min_indent = min(len(l) - len(l.lstrip()) for l in non_empty)
            lines = [l[min_indent:] for l in lines]
        content = "\n".join(lines)

        files.append({"path": path.strip(), "content": content.strip()})

    return files
