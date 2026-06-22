import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CHROME_PORT = 9222
BRIDGE_PORT = 8080
CHROME_PROFILE = Path.home() / ".chrome-ai-profile"


def find_chrome():
    """
    Locates the official Google Chrome binary across Windows, macOS, and Linux.
    Strictly avoids sandboxed variants (like Flatpak/Snap) to ensure CDP works.
    """
    if sys.platform == "win32":
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.join(
                os.environ.get("LOCALAPPDATA", ""),
                r"Google\Chrome\Application\chrome.exe",
            ),
        ]
        for candidate in candidates:
            if os.path.exists(candidate):
                return candidate

    elif sys.platform == "darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        ]
        for candidate in candidates:
            if os.path.exists(candidate):
                return candidate

    else:
        # Linux
        candidates = [
            "google-chrome-stable",
            "google-chrome",
            "chrome",
        ]
        for candidate in candidates:
            path = shutil.which(candidate)
            if path:
                return path

    return None


def port_open(port: int) -> bool:
    """Checks if a given port is currently bound and listening."""
    s = socket.socket()
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def wait_for_port(port: int, timeout: int = 10) -> bool:
    """
    Polls the port every 0.5 seconds.
    Returns True instantly when open, False if it times out.
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        if port_open(port):
            return True
        time.sleep(0.5)
    return False


def http_is_healthy(url: str) -> bool:
    """
    Performs a Layer 7 HTTP GET request to verify the service is actually responding.
    """
    try:
        # 2-second timeout prevents hanging if the port is open but unresponsive
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


def main():

    # ==========================================
    # START CHROME
    # ==========================================

    if not port_open(CHROME_PORT):
        chrome_path = find_chrome()

        if not chrome_path:
            print("[-] Error: Google Chrome not found on this system.")
            sys.exit(1)

        print(f"[+] Starting AI Chrome ({chrome_path})...")

        subprocess.Popen(
            [
                chrome_path,
                f"--remote-debugging-port={CHROME_PORT}",
                f"--user-data-dir={CHROME_PROFILE}",
                "--window-size=1920,1080",
                "--new-window",
                "--disable-session-crashed-bubble",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        print("[+] Waiting for Chrome to expose CDP port...")
        if not wait_for_port(CHROME_PORT, timeout=10):
            print(
                "[-] Error: Chrome failed to start or expose port 9222 within 10 seconds."
            )
            sys.exit(1)

        print("[+] Chrome CDP is ready.")

    else:
        print("[+] Chrome already running.")

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

        print("[+] Waiting for Bridge server to initialize...")
        if not wait_for_port(BRIDGE_PORT, timeout=10):
            print("[-] Error: Bridge server failed to start on port 8080.")
            sys.exit(1)

    else:
        print("[+] Bridge already running.")

    # ==========================================
    # HEALTH CHECK
    # ==========================================

    print("[+] Running final application health checks...")

    # 1. Check if Chrome CDP is actually responding to HTTP requests
    chrome_healthy = http_is_healthy(f"http://127.0.0.1:{CHROME_PORT}/json/version")

    # 2. Check if the Bridge API is responding (Requires @app.get("/health") in rig.bridge)
    bridge_healthy = http_is_healthy(f"http://127.0.0.1:{BRIDGE_PORT}/health")

    if chrome_healthy and bridge_healthy:
        print("")
        print("======================================")
        print("AI BRIDGE READY")
        print("======================================")
        print("")
    else:
        print("[-] Bridge health check failed.")
        if not chrome_healthy:
            print(f"    -> Chrome CDP on port {CHROME_PORT} is unresponsive.")
        if not bridge_healthy:
            print(f"    -> Bridge API on port {BRIDGE_PORT} is unresponsive.")
        sys.exit(1)


if __name__ == "__main__":
    main()
