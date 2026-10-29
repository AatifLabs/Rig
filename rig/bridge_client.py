import requests

BRIDGE_URL = "http://127.0.0.1:8080/v1/chat/completions"
HEALTH_URL = "http://127.0.0.1:8080/health"
SESSION_NEW_URL = "http://127.0.0.1:8080/session/new"
SESSION_USE_URL = "http://127.0.0.1:8080/session/use"


def ask_bridge(prompt: str, session_id: str, account: str, provider: str) -> str:
    payload = {
        "model": "openai/browser-model",
        "messages": [{"role": "user", "content": prompt}],
        "session_id": session_id,
        "account": account,
        "provider": provider,
    }
    response = requests.post(BRIDGE_URL, json=payload, timeout=600)
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]


def is_bridge_healthy(account: str | None = None, session_id: str = "code", timeout: float = 5.0) -> bool:
    try:
        params = {"session_id": session_id}
        if account is not None:
            params["account"] = account
        response = requests.get(HEALTH_URL, params=params, timeout=timeout)
        response.raise_for_status()
        return response.json().get("status") == "ok"
    except requests.RequestException:
        return False


def clear_session(session_id: str, account: str, provider: str, timeout: float = 20.0) -> bool:
    """/clear semantics: reset the given session's tab to a fresh chat."""
    try:
        response = requests.post(
            SESSION_NEW_URL,
            json={"session_id": session_id, "account": account, "provider": provider},
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json().get("status") == "cleared"
    except requests.RequestException as e:
        print(f"-> [bridge_client] clear_session failed: {e}")
        return False


def switch_provider(session_id: str, account: str, provider: str, timeout: float = 20.0) -> bool:
    """/use semantics: same tab, repointed at a different provider's site."""
    try:
        response = requests.post(
            SESSION_USE_URL,
            json={"session_id": session_id, "account": account, "provider": provider},
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json().get("status") == "switched"
    except requests.RequestException as e:
        print(f"-> [bridge_client] switch_provider failed: {e}")
        return False
