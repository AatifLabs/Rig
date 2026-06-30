def show_files(
    attached_files: list[str],
    console,
):
    if not attached_files:
        console.print("[yellow]No files attached.[/yellow]")
        return

    console.print("\n[cyan]Attached files:[/cyan]")

    for i, file in enumerate(attached_files, start=1):
        console.print(f"{i}. {file}")
