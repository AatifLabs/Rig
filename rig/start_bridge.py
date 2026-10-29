"""
rig-start — pick an account + provider, make sure the bridge is running,
then tell the bridge (over HTTP) to bring that account's Chrome up and
land the "code" session on the chosen provider.

BIG CHANGE from the old rig-start: this file used to launch Chrome itself
(find_chrome(), fixed port 9222, then a raw Playwright connect to click
page.goto on whatever tab it found). All of that ownership has moved into
registry.py, which now owns every Chrome process, one per account, on a
dynamically-allocated port. rig-start's only job now is:

  1. make sure the bridge process (the FastAPI app, fixed port 8080 — an
     application port, not a Chrome CDP port, so it's fine to keep static)
     is up
  2. ask the user which account + provider
  3. tell the bridge which one via /session/new, so the CHOICE actually
     reaches the part of the system that drives the browser — the old
     version's bug (picking a provider that the bridge never learned
     about) is fixed by construction: there is no other path to a live
     session except through this call.
  4. confirm it came up healthy

This intentionally no longer touches Playwright or Chrome directly at all.
"""

import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from .session_state import set_session
from .providers import PROVIDER_URLS
from . import bridge_client

BRIDGE_PORT = 8080
PROFILES_DIR = Path(__file__).parent / "profiles"
RUNTIME_DIR = Path(__file__).parent / ".rig_runtime"
BRIDGE_PID_FILE = RUNTIME_DIR / "bridge.pid"
BRIDGE_LOG_FILE = RUNTIME_DIR / "bridge.log"


def list_profiles():
    if not PROFILES_DIR.is_dir():
        return []
    return sorted(p.name for p in PROFILES_DIR.iterdir() if p.is_dir())


def port_open(port: int) -> bool:
    import socket
    s = socket.socket()
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def wait_for_port(port: int, timeout: int = 15) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        if port_open(port):
            return True
        time.sleep(0.3)
    return False


def http_is_healthy(url: str) -> bool:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


def choose_profile_and_provider():
    profiles = list_profiles()
    if not profiles:
        print("[-] No profiles found. Run rig-setup first to create one.")
        sys.exit(1)

    provider_names = list(PROVIDER_URLS.keys())
    provider_label = ", ".join(provider_names)

    print("\nAvailable profiles:")
    for i, name in enumerate(profiles, start=1):
        print(f"  {i}. {name}  ({provider_label})")

    while True:
        choice = input(f"\nPick a profile [1-{len(profiles)}]: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(profiles):
            profile_name = profiles[int(choice) - 1]
            break
        print("Invalid choice, try again.")

    print(f"\nProviders for '{profile_name}':")
    for i, name in enumerate(provider_names, start=1):
        print(f"  {i}. {name}")

    while True:
        choice = input(f"Pick a provider [1-{len(provider_names)}]: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(provider_names):
            provider_name = provider_names[int(choice) - 1]
            break
        print("Invalid choice, try again.")

    return profile_name, provider_name


def ensure_bridge_running():
    if port_open(BRIDGE_PORT):
        print("[+] Bridge already running.")
        return

    print("[+] Starting bridge server...")
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    log_file = open(BRIDGE_LOG_FILE, "a")

    # Detached from this terminal so the bridge keeps running after
    # rig-start exits; output goes to bridge.log instead of the terminal.
    popen_kwargs = {"stdout": log_file, "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL}
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True

    bridge_process = subprocess.Popen(
        [sys.executable, "-u", "-m", "rig.bridge"], **popen_kwargs
    )
    BRIDGE_PID_FILE.write_text(str(bridge_process.pid))

    print("[+] Waiting for Bridge server to initialize...")
    if not wait_for_port(BRIDGE_PORT, timeout=15):
        print("[-] Error: Bridge server failed to start on port 8080.")
        print(f"Bridge exited with code: {bridge_process.poll()}")
        print(f"See the log: {BRIDGE_LOG_FILE}")
        sys.exit(1)
    print(f"[+] Bridge running (pid {bridge_process.pid}), log: {BRIDGE_LOG_FILE}")

    # The FastAPI process is up, but /health only becomes meaningful once an
    # account exists — that happens via the /session/new call below, which
    # is what actually triggers registry.py to launch this account's Chrome.
    deadline = time.time() + 15
    while time.time() < deadline:
        if http_is_healthy(f"http://127.0.0.1:{BRIDGE_PORT}/health"):
            return
        time.sleep(0.3)
    print("[-] Error: Bridge API on port 8080 never became responsive.")
    sys.exit(1)


def main():
    profile_name, provider_name = choose_profile_and_provider()
    set_session("code", profile_name, provider_name)

    ensure_bridge_running()

    print(f"[+] Bringing up account '{profile_name}' on provider '{provider_name}'...")
    ok = bridge_client.clear_session(
        session_id="code", account=profile_name, provider=provider_name, timeout=60.0
    )
    if not ok:
        print("[-] Bridge failed to bring up the session. Check the bridge process's logs.")
        sys.exit(1)

    if not bridge_client.is_bridge_healthy(account=profile_name, session_id="code", timeout=10.0):
        print("[-] Session came up but health check did not report ready. "
              "It may still be loading — check the Chrome window the bridge opened.")
    else:
        print("")
        print("======================================")
        print("AI BRIDGE READY")
        print(f"account={profile_name} provider={provider_name}")
        print("======================================")
        print("")


if __name__ == "__main__":
    main()
