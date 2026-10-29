import json
from pathlib import Path

STATE_FILE = Path(__file__).parent / "state.json"


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    with open(STATE_FILE) as f:
        return json.load(f)


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def get_session(session_id: str) -> dict | None:
    return load_state().get(session_id)


def set_session(session_id: str, profile: str, provider: str):
    state = load_state()
    state[session_id] = {"profile": profile, "provider": provider}
    save_state(state)
