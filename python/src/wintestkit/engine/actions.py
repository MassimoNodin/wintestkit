"""Actions on already-resolved elements.

The model layer re-resolves the locator and waits for the element before calling these, so every
function here assumes ``el`` is current. Each prefers a UI Automation pattern and falls back to
synthetic mouse and keyboard input.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Literal

from wintestkit.backends.element import TargetElement, WpfElement, uia_of
from wintestkit.engine import waits
from wintestkit.engine.diagnose import Candidate, Diagnostic, quote
from wintestkit.engine.locator import Locator
from wintestkit.engine.managed import in_query_budget, operation_deadline
from wintestkit.engine.query import query_all
from wintestkit.errors import (
    ActionError,
    ElementNotFoundError,
    InspectorDeadlineError,
    InspectorError,
    NoUiaPeerError,
    UIAError,
)
from wintestkit.inspector.models import ElementState, ItemMatch
from wintestkit.inspector.paths import PathSegment
from wintestkit.uia import element, input, patterns, win32
from wintestkit.uia.constants import ExpandCollapseState, ToggleState
from wintestkit.uia.element import UIAElement

log = logging.getLogger("wintestkit.actions")

InputMode = Literal["pattern", "mouse"]
MouseButton = input.MouseButton

_ITEM_TYPES = ("ListItem", "DataItem", "TreeItem", "TabItem")
_STABLE_TIMEOUT = 1.0
MAX_LISTED_ITEMS = 5


def _short(el: TargetElement) -> str:
    __tracebackhide__ = True
    try:
        return el.info().short()
    except UIAError:
        return repr(el)


def _translate_wpf_error(exc: InspectorError, verb: str = "the request") -> None:
    __tracebackhide__ = True
    if exc.code == "objectStale":
        raise UIAError("The UI element is no longer available", element_gone=True) from exc
    if isinstance(exc, InspectorDeadlineError) or exc.code == "timeout":
        if in_query_budget():
            if isinstance(exc, InspectorDeadlineError):
                raise exc
            raise InspectorDeadlineError(str(exc), code=exc.code) from exc
        raise UIAError(f"The WPF inspector did not complete {verb} within its deadline") from exc


def _wpf_read(
    el: WpfElement, name: str, pattern: str | None = None, *, fail_closed: bool = False
) -> object:
    __tracebackhide__ = True
    try:
        values, _ = el.client.read(
            el.ref.object_id,
            el.ref.generation,
            [(PathSegment("uia", name),)],
            deadline=operation_deadline(2),
        )
    except InspectorError as exc:
        _translate_wpf_error(exc, f"reading {name}")
        raise
    value = values[0].value
    if value.status == "unavailable" and pattern:
        raise ActionError(f"{_short(el)} does not support the {pattern} pattern")
    if value.status != "ok" and fail_closed:
        return True
    if value.status != "ok":
        raise UIAError(f"Cannot read {name}: {value.status}")
    return value.scalar


def _wpf_patterns(el: WpfElement) -> set[str]:
    __tracebackhide__ = True
    return set(str(_wpf_read(el, "supported_patterns")).split(","))


def _wpf_act(
    el: WpfElement, verb: str, pattern: str | None = None, value: str | None = None
) -> None:
    __tracebackhide__ = True
    try:
        method = getattr(el.client, "act_" + verb)
        args = (el.ref,) if value is None else (el.ref, value)
        method(*args, timeout_ms=2000, deadline=operation_deadline(2))
    except InspectorError as exc:
        if exc.code == "actionUnsupported" and pattern:
            raise ActionError(f"{_short(el)} does not support the {pattern} pattern") from exc
        _translate_wpf_error(exc, verb.replace("_", " "))
        raise


def _window_guard(hwnd: int, process_id: int, *, activate: bool = False) -> None:
    """Validate the target and its owner chain before allowing global input."""
    __tracebackhide__ = True
    error = "Target window ownership or foreground changed; refusing global input"
    if not hwnd or not win32.IsWindow(hwnd) or win32.window_pid(hwnd) != process_id:
        raise ActionError(error)
    root = hwnd
    seen = {hwnd}
    while owner := win32.window_owner(root):
        if owner in seen or not win32.IsWindow(owner) or win32.window_pid(owner) != process_id:
            raise ActionError(error)
        seen.add(owner)
        root = owner
    foreground = win32.GetForegroundWindow()
    if activate and foreground not in (hwnd, root):
        if not win32.bring_to_foreground(root):
            raise ActionError("Cannot activate the target window; refusing global input")
        foreground = win32.GetForegroundWindow()
    if foreground not in (hwnd, root):
        raise ActionError(error)


def _wpf_window(el: WpfElement, *, activate: bool = False) -> int:
    __tracebackhide__ = True
    state = el.client.state_get(el.ref, timeout_ms=2000, deadline=operation_deadline(2))
    hwnd = state.window_handle or 0
    _window_guard(hwnd, el.process_id, activate=activate)
    return hwnd


def _wpf_keyboard_target(el: WpfElement) -> None:
    __tracebackhide__ = True
    _wpf_window(el)
    state = el.client.state_get(el.ref, timeout_ms=2000, deadline=operation_deadline(2))
    if not state.focused:
        raise ActionError("Target control does not own keyboard focus; refusing global input")


# -- visibility and focus -------------------------------------------------------------------------


def ensure_visible(el: TargetElement) -> None:
    """Scroll a virtualized or scrolled-away element into view."""
    __tracebackhide__ = True
    if isinstance(el, WpfElement):
        if not el.as_live().is_offscreen:
            return
        _wpf_act(el, "scroll_into_view" if "ScrollItem" in _wpf_patterns(el) else "bring_into_view")
        if el.as_live().is_offscreen:
            raise ActionError(f"{_short(el)} is off-screen and cannot be scrolled into view")
        return
    el = uia_of(el)
    if not el.is_offscreen:
        return
    if patterns.has_pattern(el, "VirtualizedItem"):
        patterns.realize(el)
    if patterns.has_pattern(el, "ScrollItem"):
        patterns.scroll_into_view(el)
    if el.is_offscreen:
        raise ActionError(f"{_short(el)} is off-screen and cannot be scrolled into view")


def _top_level_hwnd(el: UIAElement) -> int:
    __tracebackhide__ = True
    node: UIAElement | None = el
    while node is not None:
        handle = node.native_window_handle
        if handle:
            return win32.root_window(handle)
        node = node.parent()
    return 0


def bring_to_front(el: TargetElement) -> bool:
    """Raise the owning window without clicking or focusing the control itself."""
    __tracebackhide__ = True
    el = uia_of(el)
    hwnd = _top_level_hwnd(el)
    if not hwnd:
        return False
    raised = win32.bring_to_foreground(hwnd)
    if not raised:
        log.debug("could not bring window %#x to the foreground", hwnd)
    return raised


def window_is_minimized(el: TargetElement) -> bool:
    """Whether the element's top-level window is minimized (its controls then have no bounds)."""
    __tracebackhide__ = True
    el = uia_of(el)
    hwnd = _top_level_hwnd(el)
    return bool(hwnd) and bool(win32.IsIconic(hwnd))


