"""
Shared Chrome launching helper for Rig.

Used by:
  - rig_setup.py        (launches Chrome for manual login, then closes it)
  - bridge.py / runtime  (launches Chrome lazily per active profile, keeps it
                          alive for the session, connects to it over CDP)

This is the single place that knows how to find and start a debuggable
Chrome instance, so the launch logic never has to be duplicated or drift
apart between setup-time and runtime.
"""

import os
import platform
import shutil
import socket
import subprocess
import time


def detect_chrome_binary() -> str:
    """
    Find a Chrome/Chromium executable on this machine.
    Checks the most common binary names/paths per OS, in order, and
    returns the first one found. Raises RuntimeError if nothing matches.
    """
    system = platform.system()

    if system == "Linux":
        candidates = [
            "google-chrome-stable",
            "google-chrome",
            "chrome",
            "chromium",
            "chromium-browser",
        ]
        for name in candidates:
            path = shutil.which(name)
            if path:
                return path

    elif system == "Darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
        for path in candidates:
            if os.path.exists(path):
                return path

    elif system == "Windows":
        candidates = [
            os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            shutil.which("chrome.exe") or "",
        ]
        for path in candidates:
            if path and os.path.exists(path):
                return path

    raise RuntimeError(
        f"Could not find a Chrome/Chromium executable on this system ({system}). "
        "Install Google Chrome or Chromium, or add its path to "
        "chrome_launcher.detect_chrome_binary()."
    )


def _port_open(port: int) -> bool:
    s = socket.socket()
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def wait_for_port(port: int, timeout: int = 15) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        if _port_open(port):
            return True
        time.sleep(0.3)
    return False


def launch_chrome_profile(
    profile_dir: str,
    port: int = 9222,
    headless: bool = False,
) -> subprocess.Popen:
    """
    Launch Chrome with a given --user-data-dir (the profile) and a
    remote-debugging port, so Playwright can attach to it via CDP.

    This is THE single launch path:
      - rig-setup calls it, waits for manual login, then closes the
        returned process itself.
      - the runtime/bridge calls it lazily for whichever profile becomes
        active, and keeps the process alive for the duration of the
        session, connecting to it over CDP.

    Caller owns the returned process's lifetime (when to terminate it).
    """
    chrome_bin = detect_chrome_binary()
    os.makedirs(profile_dir, exist_ok=True)

    args = [
        chrome_bin,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={os.path.abspath(profile_dir)}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if headless:
        args.append("--headless=new")

    proc = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    if not wait_for_port(port, timeout=15):
        proc.terminate()
        raise RuntimeError(f"Chrome did not open debug port {port} within 15s.")

    return proc
