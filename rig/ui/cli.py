from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from ..actions.write import run as write_action
from ..bridge_client import ask_bridge
from ..commands.add import add_files
from ..commands.drop import drop_files
from ..commands.files import show_files
from ..service.file_system import read_attached_files
from ..service.prompt_builder import build_prompt

console = Console()
attached_files = []


def run():
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
            # Commands
            # --------------------

            if user_input.startswith("/add "):
                add_files(
                    user_input=user_input,
                    attached_files=attached_files,
                    console=console,
                )
                continue

            if user_input == "/files":
                show_files(
                    attached_files=attached_files,
                    console=console,
                )
                continue

            if user_input == "/drop all":
                drop_files(
                    user_input=user_input,
                    attached_files=attached_files,
                    console=console,
                )
                continue

            if user_input.startswith("/drop "):
                drop_files(
                    user_input=user_input,
                    attached_files=attached_files,
                    console=console,
                )
                continue

            # --------------------
            # /ask
            # --------------------

            if user_input.startswith("/ask "):
                question = user_input.split(
                    "/ask ",
                    1,
                )[1].strip()

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

            # --------------------
            # Code Mode
            # --------------------

            if not attached_files:
                console.print("[red]No files attached. Use /add filename.py[/red]")
                continue

            console.print("\n[yellow]Sending to AI Bridge...[/yellow]\n")

            project_files = read_attached_files(attached_files)

            prompt = build_prompt(
                user_input,
                project_files,
            )

            response = ask_bridge(prompt)

            print("\n" + "=" * 80)
            print("RAW RESPONSE")
            print("=" * 80)
            print(response)
            print("=" * 80 + "\n")

            updated_files = write_action(response)

            if not updated_files:
                console.print("[red]No files detected in response[/red]")
                continue

            for path in updated_files:
                console.print(f"[green]Updated:[/green] {path}")

        except KeyboardInterrupt:
            console.print("\n[yellow]Goodbye[/yellow]")
            break

        except Exception as e:
            console.print(f"\n[red]Error:[/red] {e}\n")