def raise_without_activating(el: TargetElement) -> bool:
    """Show the owning window above the others while the current window keeps keyboard focus."""
    __tracebackhide__ = True
    el = uia_of(el)
    hwnd = _top_level_hwnd(el)
    if not hwnd:
        return False
    raised = win32.raise_window(hwnd)
    if not raised:
        log.debug("could not raise window %#x", hwnd)
    return raised


def _foreground(el: UIAElement) -> None:
    __tracebackhide__ = True
    _window_guard(_top_level_hwnd(el), el.process_id, activate=True)


def _validate_foreground(el: UIAElement) -> int:
    __tracebackhide__ = True
    hwnd = _top_level_hwnd(el)
    _window_guard(hwnd, el.process_id)
    return hwnd


def _keyboard_target(el: UIAElement) -> None:
    __tracebackhide__ = True
    _validate_foreground(el)
    if not el.has_keyboard_focus:
        raise ActionError("Target control does not own keyboard focus; refusing global input")


def focus(el: TargetElement) -> None:
    """Give the element keyboard focus (bringing its window forward first)."""
    __tracebackhide__ = True
    if isinstance(el, WpfElement):
        _wpf_window(el, activate=True)
        _wpf_act(el, "focus")
        return
    el = uia_of(el)
    _foreground(el)
    try:
        el.set_focus()
    except UIAError as exc:
        raise ActionError(f"{_short(el)} cannot take keyboard focus: {exc}") from exc


