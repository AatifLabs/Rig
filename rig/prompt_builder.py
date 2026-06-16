SYSTEM_PROMPT = """You are BrowserIDE, a coding assistant that modifies files.

RULES:
- Use a code block for every file
- First line of every code block must be: # filename: yourfile.py
- Return COMPLETE file contents, never partial
- No explanation outside the code blocks
"""


def build_prompt(user_request, project_files):
    sections = [SYSTEM_PROMPT]
    sections.append("\nATTACHED FILES\n")
    for file in project_files:
        sections.append(f"# filename: {file['path']}\n{file['content']}")
    sections.append(f"\nUSER REQUEST\n{user_request}")
    return "\n".join(sections)
