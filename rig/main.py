from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from .bridge_client import ask_bridge
from .files import read_attached_files, write_file
from .parser import parse_files
from .prompt_builder import build_prompt

console = Console()
attached_files = []


def main():
    console.print(
        Panel(
            "[bold cyan]Rig v0.1[/bold cyan]",
            border_style="cyan",
        )
    )

    while True:
        try:
            user_input = Prompt.ask("[bold cyan]Rig[/bold cyan]").strip()

            if user_input.lower() in ["exit", "quit"]:
                console.print("\n[yellow]Goodbye[/yellow]")
                break

            if not user_input:
                continue

            # --------------------
            # /add
            # --------------------

            if user_input.startswith("/add "):
                filenames = user_input.split("/add ", 1)[1].strip().split()

                project_root = Path.cwd()

                for filename in filenames:
                    exact_path = project_root / filename

                    if exact_path.exists():
                        resolved_path = str(exact_path.relative_to(project_root))

                    else:
                        matches = list(project_root.rglob(filename))

                        if len(matches) == 0:
                            console.print(f"[red]File not found:[/red] {filename}")
                            continue

                        if len(matches) > 1:
                            console.print(
                                f"[red]Multiple matches found for:[/red] {filename}"
                            )

                            for match in matches:
                                console.print(f"  - {match.relative_to(project_root)}")

                            console.print("[yellow]Use full path instead.[/yellow]")
                            continue

                        resolved_path = str(matches[0].relative_to(project_root))

                    if resolved_path not in attached_files:
                        attached_files.append(resolved_path)
                        console.print(f"[green]Attached:[/green] {resolved_path}")

                continue

            # --------------------
            # /files
            # --------------------

            if user_input == "/files":
                if not attached_files:
                    console.print("[yellow]No files attached.[/yellow]")
                    continue

                console.print("\n[cyan]Attached files:[/cyan]")

                for i, file in enumerate(attached_files, start=1):
                    console.print(f"{i}. {file}")

                continue

            # --------------------
            # /drop all
            # --------------------

            if user_input == "/drop all":
                attached_files.clear()

                console.print("[green]All files removed from context.[/green]")

                continue

            # --------------------
            # /drop filename
            # --------------------

            if user_input.startswith("/drop "):
                target = user_input.split("/drop ", 1)[1].strip()

                matches = [
                    file
                    for file in attached_files
                    if file == target or Path(file).name == target
                ]

                if not matches:
                    console.print(f"[red]File not attached:[/red] {target}")
                    continue

                for file in matches:
                    attached_files.remove(file)

                    console.print(f"[green]Dropped:[/green] {file}")

                continue

            # --------------------
            # /ask
            # --------------------

            if user_input.startswith("/ask "):
                question = user_input.split("/ask ", 1)[1].strip()

                if not question:
                    console.print("[red]Usage: /ask <question>[/red]")
                    continue

                console.print("\n[yellow]Asking AI Bridge...[/yellow]\n")

                if attached_files:
                    project_files = read_attached_files(attached_files)

                    prompt = (
                        "You are a helpful coding assistant. "
                        "Answer the following question about the codebase.\n\n"
                        f"Files:\n{build_prompt('', project_files)}\n\n"
                        f"Question: {question}"
                    )
                else:
                    prompt = (
                        "You are a helpful coding assistant. "
                        f"Answer this question:\n\n{question}"
                    )

                response = ask_bridge(prompt)

                console.print(
                    Panel(
                        response,
                        title="[cyan]Answer[/cyan]",
                        border_style="cyan",
                    )
                )

                continue

            if not attached_files:
                console.print("[red]No files attached. Use /add filename.py[/red]")
                continue

            console.print("\n[yellow]Sending to AI Bridge...[/yellow]\n")

            project_files = read_attached_files(attached_files)

            prompt = build_prompt(user_input, project_files)

            response = ask_bridge(prompt)

            parsed_files = parse_files(response)

            if not parsed_files:
                console.print("[red]No files detected in response[/red]")
                continue

            for file in parsed_files:
                write_file(file["path"], file["content"])

                console.print(f"[green]Updated:[/green] {file['path']}")

        except KeyboardInterrupt:
            console.print("\n[yellow]Goodbye[/yellow]")
            break

        except Exception as e:
            console.print(f"\n[red]Error:[/red] {e}\n")


if __name__ == "__main__":
    main()
