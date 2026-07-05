from ..service.file_system import write_file
from ..service.parser import parse_files


def run(response: str) -> list[str]:
    """
    Execute the WRITE action.

    Parses the AI response, writes all returned files,
    and returns a list of updated file paths.
    """

    parsed_files = parse_files(response)

    updated_files = []

    for file in parsed_files:
        write_file(
            file["path"],
            file["content"],
        )
        updated_files.append(file["path"])

    return updated_files
