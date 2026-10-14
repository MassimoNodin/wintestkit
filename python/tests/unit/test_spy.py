"""Hook event swallowing and worker cleanup without global hooks."""

import ctypes
import threading
from typing import Any

import pytest
from fakes import FakeElement

from wintestkit.engine import spy
from wintestkit.uia import win32


def test_hook_swallowing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(win32, "CallNextHookEx", lambda *args: 42)
    monkeypatch.setattr(win32, "GetAsyncKeyState", lambda key: 0x8000)
    session = spy.SpySession(lambda el: None, lambda el: None, lambda: None)
    event = win32.MSLLHOOKSTRUCT()
    event.pt.x, event.pt.y = 10, 20
    address = ctypes.addressof(event)
    assert session._mouse_event(0, 0x0201, address) == 1
    assert session._events.get_nowait() == ("pick", 10, 20)
    assert session._mouse_event(0, 0x0202, address) == 1
    assert session._mouse_event(0, 0x0202, address) == 42
    assert session._mouse_event(-1, 0x0201, address) == 42
    keyboard = win32.KBDLLHOOKSTRUCT()
    keyboard.vkCode = 0x1B
    assert session._keyboard_event(0, 0x0100, ctypes.addressof(keyboard)) == 42
    assert session._events.get_nowait() == ("cancel", 0, 0)


def test_worker_survives_callback_and_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    closed = threading.Event()
    hovered = threading.Event()
    picked = threading.Event()
    cancelled = threading.Event()
    element = FakeElement("Button", "OK")
    element.process_id = 987

    class FakeOverlay:
        def show(self, rect: Any) -> None:
            hovered.set()

        def hide(self) -> None:
            pass

        def close(self) -> None:
            closed.set()

    def bad_hover(element: Any) -> None:
        raise RuntimeError("callback failed")

    def fake_hook(session: spy.SpySession) -> None:
        session._hook_ready.set()
        session._stop.wait(5)

    monkeypatch.setattr(spy, "Overlay", FakeOverlay)
    monkeypatch.setattr(spy, "from_point", lambda *coords: element)
    monkeypatch.setattr(spy.com, "ensure_com_initialized", lambda: None)
    monkeypatch.setattr(spy.SpySession, "_hook", fake_hook)
    session = spy.SpySession(bad_hover, lambda el: picked.set(), cancelled.set, throttle_ms=5)
    try:
        session.start()
        session.start()
        assert session.running
        session._events.put(("move", 10, 20))
        assert hovered.wait(2)
        session._events.put(("pick", 10, 20))
        assert picked.wait(2)
        session._events.put(("cancel", 0, 0))
        assert cancelled.wait(2)
    finally:
        session.stop()
        session.stop()
    assert closed.is_set()
    assert not session.running


def test_process_filter_and_own_process(monkeypatch: pytest.MonkeyPatch) -> None:
    element = FakeElement("Button", "OK")
    monkeypatch.setattr(spy, "from_point", lambda *coords: element)
    monkeypatch.setattr(spy.os, "getpid", lambda: 123)
    session = spy.SpySession(lambda el: None, lambda el: None, lambda: None, lambda pid: pid == 1)
    assert session._element_at(0, 0) is element
    element.process_id = 2
    assert session._element_at(0, 0) is None
    element.process_id = 123
    assert session._element_at(0, 0) is None


def test_invalid_throttle() -> None:
    with pytest.raises(ValueError):
        spy.SpySession(lambda el: None, lambda el: None, lambda: None, throttle_ms=0)
