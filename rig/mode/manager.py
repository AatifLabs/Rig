from . import ask
from . import coding
from ..providers import get_system_prompt

MODES = {
    "ask": ask,
    "code": coding,
}

current_mode = "code"


def get_mode():
    return current_mode


def set_mode(mode: str):
    global current_mode

    if mode not in MODES:
        raise ValueError(f"Unknown mode: {mode}")

    current_mode = mode


def get_prompt(provider: str):
    """
    CHANGED: now requires a provider argument. The prompt text is no
    longer mode-owned — it's provider-owned (gpt.py / claude.py each
    define SYSTEM_PROMPT_ASK / SYSTEM_PROMPT_CODE). This just resolves
    (provider, current_mode) through providers.get_system_prompt().

    Every existing call site of manager.get_prompt() needs updating to
    pass the current session's provider, e.g.:
        mode_manager.get_prompt(mode_pointer[mode]["provider"])
    """
    return get_system_prompt(provider, current_mode)


def get_allowed_actions():
    return MODES[current_mode].ALLOWED_ACTIONS


def get_allowed_responses():
    return MODES[current_mode].ALLOWED_RESPONSES
