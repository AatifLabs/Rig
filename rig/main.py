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

            if user_input.startswith("/add "):
                paths = user_input.split("/add ", 1)[1].strip().split()

                for path in paths:
                    if path not in attached_files:
                        attached_files.append(path)
                        console.print(f"[green]Attached:[/green] {path}")

                continue

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
