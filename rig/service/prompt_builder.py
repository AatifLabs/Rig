def build_prompt(
    system_prompt: str,
    user_request: str,
    project_files: list[dict],
):
    sections = [system_prompt]

    if project_files:
        sections.append("\nATTACHED FILES\n")

        for file in project_files:
            sections.append(
                f"#write: {file['path']}\n{file['content']}"
            )

    sections.append(f"\nUSER REQUEST\n{user_request}")

    return "\n".join(sections)
