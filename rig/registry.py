"""
Registry — the ownership hierarchy for Rig's bridge process.

    Registry (singleton, lives for the bridge process's lifetime)
      └─ AccountHandle (one per account, created lazily on first use)
           ├─ profile_dir, chrome_process, cdp_port (dynamic)
           ├─ browser / context  (ONE BrowserContext per account)
           └─ sessions: dict[session_id -> SessionHandle]
                            ├─ page      (this session's tab)
                            ├─ provider  (mutable independently of page)
                            └─ lock      (identity never changes)

Only code in this file may call `context.new_page()` or touch
`context.pages` / `browser.contexts`. bridge.py, rig_setup.py, and
rig_start.py must go through this module for anything touching a real
browser tab.

JUDGMENT CALLS (flagged per the rearchitecture prompt's request):
  - Liveness check for a Browser is `Browser.is_connected()` plus checking
    the tracked Chrome subprocess hasn't exited. This doesn't guarantee the
    *page* is usable (a single tab can still die independently) — that's
    covered separately by the Target-closed retry in `run_turn`.
  - Port-allocation retry count on launch failure: 3 attempts.
  - Orphan-recovery sidecar file: `<profiles_dir>/../.rig_runtime/<account>.json`
    storing {"port": N, "pid": N} for the Chrome subprocess of each account,
    written after every successful launch/attach and used to re-attach to a
    still-alive Chrome after the bridge process itself restarts (rather than
    launching a second Chrome on the same profile, which Chrome will refuse).
  - "Target closed" detection matches on exception message substrings
    (Playwright doesn't expose one stable public exception type for this
    across versions) — see `is_target_closed_error`.
"""

import asyncio
import json
import os
import signal
from pathlib import Path

from playwright.async_api import async_playwright

from .chrome_launcher import (
    launch_chrome_profile,
    clean_stale_singleton_lock,
    is_pid_alive,
)
from .providers import ADAPTERS, get_adapter


PORT_LAUNCH_RETRIES = 3


def is_target_closed_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(
        needle in msg
        for needle in (
            "target closed",
            "target page, context or browser has been closed",
            "has been closed",
            "browser has been closed",
        )
    )


