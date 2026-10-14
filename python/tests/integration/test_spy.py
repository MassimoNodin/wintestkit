"""Real input hooks hover, swallow picks, cancel, and restart cleanly."""

import threading
import time

import pytest
from support import DemoProcess

from wintestkit.app import App
from wintestkit.engine.locator import Locator
from wintestkit.engine.resolve import Scope, resolve
from wintestkit.engine.spy import SpySession
from wintestkit.uia import input, win32
from wintestkit.uia.element import UIAElement

pytestmark = pytest.mark.integration


def test_spy_hooks_and_restart(demo_process: DemoProcess) -> None:
    app = App.attach(pid=demo_process.pid)
    assert win32.bring_to_foreground(demo_process.hwnd)
    button = resolve(Scope(app), Locator(control_type="Button", name="Sign in"))
    status_locator = Locator(automation_id="StatusText")
    before = resolve(Scope(app), status_locator).name
    hovered = threading.Event()
    picked = threading.Event()
    cancelled = threading.Event()

    def hover(element: UIAElement) -> None:
        if element.same_as(button):
            hovered.set()

    def pick(element: UIAElement) -> None:
        if element.same_as(button):
            picked.set()

    session = SpySession(hover, pick, cancelled.set, lambda pid: pid == demo_process.pid)
    try:
        session.start()
        rect = button.rect
        assert rect is not None
        input.move_mouse(rect.left + 1, rect.top + 1)
        input.move_mouse(*rect.center)
        assert hovered.wait(5)
        try:
            input._send([input._key_event(0x11, False)])
            time.sleep(0.05)
            input.click(*rect.center)
        finally:
            input._send([input._key_event(0x11, True)])
        assert picked.wait(5)
        time.sleep(0.1)
        assert resolve(Scope(app), status_locator).name == before
        input.press("Esc")
        assert cancelled.wait(5)
    finally:
        session.stop()
    assert not session.running
    assert session._mouse_hook is None
    assert session._keyboard_hook is None
    session.start()
    assert session.running
    session.stop()
    assert not session.running
