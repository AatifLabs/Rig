"""
Claude.ai provider adapter.

Required interface (bridge/registry call these generically, never branch
on provider name anywhere else):
    async def send_message(page, text) -> None
    async def wait_until_done(page) -> None
    async def get_response(page) -> str
    async def is_ready(page) -> bool

Everything else in this file (URL, install_context, reset) is adapter-
specific plumbing the registry uses for initial navigation and /clear.

WHY THE PREVIOUS VERSION FAILED
--------------------------------
Claude's prompt box is a ProseMirror rich-text editor
(`div[contenteditable="true"].ProseMirror`), not a plain <textarea> like
ChatGPT's. The old code did:

    await page.fill(PROMPT_SELECTOR, text)

`page.fill()` sets the DOM value/text directly without firing the real
`beforeinput`/`keydown` events ProseMirror listens for to update its own
internal editor state. Result: the box visually looked "empty" to
Claude's frontend even after fill() ran, so the send button stayed
`aria-disabled="true"` (confirmed in the shared DOM dump: the button
carries `aria-disabled` + `data-trigger-disabled` attributes that gate
whether it's actually clickable) and clicking it silently did nothing.

Fix: instead of typing character-by-character (slow, laggy, and not how
the old GPT bridge worked — that used one-shot page.fill()), this
dispatches a single synthetic `paste` ClipboardEvent at the editor with
the full text in one call. ProseMirror-based editors implement their own
paste handler that reads `clipboardData` and converts plain text into
paragraphs (splitting on newlines) as part of that handler — so a
synthetic paste event is registered by ProseMirror's internal state just
like a real one, but happens instantly, in one call, matching the old
GPT bridge's "send everything at once" behavior instead of GPT's plain
<textarea>-only trick (fill()) which doesn't apply here. Then poll the
send button's aria-disabled state instead of just its visibility before
clicking — visible-but-disabled was exactly the old failure mode.

CONFIRMED VS BEST-GUESS SELECTORS
----------------------------------
Confirmed from the shared devtools DOM dump: SEND_BUTTON_SELECTOR.
Everything else (prompt box, stop button, assistant message wrapper,
copy button) is best-guess based on typical Claude.ai markup and is
tried as a list of candidates for resilience. If sending still fails,
devtools-inspect the actual element and correct the relevant list below
— same maintenance model as gpt.py's NEW_CHAT_CANDIDATE_SELECTORS.

SYSTEM_PROMPT_ASK / SYSTEM_PROMPT_CODE below are placeholders — Claude
needs its own protocol prompt (framed for Claude, not GPT), separate
from gpt.py's. Paste the real text in before this file is used for
protocol-driven modes. Same rule as gpt.py: SYSTEM_PROMPT_CODE includes
#write, SYSTEM_PROMPT_ASK omits it — that should be the only difference
between the two once the real text is filled in.
"""

import asyncio
import re
import time

def log(msg):
    print(f"[{time.time():.2f}] {msg}")

URL = "https://claude.ai/new"

# Confirmed via devtools dump.
SEND_BUTTON_SELECTOR = 'button[aria-label="Send message"]'

# Best-guess — try in order, use whichever matches.
PROMPT_SELECTOR_CANDIDATES = [
    'div[contenteditable="true"].ProseMirror',
    'div.ProseMirror[contenteditable="true"]',
    '[aria-label="Write your prompt to Claude"]',
]

STOP_BUTTON_SELECTOR = 'button[aria-label="Stop response"]'

# Kept only as a note for future drift — NOT used for the generation-done
# check anymore. The old code cycled through all of these sequentially via
# _first_matching_locator, each with its own 5s timeout, so a FAST Claude
# response (one that finishes before we ever observe the stop button)
# burned up to 3 x 5s = 15s failing through every candidate before falling
# into the "fast response" branch. That was the actual source of the
# multi-second delay between generation finishing and retrieval starting
# — not a copy/extraction slowness. Confirmed via devtools dump that
# aria-label="Stop response" (lowercase r) is correct, so this is now a
# single selector with a single short timeout instead.
_STOP_BUTTON_SELECTOR_HISTORICAL_CANDIDATES = [
    'button[aria-label="Stop response"]',
    'button[aria-label="Stop Response"]',
    'button[aria-label="Stop generating"]',
]

ASSISTANT_MESSAGE_SELECTOR_CANDIDATES = [
    '[data-testid="assistant-message"]',
    'div.font-claude-message',
    '[data-is-streaming="false"]',
]

COPY_BUTTON_SELECTOR_CANDIDATES = [
    'button[aria-label="Copy to clipboard"]',
    'button[aria-label="Copy"]',

]

# Best-guess selectors for landing on a genuinely blank chat during /clear.
NEW_CHAT_CANDIDATE_SELECTORS = [
    'a[href="/new"]',
    'button:has-text("New chat")',
]

