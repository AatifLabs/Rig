from ..mode.manager import (
    get_allowed_actions,
    get_allowed_responses,
)

from ..protocol.registry import get


def validate(protocol: dict) -> bool:
    entry = get(protocol["protocol"])

    if entry is None:
        return False

    if (
        entry["kind"] == "action"
        and protocol["protocol"] in get_allowed_actions()
    ):
        return True

    if (
        entry["kind"] == "response"
        and protocol["protocol"] in get_allowed_responses()
    ):
        return True

    return False