# -- mouse ----------------------------------------------------------------------------------------


def _wpf_mouse_target(el: WpfElement, role: str | None = None) -> tuple[int, int]:
    """Resolve stable agent-verified physical-pixel geometry."""
    __tracebackhide__ = True

    def read() -> ElementState:
        __tracebackhide__ = True
        try:
            return el.client.state_get(el.ref, timeout_ms=2000, deadline=operation_deadline(2))
        except InspectorError as exc:
            _translate_wpf_error(exc, "state.get")
            raise

    def target(state: ElementState) -> tuple[int, int]:
        __tracebackhide__ = True
        if role is None:
            point = state.click_point
            if point is not None and state.visible and not state.offscreen:
                return round(point.x), round(point.y)
        else:
            matches = [part for part in state.parts if part.role == role]
            rect = matches[0].bounds if len(matches) == 1 else None
            if (
                state.visible
                and not state.offscreen
                and rect
                and rect.width > 0
                and rect.height > 0
            ):
                x, y = round(rect.x + rect.width / 2), round(rect.y + rect.height / 2)
                if rect.x <= x < rect.x + rect.width and rect.y <= y < rect.y + rect.height:
                    return x, y
        raise ActionError(f"{_short(el)} has no on-screen rectangle to click")

    first = read()
    if first.offscreen or (role is None and first.click_point is None and first.clipped):
        _wpf_act(el, "scroll_into_view" if "ScrollItem" in _wpf_patterns(el) else "bring_into_view")
        first = read()
    target(first)
    _wpf_window(el, activate=True)

    def stable() -> ElementState | None:
        __tracebackhide__ = True
        before = read()
        a = target(before)
        time.sleep(waits.STABLE_INTERVAL)
        after = read()
        b = target(after)
        return (
            after
            if a == b
            and before.bounds == after.bounds
            and before.click_point == after.click_point
            and before.window_handle == after.window_handle
            else None
        )

    try:
        state = waits.wait_until(
            stable, _STABLE_TIMEOUT, description=f"{_short(el)} to stop moving"
        )
    except waits.WaitTimeoutError as exc:
        raise ActionError(str(exc)) from exc
    x, y = target(state)
    bounds = state.bounds
    if bounds is None or not (
        bounds.x <= x < bounds.x + bounds.width and bounds.y <= y < bounds.y + bounds.height
    ):
        raise ActionError(f"{_short(el)} has no on-screen rectangle to click")
    hwnd = _wpf_window(el)
    if hwnd != state.window_handle:
        raise ActionError("Target window ownership or foreground changed; refusing global input")
    _validate_point(hwnd, el.process_id, x, y)
    return x, y


def _wpf_mouse_click(
    el: WpfElement, button: MouseButton = "left", count: int = 1, *, role: str | None = None
) -> None:
    __tracebackhide__ = True
    x, y = _wpf_mouse_target(el, role)
    input.click(x, y, button=button, count=count)


def _mouse_target(el: UIAElement) -> tuple[int, int]:
    __tracebackhide__ = True
    ensure_visible(el)
    _foreground(el)
    waits.wait_for_state(lambda: el, "stable", _STABLE_TIMEOUT, f"{_short(el)} to stop moving")
    rect = el.rect
    if rect is None:
        raise ActionError(f"{_short(el)} has no on-screen rectangle to click")
    return rect.center


def _mouse_click(el: UIAElement, button: MouseButton = "left", count: int = 1) -> None:
    __tracebackhide__ = True
    x, y = _mouse_target(el)
    _validate_mouse_target(el, x, y)
    input.click(x, y, button=button, count=count)


def _validate_mouse_target(el: UIAElement, x: int, y: int) -> None:
    __tracebackhide__ = True
    hwnd = _validate_foreground(el)
    _validate_point(hwnd, el.process_id, x, y)


def _validate_point(hwnd: int, process_id: int, x: int, y: int) -> None:
    __tracebackhide__ = True
    hit = win32.WindowFromPoint(win32.POINT(x, y))
    if not hit or win32.root_window(hit) != hwnd or win32.window_pid(hit) != process_id:
        raise ActionError("Target point belongs to another window; refusing global input")


