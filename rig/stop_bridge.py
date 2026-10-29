"""
rig-stop — stop the bridge and every Chrome window it launched.

1. Ask the bridge to shut down (SIGTERM). Its shutdown hook closes each
   account's Chrome cleanly.
2. Anything still alive after that (bridge crashed, or Chrome orphaned)
   is killed using the pid files in .rig_runtime/.
"""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from .chrome_launcher import is_pid_alive

RUNTIME_DIR = Path(__file__).parent / ".rig_runtime"
BRIDGE_PID_FILE = RUNTIME_DIR / "bridge.pid"


def _kill(pid: int, timeout: float = 5.0) -> bool:
    """SIGTERM, wait, then SIGKILL. Returns True if the process is gone."""
    if not is_pid_alive(pid):
        return True
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return not is_pid_alive(pid)

    deadline = time.time() + timeout
    while time.time() < deadline:
        if not is_pid_alive(pid):
            return True
        time.sleep(0.2)

    if sys.platform != "win32":
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    time.sleep(0.2)
    return not is_pid_alive(pid)


def _read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def stop_bridge() -> bool:
    stopped = False

    pid = _read_pid(BRIDGE_PID_FILE)
    if pid and is_pid_alive(pid):
        # Longer timeout: the bridge closes Chrome windows during shutdown.
        stopped = _kill(pid, timeout=10.0)
    BRIDGE_PID_FILE.unlink(missing_ok=True)

    # Fallback for a bridge started some other way (e.g. `python -m rig.bridge`).
    if sys.platform != "win32":
        result = subprocess.run(["pkill", "-f", r"rig\.bridge$"], capture_output=True)
        if result.returncode == 0:
            stopped = True

    return stopped


def stop_orphaned_chrome() -> int:
    """Kill any account Chrome the bridge didn't close. Returns how many."""
    killed = 0
    if not RUNTIME_DIR.is_dir():
        return 0

    for state_file in RUNTIME_DIR.glob("*.json"):
        try:
            pid = json.loads(state_file.read_text()).get("pid")
        except (OSError, ValueError):
            pid = None

        if pid and is_pid_alive(pid) and _kill(pid):
            killed += 1
        state_file.unlink(missing_ok=True)

    return killed


def main():
    bridge_stopped = stop_bridge()
    chrome_killed = stop_orphaned_chrome()

    if bridge_stopped:
        print("[+] Bridge stopped.")
    else:
        print("[i] Bridge was not running.")

    if chrome_killed:
        print(f"[+] Closed {chrome_killed} leftover Chrome window(s).")


if __name__ == "__main__":
    main()
