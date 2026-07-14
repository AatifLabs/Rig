from ..actions import write
from ..response import ask
from ..response import read
from ..response import projectmap

PROTOCOLS = {
    "write": {
        "kind": "action",
        "handler": write.run,
        "continuity": False,
    },
    "ask": {
        "kind": "response",
        "handler": ask.run,
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
    """
    Returns the continuity flag for a protocol.
    Defaults to False if the protocol is unknown OR if the
    protocol entry simply never set "continuity" at all —
    absence of the key is treated identically to explicit False.
    """
    entry = PROTOCOLS.get(protocol)
    if entry is None:
        return False
    return entry.get("continuity", False)