def click(el: TargetElement, *, mode: InputMode = "pattern", button: MouseButton = "left") -> str:
    """Click the element; returns the strategy used (``invoke``, ``toggle``, ``mouse`` ...)."""
    __tracebackhide__ = True
    if isinstance(el, WpfElement) and mode == "pattern" and button == "left":
        available = _wpf_patterns(el)
        for pattern, verb, strategy in (
            ("Invoke", "invoke", "invoke"),
            ("Toggle", "toggle", "toggle"),
            ("SelectionItem", "select", "select"),
            ("ExpandCollapse", "expand", "expand_collapse"),
        ):
            if pattern in available:
                if (
                    pattern == "ExpandCollapse"
                    and _wpf_read(el, "expand_state", pattern) != "Collapsed"
                ):
                    verb = "collapse"
                _wpf_act(el, verb, pattern)
                return strategy
        _wpf_mouse_click(el, button=button)
        return "mouse"
    if isinstance(el, WpfElement):
        _wpf_mouse_click(el, button=button)
        return "mouse"
    el = uia_of(el)
    if mode == "pattern" and button == "left":
        if patterns.has_pattern(el, "Invoke"):
            patterns.invoke(el)
            return "invoke"
        if patterns.has_pattern(el, "Toggle"):
            patterns.toggle(el)
            return "toggle"
        if patterns.has_pattern(el, "SelectionItem"):
            patterns.select_item(el)
            return "select"
        if patterns.has_pattern(el, "ExpandCollapse"):
            if patterns.expand_state(el) == ExpandCollapseState.Collapsed:
                patterns.expand(el)
            else:
                patterns.collapse(el)
            return "expand_collapse"
    _mouse_click(el, button=button)
    return "mouse"


def double_click(el: TargetElement) -> None:
    __tracebackhide__ = True
    if isinstance(el, WpfElement):
        _wpf_mouse_click(el, count=2)
        return
    el = uia_of(el)
    _mouse_click(el, count=2)


def right_click(el: TargetElement) -> None:
    __tracebackhide__ = True
    if isinstance(el, WpfElement):
        _wpf_mouse_click(el, button="right")
        return
    el = uia_of(el)
    _mouse_click(el, button="right")


def hover(el: TargetElement) -> None:
    __tracebackhide__ = True
    if isinstance(el, WpfElement):
        x, y = _wpf_mouse_target(el)
        input.move_mouse(x, y)
        return
    el = uia_of(el)
    x, y = _mouse_target(el)
    _validate_mouse_target(el, x, y)
    input.move_mouse(x, y)


# -- text -----------------------------------------------------------------------------------------


def is_password(el: TargetElement) -> bool:
    __tracebackhide__ = True
    if isinstance(el, WpfElement):
        return bool(_wpf_read(el, "is_password", fail_closed=True))
    try:
        el = uia_of(el)
    except NoUiaPeerError:
        return True
    return el.get_property("IsPassword") == 1 or el.class_name == "PasswordBox"


def _can_set_value(el: UIAElement) -> bool:
    __tracebackhide__ = True
    return patterns.has_pattern(el, "Value") and not patterns.is_read_only(el)


def type_text(el: TargetElement, text: str, *, clear: bool = True, keys: bool = False) -> str:
    """Enter text; returns ``"value"`` (ValuePattern) or ``"keys"`` (keyboard input)."""
    __tracebackhide__ = True
    if isinstance(el, WpfElement):
        password = is_password(el)
        if (
            not keys
            and not password
            and "Value" in _wpf_patterns(el)
            and not _wpf_read(el, "is_read_only", "Value")
        ):
            value = text if clear else str(_wpf_read(el, "value", "Value")) + text
            _wpf_act(el, "set_value", "Value", value)
            return "value"
        focus(el)
        _wpf_keyboard_target(el)
        input.press("Ctrl+A Delete" if clear else "Ctrl+End")
        _wpf_keyboard_target(el)
        input.type_text(text)
        return "keys"
    el = uia_of(el)
    if not keys and _can_set_value(el) and (clear or not is_password(el)):
        try:
            patterns.set_value(el, text if clear else patterns.get_value(el) + text)
            return "value"
        except UIAError:
            log.debug("ValuePattern.SetValue failed; falling back to keys")
    focus(el)
    # Appending needs the caret at the end: SetValue and focus changes can leave it at the start.
    _keyboard_target(el)
    input.press("Ctrl+A Delete" if clear else "Ctrl+End")
    _keyboard_target(el)
    input.type_text(text)
    return "keys"


