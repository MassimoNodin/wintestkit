"""Overlay lifecycle tests without a fixture app."""

import threading

import pytest

from wintestkit.engine import overlay
from wintestkit.engine.overlay import Overlay

pytestmark = pytest.mark.integration


def overlay_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == "wtk-overlay" and t.is_alive()]


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
