from ..service.file_system import write_file


def run(protocol: dict) -> str:
    """
    Execute the WRITE action.
    """

    write_file(
        protocol["target"],
        protocol["payload"],
    )

    return protocol["target"]