def clear(el: TargetElement) -> None:
    """Remove all text from an edit control."""
    __tracebackhide__ = True
    if isinstance(el, WpfElement):
        if (
            not is_password(el)
            and "Value" in _wpf_patterns(el)
            and not _wpf_read(el, "is_read_only", "Value")
        ):
            _wpf_act(el, "set_value", "Value", "")
            return
        focus(el)
        _wpf_keyboard_target(el)
        input.press("Ctrl+A Delete")
        return
    el = uia_of(el)
    if _can_set_value(el):
        try:
            patterns.set_value(el, "")
            return
        except UIAError:
            log.debug("ValuePattern.SetValue failed; falling back to keys")
    focus(el)
    _keyboard_target(el)
    input.press("Ctrl+A Delete")


def press(el: TargetElement, keys: str) -> None:
    """Focus the element and press key combinations such as ``"Ctrl+S"``."""
    __tracebackhide__ = True
    if isinstance(el, WpfElement):
        focus(el)
        _wpf_keyboard_target(el)
        input.press(keys)
        return
    el = uia_of(el)
    focus(el)
    _keyboard_target(el)
    input.press(keys)


def get_text(el: TargetElement) -> str:
    """The element's text: its value, document text or UIA name."""
    __tracebackhide__ = True
    if isinstance(el, WpfElement):
        available = _wpf_patterns(el)
        password = is_password(el)
        if "Value" in available and not password:
            return str(_wpf_read(el, "value", "Value"))
        if "Text" in available and not password:
            return str(_wpf_read(el, "document_text", "Text"))
        return el.name
    el = uia_of(el)
    if patterns.has_pattern(el, "Value") and not is_password(el):
        return patterns.get_value(el)
    if patterns.has_pattern(el, "Text") and not is_password(el):
        return patterns.document_text(el)
    return el.name


def get_value(el: TargetElement) -> str:
    __tracebackhide__ = True
    if is_password(el):
        raise ActionError("Cannot read a password value")
    if isinstance(el, WpfElement):
        return str(_wpf_read(el, "value", "Value"))
    el = uia_of(el)
    return patterns.get_value(el)


# -- state ----------------------------------------------------------------------------------------


def set_checked(el: TargetElement, checked: bool) -> None:
    """Toggle a check box or toggle button until it reaches the requested state."""
    __tracebackhide__ = True
    if isinstance(el, WpfElement):
        target_name = "On" if checked else "Off"
        for _ in range(3):
            if _wpf_read(el, "toggle_state", "Toggle") == target_name:
                return
            _wpf_act(el, "toggle", "Toggle")
        if _wpf_read(el, "toggle_state", "Toggle") != target_name:
            raise ActionError(f"{_short(el)} did not reach the {target_name} state")
        return
    el = uia_of(el)
    target = ToggleState.On if checked else ToggleState.Off
    for _ in range(3):
        if patterns.toggle_state(el) == target:
            return
        patterns.toggle(el)
    if patterns.toggle_state(el) != target:
        raise ActionError(f"{_short(el)} did not reach the {target.name} state")


def is_checked(el: TargetElement) -> bool:
    __tracebackhide__ = True
    if isinstance(el, WpfElement):
        return _wpf_read(el, "toggle_state", "Toggle") == "On"
    el = uia_of(el)
    return patterns.toggle_state(el) == ToggleState.On


def toggle(el: TargetElement) -> None:
    __tracebackhide__ = True
    if isinstance(el, WpfElement):
        _wpf_act(el, "toggle", "Toggle")
        return
    el = uia_of(el)
    patterns.toggle(el)


def select_self(el: TargetElement) -> None:
    """Select the element itself (a radio button, list item or tab)."""
    __tracebackhide__ = True
    if isinstance(el, WpfElement):
        _wpf_act(el, "select", "SelectionItem")
        return
    el = uia_of(el)
    patterns.select_item(el)


