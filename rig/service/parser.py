import re


def clean_payload(content: str) -> str:
    lines = content.split("\n")
    non_empty = [line for line in lines if line.strip()]

    if non_empty:
        min_indent = min(
            len(line) - len(line.lstrip())
            for line in non_empty
        )
        lines = [line[min_indent:] for line in lines]

    return "\n".join(lines).strip()


def parse_protocols(response: str) -> list[dict]:
    pattern = (
        r"^\s*#\s*"
        r"([a-zA-Z_][a-zA-Z0-9_]*)"   # protocol
        r"\s*"
        r"(?:\:\s*(.*?))?"            # optional target
        r"\s*$"
        r"(.*?)"
        r"(?=^\s*#\s*[a-zA-Z_][a-zA-Z0-9_]*\s*(?:\:|\n)|\Z)"
    )

    matches = re.findall(
        pattern,
        response,
        re.MULTILINE | re.DOTALL,
    )

    protocols = []

    for protocol, target, payload in matches:
        protocols.append(
            {
                "protocol": protocol.strip().lower(),
                "target": (target or "").strip(),
                "payload": clean_payload(payload),
            }
        )

    return protocols
