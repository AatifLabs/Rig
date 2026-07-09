from . import ask
from . import coding

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


def get_prompt():
    return MODES[current_mode].SYSTEM_PROMPT


def get_allowed_actions():
    return MODES[current_mode].ALLOWED_ACTIONS


def get_allowed_responses():
    return MODES[current_mode].ALLOWED_RESPONSES