def is_selected(el: TargetElement) -> bool:
    __tracebackhide__ = True
    if isinstance(el, WpfElement):
        return bool(_wpf_read(el, "is_selected", "SelectionItem"))
    el = uia_of(el)
    return patterns.is_selected(el)


def _wpf_expand_collapse_mouse(el: WpfElement, *, expanded: bool) -> None:
    __tracebackhide__ = True
    state = _wpf_read(el, "expand_state", "ExpandCollapse")
    if state == ("Expanded" if expanded else "Collapsed"):
        return
    roles = {"ComboBox": "comboDropDown", "TreeItem": "treeItemExpander", "Group": "expanderToggle"}
    role = roles.get(el.control_type)
    if role is None:
        raise ActionError(f"{_short(el)} has no on-screen rectangle to click")
    _wpf_mouse_click(el, role=role)


def expand(el: TargetElement, *, mode: InputMode = "pattern") -> None:
    __tracebackhide__ = True
    if isinstance(el, WpfElement):
        if mode == "mouse":
            _wpf_expand_collapse_mouse(el, expanded=True)
            return
        _wpf_act(el, "expand", "ExpandCollapse")
        return
    el = uia_of(el)
    patterns.expand(el)


def collapse(el: TargetElement, *, mode: InputMode = "pattern") -> None:
    __tracebackhide__ = True
    if isinstance(el, WpfElement):
        if mode == "mouse":
            _wpf_expand_collapse_mouse(el, expanded=False)
            return
        _wpf_act(el, "collapse", "ExpandCollapse")
        return
    el = uia_of(el)
    patterns.collapse(el)


def selected_items(el: TargetElement) -> list[str]:
    """Names of the selected items of a list-like element."""
    __tracebackhide__ = True
    if isinstance(el, WpfElement):
        available = _wpf_patterns(el)
        if "Selection" not in available:
            if "SelectionItem" in available:
                return [el.name] if is_selected(el) else []
            raise ActionError(f"{_short(el)} does not expose a selection")
        count = int(str(_wpf_read(el, "selection_count", "Selection")))
        return [
            str(_wpf_read(el, f"selection_name_{index}", "Selection")) for index in range(count)
        ]
    el = uia_of(el)
    if patterns.has_pattern(el, "Selection"):
        return [item.name for item in patterns.selection(el)]
    if patterns.has_pattern(el, "SelectionItem"):
        return [el.name] if patterns.is_selected(el) else []
    raise ActionError(f"{_short(el)} does not expose a selection")


# -- selecting items ------------------------------------------------------------------------------

Item = str | int | re.Pattern[str]


def _describe_item(item: Item) -> str:
    __tracebackhide__ = True
    if isinstance(item, str):
        return quote(item)
    if isinstance(item, int):
        return f"#{item}"
    return f"/{item.pattern}/"


def _item_matches(item: str | re.Pattern[str], name: str) -> bool:
    __tracebackhide__ = True
    return item == name if isinstance(item, str) else item.search(name) is not None


def _item_not_found(
    el: UIAElement, item: Item, available: list[UIAElement]
) -> ElementNotFoundError:
    __tracebackhide__ = True
    names = ", ".join(quote(a.name) for a in available[:MAX_LISTED_ITEMS]) or "none"
    short = _short(el)
    return ElementNotFoundError(
        Diagnostic(
            kind="not_found",
            message=f"No item {_describe_item(item)} in {short} (available: {names})",
            locator=f"select({_describe_item(item)})",
            searched_in=short,
            match_count=0,
            candidates=tuple(Candidate(a.info(), 0, ()) for a in available[:MAX_LISTED_ITEMS]),
        )
    )


def _popup_roots(el: UIAElement) -> list[UIAElement]:
    __tracebackhide__ = True
    roots: list[UIAElement] = []
    for hwnd in win32.top_level_windows({el.process_id}):
        try:
            window = element.from_handle(hwnd)
            if window.class_name == "Popup" or window.control_type == "Menu":
                roots.append(window)
        except UIAError:
            continue
    return roots


def _combo_items(combo: UIAElement) -> list[UIAElement]:
    __tracebackhide__ = True
    locator = Locator(control_type="ListItem")
    items = query_all(combo, locator)
    if items:
        return items
    for popup in _popup_roots(combo):
        items.extend(query_all(popup, locator))
    return items


