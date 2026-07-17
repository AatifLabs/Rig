from pathlib import Path


def read_attached_files(paths):
    files = []
    for path in paths:
        try:
            content = Path(path).read_text()
            files.append({"path": path, "content": content})
        except Exception as e:
            print(f"Failed to read {path}: {e}")
    return files


def write_file(path, content):
    file_path = Path(path)

    # Create parent directories if needed.
    file_path.parent.mkdir(parents=True, exist_ok=True)

    file_path.write_text(content)


def read_files(paths):
    """
    Attempts to read each given path.
    Returns (valid, invalid):
      - valid: list of {"path": ..., "content": ...} dicts
      - invalid: list of path strings that failed to read
    Unlike read_attached_files(), this does not silently print
    and drop failures — callers (e.g. the read protocol) need to
    report exactly which requested files were invalid.
    """
    valid = []
    invalid = []

    for path in paths:
        try:
            content = Path(path).read_text()
            valid.append({"path": path, "content": content})
        except Exception:
            invalid.append(path)

    return valid, invalid
