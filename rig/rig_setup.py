
"""
rig-setup — provisions a Chrome profile.

Model: one Chrome profile = one identity/account. ChatGPT, Claude, Google,
or anything else this identity needs all get logged into inside the SAME
profile — there's no per-provider subfolder.

Usage:
    python rig_setup.py

Flow:
  1. Ask for a profile name.
  2. Launch Chrome on profiles/{profile_name} (creates the folder if it's
     new, reuses it as-is if it already exists — same code path either
     way, no separate add/edit mode).
  3. Land on the first known provider as a starting point.
  4. User manually logs into whatever this profile needs.
  5. User presses Enter here when done.
  6. Chrome closes. Done.

Directory contract: profiles/{profile_name}/ is Chrome's user-data-dir
and NOTHING else writes into it — no metadata, no config files. If this
identity's login expires later, re-running rig-setup on the same name
just reopens that same profile for re-login.
"""

import os
import sys

from playwright.sync_api import sync_playwright

from chrome_launcher import launch_chrome_profile
from providers import PROVIDERS

PROFILES_DIR = "profiles"
SETUP_DEBUG_PORT = 9222  # setup only ever runs one Chrome at a time


def main():
    profile_name = input("Profile name (e.g. personal, work): ").strip()
    if not profile_name:
        print("Profile name can't be empty.")
        sys.exit(1)

    profile_dir = os.path.join(PROFILES_DIR, profile_name)
    is_new = not os.path.isdir(profile_dir)

    print(f"\n[+] {'Creating new' if is_new else 'Reopening existing'} profile: {profile_dir}")
    print("[+] Launching Chrome...")

    proc = launch_chrome_profile(profile_dir, port=SETUP_DEBUG_PORT, headless=False)

    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://localhost:{SETUP_DEBUG_PORT}")
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.pages[0] if context.pages else context.new_page()

            # Land on the first known provider as a starting point. The user
            # is free to navigate anywhere from here (Google, ChatGPT,
            # Claude, whatever else this identity needs) — setup doesn't
            # enforce a sequence.
            first_url = next(iter(PROVIDERS.values()))["url"]
            page.goto(first_url, wait_until="domcontentloaded", timeout=30000)

            print("\nLog into whatever this profile needs (Google, then each provider).")
            print("Providers to check while you're in here:")
            for name, meta in PROVIDERS.items():
                print(f"  - {name}: {meta['url']}")
            input("\nPress Enter here once you're done logging in...")
    finally:
        print("[+] Closing Chrome...")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

    print(f"[+] Profile '{profile_name}' ready at {profile_dir}")


if __name__ == "__main__":
    main()
