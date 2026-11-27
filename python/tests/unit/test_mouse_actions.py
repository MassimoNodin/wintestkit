"""Positioned and modified clicks, drags and wheel input; global input is always mocked."""

from typing import Any

import pytest
from fakes import FakeElement

from wintestkit.engine import actions
from wintestkit.errors import ActionError
from wintestkit.uia import input, patterns, win32
from wintestkit.uia.element import Rect

CTRL, SHIFT = 0x11, 0x10


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[list[Any]]:
    """Capture every SendInput batch as decoded tuples."""
    batches: list[list[Any]] = []

    def decode(event: Any) -> tuple[Any, ...]:
        if event.type == win32.INPUT_KEYBOARD:
            return ("key", event.ki.wVk, bool(event.ki.dwFlags & win32.KEYEVENTF_KEYUP))
        flags = event.mi.dwFlags
        if flags & win32.MOUSEEVENTF_MOVE:
            return ("move",)
        return ("mouse", flags, event.mi.mouseData)

    monkeypatch.setattr(input, "_send", lambda events: batches.append([decode(e) for e in events]))
    monkeypatch.setattr(input.time, "sleep", lambda _: None)
    monkeypatch.setattr(win32, "MapVirtualKeyW", lambda vk, kind: 0)
    monkeypatch.setattr(win32, "virtual_screen_rect", lambda: Rect(0, 0, 1920, 1080))
    monkeypatch.setattr(win32, "GetSystemMetrics", lambda index: 4)
    return batches


def flat(batches: list[list[Any]]) -> list[Any]:
    return [event for batch in batches for event in batch]


# -- input layer ------------------------------------------------------------------------------


def test_parse_modifiers() -> None:
    assert input.parse_modifiers(None) == ()
    assert input.parse_modifiers("Ctrl+shift") == (CTRL, SHIFT)
    assert input.parse_modifiers("Control+Ctrl") == (CTRL,)
    with pytest.raises(ValueError, match="unknown modifier"):
        input.parse_modifiers("Ctrl+Hyper")
    with pytest.raises(ActionError, match="unknown modifier"):
        actions.parse_modifiers("Bogus")


def test_modified_click_is_one_batch_in_order(sent: list[list[Any]]) -> None:
    input.click(5, 5, "left", 1, modifiers=(CTRL, SHIFT))
    (batch,) = sent
    assert batch == [
        ("key", CTRL, False),
        ("key", SHIFT, False),
        ("move",),
        ("mouse", win32.MOUSEEVENTF_LEFTDOWN, 0),
        ("mouse", win32.MOUSEEVENTF_LEFTUP, 0),
        ("key", SHIFT, True),
        ("key", CTRL, True),
    ]


