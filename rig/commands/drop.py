from pathlib import Path


def drop_all(attached_files: list[str]):
    dropped = attached_files.copy()
    attached_files.clear()
    return dropped


def drop_files(
    filenames: list[str],
    attached_files: list[str],
):
    dropped = []
    missing = []

    for target in filenames:
        matches = [
            file
            for file in attached_files
            if file == target or Path(file).name == target
        ]

        if not matches:
            missing.append(target)
            continue

        for file in matches:
            attached_files.remove(file)
            dropped.append(file)

    return dropped, missing
