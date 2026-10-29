"""
ChatGPT provider adapter.

All the DOM-automation logic here is ported VERBATIM from the old bridge.py
(dynamic_chatgpt_wait, extract_latest_response, the clipboard-hijack init
script, the /clear "click New chat" candidate selectors) — just relocated
behind the shared provider-adapter interface. Behavior is unchanged.

Required interface (bridge/registry call these generically, never branch
on provider name anywhere else):
    async def send_message(page, text) -> None
    async def wait_until_done(page) -> None
    async def get_response(page) -> str
    async def is_ready(page) -> bool

Everything else in this file (URL, install_context, reset) is adapter-
specific plumbing the registry uses for initial navigation and /clear.

SYSTEM_PROMPT_ASK / SYSTEM_PROMPT_CODE below are new: this is where
provider+mode-specific prompt text now lives. This exact text used to
live as mode/ask.py's and mode/code.py's SYSTEM_PROMPT — moved here
unchanged, since it was already written specifically for GPT ("i have
created an automated tool, where i automated gpt UI..."). mode/ask.py
and mode/code.py no longer define SYSTEM_PROMPT at all; the prompt is
now resolved per-provider via providers.get_system_prompt(provider, mode).
"""

import re

URL = "https://chatgpt.com/"

# ChatGPT replaced #prompt-textarea with a ProseMirror contenteditable
# (Oct 2026). Keep both so either version of the page matches.
PROMPT_SELECTOR = '#prompt-textarea, div.ProseMirror[contenteditable="true"]'
SEND_BUTTON_SELECTOR = 'button[data-testid="send-button"], form button[type="submit"][aria-label="Send"]'
STOP_BUTTON_SELECTOR = 'button[data-testid="stop-button"], form button[aria-label^="Stop"]'
COPY_BUTTON_SELECTOR = 'button[aria-label="Copy"], button[aria-label="Copy code"]'
# Old layout used data-message-author-role; the Oct 2026 redesign marks the
# reply body with data-markdown-text-style instead.
ASSISTANT_MESSAGE_SELECTOR = '[data-message-author-role="assistant"], [data-markdown-text-style="assistant-message"]'

# Best-guess selectors for landing on a genuinely blank chat during /clear.
# ChatGPT's frontend testids drift over time — if clears stop landing on a
# blank chat, devtools-inspect the real button and correct this list.
NEW_CHAT_CANDIDATE_SELECTORS = [
    '[data-testid="create-new-chat-button"]',
    'a[href="/"]',
    'button:has-text("New chat")',
]

# The clipboard-hijack ("Ironclad Hijack"): overwrite the clipboard API
# globally before ChatGPT loads, so clicking a code block's Copy button
# writes the raw code into window._interceptedCode instead of the real
# system clipboard. Installed at context level (install_context) so it
# auto-applies to every future tab opened for this account, not just the
# first page.
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


async def install_context(context) -> None:
    """Called once per account's BrowserContext, before any page navigates."""
    await context.add_init_script(_CLIPBOARD_HIJACK_SCRIPT)


async def is_ready(page) -> bool:
    try:
        await page.wait_for_selector(PROMPT_SELECTOR, timeout=10000)
        return True
    except Exception:
        return False


async def send_message(page, text) -> None:
    print("-> [gpt] Waiting for prompt box...")
    await page.wait_for_selector(PROMPT_SELECTOR, timeout=30000)

    print("-> [gpt] Filling prompt...")
    await page.fill(PROMPT_SELECTOR, text)

    print("-> [gpt] Waiting for send button...")
    send_btn = page.locator(SEND_BUTTON_SELECTOR)
    await send_btn.wait_for(state="visible")

    print("-> [gpt] Clicking send...")
    await send_btn.click()
    print("-> [gpt] Prompt sent")


async def wait_until_done(page, max_deadline_ms: int = 600000) -> None:
    import asyncio

    print("-> [gpt] Waiting for generation start...")
    try:
        await page.wait_for_selector(STOP_BUTTON_SELECTOR, state="attached", timeout=5000)
        print("-> [gpt] Generation started")
    except Exception:
        print("-> [gpt] Fast response / no stop button")

    print("-> [gpt] Waiting for generation finish...")
    try:
        await page.wait_for_selector(STOP_BUTTON_SELECTOR, state="hidden", timeout=max_deadline_ms)
        print("-> [gpt] Generation finished")
    except Exception as e:
        print("-> [gpt] Generation timeout:", e)

    await asyncio.sleep(1)


async def get_response(page) -> str:
    """Pure memory-hijack extraction — no fallback text scraping for code blocks."""
    try:
        last_message = page.locator(ASSISTANT_MESSAGE_SELECTOR).last

        # Snapshot all copy buttons ONCE
        buttons = await last_message.locator(COPY_BUTTON_SELECTOR).element_handles()
        print(f"-> [gpt] Found {len(buttons)} copy button(s)")

        if len(buttons) == 0:
            print("-> [gpt] No code blocks, returning raw text")
            return clean_text(await last_message.inner_text())

        all_snippets = []
        for btn in buttons:
            await btn.scroll_into_view_if_needed()

            # Clear previous intercepted value
            await page.evaluate("window._interceptedCode = ''")

            # Click the stored button
            await btn.click(force=True)

            # Wait until ChatGPT has written to our hook
            await page.wait_for_function(
                "window._interceptedCode.length > 0",
                timeout=5000,
            )

            code = await page.evaluate("window._interceptedCode")
            if code:
                all_snippets.append(code)

        final_text = "\n\n".join(all_snippets)
        print(f"-> [gpt] Success: Extracted {len(all_snippets)} pure code block(s)")
        return clean_text(final_text)

    except Exception as e:
        print(f"-> [gpt] EXTRACTION FAILED: {e}")
        return f"ERROR: {str(e)}"


