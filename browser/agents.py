"""Creates the Jev Ultrafast agent (or the fake one) and wraps the few Browser Harness calls we need."""
import logging
import threading

import config

log = logging.getLogger("browser.agents")

try:
    from jev_ultrafast.browser import StalePage
except Exception:   # jev-ultrafast not installed: only the fake agent can run
    class StalePage(ValueError):
        """A decision no longer refers to the observed page."""


def make_agent(url: str, goal: str):
    if config.FAKE:
        from fake_agent import FakeAgent
        return FakeAgent(url, goal)
    from jev_ultrafast import Agent
    return Agent(url, goal)


def chrome_ready() -> bool:
    """Cheap check that Browser Harness holds a live Chrome connection. Never blocks on Chrome's Allow prompt."""
    if config.FAKE:
        return True
    try:
        from browser_harness.admin import daemon_alive
        return bool(daemon_alive())
    except Exception as e:
        log.warning("harness check failed: %r", e)
        return False


def connect() -> bool:
    """Start the harness daemon. Can wait on Chrome's "Allow remote debugging?" prompt, so only run it off the request path."""
    if config.FAKE:
        return True
    try:
        from browser_harness.admin import ensure_daemon
        ensure_daemon()
        return True
    except Exception as e:
        log.error("could not connect to Chrome: %r", e)
        return False


_connecting = threading.Lock()


def reconnect_in_background() -> None:
    """After a "Chrome isn't connected" reply, try again off the request path so the next attempt can work."""
    if config.FAKE or not _connecting.acquire(blocking=False):
        return

    def run():
        try:
            connect()
        finally:
            _connecting.release()

    threading.Thread(target=run, name="harness-reconnect", daemon=True).start()


def activate(browser) -> None:
    """Bring the agent's tab to the front so judges watch it work (Jev opens it in the background)."""
    if config.FAKE:
        return
    try:
        from browser_harness.helpers import cdp
        cdp("Target.activateTarget", targetId=browser.target)
    except Exception as e:
        log.warning("could not foreground the tab: %r", e)


def navigate(browser, url: str) -> None:
    browser.call("Page.navigate", url=url)
