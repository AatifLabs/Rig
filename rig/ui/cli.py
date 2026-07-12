from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from ..bridge_client import ask_bridge, clear_session
from ..commands.add import (
    add_all,
    add_file,
    attach_file,
)
from ..commands.drop import (
    drop_all,
    drop_files,
)
from ..commands.files import list_files
from ..mode.manager import (
    get_mode,
    set_mode,
    get_prompt,
    get_allowed_actions,
    get_allowed_responses,
)
from ..protocol.registry import exists as protocol_exists
from ..service.dispatcher import dispatch
from ..service.file_system import read_attached_files
from ..service.parser import parse_protocols
from ..service.prompt_builder import build_prompt
from ..service.validator import validate

console = Console()
attached_files = []


def prompt_label() -> str:
    return "Ask" if get_mode() == "ask" else "Rig"


def handle_protocol(protocol: dict):
    """
    Validate, dispatch and display a single parsed protocol.
    """

    if not protocol_exists(protocol["protocol"]):
        console.print(f"[red]Unknown protocol:[/red] {protocol['protocol']}")
        return

    if not validate(protocol):
        console.print(
            f"[red]Protocol not permitted in {get_mode()} mode:[/red] "
            f"{protocol['protocol']}"
        )
        return

    result = dispatch(protocol)

    if result["kind"] == "action":
        console.print(f"[green]Updated:[/green] {result['result']}")
    else:
        console.print(
            Panel(
                result["result"],
                title=f"[cyan]{result['protocol'].capitalize()}[/cyan]",
                border_style="cyan",
            )
        )


def run():
    console.print(
        Panel(
            "[bold cyan]Rig v0.1[/bold cyan]",
            border_style="cyan",
        )
    )

    while True:
        try:
            user_input = Prompt.ask(f"[bold cyan]{prompt_label()}[/bold cyan]").strip()

            if user_input.lower() in ["exit", "quit"]:
                console.print("\n[yellow]Goodbye[/yellow]")
                break

            if not user_input:
                continue

            # --------------------
            # /ask, /code (mode switching)
            # --------------------

            if user_input == "/ask":
                set_mode("ask")
                console.print("[cyan]Switched to Ask mode.[/cyan]")
                continue

            if user_input == "/code":
                set_mode("code")
                console.print("[cyan]Switched to Code mode.[/cyan]")
                continue

            # --------------------
            # /clear
            # --------------------
            # Resets the browser-side ChatGPT thread via the bridge, so the
            # next message starts a brand new session instead of continuing
            # the existing persistent chat.
            #
            # NOTE: attached_files is intentionally left untouched here.
            # /clear only resets the AI conversation state, not Rig's own
            # file-attachment context. If you want /clear to also drop
            # attached files, add `attached_files.clear()` below.

            if user_input == "/clear":
                console.print("[yellow]Clearing session...[/yellow]")

                ok = clear_session()

                if ok:
                    console.print("[green]Session cleared. Starting fresh.[/green]")
                else:
                    console.print(
                        "[red]Failed to clear session — bridge may be unreachable.[/red]"
                    )

                continue

            # --------------------
            # /add
            # --------------------

            if user_input.startswith("/add "):
                if user_input.strip() == "/add all":
                    added = add_all(attached_files)

                    console.print(f"[green]Attached {len(added)} files.[/green]")
                    console.print("[cyan]Use /files to inspect attached files.[/cyan]")

                    continue

                filenames = user_input.split("/add ", 1)[1].strip().split()

                added = []

                for filename in filenames:
                    matches = add_file(filename)

                    if len(matches) == 0:
                        console.print(f"[red]File not found:[/red] {filename}")
                        continue

                    if len(matches) > 1:
                        console.print(
                            f"[red]Multiple matches found for:[/red] {filename}\n"
                        )

                        for i, match in enumerate(matches, start=1):
                            console.print(f"{i}. {match.relative_to(Path.cwd())}")

                        while True:
                            choice = Prompt.ask(
                                "[cyan]Select file number (Enter to cancel)[/cyan]",
                                default="",
                            ).strip()

                            if choice == "":
                                break

                            if choice.isdigit() and 1 <= int(choice) <= len(matches):
                                attached = attach_file(
                                    matches[int(choice) - 1],
                                    attached_files,
                                )

                                if attached:
                                    added.append(attached)
                                    console.print(
                                        f"[green]Attached:[/green] {attached}"
                                    )

                                break

                            console.print("[red]Invalid selection.[/red]")

                        continue

                    attached = attach_file(
                        matches[0],
                        attached_files,
                    )

                    if attached:
                        added.append(attached)

                if added:
                    console.print(f"[green]Attached:[/green] {' '.join(added)}")

                continue

            # --------------------
            # /files
            # --------------------

            if user_input == "/files":
                files = list_files(attached_files)

                if not files:
                    console.print("[yellow]No files attached.[/yellow]")
                else:
                    console.print("\n[cyan]Attached files:[/cyan]")

                    for i, file in enumerate(files, start=1):
                        console.print(f"{i}. {file}")

                continue

            # --------------------
            # /drop
            # --------------------

            if user_input == "/drop all":
                drop_all(attached_files)

                console.print("[green]All files removed from context.[/green]")
                continue

            if user_input.startswith("/drop "):
                filenames = user_input.split("/drop ", 1)[1].strip().split()

                dropped, missing = drop_files(
                    filenames,
                    attached_files,
                )

                for file in dropped:
                    console.print(f"[green]Dropped:[/green] {file}")

                for file in missing:
                    console.print(f"[red]File not attached:[/red] {file}")

                continue

            # --------------------
            # New execution pipeline
            # build_prompt -> ask_bridge -> parse_protocols -> validate -> dispatch
            # /add is optional: empty attached_files is fine.
            # --------------------

            project_files = read_attached_files(attached_files) if attached_files else []

            prompt = build_prompt(
                get_prompt(),
                user_input,
                project_files,
            )

            console.print("\n[yellow]Sending to AI Bridge...[/yellow]\n")

            response = ask_bridge(prompt)

            protocols = parse_protocols(response)

            if not protocols:
                console.print("[red]No protocol detected.[/red]")
                continue

            for protocol in protocols:
                handle_protocol(protocol)

        except KeyboardInterrupt:
            console.print("\n[yellow]Goodbye[/yellow]")
            break

        except Exception as e:
            console.print(f"\n[red]Error:[/red] {e}\n")
