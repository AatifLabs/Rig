"""
Ask mode.

SYSTEM_PROMPT used to live here as a single hardcoded string. It's now
provider-owned (providers/gpt.py's and providers/claude.py's
SYSTEM_PROMPT_ASK) since GPT and Claude need different prompt text.
mode/manager.py resolves the actual prompt via
providers.get_system_prompt(provider, "ask") — this file only owns what's
actually mode-level and provider-agnostic: the mode's name and its
allowed actions/responses.
"""

MODE_NAME = "ask"

ALLOWED_ACTIONS = []

ALLOWED_RESPONSES = [
    "chat", "read", "projectmap"
]
