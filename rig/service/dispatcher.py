from ..protocol.registry import get, get_continuity


def dispatch(protocol: dict):
    entry = get(protocol["protocol"])

    if entry is None:
        raise ValueError(
            f"Unknown protocol: {protocol['protocol']}"
        )

    return {
        "kind": entry["kind"],
        "protocol": protocol["protocol"],
        "result": entry["handler"](protocol),
        "continuity": get_continuity(protocol["protocol"]),
    }
