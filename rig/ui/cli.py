from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import InMemoryHistory
from ..protocol.registry import get, get_continuity, get_confirmation, exists as protocol_exists
from ..service.project_map import generate_project_map
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
pending_context = None

VERSION = "1.2"

# Tracks whether each mode's session has already received its system
# prompt. "code" starts True because bridge.py eagerly creates and the
# first turn in code mode still needs to send the prompt once — so this
# starts False for both; only rig-start's browser-tab creation is eager,
# not the system-prompt send. The prompt is sent on first USE, not boot.
sessions_initialized = {
    "code": False,
    "ask": False,
}

# --------------------
# Command metadata — single source of truth for /help and autocomplete
# --------------------
COMMANDS = [
    ("/help", "Show all available commands"),
    ("/ask", "Switch to Ask mode (read-only session)"),
    ("/code", "Switch to Code mode (file writes allowed)"),
    ("/clear", "Reset the current mode's AI session"),
    ("/add", "Attach a file to context — /add <filename>"),
    ("/add all", "Attach every discoverable file to context"),
    ("/files", "List currently attached files"),
    ("/drop", "Remove a file from context — /drop <filename>"),
    ("/drop all", "Remove all attached files from context"),
    ("/projectmap", "Generate a project map for the next message only"),
    ("exit", "Exit Rig"),
    ("quit", "Exit Rig"),
]

# Status message + icon shown while a protocol is being dispatched /
# rendered. Falls back to a generic entry if a protocol isn't listed.
PROTOCOL_UI = {
    "read": {"status": "Reading files...", "icon": "📖"},
    "write": {"status": "Writing changes...", "icon": "✍️"},
    "grep": {"status": "Searching codebase...", "icon": "🔍"},
    "terminal": {"status": "Executing command...", "icon": "💻"},
    "gitdiff": {"status": "Computing diff...", "icon": "🔀"},
    "projectmap": {"status": "Mapping project...", "icon": "🗺️"},
    "chat": {"status": "Thinking...", "icon": "💬"},
    "askuser": {"status": "Waiting on input...", "icon": "❓"},
}
DEFAULT_PROTOCOL_UI = {"status": "Processing...", "icon": "⚙️"}


class CommandCompleter(Completer):
    """
    Popup autocomplete for slash-commands (and bare exit/quit). Only
    activates once the user starts typing "/" — mirrors typing "/" in
    Slack/Discord-style command palettes.
    """

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

        if text == "" or text.startswith("/"):
            for cmd, desc in COMMANDS:
                if cmd.startswith(text):
                    yield Completion(
                        cmd[len(text):],
                        start_position=0,
                        display=cmd,
                        display_meta=desc,
                    )


prompt_session = PromptSession(
    history=InMemoryHistory(),
    completer=CommandCompleter(),
    complete_while_typing=True,
)


def prompt_label() -> str:
    return "Ask" if get_mode() == "ask" else "Rig"


def print_banner():
    console.print(
        Panel(
            f"[bold cyan]Rig v{VERSION}[/bold cyan]  "
            f"[dim]mode: {get_mode()}[/dim]",
            border_style="cyan",
        )
    )


def print_help():
    table = Table(title=f"Rig v{VERSION} — Commands", border_style="cyan")
    table.add_column("Command", style="bold cyan", no_wrap=True)
    table.add_column("Description", style="white")

    for cmd, desc in COMMANDS:
        table.add_row(cmd, desc)

    console.print(table)
    console.print(
        "[dim]Type[/dim] [cyan]/[/cyan] [dim]at any prompt to see a live "
        "command popup as you type.[/dim]"
    )


def print_error(title: str, message: str):
    console.print(
        Panel(
            message,
            title=f"[bold red]{title}[/bold red]",
            border_style="red",
        )
    )


def is_diff_like(text: str) -> bool:
    lines = text.splitlines()
    return any(
        line.startswith(("+++", "---", "@@", "+", "-"))
        for line in lines
    )


def render_diff(text: str) -> Text:
    """
    Colorizes unified-diff-style output line by line: additions green,
    removals red, hunk headers cyan, everything else dim default.
    """

    rendered = Text()

    for line in text.splitlines():
        if line.startswith(("+++", "---")):
            style = "bold cyan"
        elif line.startswith("@@"):
            style = "cyan"
        elif line.startswith("+"):
            style = "green"
        elif line.startswith("-"):
            style = "red"
        else:
            style = "white"

        rendered.append(line + "\n", style=style)

    return rendered

def format_feedback(protocol_name: str, status: str, detail: str = "") -> str:
    """
    Uniform envelope for every protocol outcome, so the AI can parse
    what happened at a glance regardless of protocol. Response-kind
    OK results carry their own native payload as `detail` (e.g. read's
    === FILES === blocks); everything else is a short reason.
    """
    header = f"[{protocol_name.upper()}:{status}]"
    if detail:
        return f"{header}\n{detail}"
    return header


