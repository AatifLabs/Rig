from ..actions import write
from ..response import chat
from ..response import read
from ..response import projectmap

PROTOCOLS = {
    "write": {
        "kind": "action",
        "handler": write.run,
        "continuity": True,
        "confirmation": True,
    },
    "chat": {
        "kind": "response",
        "handler": chat.run,
        "continuity": False,
    },
    "read": {
        "kind": "response",
        "handler": read.run,
        "continuity": True,
    },
    "projectmap": {
        "kind": "response",
        "handler": projectmap.run,
        "continuity": True,
    },
}


def get(protocol: str):
    return PROTOCOLS.get(protocol)


def exists(protocol: str) -> bool:
    return protocol in PROTOCOLS


def get_continuity(protocol: str) -> bool:
    entry = PROTOCOLS.get(protocol)
    if entry is None:
        return False
    return entry.get("continuity", False)


def get_confirmation(protocol: str) -> bool:
    """
    Returns the confirmation flag for a protocol. Defaults to False —
    absence of the key means no human gate before the handler runs.
    """
    entry = PROTOCOLS.get(protocol)
    if entry is None:
        return False
    return entry.get("confirmation", False)