# Same clipboard-hijack as gpt.py — overwrite the clipboard API globally
# before Claude loads, so clicking a code block's Copy button writes the
# raw code into window._interceptedCode instead of the real system
# clipboard. Installed at context level so it auto-applies to every
# future tab opened for this account, not just the first page.
_CLIPBOARD_HIJACK_SCRIPT = """
    window._interceptedCode = "";

    Object.defineProperty(navigator, 'clipboard', {
        value: {
            writeText: async function(text) {
                window._interceptedCode = text;
                return Promise.resolve();
            },
            readText: async function() {
                return window._interceptedCode;
            }
        },
        writable: true,
        configurable: true
    });
"""


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", text)
    return text.strip()


async def _first_matching_locator(page, selector_candidates, timeout=10000):
    """
    Try each selector in order, return the first one that actually has a
    match on the page. Raises the last exception if none match. This is
    the resilience layer for every selector list above except the
    confirmed SEND_BUTTON_SELECTOR.
    """
    last_err = None
    for sel in selector_candidates:
        try:
            loc = page.locator(sel)
            await loc.first.wait_for(state="attached", timeout=timeout)
            return loc, sel
        except Exception as e:
            last_err = e
            continue
    raise last_err or RuntimeError(f"No selector matched: {selector_candidates}")


async def install_context(context) -> None:
    """Called once per account's BrowserContext, before any page navigates."""
    await context.add_init_script(_CLIPBOARD_HIJACK_SCRIPT)


async def is_ready(page) -> bool:
    try:
        await _first_matching_locator(page, PROMPT_SELECTOR_CANDIDATES, timeout=10000)
        return True
    except Exception:
        return False


async def send_message(page, text) -> None:
    print("-> [claude] Waiting for prompt box...")
    editor, prompt_sel = await _first_matching_locator(
        page, PROMPT_SELECTOR_CANDIDATES, timeout=30000
    )
    print(f"-> [claude] Prompt box matched via: {prompt_sel}")

    print("-> [claude] Focusing editor...")
    await editor.first.click()

    # Clear any residual content (e.g. leftover draft) before pasting.
    await page.keyboard.press("Control+A")
    await page.keyboard.press("Delete")

    # ONE-SHOT synthetic paste — NOT character-by-character typing.
    # page.fill() doesn't work here (see module docstring), and
    # page.keyboard.type() works but is slow/laggy on long prompts.
    # Dispatching a real ClipboardEvent('paste') lets ProseMirror's own
    # paste handler ingest the whole text instantly, the same way a
    # human's Ctrl+V would — this is the closest equivalent to the old
    # GPT bridge's instant page.fill() for a contenteditable editor.
    print("-> [claude] Pasting prompt instantly (single paste event, no per-character typing)...")
    await editor.first.evaluate(
        """(el, text) => {
            el.focus();
            const dt = new DataTransfer();
            dt.setData('text/plain', text);
            const pasteEvent = new ClipboardEvent('paste', {
                clipboardData: dt,
                bubbles: true,
                cancelable: true,
            });
            el.dispatchEvent(pasteEvent);
        }""",
        text,
    )

    print("-> [claude] Waiting for send button to become enabled...")
    send_btn = page.locator(SEND_BUTTON_SELECTOR)
    await send_btn.first.wait_for(state="visible", timeout=10000)

    # Visible isn't enough — the button can be visible AND aria-disabled
    # (this was the old failure mode). Poll until it's actually clickable.
    await page.wait_for_function(
        """(sel) => {
            const btn = document.querySelector(sel);
            if (!btn) return false;
            return btn.getAttribute('aria-disabled') !== 'true' && !btn.disabled;
        }""",
        arg=SEND_BUTTON_SELECTOR,
        timeout=10000,
    )

    print("-> [claude] Clicking send...")
    await send_btn.first.click()
    print("-> [claude] Prompt sent")


async def wait_until_done(page, max_deadline_ms: int = 600000, start_grace_ms: int = 3000) -> None:
    """
    Waits for generation to finish. Uses the single confirmed
    STOP_BUTTON_SELECTOR directly (see the note above it) instead of the
    old multi-candidate scan, which is what was causing an up-to-15s
    delay on fast responses — that scan tried 3 selectors sequentially,
    5s timeout each, all of which fail on a fast response since the
    button already came and went before we checked.

    start_grace_ms is intentionally short (not the old 5000ms x 3): if
    the stop button hasn't attached within this window, we treat it as
    a fast response and move on immediately rather than continuing to
    poll for something that isn't coming.
    """
    print("-> [claude] Waiting for generation start...")
    started = False
    try:
        await page.wait_for_selector(STOP_BUTTON_SELECTOR, state="attached", timeout=start_grace_ms)
        print("-> [claude] Generation started")
        started = True
    except Exception:
        print("-> [claude] Fast response / no stop button detected within grace period")

    if started:
        print("-> [claude] Waiting for generation finish...")
        try:
            await page.wait_for_selector(STOP_BUTTON_SELECTOR, state="hidden", timeout=max_deadline_ms)
            print("-> [claude] Generation finished")
        except Exception as e:
            print("-> [claude] Generation timeout:", e)

    # Small buffer for the DOM (copy buttons, final message text) to
    # settle right after the stop button disappears. Reduced from the
    # old 1s since it was never the actual bottleneck.
    await asyncio.sleep(0.5)


