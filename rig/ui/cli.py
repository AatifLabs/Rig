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

# Tracks whether each mode's session has already received its system
# prompt. "code" starts True because bridge.py eagerly creates and the
# first turn in code mode still needs to send the prompt once — so this
# starts False for both; only rig-start's browser-tab creation is eager,
# not the system-prompt send. The prompt is sent on first USE, not boot.
sessions_initialized = {
    "code": False,
    "ask": False,
}


def prompt_label() -> str:
    return "Ask" if get_mode() == "ask" else "Rig"


def handle_protocol(protocol: dict):
    """
    Validate, dispatch and display a single parsed protocol.
    Returns the dispatch result dict (or None if it wasn't dispatched),
    so callers can inspect "continuity" afterward.
    """

    if not protocol_exists(protocol["protocol"]):
        console.print(f"[red]Unknown protocol:[/red] {protocol['protocol']}")
        return None

    if not validate(protocol):
        console.print(
            f"[red]Protocol not permitted in {get_mode()} mode:[/red] "
            f"{protocol['protocol']}"
        )
        return None

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

    return result


def run_ai_turn(prompt: str):
    """
    Sends `prompt` to the AI (in whatever mode/session is currently
    active), processes every protocol in the response, and — if any
    dispatched protocol has continuity=True — automatically feeds those
    results back to the AI as the next turn, without waiting for the
    human. Recurses until a turn produces no continuity=True protocols,
    at which point control returns to the human prompt loop.

    Every call — including this recursive follow-up — targets the same
    session_id (the mode active when the turn started), and never
    re-sends the system prompt, since by definition the session was
    already initialized to get here.
    """

    session_id = get_mode()

    console.print("\n[yellow]Sending to AI Bridge...[/yellow]\n")

    response = ask_bridge(prompt, session_id=session_id)

    protocols = parse_protocols(response)

    if not protocols:
        console.print("[red]No protocol detected.[/red]")
        return

    continuity_results = []

    for protocol in protocols:
        result = handle_protocol(protocol)

        if result is not None and result.get("continuity"):
            continuity_results.append(
                f"[{result['protocol']} result]\n{result['result']}"
            )

    if continuity_results:
        followup_prompt = "\n\n".join(continuity_results)
        run_ai_turn(followup_prompt)


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
            # Pure pointer switch. No network call, no reset, no system
            # prompt sent here — that only happens lazily on the next
            # actual turn if this mode's session hasn't been initialized
            # yet (see sessions_initialized below).

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
            # Resets ONLY the current mode's session on the bridge side,
            # and marks it uninitialized so the next turn in this mode
            # sends the system prompt fresh again. The other mode's
            # session is completely untouched.
            #
            # NOTE: attached_files is intentionally left untouched here.
            # /clear only resets the AI conversation state, not Rig's own
            # file-attachment context. If you want /clear to also drop
            # attached files, add `attached_files.clear()` below.

            if user_input == "/clear":
                session_id = get_mode()
                console.print(f"[yellow]Clearing {session_id} session...[/yellow]")

                ok = clear_session(session_id=session_id)

                if ok:
                    sessions_initialized[session_id] = False
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
            #
            # System prompt is included only if this mode's session has
            # not been initialized yet. After sending, it's marked
            # initialized so subsequent turns in this mode never resend
            # it — until /clear flips it back to False.
            # --------------------

            session_id = get_mode()
            include_system_prompt = not sessions_initialized[session_id]

            project_files = read_attached_files(attached_files) if attached_files else []

            prompt = build_prompt(
                get_prompt(),
                user_input,
                project_files,
                include_system_prompt=include_system_prompt,
            )

            if include_system_prompt:
                sessions_initialized[session_id] = True

            run_ai_turn(prompt)

        except KeyboardInterrupt:
            console.print("\n[yellow]Goodbye[/yellow]")
            break

        except Exception as e:
            console.print(f"\n[red]Error:[/red] {e}\n")
