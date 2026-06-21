import subprocess


def main():

    subprocess.run(
        ["pkill", "-f", "rig.bridge"],
        capture_output=True,
    )

    subprocess.run(
        ["pkill", "-f", "remote-debugging-port=9222"],
        capture_output=True,
    )

    print("AI bridge stopped")


if __name__ == "__main__":
    main()
