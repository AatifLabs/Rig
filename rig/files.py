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

    Path(path).write_text(content)
