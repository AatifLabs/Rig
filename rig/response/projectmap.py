from pathlib import Path

from ..service.project_map import generate_project_map


def run(protocol: dict) -> str:
    target = protocol.get("target", "").strip()
    root = Path(target) if target else Path.cwd()

    if not root.exists():
        return f"#projectmap: path not found: {target}"

    return generate_project_map(root)
