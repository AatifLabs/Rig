"""
Single source of truth for provider metadata.

Used by:
  - rig_setup.py  (knows where to point the browser during login)
  - runtime       (adapter selection, /use provider switching)

Adding a new provider later (e.g. gemini) means adding one entry here —
nothing else should hardcode a provider's URL.
"""

PROVIDERS = {
    "chatgpt": {
        "url": "https://chatgpt.com/",
    },
    "claude": {
        "url": "https://claude.ai/",
    },
}