def confirm_action(protocol: dict) -> tuple[bool, str]:
    """
    Shows the human what a confirmation-gated protocol is about to do
    and asks y/n. On decline, also asks for an optional free-text
    reason. Returns (accepted, reason) — reason is "" when accepted
    or left blank on decline.
    """
    target = protocol.get("target", "")
    payload = protocol.get("payload", "")

    console.print(
        Panel(
            payload if payload else "[dim](no content)[/dim]",
            title=f"✍️  [yellow]Confirm write → {target}[/yellow]",
            border_style="yellow",
        )
    )

    answer = prompt_session.prompt(
        HTML(f"<ansiyellow><b>Accept this write to {target}? (y/n)</b></ansiyellow> ")
    ).strip().lower()

    if answer == "y":
        return True, ""

    reason = prompt_session.prompt(
        HTML("<ansiyellow>Reason (optional, Enter to skip)</ansiyellow> ")
    ).strip()

    return False, reason

def handle_protocol(protocol: dict):
    """
    Validate, (optionally) confirm, dispatch and display a single
    parsed protocol. Always returns a result dict with "continuity" —
    every outcome loops back to the AI except protocols explicitly
    declared continuity=False (currently only chat/askuser).
    """

    name = protocol["protocol"]
    ui = PROTOCOL_UI.get(name, DEFAULT_PROTOCOL_UI)

    if not protocol_exists(name):
        print_error("Unknown Protocol", f"'{name}' is not a recognized protocol.")
        return {
            "protocol": name,
            "status": "INVALID",
            "result": format_feedback(
                name, "INVALID",
                f"'{name}' is not a recognized protocol. Check the name and try again.",
            ),
            "continuity": True,
        }

    if not validate(protocol):
        print_error(
            "Protocol Not Permitted",
            f"'{name}' is not allowed in [bold]{get_mode()}[/bold] mode.",
        )
        return {
            "protocol": name,
            "status": "UNAUTHORIZED",
            "result": format_feedback(
                name, "UNAUTHORIZED",
                f"'{name}' exists but is not permitted in {get_mode()} mode.",
            ),
            "continuity": True,
        }

    if get_confirmation(name):
        accepted, reason = confirm_action(protocol)

        if not accepted:
            console.print(f"[red]✘ Rejected:[/red] {protocol.get('target', name)}")

            detail_lines = [
                "User denied.",
                f"target: {protocol.get('target', '')}",
            ]
            if reason:
                detail_lines.append(f"reason: {reason}")

            return {
                "protocol": name,
                "status": "REJECTED",
                "result": format_feedback(name, "REJECTED", "\n".join(detail_lines)),
                "continuity": get_continuity(name),
            }

    with console.status(f"[cyan]{ui['status']}[/cyan]", spinner="dots"):
        result = dispatch(protocol)

    if result["kind"] == "action":
        console.print(f"[green]✔ Updated:[/green] {result['result']}")
        feedback = format_feedback(name, "OK", f"Successfully written to {result['result']}")
    else:
        result_text = result["result"]
        body = render_diff(result_text) if is_diff_like(result_text) else result_text

        console.print(
            Panel(
                body,
                title=f"{ui['icon']} [cyan]{result['protocol'].capitalize()}[/cyan]",
                border_style="cyan",
            )
        )
        feedback = format_feedback(name, "OK", result_text)

    return {
        "protocol": name,
        "status": "OK",
        "result": feedback,
        "continuity": result["continuity"],
    }

def run_ai_turn(prompt: str, origin: str = "human"):
    """
    Sends `prompt` to the AI (in whatever mode/session is currently
    active), processes every protocol in the response, and — if any
    dispatched protocol has continuity=True — automatically feeds those
    results back to the AI as the next turn, without waiting for the
    human. Recurses until a turn produces no continuity=True protocols,
    at which point control returns to the human prompt loop.

    `origin` labels *why* this particular turn is happening, purely for
    console visibility — it has no effect on dispatch logic. "human" is
    a real person typing; "feedback" is Rig auto-forwarding a protocol
    result the AI needs to react to; "recovery" is Rig nudging the AI
    after it failed to produce a usable protocol at all.

    Every call — including this recursive follow-up — targets the same
    session_id (the mode active when the turn started), and never
    re-sends the system prompt, since by definition the session was
    already initialized to get here.
    """
    session_id = get_mode()

    ORIGIN_UI = {
        "human":    ("[bold cyan]You → AI[/bold cyan]", "[yellow]Sending to AI Bridge...[/yellow]"),
        "feedback": ("[bold green]Rig → AI[/bold green] [dim](forwarding protocol result)[/dim]", "[yellow]Sending protocol feedback...[/yellow]"),
        "recovery": ("[bold yellow]Rig → AI[/bold yellow] [dim](retrying after failure)[/dim]", "[yellow]Asking AI to retry...[/yellow]"),
    }
    label, status_msg = ORIGIN_UI.get(origin, ORIGIN_UI["human"])
    console.print(label)

    with console.status(status_msg, spinner="dots"):
        response = ask_bridge(prompt, session_id=session_id)

    protocols = parse_protocols(response)

    if not protocols:
        print_error("No Protocol Detected", "The AI response contained no parseable protocol.")

        feedback = format_feedback(
            "response", "NO_PROTOCOL",
            "No protocol was detected in your last message. Either you "
            "didn't emit one, or the parser failed to recognize the format "
            "you used — check the syntax and try again.",
        )
        run_ai_turn(feedback, origin="recovery")
        return

    continuity_results = []

    for protocol in protocols:
        result = handle_protocol(protocol)

        if result and result.get("continuity"):
            continuity_results.append(result["result"])

    if continuity_results:
        followup_prompt = "\n\n".join(continuity_results)
        run_ai_turn(followup_prompt, origin="feedback")