class AdoptedProcess:
    """
    Duck-types the bits of subprocess.Popen that registry.py needs, for a
    Chrome process we didn't spawn ourselves (recovered from the sidecar
    file after a bridge restart) but still want to track/terminate the
    same way as one we launched directly.
    """

    def __init__(self, pid: int):
        self.pid = pid

    def poll(self):
        return None if is_pid_alive(self.pid) else 1

    def terminate(self):
        try:
            os.kill(self.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


class SessionHandle:
    """One browser tab + which provider adapter is currently driving it."""

    def __init__(self, session_id: str, page, provider: str):
        self.session_id = session_id
        self.page = page
        self.provider = provider
        # Created once, identity never changes across /clear or provider
        # switches — every mutation path for this session's `page` must
        # acquire this same lock object.
        self.lock = asyncio.Lock()


class AccountHandle:
    """
    One Chrome process + one BrowserContext for one account (profile dir),
    holding all of that account's sessions.
    """

    def __init__(self, account_name: str, profile_dir: Path, runtime_state_dir: Path):
        self.account_name = account_name
        self.profile_dir = profile_dir
        self._state_file = runtime_state_dir / f"{account_name}.json"

        self.chrome_process = None
        self.cdp_port = None
        self.playwright_instance = None
        self.browser = None
        self.context = None

        self.sessions: dict[str, SessionHandle] = {}

        # Guards (re)launch of this account's Chrome/browser/context —
        # deliberately separate from any session's lock, since relaunching
        # the browser affects every session under this account at once.
        self._lifecycle_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Liveness / (re)launch
    # ------------------------------------------------------------------

    def _is_alive(self) -> bool:
        if self.chrome_process is None or self.browser is None:
            return False
        if self.chrome_process.poll() is not None:
            return False
        try:
            return self.browser.is_connected()
        except Exception:
            return False

    async def ensure_alive(self):
        """Call before using this account for anything. Relaunches if dead."""
        async with self._lifecycle_lock:
            if self._is_alive():
                return
            await self._teardown(quiet=True)
            await self._launch_or_attach()

    def _read_state_file(self):
        try:
            with open(self._state_file) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def _write_state_file(self, port: int, pid: int):
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._state_file, "w") as f:
            json.dump({"port": port, "pid": pid}, f)

    async def _try_attach_to_orphan(self) -> bool:
        """
        If a previous bridge process launched this account's Chrome and then
        crashed/restarted, the Chrome subprocess may still be alive. Check
        the sidecar state file; if the pid is alive and the CDP port still
        responds, attach to it instead of launching a second Chrome on the
        same profile (which Chrome will refuse to do anyway).
        """
        state = self._read_state_file()
        if not state:
            return False

        port, pid = state.get("port"), state.get("pid")
        if not port or not pid or not is_pid_alive(pid):
            return False

        try:
            self.playwright_instance = await async_playwright().start()
            self.browser = await self.playwright_instance.chromium.connect_over_cdp(
                f"http://localhost:{port}"
            )
        except Exception as e:
            print(f"-> [{self.account_name}] Orphan attach failed ({e}), will relaunch")
            try:
                await self.playwright_instance.stop()
            except Exception:
                pass
            self.playwright_instance = None
            return False

        self.chrome_process = AdoptedProcess(pid)
        self.cdp_port = port
        await self._prepare_context()
        print(f"-> [{self.account_name}] Re-attached to orphaned Chrome on port {port} (pid {pid})")
        return True

    async def _launch_or_attach(self):
        if await self._try_attach_to_orphan():
            return

        cleaned = clean_stale_singleton_lock(str(self.profile_dir))
        if cleaned:
            print(f"-> [{self.account_name}] Cleaned stale SingletonLock")

        last_error = None
        for attempt in range(1, PORT_LAUNCH_RETRIES + 1):
            try:
                proc, port = launch_chrome_profile(str(self.profile_dir), port=None, headless=False)
                self.chrome_process = proc
                self.cdp_port = port
                break
            except Exception as e:
                last_error = e
                print(f"-> [{self.account_name}] Launch attempt {attempt} failed: {e}")
        else:
            raise RuntimeError(
                f"Could not launch Chrome for account '{self.account_name}' "
                f"after {PORT_LAUNCH_RETRIES} attempts: {last_error}"
            )

        self.playwright_instance = await async_playwright().start()
        self.browser = await self.playwright_instance.chromium.connect_over_cdp(
            f"http://localhost:{self.cdp_port}"
        )
        await self._prepare_context()
        self._write_state_file(self.cdp_port, self.chrome_process.pid)
        print(f"-> [{self.account_name}] Chrome launched on port {self.cdp_port}")

    async def _prepare_context(self):
        # ONE BrowserContext per account — reuse Chrome's default context if
        # present, otherwise create the one context this account will ever
        # use. This is the single sanctioned place `browser.contexts` is
        # touched; it is not the "grab an arbitrary open tab" pattern the
        # rearchitecture prompt bans (that's specifically about
        # `context.pages[0]`, handled below in get_or_create_session).
        self.context = self.browser.contexts[0] if self.browser.contexts else await self.browser.new_context()

        for name, adapter in ADAPTERS.items():
            install = getattr(adapter, "install_context", None)
            if install:
                try:
                    await install(self.context)
                except Exception as e:
                    print(f"-> [{self.account_name}] install_context for '{name}' failed: {e}")

    async def _teardown(self, quiet: bool = False):
        if not quiet:
            print(f"-> [{self.account_name}] Tearing down...")
        try:
            if self.browser:
                await self.browser.close()
        except Exception:
            pass
        try:
            if self.playwright_instance:
                await self.playwright_instance.stop()
        except Exception:
            pass
        self.browser = None
        self.context = None
        self.playwright_instance = None
        # Note: chrome_process itself is intentionally left running here —
        # tearing down our Playwright connection doesn't mean we want to
        # kill the user's browser; only shutdown() (full bridge stop) or an
        # explicit account removal terminates the actual process.

    async def shutdown(self):
        """Full teardown, including killing this account's Chrome process."""
        for session in list(self.sessions.values()):
            try:
                await session.page.close()
            except Exception:
                pass
        self.sessions.clear()
        await self._teardown()
        if self.chrome_process:
            try:
                self.chrome_process.terminate()
            except Exception:
                pass
        try:
            self._state_file.unlink()
        except FileNotFoundError:
            pass

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    async def get_or_create_session(self, session_id: str, provider: str) -> SessionHandle:
        """
        The single source of truth for "give me a session's tab". Never
        uses `context.pages[0]` or any positional access — every tab is
        created explicitly via `context.new_page()` and stored by
        session_id, exactly once.
        """
        if session_id in self.sessions:
            return self.sessions[session_id]

        adapter = get_adapter(provider)
        print(f"-> [{self.account_name}:{session_id}] No tab yet, creating new one (provider={provider})...")
        page = await self.context.new_page()
        await page.goto(adapter.URL, wait_until="domcontentloaded", timeout=30000)
        session = SessionHandle(session_id, page, provider)
        self.sessions[session_id] = session
        return session

    async def reset_session(self, session_id: str, provider: str | None = None) -> SessionHandle:
        """
        /clear semantics: reuse the SAME lock object, close the OLD page
        before replacing it, land on a fresh chat for the (possibly
        unchanged) provider.
        """
        if session_id not in self.sessions:
            return await self.get_or_create_session(session_id, provider or "gpt")

        session = self.sessions[session_id]
        async with session.lock:
            if provider:
                session.provider = provider
            adapter = get_adapter(session.provider)

            old_page = session.page
            new_page = await self.context.new_page()
            await new_page.goto(adapter.URL, wait_until="domcontentloaded", timeout=30000)
            try:
                await adapter.reset(new_page)
            except Exception as e:
                print(f"-> [{self.account_name}:{session_id}] adapter.reset failed (non-fatal): {e}")

            session.page = new_page
            try:
                await old_page.close()
            except Exception:
                pass

        return session

    async def switch_provider(self, session_id: str, new_provider: str) -> SessionHandle:
        """
        Provider is mutable independently of `page` — this does NOT create
        a new tab/session. It navigates the SAME tab to the new provider's
        site and just repoints session.provider at the new adapter.
        """
        session = self.sessions.get(session_id)
        if session is None:
            return await self.get_or_create_session(session_id, new_provider)

        adapter = get_adapter(new_provider)
        async with session.lock:
            await session.page.goto(adapter.URL, wait_until="domcontentloaded", timeout=30000)
            session.provider = new_provider
        return session

    async def recreate_session_page(self, session: SessionHandle):
        """
        Called when a session's page is found dead (Target closed). Must be
        called with session.lock already held by the caller.
        """
        adapter = get_adapter(session.provider)
        try:
            await session.page.close()
        except Exception:
            pass
        new_page = await self.context.new_page()
        await new_page.goto(adapter.URL, wait_until="domcontentloaded", timeout=30000)
        session.page = new_page


