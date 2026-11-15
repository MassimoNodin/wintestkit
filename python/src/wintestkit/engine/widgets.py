"""Actions of the range, date, expander, toolbar and status bar controls."""

# These actions share the mouse and agent helpers of ``actions``.
# pyright: reportPrivateUsage=false

from __future__ import annotations

import datetime
import re
from collections.abc import Iterator

from wintestkit.backends.element import TargetElement, WpfElement, uia_of
from wintestkit.engine import actions, dates, waits
from wintestkit.errors import ActionError, UIAError
from wintestkit.uia import patterns
from wintestkit.uia.element import UIAElement

InputMode = actions.InputMode

_MAX_DEPTH = 4
_MAX_KEYS = 50
_SLIDE_ROUNDS = 40
_SETTLE = 2.0
_BUTTONS = ("Button", "SplitButton")


def _walk(el: TargetElement, depth: int = _MAX_DEPTH) -> Iterator[UIAElement]:
    """Descendants in document order, down to ``depth`` levels."""
    if depth <= 0:
        return
    for child in uia_of(el).children():
        yield child
        yield from _walk(child, depth - 1)


def _first(el: TargetElement, *control_types: str) -> UIAElement | None:
    return next((e for e in _walk(el) if e.control_type in control_types), None)


# -- ranges ---------------------------------------------------------------------------------------


def read_range(el: TargetElement) -> patterns.RangeInfo:
    __tracebackhide__ = True
    return patterns.range_info(el)


def _tolerance(info: patterns.RangeInfo) -> float:
    return max(info.small_change / 2, 1e-9)


def _check_target(el: TargetElement, info: patterns.RangeInfo, value: float) -> None:
    __tracebackhide__ = True
    if info.read_only:
        raise ActionError(f"{actions._short(el)} is read-only")
    if not info.minimum <= value <= info.maximum:
        raise ActionError(
            f"{value:g} is outside the range {info.minimum:g} to {info.maximum:g} of "
            f"{actions._short(el)}"
        )


def _verify(el: TargetElement, info: patterns.RangeInfo, value: float) -> None:
    __tracebackhide__ = True
    reached = read_range(el).value
    if abs(reached - value) > _tolerance(info):
        raise ActionError(f"{actions._short(el)} is at {reached:g}, not {value:g}")


def set_range_by_pattern(el: TargetElement, value: float) -> None:
    """Set the RangeValue (the agent's ``setRange`` on a WPF element)."""
    __tracebackhide__ = True
    info = read_range(el)
    _check_target(el, info, value)
    if isinstance(el, WpfElement):
        actions._wpf_act(el, "set_range", "RangeValue", value)
    else:
        patterns.set_range_value(el, value)
    _verify(el, info, value)


def set_scroll_bar(el: TargetElement, value: float, *, mode: InputMode) -> None:
    __tracebackhide__ = True
    if mode == "mouse":
        raise ActionError("ScrollBar.set_value needs input_mode pattern or mode='pattern'")
    set_range_by_pattern(el, value)


def _press_keys(el: TargetElement, key: str, count: int) -> None:
    __tracebackhide__ = True
    actions.press(el, " ".join([key] * count))


def step_slider(el: TargetElement, steps: int, *, up: bool) -> None:
    """Press an arrow key ``steps`` times."""
    __tracebackhide__ = True
    if steps < 1:
        raise ValueError("steps must be at least 1")
    key = "Right" if up else "Left"
    for start in range(0, steps, _MAX_KEYS):
        _press_keys(el, key, min(_MAX_KEYS, steps - start))


def _click_thumb(el: TargetElement) -> None:
    __tracebackhide__ = True
    thumb = _first(el, "Thumb")
    if thumb is None:
        raise ActionError(f"{actions._short(el)} has no thumb to click")
    actions._mouse_click(thumb)


def set_slider(el: TargetElement, value: float, *, mode: InputMode) -> None:
    """Set a slider: by pattern, or by keyboard after clicking its thumb in mouse mode."""
    __tracebackhide__ = True
    if mode == "pattern":
        set_range_by_pattern(el, value)
        return
    info = read_range(el)
    _check_target(el, info, value)
    tolerance = _tolerance(info)
    _click_thumb(el)
    if value == info.minimum:
        _press_keys(el, "Home", 1)
    elif value == info.maximum:
        _press_keys(el, "End", 1)
    reverse = False
    for _ in range(_SLIDE_ROUNDS):
        current = read_range(el).value
        difference = value - current
        if abs(difference) <= tolerance:
            return
        up = (difference > 0) != reverse
        if info.large_change > 0 and abs(difference) >= info.large_change - tolerance:
            keys = ("PageUp", "PageDown")
            count = int(abs(difference) / info.large_change + 1e-9)
        elif info.small_change > 0:
            keys = ("Right", "Left")
            count = max(1, round(abs(difference) / info.small_change))
        else:
            raise ActionError(f"{actions._short(el)} has no step size to move by keys")
        _press_keys(el, keys[0] if up else keys[1], min(count, _MAX_KEYS))
        moved = read_range(el).value - current
        if moved == 0:
            raise ActionError(
                f"{actions._short(el)} did not move from {current:g} towards {value:g} by keys"
            )
        if moved * difference < 0:
            reverse = not reverse
    raise ActionError(
        f"Could not bring {actions._short(el)} to {value:g} by keys (it is at "
        f"{read_range(el).value:g})"
    )


