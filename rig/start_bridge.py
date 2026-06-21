import socket
import subprocess
import sys
import time
from pathlib import Path

CHROME_PORT = 9222
BRIDGE_PORT = 8080

CHROME_PROFILE = Path.home() / ".chrome-ai-profile"


def port_open(port: int) -> bool:
    s = socket.socket()
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def main():

    # ==========================================
    # START CHROME
    # ==========================================

    if not port_open(CHROME_PORT):
        print("[+] Starting AI Chrome...")

        subprocess.Popen(
            [
                "google-chrome-stable",
                f"--remote-debugging-port={CHROME_PORT}",
                f"--user-data-dir={CHROME_PROFILE}",
                "--window-size=1920,1080",
                "--new-window",
                "--disable-session-crashed-bubble",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        time.sleep(5)

    else:
        print("[+] Chrome already running")

    # ==========================================
    # START BRIDGE
    # ==========================================

    if not port_open(BRIDGE_PORT):
        print("[+] Starting bridge server...")

        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "rig.bridge",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        time.sleep(3)

    else:
        print("[+] Bridge already running")

    # ==========================================
    # HEALTH CHECK
    # ==========================================

    if port_open(BRIDGE_PORT):
        print("")
        print("======================================")
        print("AI BRIDGE READY")
        print("======================================")
        print("")

    else:
        print("[-] Bridge health check failed")


if __name__ == "__main__":
    main()
