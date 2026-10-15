"""Integration tests for the highlight overlay."""

import ctypes
import threading
import time
from ctypes import wintypes

import pytest
from support import DemoProcess, decode_png_rgb

from wintestkit.app import App
from wintestkit.engine import overlay
from wintestkit.engine.locator import Locator
from wintestkit.engine.overlay import Overlay, flash
from wintestkit.engine.resolve import Scope, resolve
from wintestkit.uia import input, screenshot, win32

pytestmark = pytest.mark.integration


def sign_in_rect(demo: DemoProcess):
    scope = Scope(App.attach(pid=demo.pid))
    button = resolve(scope, Locator(control_type="Button", name="Sign in"))
    assert button.rect is not None
    return scope, button, button.rect


def overlay_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == "wtk-overlay" and t.is_alive()]


def test_flash_blocks_for_the_duration(demo_process: DemoProcess) -> None:
    _, _, rect = sign_in_rect(demo_process)
    started = time.monotonic()
    flash(rect, 800, block=True)
    elapsed = time.monotonic() - started
    assert 0.7 <= elapsed <= 2.0
    assert not overlay_threads()


def test_flash_without_blocking_returns_immediately(demo_process: DemoProcess) -> None:
    _, _, rect = sign_in_rect(demo_process)
    started = time.monotonic()
    flash(rect, 400, blink=False)
    assert time.monotonic() - started < 0.3
    deadline = time.monotonic() + 3
    while overlay_threads() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not overlay_threads()


def test_overlay_is_click_through_and_does_not_steal_focus(demo_process: DemoProcess) -> None:
    scope, button, rect = sign_in_rect(demo_process)
    status = resolve(scope, Locator(automation_id="StatusText"))
    assert win32.bring_to_foreground(demo_process.hwnd)
    with Overlay() as shown:
        shown.show(rect)
        assert win32.IsWindowVisible(shown.hwnd)
        assert win32.GetForegroundWindow() == demo_process.hwnd
        input.click(*rect.center)
        deadline = time.monotonic() + 5
        while status.name != "Invalid credentials" and time.monotonic() < deadline:
            time.sleep(0.05)
        assert status.name == "Invalid credentials"
        assert win32.GetForegroundWindow() == demo_process.hwnd
        assert button.is_alive()
    assert not overlay_threads()


def test_overlay_geometry_and_rendering(demo_process: DemoProcess) -> None:
    _, _, rect = sign_in_rect(demo_process)
    assert win32.bring_to_foreground(demo_process.hwnd)
    with Overlay(thickness=4) as shown:
        shown.show(rect)
        window_rect = wintypes.RECT()
        win32.user32.GetWindowRect(wintypes.HWND(shown.hwnd), ctypes.byref(window_rect))
        assert (window_rect.left, window_rect.top) == (rect.left, rect.top)
        assert window_rect.right - window_rect.left == rect.width
        assert window_rect.bottom - window_rect.top == rect.height
        time.sleep(0.2)  # let DWM compose the layered window
        png = screenshot.capture(rect)
        _, _, pixels = decode_png_rgb(png)
        triples = {pixels[i : i + 3] for i in range(0, len(pixels), 3)}
        assert b"\xff\x00\x00" in triples, "outline colour was not drawn"
        assert b"\xff\x00\xff" not in triples, "colour-key magenta must be transparent"

        shown.show(rect.inflate(-10))  # repositions while visible
        shown.hide()
        assert not win32.IsWindowVisible(shown.hwnd)


def test_close_leaves_no_thread_and_is_idempotent() -> None:
    before = len(overlay_threads())
    shown = Overlay()
    assert len(overlay_threads()) == before + 1
    shown.close()
    shown.close()
    assert len(overlay_threads()) == before
    shown.show(overlay.Rect(0, 0, 10, 10))  # no-op after close, must not raise
    assert not shown.is_alive()


def test_many_overlays_can_coexist() -> None:
    with Overlay() as first, Overlay(color=0x0000FF00) as second:
        assert first.hwnd != second.hwnd