class Registry:
    """Singleton owning every AccountHandle for the bridge process's life."""

    def __init__(self, profiles_dir: Path):
        self.profiles_dir = profiles_dir
        self.runtime_state_dir = profiles_dir.parent / ".rig_runtime"
        self.accounts: dict[str, AccountHandle] = {}
        # Guards creation of a brand new AccountHandle object (not its
        # Chrome launch, which AccountHandle._lifecycle_lock covers) so two
        # concurrent requests for a never-seen-before account name can't
        # both construct separate AccountHandle objects for the same name.
        self._accounts_lock = asyncio.Lock()

    async def get_account(self, account_name: str) -> AccountHandle:
        if account_name not in self.accounts:
            async with self._accounts_lock:
                if account_name not in self.accounts:
                    profile_dir = self.profiles_dir / account_name
                    self.accounts[account_name] = AccountHandle(
                        account_name, profile_dir, self.runtime_state_dir
                    )
        account = self.accounts[account_name]
        await account.ensure_alive()
        return account

    async def run_turn(self, account_name: str, session_id: str, provider: str, prompt: str) -> str:
        """
        Full request path: get account -> get/create session -> send ->
        wait -> extract, all under the session's own lock (never a global
        lock), with one retry if the page turns out to be dead.
        """
        account = await self.get_account(account_name)
        session = await account.get_or_create_session(session_id, provider)

        # Session's provider may have been switched since creation by a
        # concurrent /use — always drive with whatever it currently says.
        async with session.lock:
            if session.provider != provider:
                # Caller explicitly asked for a different provider than the
                # session currently has — treat as a provider switch made
                # inline with this request rather than silently ignoring it.
                adapter = get_adapter(provider)
                await session.page.goto(adapter.URL, wait_until="domcontentloaded", timeout=30000)
                session.provider = provider

            adapter = get_adapter(session.provider)

            async def _turn():
                await adapter.send_message(session.page, prompt)
                await adapter.wait_until_done(session.page)
                return await adapter.get_response(session.page)

            try:
                return await _turn()
            except Exception as e:
                if not is_target_closed_error(e):
                    raise
                print(f"-> [{account_name}:{session_id}] Page died mid-turn ({e}), recreating and retrying once")
                await account.recreate_session_page(session)
                return await _turn()

    async def shutdown_all(self):
        for account in list(self.accounts.values()):
            await account.shutdown()
        self.accounts.clear()
