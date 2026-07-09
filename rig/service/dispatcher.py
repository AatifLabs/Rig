from ..protocol.registry import get


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
    }