def run():
    global pending_context

    print_banner()

    while True:
        try:
            user_input = prompt_session.prompt(
                HTML(f"<ansicyan><b>{prompt_label()}</b></ansicyan> ")
            ).strip()

            if user_input.lower() in ["exit", "quit"]:
                console.print("\n[yellow]Goodbye[/yellow]")
                break

            if not user_input:
                continue

            # --------------------
            # /help
            # --------------------

            if user_input == "/help":
                print_help()
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

                with console.status(f"[yellow]Clearing {session_id} session...[/yellow]", spinner="dots"):
                    ok = clear_session(session_id=session_id)

                if ok:
                    sessions_initialized[session_id] = False
                    console.print("[green]✔ Session cleared. Starting fresh.[/green]")
                else:
                    print_error(
                        "Session Clear Failed",
                        "Could not clear the session — the bridge may be unreachable.",
                    )

                continue

            # --------------------
            # /add
            # --------------------

            if user_input.startswith("/add "):
                if user_input.strip() == "/add all":
                    added = add_all(attached_files)

                    console.print(f"[green]✔ Attached {len(added)} files.[/green]")
                    console.print("[cyan]Use /files to inspect attached files.[/cyan]")

                    continue

                filenames = user_input.split("/add ", 1)[1].strip().split()

                added = []

                for filename in filenames:
                    matches = add_file(filename)

                    if len(matches) == 0:
                        print_error("File Not Found", filename)
                        continue

                    if len(matches) > 1:
                        console.print(
                            f"[yellow]Multiple matches found for:[/yellow] {filename}\n"
                        )

                        for i, match in enumerate(matches, start=1):
                            console.print(f"{i}. {match.relative_to(Path.cwd())}")

                        while True:
                            choice = prompt_session.prompt(
                                HTML("<ansicyan>Select file number (Enter to cancel)</ansicyan> ")
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
                                        f"[green]✔ Attached:[/green] {attached}"
                                    )

                                break

                            print_error("Invalid Selection", "Please enter a valid number.")

                        continue

                    attached = attach_file(
                        matches[0],
                        attached_files,
                    )

                    if attached:
                        added.append(attached)

                if added:
                    console.print(f"[green]✔ Attached:[/green] {' '.join(added)}")

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

                console.print("[green]✔ All files removed from context.[/green]")
                continue

            if user_input.startswith("/drop "):
                filenames = user_input.split("/drop ", 1)[1].strip().split()

                dropped, missing = drop_files(
                    filenames,
                    attached_files,
                )

                for file in dropped:
                    console.print(f"[green]✔ Dropped:[/green] {file}")

                for file in missing:
                    print_error("File Not Attached", file)

                continue

            # --------------------
            # /projectmap
            # --------------------
            # One-shot context injection. Generates the map immediately,
            # stores it in `pending_context`, and does NOT talk to the AI.
            # It rides along with the *next* user prompt only, then is
            # cleared — nothing persists, nothing touches attached_files,
            # nothing is written to disk.

            if user_input == "/projectmap" or user_input.startswith("/projectmap "):
                target = user_input[len("/projectmap"):].strip()
                root = Path(target) if target else Path.cwd()

                if not root.exists():
                    print_error("Path Not Found", target)
                    continue

                with console.status("[cyan]Mapping project...[/cyan]", spinner="dots"):
                    pending_context = generate_project_map(root)

                console.print(
                    "[green]✔ Project map ready[/green] — it will be included "
                    "with your next message only."
                )

                continue

            # --------------------
            # New execution pipeline
            # build_prompt -> ask_bridge -> parse_protocols -> validate -> dispatch
            # --------------------

            session_id = get_mode()
            include_system_prompt = not sessions_initialized[session_id]

            project_files = read_attached_files(attached_files) if attached_files else []

            prompt = build_prompt(
                get_prompt(),
                user_input,
                project_files,
                include_system_prompt=include_system_prompt,
                pending_context=pending_context,
            )

            pending_context = None  # cleared before send, never survives past this point

            if include_system_prompt:
                sessions_initialized[session_id] = True

            run_ai_turn(prompt)

        except KeyboardInterrupt:
            console.print("\n[yellow]Goodbye[/yellow]")
            break

        except EOFError:
            console.print("\n[yellow]Goodbye[/yellow]")
            break

        except Exception as e:
            print_error(type(e).__name__, str(e))
