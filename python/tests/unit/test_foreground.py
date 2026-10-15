"""Resolve child controls to their owning native window without interacting with them."""

import pytest
from fakes import FakeElement

from wintestkit.engine import actions
from wintestkit.uia import win32


@pytest.mark.parametrize("child_handle", [0, 101])
def test_child_raises_owning_window(monkeypatch: pytest.MonkeyPatch, child_handle: int) -> None:
    child = FakeElement("Button", "Save")
    root = FakeElement("Window", "Demo", children=[child])
    root.native_window_handle = 100
    child.native_window_handle = child_handle
    resolved: list[int] = []
    raised: list[int] = []

    def root_window(handle: int) -> int:
        resolved.append(handle)
        return 100

    def foreground(handle: int) -> bool:
        raised.append(handle)
        return True

    monkeypatch.setattr(win32, "root_window", root_window)
    monkeypatch.setattr(win32, "bring_to_foreground", foreground)
    assert actions.bring_to_front(child)
    assert resolved == [child_handle or 100]
    assert raised == [100]
    assert not child.has_keyboard_focus


def test_foreground_denied_is_best_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    root = FakeElement("Window", "Demo")
    monkeypatch.setattr(win32, "root_window", lambda handle: 100)
    monkeypatch.setattr(win32, "bring_to_foreground", lambda handle: False)
    assert not actions.bring_to_front(root)


def test_no_native_window_does_not_activate_another_app(monkeypatch: pytest.MonkeyPatch) -> None:
    root = FakeElement("Pane", "Desktop")
    root.native_window_handle = 0

    def unexpected(handle: int) -> bool:
        pytest.fail("must not activate a window without a native handle")

    monkeypatch.setattr(win32, "bring_to_foreground", unexpected)
    assert not actions.bring_to_front(root)