def _select_in_combo(el: UIAElement, item: Item) -> None:
    __tracebackhide__ = True
    patterns.expand(el)
    try:
        items = waits.wait_until(
            lambda: _combo_items(el) or None,
            _STABLE_TIMEOUT,
            description=f"the items of {_short(el)}",
        )
    except waits.WaitTimeoutError:
        items = []
    if isinstance(item, int):
        chosen = items[item] if 0 <= item < len(items) else None
    else:
        chosen = next((i for i in items if _item_matches(item, i.name)), None)
    try:
        if chosen is None:
            raise _item_not_found(el, item, items)
        patterns.select_item(chosen)
    finally:
        if patterns.expand_state(el) == ExpandCollapseState.Expanded:
            patterns.collapse(el)


def select_in_combo(el: TargetElement, item: Item, *, mode: InputMode = "pattern") -> None:
    """Select an item of a combo box (even one that does not report the ``ComboBox`` type)."""
    __tracebackhide__ = True
    if isinstance(el, WpfElement):
        _wpf_select(el, item, mode=mode, combo=True)
        return
    el = uia_of(el)
    _select_in_combo(el, item)


def combo_item_names(el: TargetElement) -> list[str]:
    """Names of a combo box's items."""
    __tracebackhide__ = True
    if isinstance(el, WpfElement):
        # Item peer reads work with the dropdown closed; open only if unavailable.
        try:
            return _wpf_item_names(el)
        except UIAError as error:
            if not str(error).endswith(": unavailable"):
                raise
        was_expanded = _wpf_read(el, "expand_state", "ExpandCollapse") == "Expanded"
        if not was_expanded:
            expand(el)
        try:
            return _wpf_item_names(el)
        finally:
            if not was_expanded and _wpf_read(el, "expand_state", "ExpandCollapse") == "Expanded":
                collapse(el)
    el = uia_of(el)
    was_expanded = patterns.expand_state(el) == ExpandCollapseState.Expanded
    if not was_expanded:
        patterns.expand(el)
    try:
        try:
            items = waits.wait_until(
                lambda: _combo_items(el) or None,
                _STABLE_TIMEOUT,
                description=f"the items of {_short(el)}",
            )
        except waits.WaitTimeoutError:
            items = []
        return [item.name for item in items]
    finally:
        if not was_expanded and patterns.expand_state(el) == ExpandCollapseState.Expanded:
            patterns.collapse(el)


def listed_item_names(el: TargetElement) -> list[str]:
    """Names of the items of a list, tree or tab control that are currently realized."""
    __tracebackhide__ = True
    if isinstance(el, WpfElement):
        from wintestkit.engine.wpf_resolve import query

        return [
            str(_wpf_read(c, "name"))
            for t in _ITEM_TYPES
            for c in query(el, Locator(control_type=t))
        ]
    el = uia_of(el)
    return [c.name for t in _ITEM_TYPES for c in query_all(el, Locator(control_type=t))]


def _find_listed_item(el: UIAElement, item: str | re.Pattern[str]) -> UIAElement | None:
    """Find an item among the realized children, then ask a virtualized container for it."""
    __tracebackhide__ = True
    for item_type in _ITEM_TYPES:
        for candidate in query_all(el, Locator(control_type=item_type)):
            if _item_matches(item, candidate.name):
                return candidate.as_live()
    if isinstance(item, str) and patterns.has_pattern(el, "ItemContainer"):
        found = patterns.find_item_by_property(el, None, "Name", item)
        if found is not None:
            patterns.realize(found)
            return found
    return None


def _item_by_index(el: UIAElement, index: int) -> UIAElement | None:
    __tracebackhide__ = True
    if index < 0:
        return None
    if el.control_type == "DataGrid" or patterns.has_pattern(el, "Grid"):
        rows, _ = patterns.grid_size(el)
        if index >= rows:
            return None
        return patterns.grid_item(el, index, 0).parent()
    if patterns.has_pattern(el, "ItemContainer"):
        current: UIAElement | None = None
        for _ in range(index + 1):
            current = patterns.find_item_by_property(el, current, None, None)
            if current is None:
                return None
        return current
    realized = [c for t in _ITEM_TYPES for c in query_all(el, Locator(control_type=t))]
    return realized[index].as_live() if index < len(realized) else None


