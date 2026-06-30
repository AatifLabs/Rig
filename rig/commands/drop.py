from pathlib import Path


def drop_files(
    user_input: str,
    attached_files: list[str],
    console,
):
    # --------------------
    # /drop all
    # --------------------

    if user_input == "/drop all":
        attached_files.clear()

        console.print("[green]All files removed from context.[/green]")
        return

    # --------------------
    # /drop filename
    # --------------------

    target = user_input.split(
        "/drop ",
        1,
    )[1].strip()

    matches = [
        file for file in attached_files if file == target or Path(file).name == target
    ]

    if not matches:
        console.print(f"[red]File not attached:[/red] {target}")
        return

    for file in matches:
        attached_files.remove(file)
        console.print(f"[green]Dropped:[/green] {file}")
