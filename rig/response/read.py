from ..service.file_system import read_files


def run(protocol: dict) -> str:
    """
    Handles: #read: hi.py super.py main.py backend.py
    protocol["target"] == "hi.py super.py main.py backend.py"

    Output format matches the same === FILE === / === END FILE ===
    convention used in build_prompt for attached files, so read
    results look consistent with everything else the AI sees.
    """
    filenames = protocol.get("target", "").split()

    if not filenames:
        return "No files specified for #read."

    valid, invalid = read_files(filenames)

    lines = []

    lines.append(f"Requested files: {len(filenames)}")
    lines.append(f"Denied files: {len(invalid)}")

    if invalid:
        lines.append("Denied (not found): " + ", ".join(invalid))

    lines.append("")
    lines.append("=== FILES ===")

    for f in valid:
        lines.append("=== FILE ===")
        lines.append(f"filename: {f['path']}")
        lines.append(f['content'])
        lines.append("=== END FILE ===")

    lines.append("=== END FILES ===")

    return "\n".join(lines)