def _wpf_item_names(el: WpfElement, *, limit: int | None = None) -> list[str]:
    __tracebackhide__ = True
    count = int(str(_wpf_read(el, "item_count")))
    return [str(_wpf_read(el, f"item_name_{i}")) for i in range(min(count, limit or count))]


def _wpf_item_not_found(el: WpfElement, item: Item) -> ElementNotFoundError:
    __tracebackhide__ = True
    names = ", ".join(quote(name) for name in _wpf_item_names(el, limit=MAX_LISTED_ITEMS)) or "none"
    short = _short(el)
    return ElementNotFoundError(
        Diagnostic(
            kind="not_found",
            message=f"No item {_describe_item(item)} in {short} (available: {names})",
            locator=f"select({_describe_item(item)})",
            searched_in=short,
            match_count=0,
            candidates=(),
        )
    )


def _wpf_select(el: WpfElement, item: Item, *, mode: InputMode, combo: bool) -> None:
    __tracebackhide__ = True
    from wintestkit.engine.wpf_query import UnsupportedQuery, predicate
    from wintestkit.errors import InvalidLocatorError

    if isinstance(item, int):
        match = ItemMatch("index", index=item) if 0 <= item <= 9999 else None
    else:
        try:
            match = ItemMatch.from_json(predicate((PathSegment("uia", "name"),), item).to_json())
        except UnsupportedQuery as error:
            raise InvalidLocatorError(f"Unsupported WPF item locator: {error}") from error
    if combo:
        expand(el, mode=mode)
    try:
        if match is None:
            raise _wpf_item_not_found(el, item)
        try:
            result = el.client.act_realize_item(
                el.ref, match, max_items=10000, timeout_ms=2000, deadline=operation_deadline(2)
            )
        except InspectorError as error:
            if error.code == "notFound":
                raise _wpf_item_not_found(el, item) from error
            _translate_wpf_error(error, "realizing item")
            raise
        chosen = WpfElement(el.client, result.handle, el.process_id)
        if mode == "mouse":
            if combo:

                def ready() -> bool:
                    __tracebackhide__ = True
                    state = chosen.client.state_get(
                        chosen.ref, timeout_ms=2000, deadline=operation_deadline(2)
                    )
                    return state.visible and not state.offscreen and state.click_point is not None

                waits.wait_until(ready, _STABLE_TIMEOUT, description="combo item to become visible")
            if _wpf_read(el, "control_type") == "DataGrid":
                try:
                    point = _wpf_mouse_target(chosen, "gridRowHeader")
                except ActionError:
                    _wpf_act(chosen, "select", "SelectionItem")
                else:
                    input.click(*point, button="left", count=1)
            else:
                _wpf_mouse_click(chosen)
        else:
            if "ScrollItem" in _wpf_patterns(chosen):
                _wpf_act(chosen, "scroll_into_view", "ScrollItem")
            _wpf_act(chosen, "select", "SelectionItem")
    finally:
        if combo and _wpf_read(el, "expand_state", "ExpandCollapse") == "Expanded":
            collapse(el, mode=mode)


def select(el: TargetElement, item: Item, *, mode: InputMode = "pattern") -> None:
    """Select an item of a combo box, list, grid, tree or tab control by name, regex or index."""
    __tracebackhide__ = True
    if isinstance(el, WpfElement):
        kind = str(_wpf_read(el, "control_type"))
        if kind != "ComboBox" and "Selection" not in _wpf_patterns(el):
            raise ActionError(f"select() is not supported on {_short(el)}")
        _wpf_select(el, item, mode=mode, combo=kind == "ComboBox")
        return
    el = uia_of(el)
    if el.control_type == "ComboBox":
        _select_in_combo(el, item)
        return
    if not patterns.has_pattern(el, "Selection"):
        raise ActionError(f"select() is not supported on {_short(el)}")
    chosen = _item_by_index(el, item) if isinstance(item, int) else _find_listed_item(el, item)
    if chosen is None:
        available = [c for t in _ITEM_TYPES for c in query_all(el, Locator(control_type=t))]
        raise _item_not_found(el, item, available)
    if patterns.has_pattern(chosen, "ScrollItem"):
        patterns.scroll_into_view(chosen)
    patterns.select_item(chosen)
