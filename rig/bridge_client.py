import requests

BRIDGE_URL = "http://127.0.0.1:8080/v1/chat/completions"


def ask_bridge(prompt: str) -> str:

    payload = {
        "model": "openai/browser-model",
        "messages": [{"role": "user", "content": prompt}],
    }

    response = requests.post(BRIDGE_URL, json=payload, timeout=600)

    response.raise_for_status()

    data = response.json()

    return data["choices"][0]["message"]["content"]
