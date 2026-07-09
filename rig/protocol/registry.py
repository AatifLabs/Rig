from ..actions import write
from ..response import ask


PROTOCOLS = {
    "write": {
        "kind": "action",
        "handler": write.run,
    },
    "ask": {
        "kind": "response",
        "handler": ask.run,
    },
}


def get(protocol: str):
    return PROTOCOLS.get(protocol)


def exists(protocol: str) -> bool:
    return protocol in PROTOCOLS