# -- date picker ----------------------------------------------------------------------------------


def _date_edit(el: TargetElement) -> UIAElement:
    __tracebackhide__ = True
    own = uia_of(el)
    if own.control_type == "Edit":
        return own
    edit = _first(el, "Edit")
    if edit is None:
        raise ActionError(f"{actions._short(el)} has no text box for the date")
    return edit


def date_text(el: TargetElement) -> str:
    """The text the date picker shows."""
    __tracebackhide__ = True
    return actions.get_value(_date_edit(el))


def read_date(el: TargetElement) -> datetime.date | None:
    __tracebackhide__ = True
    return dates.parse_date(date_text(el), dates.system_short_date_format())


def _current_date(el: TargetElement) -> datetime.date | None:
    try:
        return read_date(el)
    except (ActionError, UIAError):
        return None


def set_date(el: TargetElement, value: datetime.date, *, mode: InputMode) -> None:
    """Type ``value`` in the system short date format into the text box and commit it."""
    __tracebackhide__ = True
    text = dates.format_date(value, dates.system_short_date_format())
    edit = _date_edit(el)
    if mode == "mouse":
        actions._mouse_click(edit)
        actions.type_text(edit, text, keys=True)
    else:
        actions.type_text(edit, text)
    for commit in ("Enter", "Tab"):
        actions.press(edit, commit)
        try:
            waits.wait_until(
                lambda: _current_date(el) == value or None,
                _SETTLE,
                description=f"{actions._short(el)} to show {text}",
            )
            return
        except waits.WaitTimeoutError:
            continue
    raise ActionError(
        f"{actions._short(el)} shows {date_text(el)!r} after typing {text!r}, not {value}"
    )


# -- expander -------------------------------------------------------------------------------------


def set_expanded(el: TargetElement, expanded: bool, *, mode: InputMode) -> None:
    __tracebackhide__ = True
    if mode == "pattern" or isinstance(el, WpfElement):
        (actions.expand if expanded else actions.collapse)(el, mode=mode)
    elif actions.is_expanded(el) != expanded:
        toggle = _first(el, "Button")
        if toggle is None:
            raise ActionError(f"{actions._short(el)} has no header button to click")
        actions._mouse_click(toggle)
    state = "expanded" if expanded else "collapsed"
    try:
        waits.wait_until(
            lambda: actions.is_expanded(el) == expanded or None,
            _SETTLE,
            description=f"{actions._short(el)} to be {state}",
        )
    except waits.WaitTimeoutError as exc:
        raise ActionError(str(exc)) from exc


# -- toolbar and status bar -----------------------------------------------------------------------


def _button_matches(button: UIAElement, name: str | re.Pattern[str]) -> bool:
    labels = (button.name, button.automation_id)
    if isinstance(name, str):
        return name in labels
    return any(label and name.search(label) for label in labels)


def click_toolbar_button(
    el: TargetElement, name: str | re.Pattern[str], *, mode: InputMode
) -> None:
    """Click the button whose name (or automation id) is ``name``."""
    __tracebackhide__ = True
    buttons = [b for b in _walk(el) if b.control_type in _BUTTONS]
    for button in buttons:
        if _button_matches(button, name):
            actions.click(button, mode=mode)
            return
    shown = ", ".join(repr(b.name or b.automation_id) for b in buttons) or "none"
    label = name if isinstance(name, str) else name.pattern
    raise ActionError(f"{actions._short(el)} has no button {label!r}; its buttons: {shown}")


def status_texts(el: TargetElement) -> list[str]:
    """The texts of the status bar's items, in order."""
    __tracebackhide__ = True
    found: list[str] = []

    def visit(node: UIAElement, depth: int) -> None:
        if depth <= 0:
            return
        for child in node.children():
            if child.control_type == "Text" and not any(
                e.control_type == "Text" for e in _walk(child, depth - 1)
            ):
                if child.name:
                    found.append(child.name)
            else:
                visit(child, depth - 1)

    visit(uia_of(el), _MAX_DEPTH)
    return found