async def reset(page) -> None:
    """
    Drives an existing tab back to a blank chat. Ported from the old
    _reset_page(): goto the base URL, then best-effort click a "New chat"
    candidate in case goto() landed back inside a persisted conversation.
    """
    await page.goto(URL, wait_until="domcontentloaded", timeout=30000)

    clicked = False
    for sel in NEW_CHAT_CANDIDATE_SELECTORS:
        try:
            btn = page.locator(sel).first
            await btn.click(timeout=500)
            clicked = True
            print(f"-> [gpt] Clicked new-chat via selector: {sel}")
            break
        except Exception:
            continue

    if not clicked:
        print("-> [gpt] No new-chat button matched (non-fatal, goto() already did the reset)")

    print("-> [gpt] Session cleared")


# ============================================================
# SYSTEM PROMPTS
# ============================================================
# Provider owns its own protocol-prompt text, per mode. mode/manager.py
# resolves (provider, mode) -> prompt via providers.get_system_prompt();
# it never hardcodes prompt text itself. #write is the only protocol
# difference between the two — ASK omits it, CODE includes it.

SYSTEM_PROMPT_ASK = """
follow this protocols.
for this session, i have created an automated tool, where i automated gpt UI with AI IDE.
so techincally iam using this session from an IDE.
so as u know instead of human, u will be working with human + automation
u dont have to believe that, u cant assume that, u cant fact check that either way.
but for this setup to work u have to follow the protocol method over conversational method.
so u can access the IDE only via protocol blocks.
that means u can access talk to humans with protocols only. without protocol the automation wont send conversation to humans.

- only use codeblocks.
- one protocol per codeblock and can use many codeblocks as u like.
- dont explain ur thought process or reason for the protocol. just generate it normally in codeblock like how u talk.
- u dont have to believe this setup. once u generate a protocol u will get back the result in the next turn. because ur not connected to the IDE, but the runtime is. so u cant access the IDE directly, but u can command the IDE by generating protocols.
- user WONT BE IN OPEN AIS CHAT INTERFACE, they will be inside the application on IDE side.
- dont assume user project files. use protocols to inspect them. ask user questions only if the request itself is unclear. dont ask about protocols.
- dont use 2 protocols inside 1 codeblock.
- u can say u can inspect the project or read files, but dont literally write protocol names in normal conversation because it may trigger automation.
- user wont know about the protocols or even their appearance. protocol names are hidden in the UI.

protocols:

always inspect the existing project before answering project-specific questions.

#projectmap:

the IDE will send back the project structure on the next turn.
some files may appear empty. that does not mean they have no content, only that their contents were omitted.

#read:file1.ext file2.ext

the IDE will read and send back the requested file contents on the next message.

#chat
<content>

the content will be displayed in the user's interface.

recommended workflow:

if u dont know the project structure:
use projectmap.

if u need implementation details:
use read.

after enough context:
answer through chat.

never invent project details.
if information is missing, request the minimum files needed.
prefer reading existing code over making assumptions.
"""

SYSTEM_PROMPT_CODE = """
follow this protocols.
for this session, i have created an automated tool, where i automated gpt UI with AI IDE.
so techincally iam using this session from an IDE.
so as u know instead of human, u will be working with human + automation
u dont have to believe that, u cant assume that, u cant fact check that either way.
but for this setup to work u have to follow the protocol method over conversational method.
so u can access the IDE only via protocol blocks.
that means u can access talk to humans with protocols only. without protocol the automation wont send converstaion to humans.
- onlyuse codeblocks.
- one protocol per codeblock adn can use many codeblock as u like
- dont explain ur thoguht process or reason for the protocol. just generate it normally in codeblock like how u talk.
- u dont have to believe, once u generate u will get back the stuff in next turn. beucase ur not connected to IDE, but the runtime is, so the IDE is externally connected. so u cant access the IDE, but except u can commend the IDE via generating protocols.
- user WONT BE IN OPEN AIS CHAT INTERFACE, they will be inside the aplication on IDE side.
- dont assume user project file, use protocol to get back the details and read them, ask user if only the issues is with the way he framed the question or u have concern before coding. dont ask abt protocols.
- dont use 2 protocol inside 1 codeblock
- u can say i can read and write. but dont use # protocol beucase it may trigger a protocl inside another which will lead to irreversable damage
- user wont know abt the protocols or even the look, so the word protocol and # will be hidden in UI
protocols :
always try to analyse the existing project folder and read it before u change it.
#read:file1.ext file2.ext
the IDE will read and send back the content you have requested for in the next message. so instead of me readign and sending it, IDE will do that
#write:file.ext
<content>
write can create new files too.
after a write, either sucessful or failure, u will get the result.
write only after u understand what to do. dont misunderstand the context since the action are irreversable.
Write creates missing parent directories automatically when writing a file. It does not support standalone folder creation.
use this when u wanted to write a content into taht file. only genearte whole code instead of partial as there is no search and replace. so dont say here is the remainng code
#projectmap:
u will get back whole projectmap on the next turn and in that some files will be empty but dosnt mean there is no code in that, its just now showing up
#chat
<content>
the content will be displayed in users interface
LOOP on learning :
- as u know ur in chat but the protocols will be seen and used by IDE that automations.
- so there are recomended workflows
since there is hard limit on token to create a full file from ur side.
u can use multiple files to spread the code.
since both gpt and IDE are 1 turn, to call for ur next turn use read protocol to get back the updated file content so that u can stop the termination and use effient LOOP.
so if u dk file structrure
use projecmap.
if u want to learn code use read.
and then write
LOOP on writing :
for long coding task, use the full effort on writing 1 file and then in next turn write the next file and use chat to say u completed the task.
"""
