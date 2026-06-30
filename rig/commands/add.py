from pathlib import Path

from rich.prompt import Prompt


def add_files(
    user_input: str,
    attached_files: list[str],
    console,
):
    project_root = Path.cwd()

    # --------------------
    # /add all
    # --------------------

    if user_input.strip() == "/add all":
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

        console.print(f"[green]Attached {len(added)} files.[/green]")
        console.print("[cyan]Use /files to inspect attached files.[/cyan]")

        return

    # --------------------
    # normal /add
    # --------------------

    filenames = user_input.split("/add ", 1)[1].strip().split()

    added = []

    for filename in filenames:
        matches = [match for match in project_root.rglob(filename) if match.is_file()]

        if len(matches) == 0:
            console.print(f"[red]File not found:[/red] {filename}")
            continue

        if len(matches) > 1:
            console.print(f"[red]Multiple matches found for:[/red] {filename}\n")

            for i, match in enumerate(matches, start=1):
                console.print(f"{i}. {match.relative_to(project_root)}")

            while True:
                choice = Prompt.ask(
                    "[cyan]Select file number (Enter to cancel)[/cyan]",
                    default="",
                ).strip()

                if choice == "":
                    break

                if choice.isdigit() and 1 <= int(choice) <= len(matches):
                    selected = matches[int(choice) - 1]

                    resolved_path = str(selected.relative_to(project_root))

                    if resolved_path not in attached_files:
                        attached_files.append(resolved_path)
                        added.append(resolved_path)

                    console.print(f"[green]Attached:[/green] {resolved_path}")

                    break

                console.print("[red]Invalid selection.[/red]")

            continue

        resolved_path = str(matches[0].relative_to(project_root))

        if resolved_path not in attached_files:
            attached_files.append(resolved_path)
            added.append(resolved_path)

    if added:
        console.print(f"[green]Attached:[/green] {' '.join(added)}")
