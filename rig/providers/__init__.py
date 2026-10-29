"""
Provider adapter registry.

This folder replaces the old flat providers.py file. That file used to hold
just a {name: {"url": ...}} lookup table; now each provider is a full module
implementing the shared adapter interface (send_message / wait_until_done /
get_response / is_ready), and this __init__ is the single place that maps a
provider *key* (the string stored on a SessionHandle, e.g. "gpt" / "claude")
to its adapter module.

JUDGMENT CALL: the original flat providers.py used the key "chatgpt". The
rearchitecture prompt's own example code uses "gpt" (`adapters[session.provider]`,
"claude" / "gpt" naming). Renamed the key to "gpt" to match the adapter
filename (providers/gpt.py) and the prompt's own wording — flag this if you
had scripts/state.json referencing the old "chatgpt" key, since they'll need
updating to "gpt".

Adding a new provider later (e.g. gemini) means adding one file here
(providers/gemini.py, implementing the same four functions plus
SYSTEM_PROMPT_ASK / SYSTEM_PROMPT_CODE) and one line below — nothing else
in the codebase should ever hardcode a provider name, URL, or prompt text.
"""

from . import gpt, claude

# provider key -> adapter module
ADAPTERS = {
    "gpt": gpt,
    "claude": claude,
}

# Derived, not hand-maintained: provider key -> landing URL, for anything
# (rig_setup's login flow, registry's initial page.goto) that just needs
# "where does this provider live", without caring about DOM automation.
PROVIDER_URLS = {name: adapter.URL for name, adapter in ADAPTERS.items()}


def get_adapter(provider: str):
    try:
        return ADAPTERS[provider]
    except KeyError:
        raise ValueError(
            f"Unknown provider '{provider}'. Known providers: {list(ADAPTERS)}"
        )


# mode name -> provider attribute holding that mode's prompt. Each adapter
# module (gpt.py, claude.py) exposes SYSTEM_PROMPT_ASK / SYSTEM_PROMPT_CODE
# as module-level constants; this is just the mode->attribute-name mapping,
# so adding a new mode later means adding one line here, not branching
# logic anywhere else.
_PROMPT_ATTR_BY_MODE = {
    "ask": "SYSTEM_PROMPT_ASK",
    "code": "SYSTEM_PROMPT_CODE",
}


def get_system_prompt(provider: str, mode: str) -> str:
    """
    Resolve the (provider, mode) pair to that provider's prompt text for
    that mode. This is the single seam mode/manager.py calls through —
    it never imports or branches on gpt.py/claude.py directly.
    """
    adapter = get_adapter(provider)

    try:
        attr = _PROMPT_ATTR_BY_MODE[mode]
    except KeyError:
        raise ValueError(
            f"Unknown mode '{mode}'. Known modes: {list(_PROMPT_ATTR_BY_MODE)}"
        )

    try:
        return getattr(adapter, attr)
    except AttributeError:
        raise ValueError(
            f"Provider '{provider}' has no {attr} defined (missing prompt for mode '{mode}')"
        )
