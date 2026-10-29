"""
Shared Chrome launching helper for Rig.

Used by:
  - rig_setup.py   (launches a disposable Chrome for manual login, closes it
                     itself, never touches the bridge's registry/browser)
  - registry.py    (launches Chrome lazily per AccountHandle, keeps it alive
                     for the process's life, connects to it over CDP)

This is the single place that knows how to find/start a debuggable Chrome
instance and how to detect+clean a stale profile lock, so that logic never
drifts apart between setup-time and runtime.

JUDGMENT CALLS (not specified in the rearchitecture prompt, called out here):
  - Free-port allocation binds to port 0, reads back the OS-assigned port,
    then closes the socket before handing it to Chrome. There's an inherent
    TOCTOU race (something else could grab the port between our close() and
    Chrome's bind()) — kept the retry loop in registry.py at 3 attempts to
    absorb that rather than adding a dependency to hold the port open.
  - Stale-lock detection uses os.kill(pid, 0): ProcessLookupError -> treat
    as dead/stale and clean it up; PermissionError -> pid exists but is
    owned by another user, treated as "still alive", left untouched.
"""

import os
import platform
import shutil
import socket
import subprocess
import time
from pathlib import Path

SINGLETON_FILES = ("SingletonLock", "SingletonCookie", "SingletonSocket")


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


def get_free_port() -> int:
    """
    Ask the OS for a free port by binding to port 0 and reading back what
    it assigned. Never hardcode a CDP port anywhere else.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


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


def is_pid_alive(pid: int) -> bool:
    """True if a process with this pid exists and we can at least see it."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Exists, just owned by someone else — treat as alive.
        return True
    except Exception:
        return False


def clean_stale_singleton_lock(profile_dir: str) -> bool:
    """
    Chrome writes SingletonLock (a symlink encoding "hostname-pid") into a
    profile dir it owns. If the bridge crashed uncleanly, that lock can be
    left behind pointing at a pid that's no longer running, which makes a
    fresh Chrome launch on that profile fail with a confusing error.

    Checks whether the pid encoded in the lock is still alive:
      - alive  -> do nothing, return False (not stale, don't touch a real
                  running Chrome instance)
      - dead / unreadable -> remove the Singleton* files, return True

    Callers should call this before launching Chrome on a profile whenever
    they don't already have a live, tracked handle for it (see registry.py's
    orphan-recovery path, which checks a sidecar pid/port file first and
    only falls through to this when that check fails).
    """
    profile_path = Path(profile_dir)
    lock_file = profile_path / "SingletonLock"

    if not lock_file.exists() and not lock_file.is_symlink():
        return False

    pid = None
    try:
        target = os.readlink(lock_file)
        _, _, pid_str = target.rpartition("-")
        pid = int(pid_str)
    except (OSError, ValueError):
        pid = None

    if pid is not None and is_pid_alive(pid):
        return False  # a real Chrome may still be holding this profile

    for name in SINGLETON_FILES:
        p = profile_path / name
        try:
            p.unlink()
        except FileNotFoundError:
            pass
        except Exception:
            pass
    return True


def launch_chrome_profile(
    profile_dir: str,
    port: int | None = None,
    headless: bool = False,
) -> tuple[subprocess.Popen, int]:
    """
    Launch Chrome with a given --user-data-dir (the profile) and a
    remote-debugging port, so Playwright can attach to it via CDP.

    If `port` is None, a free port is allocated dynamically. Returns
    (process, port_used) so callers that didn't pick the port can still
    record it (registry.py persists this in its sidecar state file).

    This is THE single launch path:
      - rig-setup calls it for a disposable login tab, then closes the
        returned process itself.
      - registry.py calls it lazily for whichever account becomes active,
        and keeps the process alive for the duration of the session,
        connecting to it over CDP.

    Caller owns the returned process's lifetime (when to terminate it).
    Caller is also responsible for calling clean_stale_singleton_lock()
    first if appropriate — this function does not do that itself, since
    whether a stale lock is safe to clean depends on context registry.py
    has (a sidecar pid/port record) that this generic helper doesn't.
    """
    chrome_bin = detect_chrome_binary()
    os.makedirs(profile_dir, exist_ok=True)

    if port is None:
        port = get_free_port()

    args = [
        chrome_bin,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={os.path.abspath(profile_dir)}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if headless:
        args.append("--headless=new")

    # Chrome's own output goes to .rig_runtime/chrome-<profile>.log so
    # crashes can be diagnosed instead of vanishing.
    log_dir = Path(__file__).parent / ".rig_runtime"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = open(log_dir / f"chrome-{Path(profile_dir).name}.log", "w")

    proc = subprocess.Popen(
        args,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )

    if not wait_for_port(port, timeout=15):
        proc.terminate()
        raise RuntimeError(f"Chrome did not open debug port {port} within 15s.")

    return proc, port
