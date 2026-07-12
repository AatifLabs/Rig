import requests

BRIDGE_URL = "http://127.0.0.1:8080/v1/chat/completions"
HEALTH_URL = "http://127.0.0.1:8080/health"
SESSION_URL = "http://127.0.0.1:8080/session/new"


def ask_bridge(prompt: str) -> str:
    payload = {
        "model": "openai/browser-model",
        "messages": [{"role": "user", "content": prompt}],
    }
    response = requests.post(BRIDGE_URL, json=payload, timeout=600)
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]


def is_bridge_healthy(timeout: float = 5.0) -> bool:
    try:
        response = requests.get(HEALTH_URL, timeout=timeout)
        response.raise_for_status()
        return response.json().get("status") == "ok"
    except requests.RequestException:
        return False


def clear_session(timeout: float = 20.0) -> bool:
    try:
        response = requests.post(SESSION_URL, timeout=timeout)
        response.raise_for_status()
        return response.json().get("status") == "cleared"
    except requests.RequestException as e:
        print(f"-> [bridge_client] clear_session failed: {e}")
        return False
