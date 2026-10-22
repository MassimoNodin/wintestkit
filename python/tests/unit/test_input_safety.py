"""Global input is mocked throughout: no desktop input or activation is permitted."""

from typing import Any

import pytest
from fakes import FakeElement

from wintestkit.engine import actions
from wintestkit.errors import ActionError
from wintestkit.uia import input, patterns, win32


@pytest.fixture
def target(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, list[str]]:
    control = FakeElement("Edit")
    calls: list[str] = []
    control.has_keyboard_focus = True
    monkeypatch.setattr(actions, "bring_to_front", lambda element: True)
    monkeypatch.setattr(actions, "_top_level_hwnd", lambda element: 100)
    monkeypatch.setattr(win32, "IsWindow", lambda hwnd: True)
    monkeypatch.setattr(win32, "window_pid", lambda hwnd: control.process_id)
    monkeypatch.setattr(win32, "GetForegroundWindow", lambda: 100)
    monkeypatch.setattr(win32, "WindowFromPoint", lambda point: 101)
    monkeypatch.setattr(win32, "root_window", lambda hwnd: 100)
    monkeypatch.setattr(actions.waits, "wait_for_state", lambda *args: None)
    monkeypatch.setattr(patterns, "has_pattern", lambda *args: False)
    monkeypatch.setattr(control, "set_focus", lambda: None, raising=False)
    for name in ("click", "move_mouse", "press", "type_text"):
        monkeypatch.setattr(input, name, lambda *args, _name=name, **kwargs: calls.append(_name))
    return control, calls


@pytest.mark.parametrize(
    "action",
    [
        actions.click,
        actions.hover,
        actions.clear,
        lambda element: actions.type_text(element, "sentinel"),
        lambda element: actions.press(element, "Enter"),
    ],
)
def test_activation_denied_never_injects(
    target: tuple[Any, list[str]], monkeypatch: pytest.MonkeyPatch, action: Any
) -> None:
    control, calls = target
    monkeypatch.setattr(actions, "bring_to_front", lambda element: False)
    with pytest.raises(ActionError, match="refusing global input"):
        action(control)
    assert calls == []


@pytest.mark.parametrize("failure", ["missing", "destroyed", "owner", "foreground", "hit"])
def test_mouse_requires_live_owned_foreground_and_unobscured_point(
    target: tuple[Any, list[str]], monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    control, calls = target
    if failure == "missing":
        monkeypatch.setattr(actions, "_top_level_hwnd", lambda element: 0)
    elif failure == "destroyed":
        monkeypatch.setattr(win32, "IsWindow", lambda hwnd: False)
    elif failure == "owner":
        monkeypatch.setattr(win32, "window_pid", lambda hwnd: 999)
    elif failure == "foreground":
        monkeypatch.setattr(win32, "GetForegroundWindow", lambda: 999)
    else:
        monkeypatch.setattr(win32, "root_window", lambda hwnd: 999)
    with pytest.raises(ActionError, match="refusing global input"):
        actions.click(control)
    assert calls == []


def test_keyboard_requires_control_focus(target: tuple[Any, list[str]]) -> None:
    control, calls = target
    control.has_keyboard_focus = False
    with pytest.raises(ActionError, match="keyboard focus"):
        actions.type_text(control, "sentinel")
    assert calls == []


def test_mouse_rechecks_after_waiting_for_stability(
    target: tuple[Any, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    control, calls = target

    def lose_foreground(*args: Any) -> None:
        monkeypatch.setattr(win32, "GetForegroundWindow", lambda: 999)

    monkeypatch.setattr(actions.waits, "wait_for_state", lose_foreground)
    with pytest.raises(ActionError, match="foreground changed"):
        actions.click(control)
    assert calls == []


def test_mouse_rejects_foreign_child_in_owned_window(
    target: tuple[Any, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    control, calls = target
    monkeypatch.setattr(win32, "window_pid", lambda hwnd: control.process_id if hwnd == 100 else 999)
    with pytest.raises(ActionError, match="another window"):
        actions.click(control)
    assert calls == []


def test_keyboard_rechecks_before_text(
    target: tuple[Any, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    control, calls = target

    def lose_focus(*args: Any) -> None:
        calls.append("press")
        control.has_keyboard_focus = False

    monkeypatch.setattr(input, "press", lose_focus)
    with pytest.raises(ActionError, match="keyboard focus"):
        actions.type_text(control, "sentinel")
    assert calls == ["press"]


def test_validated_mouse_and_keyboard_paths(target: tuple[Any, list[str]]) -> None:
    control, calls = target
    actions.click(control)
    actions.hover(control)
    actions.type_text(control, "sentinel")
    assert calls == ["click", "move_mouse", "press", "type_text"]


def test_foreground_activation_never_uses_synthetic_alt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(win32, "IsIconic", lambda hwnd: False)
    monkeypatch.setattr(win32, "GetForegroundWindow", lambda: 999)
    monkeypatch.setattr(win32, "AllowSetForegroundWindow", lambda *args: True)
    monkeypatch.setattr(win32, "SetForegroundWindow", lambda *args: False)
    monkeypatch.setattr(win32, "BringWindowToTop", lambda *args: False)
    monkeypatch.setattr(win32, "_tap_alt", lambda: pytest.fail("unsafe synthetic Alt"))
    assert not win32.bring_to_foreground(100, timeout=0)
