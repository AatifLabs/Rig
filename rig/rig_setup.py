"""
rig-setup — add / edit / delete a Chrome profile.

Model: one Chrome profile = one identity/account. ChatGPT, Claude, Google,
or anything else this identity needs all get logged into inside the SAME
profile — there's no per-provider subfolder.

This file is entirely disposable-tab / setup-time only. It never imports
or touches registry.py, never shares a Chrome process with the running
bridge, and never does `context.pages[0]` / positional tab access — it
always opens its own fresh page explicitly via `context.new_page()`.
"""

import os
import shutil
import sys

from playwright.sync_api import sync_playwright

from .chrome_launcher import launch_chrome_profile, get_free_port
from .providers import PROVIDER_URLS

# Same folder bridge.py / start_bridge.py use, no matter where rig-setup is run from.
PROFILES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profiles")


def list_profiles():
    if not os.path.isdir(PROFILES_DIR):
        return []
    return sorted(
        name for name in os.listdir(PROFILES_DIR)
        if os.path.isdir(os.path.join(PROFILES_DIR, name))
    )


def add_profile():
    profile_name = input("Profile name (e.g. personal, work): ").strip()
    if not profile_name:
        print("Profile name can't be empty.")
        return

    profile_dir = os.path.join(PROFILES_DIR, profile_name)
    is_new = not os.path.isdir(profile_dir)
    print(f"\n[+] {'Creating new' if is_new else 'Reopening existing'} profile: {profile_dir}")
    print("[+] Launching Chrome...")

    setup_port = get_free_port()
    proc, port = launch_chrome_profile(profile_dir, port=setup_port, headless=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://localhost:{port}")
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            # Disposable setup tab — always opened explicitly, never grabbed
            # positionally from whatever tabs happen to already be open.
            page = context.new_page()
            first_url = next(iter(PROVIDER_URLS.values()))
            page.goto(first_url, wait_until="domcontentloaded", timeout=30000)

            print("\nLog into whatever this profile needs (Google, then each provider).")
            print("Providers to check while you're in here:")
            for name, url in PROVIDER_URLS.items():
                print(f"  - {name}: {url}")
            input("\nPress Enter here once you're done logging in...")
    finally:
        print("[+] Closing Chrome...")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

    print(f"[+] Profile '{profile_name}' ready at {profile_dir}")


def edit_profile():
    profiles = list_profiles()
    if not profiles:
        print("No profiles exist yet.")
        return

    print("\nExisting profiles:")
    for i, name in enumerate(profiles, start=1):
        print(f"  {i}. {name}")

    choice = input(f"Pick a profile to rename [1-{len(profiles)}]: ").strip()
    if not choice.isdigit() or not (1 <= int(choice) <= len(profiles)):
        print("Invalid choice.")
        return

    old_name = profiles[int(choice) - 1]
    new_name = input(f"New name for '{old_name}': ").strip()
    if not new_name:
        print("Name can't be empty.")
        return

    old_dir = os.path.join(PROFILES_DIR, old_name)
    new_dir = os.path.join(PROFILES_DIR, new_name)
    if os.path.exists(new_dir):
        print(f"A profile named '{new_name}' already exists.")
        return

    os.rename(old_dir, new_dir)
    print(f"[+] Renamed '{old_name}' -> '{new_name}'")
    print("[!] Note: if the bridge has a running AccountHandle/sidecar state "
          "for the old name, restart the bridge so it re-derives state under "
          "the new name.")


def delete_profile():
    profiles = list_profiles()
    if not profiles:
        print("No profiles exist yet.")
        return

    print("\nExisting profiles:")
    for i, name in enumerate(profiles, start=1):
        print(f"  {i}. {name}")

    choice = input(f"Pick a profile to delete [1-{len(profiles)}]: ").strip()
    if not choice.isdigit() or not (1 <= int(choice) <= len(profiles)):
        print("Invalid choice.")
        return

    profile_name = profiles[int(choice) - 1]
    profile_dir = os.path.join(PROFILES_DIR, profile_name)

    confirm1 = input(
        f"Are you sure you want to delete profile '{profile_name}'? [y/N]: "
    ).strip().lower()
    if confirm1 != "y":
        print("Cancelled.")
        return

    confirm2 = input(
        f"This permanently deletes '{profile_dir}' and logs it out on this machine. "
        f"Type the profile name to confirm: "
    ).strip()
    if confirm2 != profile_name:
        print("Name didn't match. Cancelled.")
        return

    shutil.rmtree(profile_dir)
    print(f"[+] Deleted profile '{profile_name}'")
    print("[!] Note: if the bridge is currently running with this account live, "
          "it still holds an open Chrome process against the now-deleted "
          "directory — restart the bridge (or let it hit /session/new against "
          "a fresh account name) to clear that out.")


def main():
    print("rig-setup")
    print("  1. Add profile")
    print("  2. Edit profile (rename)")
    print("  3. Delete profile")
    choice = input("Choose an option [1-3]: ").strip()

    if choice == "1":
        add_profile()
    elif choice == "2":
        edit_profile()
    elif choice == "3":
        delete_profile()
    else:
        print("Invalid choice.")
        sys.exit(1)


if __name__ == "__main__":
    main()