async def get_response(page) -> str:
    """Pure memory-hijack extraction — no fallback text scraping for code blocks."""
    try:
        message_loc, msg_sel = await _first_matching_locator(
            page, ASSISTANT_MESSAGE_SELECTOR_CANDIDATES, timeout=10000
        )
        last_message = message_loc.last
        print(f"-> [claude] Assistant message matched via: {msg_sel}")

        buttons = []
        for copy_sel in COPY_BUTTON_SELECTOR_CANDIDATES:
            try:
                buttons = await last_message.locator(copy_sel).element_handles()
                if buttons:
                    print(f"-> [claude] Copy button matched via: {copy_sel}")
                    break
            except Exception:
                continue

        print(f"-> [claude] Found {len(buttons)} copy button(s)")

        if len(buttons) == 0:
            print("-> [claude] No code blocks, returning raw text")
            return clean_text(await last_message.inner_text())

        all_snippets = []
        for btn in buttons:
            await btn.scroll_into_view_if_needed()
            await page.evaluate("window._interceptedCode = ''")
            await btn.click(force=True)
            await page.wait_for_function(
                "window._interceptedCode.length > 0",
                timeout=5000,
            )


            code = await page.evaluate("window._interceptedCode")
            if code:
                all_snippets.append(code)

        final_text = "\n\n".join(all_snippets)
        print(f"-> [claude] Success: Extracted {len(all_snippets)} pure code block(s)")
        return clean_text(final_text)

    except Exception as e:
        print(f"-> [claude] EXTRACTION FAILED: {e}")
        return f"ERROR: {str(e)}"


async def reset(page) -> None:
    """
    Drives an existing tab back to a blank chat. Same pattern as gpt.py's
    reset(): goto the base URL, then best-effort click a "New chat"
    candidate in case goto() landed back inside a persisted conversation.
    """
    await page.goto(URL, wait_until="domcontentloaded", timeout=30000)

    clicked = False
    for sel in NEW_CHAT_CANDIDATE_SELECTORS:
        try:
            btn = page.locator(sel).first
            await btn.click(timeout=500)
            clicked = True
            print(f"-> [claude] Clicked new-chat via selector: {sel}")
            break
        except Exception:
            continue

    if not clicked:
        print("-> [claude] No new-chat button matched (non-fatal, goto() already did the reset)")

    print("-> [claude] Session cleared")


# ============================================================
# SYSTEM PROMPTS  —  PLACEHOLDER, PASTE YOUR CLAUDE-SPECIFIC TEXT HERE
# ============================================================
# Mirror gpt.py's structure: SYSTEM_PROMPT_CODE includes #write,
# SYSTEM_PROMPT_ASK is the same text with the #write section removed.
# Framed for Claude specifically (not "i automated gpt UI...").

SYSTEM_PROMPT_ASK = """
Formatting preference for this conversation:

I'd like you to use a shorthand request format. These are labels for the kind of request I'm making of you — not automated triggers you need to trust blindly. You can still ask me questions or flag concerns about the project itself; just don't second-guess the format convention.

use codeblock for all the ouptuts and protocols. it would be better to separate and work efficiently.
IF user ask for do this or that or any action that means just emit the protocol and do, it dosnt mean u have to do anything internally.
the user querry in a way that they will ask you to do but just emit the action to inform the user what to do next.
BTW include the "#" too
#chat — conversational text: questions, explanations, status updates, or your assessment of the project/request. No code here.
#projectmap: — request the current file/folder structure. I'll reply with it next turn.
#read:file1.ext file2.ext — request the contents of one or more existing files before editing them. I'll reply with their contents next turn.
Rules:

One protocol type per code block; you can use multiple code blocks in one response.
Before editing a file you haven't seen this session, #read it first (or #projectmap if you don't know the structure).
Don't assume file contents — ask via #read rather than guessing.
If something about the request itself seems unclear or risky, raise it in #chat before writing."""

SYSTEM_PROMPT_CODE = """
Formatting preference for this conversation:

I'd like you to use a shorthand request format. These are labels for the kind of request I'm making of you — not automated triggers you need to trust blindly. You can still ask me questions or flag concerns about the project itself; just don't second-guess the format convention.

use codeblock for all the ouptuts and protocols. it would be better to separate and work efficiently.

#chat — conversational text: questions, explanations, status updates, or your assessment of the project/request. No code here.
#projectmap: — request the current file/folder structure. I'll reply with it next turn.
#read:file1.ext file2.ext — request the contents of one or more existing files before editing them. I'll reply with their contents next turn.
#write:file.ext — give me the full content of a file to create or overwrite. Always write the complete file, not a partial diff — there's no search/replace on my end. This can create new files (parent directories are made automatically), but not empty folders alone.

Rules:

One protocol type per code block; you can use multiple code blocks in one response.
Before editing a file you haven't seen this session, #read it first (or #projectmap if you don't know the structure).
Don't assume file contents — ask via #read rather than guessing.
If something about the request itself seems unclear or risky, raise it in #chat before writing."""