def test_modifiers_are_released_when_the_batch_is_blocked(
    sent: list[list[Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[Any]] = []

    def blocked(events: list[Any]) -> None:
        calls.append(events)
        if len(calls) == 1:
            raise ActionError("input was blocked")

    monkeypatch.setattr(input, "_send", blocked)
    with pytest.raises(ActionError, match="blocked"):
        input.click(1, 1, modifiers=(CTRL,))
    assert len(calls) == 2
    assert len(calls[1]) == 1 and calls[1][0].ki.wVk == CTRL


@pytest.mark.parametrize(
    ("button", "down", "up"),
    [
        ("left", win32.MOUSEEVENTF_LEFTDOWN, win32.MOUSEEVENTF_LEFTUP),
        ("right", win32.MOUSEEVENTF_RIGHTDOWN, win32.MOUSEEVENTF_RIGHTUP),
        ("middle", win32.MOUSEEVENTF_MIDDLEDOWN, win32.MOUSEEVENTF_MIDDLEUP),
    ],
)
def test_button_flags(sent: list[list[Any]], button: Any, down: int, up: int) -> None:
    input.click(1, 1, button, 2)
    assert [e[1] for e in flat(sent) if e[0] == "mouse"] == [down, up, down, up]


@pytest.mark.parametrize(
    ("clicks", "horizontal", "flag", "data"),
    [
        (3, False, win32.MOUSEEVENTF_WHEEL, 360),
        (-2, False, win32.MOUSEEVENTF_WHEEL, (-240) & 0xFFFFFFFF),
        (1, True, win32.MOUSEEVENTF_HWHEEL, 120),
        (-1, True, win32.MOUSEEVENTF_HWHEEL, (-120) & 0xFFFFFFFF),
    ],
)
def test_wheel_events(
    sent: list[list[Any]], clicks: int, horizontal: bool, flag: int, data: int
) -> None:
    input.scroll_wheel(10, 10, clicks, horizontal=horizontal)
    assert flat(sent) == [("move",), ("mouse", flag, data)]


def test_drag_sequence(sent: list[list[Any]]) -> None:
    input.drag(100, 100, 300, 100, "left", (CTRL,))
    events = flat(sent)
    assert events[0] == ("key", CTRL, False)
    assert events[1] == ("move",)
    assert events[2] == ("mouse", win32.MOUSEEVENTF_LEFTDOWN, 0)
    assert events[-2:] == [("mouse", win32.MOUSEEVENTF_LEFTUP, 0), ("key", CTRL, True)]
    middle = events[3:-2]
    assert middle and all(e == ("move",) for e in middle)
    assert len(middle) >= input.DRAG_STEPS  # interpolated steps plus the final move


def test_drag_path_first_move_passes_the_drag_threshold(sent: list[list[Any]]) -> None:
    path = input.drag_path(0, 0, 200, 0)
    assert path[0] == (10, 0)
    assert path[-1][0] < 200
    assert [p[0] for p in path] == sorted(p[0] for p in path)
    assert input.drag_path(5, 5, 5, 5) == []
    assert input.drag_path(0, 0, 3, 0)[0] == (3, 0)  # never overshoots a short drag


def _failing_send(monkeypatch: pytest.MonkeyPatch, fail_on: int) -> list[list[Any]]:
    batches: list[list[Any]] = []

    def failing(events: list[Any]) -> None:
        batches.append(events)
        if len(batches) == fail_on:
            raise ActionError("input was blocked")

    monkeypatch.setattr(input, "_send", failing)
    monkeypatch.setattr(input.time, "sleep", lambda _: None)
    monkeypatch.setattr(win32, "MapVirtualKeyW", lambda vk, kind: 0)
    monkeypatch.setattr(win32, "virtual_screen_rect", lambda: Rect(0, 0, 1920, 1080))
    monkeypatch.setattr(win32, "GetSystemMetrics", lambda index: 4)
    return batches


def test_drag_releases_button_and_modifiers_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    batches = _failing_send(monkeypatch, fail_on=4)
    with pytest.raises(ActionError, match="blocked"):
        input.drag(0, 0, 100, 0, "right", (SHIFT,))
    release = batches[-1]
    assert release[0].type == win32.INPUT_MOUSE
    assert release[0].mi.dwFlags == win32.MOUSEEVENTF_RIGHTUP
    assert release[1].type == win32.INPUT_KEYBOARD
    assert release[1].ki.wVk == SHIFT and release[1].ki.dwFlags & win32.KEYEVENTF_KEYUP
    assert len(release) == 2


def test_drag_failing_before_press_only_releases_modifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batches = _failing_send(monkeypatch, fail_on=1)
    with pytest.raises(ActionError):
        input.drag(0, 0, 50, 0, "left", (CTRL,))
    assert len(batches[-1]) == 1 and batches[-1][0].type == win32.INPUT_KEYBOARD


# -- actions (UIA element) -------------------------------------------------------------------


@pytest.fixture
def uia(monkeypatch: pytest.MonkeyPatch) -> tuple[FakeElement, list[tuple[str, Any, Any]]]:
    control = FakeElement("Button", rect=Rect(100, 200, 50, 40))
    calls: list[tuple[str, Any, Any]] = []
    monkeypatch.setattr(actions, "bring_to_front", lambda element: True)
    monkeypatch.setattr(actions, "ensure_visible", lambda element: None)
    monkeypatch.setattr(actions, "_top_level_hwnd", lambda element: 100)
    monkeypatch.setattr(win32, "IsWindow", lambda hwnd: True)
    monkeypatch.setattr(win32, "window_pid", lambda hwnd: control.process_id)
    monkeypatch.setattr(win32, "window_owner", lambda hwnd: 0)
    monkeypatch.setattr(win32, "GetForegroundWindow", lambda: 100)
    monkeypatch.setattr(win32, "WindowFromPoint", lambda point: 101)
    monkeypatch.setattr(win32, "root_window", lambda hwnd: 100)
    monkeypatch.setattr(win32, "virtual_screen_rect", lambda: Rect(0, 0, 1000, 800))
    monkeypatch.setattr(actions.waits, "wait_for_state", lambda *args: None)
    monkeypatch.setattr(patterns, "has_pattern", lambda *args: True)  # invoke would be possible
    monkeypatch.setattr(patterns, "invoke", lambda el: calls.append(("invoke", None, None)))
    monkeypatch.setattr(input, "click", lambda x, y, **kw: calls.append(("click", (x, y), kw)))
    monkeypatch.setattr(input, "drag", lambda *a, **kw: calls.append(("drag", a, kw)))
    monkeypatch.setattr(
        input, "scroll_wheel", lambda x, y, n, **kw: calls.append(("scroll", (x, y, n), kw))
    )
    return control, calls


def test_offset_is_relative_to_the_top_left_corner(uia: Any) -> None:
    control, calls = uia
    actions.click(control, mode="mouse", offset=(5, 7))
    assert calls == [("click", (105, 207), {"button": "left", "count": 1})]


def test_default_point_stays_the_centre(uia: Any) -> None:
    control, calls = uia
    actions.right_click(control)
    assert calls == [("click", (125, 220), {"button": "right", "count": 1})]


@pytest.mark.parametrize("offset", [(50, 5), (5, 40), (-2, 5), (5, -2), (-1, 40), (50, -1)])
def test_offset_outside_the_element_is_rejected(uia: Any, offset: tuple[int, int]) -> None:
    control, calls = uia
    with pytest.raises(ActionError, match="outside"):
        actions.click(control, mode="mouse", offset=offset)
    assert calls == []


@pytest.mark.parametrize(
    ("offset", "point"),
    [
        ((-1, -1), (125, 220)),  # the centre
        ((-1, 4), (125, 204)),  # the middle of the top edge
        ((6, -1), (106, 220)),  # the middle of the left side
        ((0, 0), (100, 200)),
        ((49, 39), (149, 239)),
    ],
)
def test_minus_one_is_the_centre_of_that_axis(
    uia: Any, offset: tuple[int, int], point: tuple[int, int]
) -> None:
    control, calls = uia
    actions.click(control, mode="mouse", offset=offset)
    assert calls == [("click", point, {"button": "left", "count": 1})]


def test_the_centre_is_inside_a_one_pixel_element(uia: Any) -> None:
    control, calls = uia
    control.rect = Rect(10, 20, 1, 1)
    actions.click(control, mode="mouse", offset=(-1, -1))
    assert calls[0][1] == (10, 20)


def test_minus_one_applies_to_every_mouse_action(uia: Any) -> None:
    control, calls = uia
    actions.double_click(control, offset=(-1, -1), modifiers=(SHIFT,))
    actions.right_click(control, offset=(-1, 10))
    actions.scroll(control, 5, offset=(-1, -1))
    actions.drag_by(control, 10, 0, source_offset=(-1, -1), modifiers=(SHIFT,))
    assert calls == [
        ("click", (125, 220), {"button": "left", "count": 2, "modifiers": (SHIFT,)}),
        ("click", (125, 210), {"button": "right", "count": 1}),
        ("scroll", (125, 220, 5), {"horizontal": False}),
        ("drag", (125, 220, 135, 220), {"button": "left", "modifiers": (SHIFT,)}),
    ]


def test_drag_to_accepts_minus_one_on_both_ends(uia: Any) -> None:
    control, calls = uia
    other = FakeElement("ListItem", rect=Rect(400, 300, 100, 60))
    actions.drag_to(control, other, source_offset=(-1, 0), target_offset=(-1, -1))
    assert calls == [("drag", (125, 200, 450, 330), {"button": "left", "modifiers": ()})]


def test_offset_needs_both_coordinates() -> None:
    assert actions.parse_offset(None, None) is None
    assert actions.parse_offset(3, 4) == (3, 4)
    with pytest.raises(ActionError, match="together"):
        actions.parse_offset(3, None)


@pytest.mark.parametrize(
    "kwargs",
    [{"offset": (1, 1)}, {"button": "right"}, {"button": "middle"}, {"modifiers": (CTRL,)}],
)
def test_positioned_modified_or_other_button_clicks_force_the_mouse(
    uia: Any, kwargs: dict[str, Any]
) -> None:
    control, calls = uia
    assert actions.click(control, mode="pattern", **kwargs) == "mouse"
    assert [call[0] for call in calls] == ["click"]
    assert actions.click(control, mode="pattern") == "invoke"


def test_modifiers_reach_every_click_flavour(uia: Any) -> None:
    control, calls = uia
    actions.double_click(control, modifiers=(CTRL,))
    actions.middle_click(control, offset=(1, 2), modifiers=(SHIFT,))
    assert calls == [
        ("click", (125, 220), {"button": "left", "count": 2, "modifiers": (CTRL,)}),
        ("click", (101, 202), {"button": "middle", "count": 1, "modifiers": (SHIFT,)}),
    ]


def test_click_keeps_the_ownership_checks(uia: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    control, calls = uia
    monkeypatch.setattr(win32, "root_window", lambda hwnd: 999)
    with pytest.raises(ActionError, match="refusing global input"):
        actions.middle_click(control, offset=(1, 1), modifiers=(CTRL,))
    assert calls == []


def test_drag_to_resolves_destination_in_another_window(uia: Any) -> None:
    control, calls = uia
    other = FakeElement("ListItem", rect=Rect(400, 300, 100, 60))
    actions.drag_to(control, other, target_offset=(10, 10), modifiers=(CTRL,))
    assert calls == [("drag", (125, 220, 410, 310), {"button": "left", "modifiers": (CTRL,)})]


def test_drag_source_must_belong_to_the_window(uia: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    control, calls = uia
    monkeypatch.setattr(win32, "root_window", lambda hwnd: 999)
    with pytest.raises(ActionError, match="refusing global input"):
        actions.drag_to(control, FakeElement("Button", rect=Rect(10, 10, 5, 5)))
    assert calls == []


def test_drag_destination_must_be_on_screen(uia: Any) -> None:
    control, calls = uia
    off = FakeElement("Button", rect=Rect(2000, 10, 50, 50))
    with pytest.raises(ActionError, match="outside the screen"):
        actions.drag_to(control, off)
    with pytest.raises(ActionError, match="outside the screen"):
        actions.drag_by(control, 5000, 0)
    assert calls == []


def test_drag_by_and_source_offset(uia: Any) -> None:
    control, calls = uia
    actions.drag_by(control, 30, -20, source_offset=(0, 0), button="right")
    assert calls == [("drag", (100, 200, 130, 180), {"button": "right", "modifiers": ()})]


def test_scroll_uses_the_centre_or_an_offset(uia: Any) -> None:
    control, calls = uia
    actions.scroll(control, -3)
    actions.scroll(control, 2, offset=(1, 1), horizontal=True)
    assert calls == [
        ("scroll", (125, 220, -3), {"horizontal": False}),
        ("scroll", (101, 201, 2), {"horizontal": True}),
    ]


def test_scroll_validates_the_target_point(uia: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    control, calls = uia
    monkeypatch.setattr(win32, "root_window", lambda hwnd: 999)
    with pytest.raises(ActionError, match="refusing global input"):
        actions.scroll(control, 1)
    assert calls == []


def test_header_offset_aims_at_the_first_row_of_an_item_with_children() -> None:
    assert actions._header_offset(600, 48, 16) == (40, 8)
    assert actions._header_offset(30, 16, None) == (15, 8)
    assert actions._header_offset(600, 48, 500) == (40, 24)  # never beyond the rectangle


def test_click_header_uses_an_offset_on_the_first_row(uia: Any) -> None:
    control, calls = uia
    control.rect = Rect(100, 200, 600, 48)
    actions.click_header(control, 16)
    assert calls == [("click", (140, 208), {"button": "left", "count": 1})]


def test_check_reports_new_dialog_without_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    checkbox = FakeElement("CheckBox")
    windows = [1]
    monkeypatch.setattr(win32, "top_level_windows", lambda pids: list(windows))
    monkeypatch.setattr(win32, "window_text", lambda hwnd: "Confirm")
    monkeypatch.setattr(win32, "is_dialog_window", lambda hwnd: True)
    monkeypatch.setattr(actions, "is_checked", lambda el: False)
    monkeypatch.setattr(actions, "click", lambda el, mode: windows.append(2))
    start = time.monotonic()
    with pytest.raises(ActionError, match='dialog "Confirm"'):
        actions.set_checked(checkbox, True, mode="mouse", timeout=10)
    assert time.monotonic() - start < 1


@pytest.mark.parametrize("reason", ["workTimeout", "clientDeadline", "queueWait"])
def test_pattern_check_reports_dialog_on_inspector_work_timeout(
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
) -> None:
    from wintestkit.backends.element import WpfElement
    from wintestkit.errors import InspectorDeadlineError

    checkbox = WpfElement.__new__(WpfElement)
    checkbox._process_id = 1
    windows = [1]
    monkeypatch.setattr(win32, "top_level_windows", lambda pids: list(windows))
    monkeypatch.setattr(win32, "window_text", lambda hwnd: "Confirm")
    monkeypatch.setattr(win32, "is_dialog_window", lambda hwnd: True)
    monkeypatch.setattr(actions, "_wpf_read", lambda *args: "Off")

    def fail(*args: Any) -> None:
        windows.append(2)
        error = InspectorDeadlineError("timeout", code="dispatcherUnavailable")
        error.details = {"reason": reason}
        raise error

    monkeypatch.setattr(actions, "_wpf_act", fail)
    with pytest.raises(ActionError, match='dialog "Confirm"'):
        actions.set_checked(checkbox, True)


def test_new_dialog_ignores_tool_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    ex_styles = {2: win32.WS_EX_TOOLWINDOW, 3: win32.WS_EX_NOACTIVATE}
    monkeypatch.setattr(win32, "top_level_windows", lambda pids: [1, 2, 3, 4])
    monkeypatch.setattr(win32, "IsWindowVisible", lambda hwnd: True)
    monkeypatch.setattr(
        win32,
        "GetWindowLongW",
        lambda hwnd, index: ex_styles.get(hwnd, 0) if index == win32.GWL_EXSTYLE else 0,
    )
    monkeypatch.setattr(win32, "window_text", lambda hwnd: f"Window {hwnd}")
    # Window 4 has no caption (custom chrome) but can take focus, so it counts as a dialog.
    assert actions._new_dialog(FakeElement("CheckBox"), {1}) == "Window 4"
    monkeypatch.setattr(win32, "top_level_windows", lambda pids: [1, 2, 3])
    assert actions._new_dialog(FakeElement("CheckBox"), {1}) is None


def test_pattern_check_reports_dialog_for_nested_budget_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from wintestkit.backends.element import WpfElement
    from wintestkit.errors import UIAError
    from wintestkit.inspector.client import _error

    checkbox = WpfElement.__new__(WpfElement)
    checkbox._process_id = 1
    windows = [1]
    monkeypatch.setattr(win32, "top_level_windows", lambda pids: list(windows))
    monkeypatch.setattr(win32, "window_text", lambda hwnd: "Confirm")
    monkeypatch.setattr(win32, "is_dialog_window", lambda hwnd: True)
    monkeypatch.setattr(actions, "_wpf_read", lambda *args: "Off")

    def fail(*args: Any) -> None:
        windows.append(2)
        try:
            raise _error("limitExceeded", {"deadline": True})
        except Exception as error:
            try:
                raise RuntimeError("intermediate") from error
            except RuntimeError as intermediate:
                raise UIAError("wrapper") from intermediate

    monkeypatch.setattr(actions, "_wpf_act", fail)
    with pytest.raises(ActionError, match='toggle opened a dialog "Confirm"'):
        actions.set_checked(checkbox, True)
