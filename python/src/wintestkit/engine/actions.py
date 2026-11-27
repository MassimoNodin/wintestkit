"""Actions on already-resolved elements.

The model layer re-resolves the locator and waits for the element before calling these, so every
function here assumes ``el`` is current. Each prefers a UI Automation pattern and falls back to
synthetic mouse and keyboard input.
"""

from __future__ import annotations

import contextlib
import logging
import re
import time
from collections import Counter
from collections.abc import Sequence
from typing import Any, Literal

from wintestkit import runtime
from wintestkit.backends.element import TargetElement, WpfElement, uia_of
from wintestkit.engine import waits
from wintestkit.engine.diagnose import Candidate, Diagnostic, quote
from wintestkit.engine.locator import Locator
from wintestkit.engine.managed import in_query_budget, operation_deadline
from wintestkit.engine.query import query_all
from wintestkit.engine.wpf_resolve import managed_capable, to_managed
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
_HEADER_X = 40
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
        message = f"The WPF inspector did not complete {verb} within its deadline"
        if "inspector.request_timeout=" in str(exc):
            message = f"{message}: {exc}"
        raise UIAError(message) from exc


def _wpf_read(
    el: WpfElement,
    name: str,
    pattern: str | None = None,
    *,
    fail_closed: bool = False,
    independent_deadline: bool = False,
) -> object:
    __tracebackhide__ = True
    try:
        values, _ = el.client.read(
            el.ref.object_id,
            el.ref.generation,
            [(PathSegment("uia", name),)],
            deadline=time.monotonic() + 2 if independent_deadline else operation_deadline(2),
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
    el: WpfElement, verb: str, pattern: str | None = None, value: str | float | None = None
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
        raised = win32.bring_to_foreground(root)
        foreground = win32.GetForegroundWindow()
        if not raised and foreground not in (hwnd, root):
            raise ActionError("Cannot activate the target window; refusing global input")
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
        try:
            if not el.as_live().is_offscreen:
                return
            _wpf_act(
                el, "scroll_into_view" if "ScrollItem" in _wpf_patterns(el) else "bring_into_view"
            )
            if el.as_live().is_offscreen:
                raise ActionError(f"{_short(el)} is off-screen and cannot be scrolled into view")
        except InspectorError as exc:
            _translate_wpf_error(exc, "checking visibility")
            raise
        return
    el = uia_of(el)
    if not el.is_offscreen:
        return
    if patterns.has_pattern(el, "VirtualizedItem"):
        patterns.realize(el)
    if patterns.has_pattern(el, "ScrollItem"):
        patterns.scroll_into_view(el)
    if el.is_offscreen:
        _scroll_realized_item(el)
    if el.is_offscreen:
        raise ActionError(f"{_short(el)} is off-screen and cannot be scrolled into view")


#: UI Automation item types that a scrolling container realizes and can scroll to.
_SCROLLABLE_ITEMS = ("DataItem", "ListItem", "TreeItem")
#: How far above a cell or item the ScrollItem pattern of its row is looked for.
_SCROLL_ANCESTORS = 2
_SETTLE_ATTEMPTS = 5


def scrolls_through_agent(el: TargetElement) -> bool:
    """Whether the agent can scroll an off-screen realized grid row, cell or list item into view.

    Its container scrolls it into view even when its own UI Automation peer does not advertise
    the ScrollItem pattern: the agent scrolls the WPF object.
    """
    __tracebackhide__ = True
    return managed_capable(el) and getattr(el, "control_type", "") in _SCROLLABLE_ITEMS


def _settled_visible(el: UIAElement) -> bool:
    """Whether the element is on screen, allowing the layout a moment to follow a scroll."""
    __tracebackhide__ = True
    for attempt in range(_SETTLE_ATTEMPTS):
        if not el.is_offscreen:
            return True
        if attempt + 1 < _SETTLE_ATTEMPTS:
            time.sleep(0.05)
    return False


def _scroll_realized_item(el: UIAElement) -> None:
    """Scroll an off-screen element that is realized (a grid row or cell, a list item).

    First through UI Automation: the element's own ScrollItem pattern, then its row's. When the
    element is still off-screen, through the agent, which scrolls the WPF object into view.
    """
    __tracebackhide__ = True
    node: UIAElement | None = el
    for _ in range(_SCROLL_ANCESTORS + 1):
        if node is None or not patterns.has_pattern(node, "ScrollItem"):
            node = node.parent() if node is not None else None
            continue
        with contextlib.suppress(UIAError):
            patterns.scroll_into_view(node)
        if _settled_visible(el):
            return
        node = node.parent()
    if not managed_capable(el):
        return
    try:
        managed = to_managed(el)
        _wpf_act(
            managed,
            "scroll_into_view" if "ScrollItem" in _wpf_patterns(managed) else "bring_into_view",
        )
    except (InspectorError, ActionError, UIAError) as exc:
        log.debug("managed scroll into view failed for %s: %s", _short(el), exc)
        return
    _settled_visible(el)


def _top_level_hwnd(el: TargetElement) -> int:
    __tracebackhide__ = True
    if isinstance(el, WpfElement):
        handle = el.state().window_handle
        return win32.root_window(handle) if handle else 0
    node: TargetElement | None = el
    while node is not None:
        handle = node.native_window_handle
        if handle:
            return win32.root_window(handle)
        node = node.parent()
    return 0


def bring_to_front(el: TargetElement) -> bool:
    """Raise the owning window without clicking or focusing the control itself."""
    __tracebackhide__ = True
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
    hwnd = _top_level_hwnd(el)
    return bool(hwnd) and bool(win32.IsIconic(hwnd))


def raise_without_activating(el: TargetElement) -> bool:
    """Show the owning window above the others while the current window keeps keyboard focus."""
    __tracebackhide__ = True
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


# -- windows --------------------------------------------------------------------------------------


def _window_target(el: TargetElement) -> tuple[int, int]:
    """The top-level window handle and process id of a window element."""
    __tracebackhide__ = True
    if isinstance(el, WpfElement):
        state = el.client.state_get(el.ref, timeout_ms=2000, deadline=operation_deadline(2))
        return state.window_handle or 0, el.process_id
    uia = uia_of(el)
    return _top_level_hwnd(uia), uia.process_id


def activate_window(el: TargetElement) -> None:
    """Make the window the foreground window; ``ActionError`` when Windows refuses."""
    __tracebackhide__ = True
    hwnd, process_id = _window_target(el)
    if not hwnd or not win32.IsWindow(hwnd) or win32.window_pid(hwnd) != process_id:
        raise ActionError("The window is no longer available to activate")
    if win32.GetForegroundWindow() == hwnd:
        return
    raised = win32.bring_to_foreground(hwnd)
    if not raised and win32.GetForegroundWindow() != hwnd:
        raise ActionError("Windows refused to bring the window to the foreground")


def window_is_active(el: TargetElement) -> bool:
    """Whether the window, or a window it owns, is the foreground window."""
    __tracebackhide__ = True
    hwnd, _ = _window_target(el)
    current = win32.GetForegroundWindow()
    seen: set[int] = set()
    while current and current not in seen:
        if current == hwnd:
            return bool(hwnd)
        seen.add(current)
        current = win32.window_owner(current)
    return False


def activate_for_keys(el: TargetElement) -> None:
    """Activate the window and check it owns the foreground; no element focus is required."""
    __tracebackhide__ = True
    hwnd, process_id = _window_target(el)
    _window_guard(hwnd, process_id, activate=True)


def press_in_window(el: TargetElement, keys: str) -> None:
    """Activate the window and press keys; they go to whatever has focus inside it."""
    __tracebackhide__ = True
    activate_for_keys(el)
    input.press(keys)


def type_in_window(el: TargetElement, text: str) -> None:
    """Activate the window and type text into whatever has focus inside it."""
    __tracebackhide__ = True
    activate_for_keys(el)
    input.type_text(text)


def _require_normal_window(el: TargetElement, verb: str) -> None:
    __tracebackhide__ = True
    state = patterns.window_visual_state(el)
    if state != "normal":
        raise ActionError(f"Cannot {verb} a {state} window; call restore() first")


def move_window(el: TargetElement, x: int, y: int) -> None:
    """Move the window's top-left corner to physical screen coordinates."""
    __tracebackhide__ = True
    _require_normal_window(el, "move")
    if patterns.transform_can(el, "move"):
        patterns.transform_move(el, x, y)
        return
    hwnd, _ = _window_target(el)
    if not hwnd or not win32.move_resize_window(hwnd, x=x, y=y):
        raise ActionError("The window cannot be moved")


def resize_window(el: TargetElement, width: int, height: int) -> None:
    """Resize the window to ``width`` x ``height`` physical pixels (outer size)."""
    __tracebackhide__ = True
    _require_normal_window(el, "resize")
    if patterns.transform_can(el, "resize"):
        patterns.transform_resize(el, width, height)
        return
    hwnd, _ = _window_target(el)
    if not hwnd or not win32.move_resize_window(hwnd, width=width, height=height):
        raise ActionError("The window cannot be resized")


# -- mouse ----------------------------------------------------------------------------------------


Offset = tuple[int, int]


def parse_offset(x: int | None, y: int | None) -> Offset | None:
    """Combine the ``x``/``y`` arguments of an action into one offset (both or neither)."""
    __tracebackhide__ = True
    if (x is None) != (y is None):
        raise ActionError("x and y must be given together")
    if x is None or y is None:
        return None
    return int(x), int(y)


def parse_modifiers(text: str | None) -> tuple[int, ...]:
    """Parse a modifier string such as ``"Ctrl+Shift"`` into key codes."""
    __tracebackhide__ = True
    try:
        return input.parse_modifiers(text)
    except ValueError as exc:
        raise ActionError(str(exc)) from exc


def _offset_point(
    el_text: str, left: float, top: float, width: float, height: float, offset: Offset
) -> tuple[int, int]:
    __tracebackhide__ = True
    ox, oy = offset
    if not (0 <= ox < width and 0 <= oy < height):
        raise ActionError(
            f"Offset ({ox}, {oy}) lies outside {el_text} ({round(width)}x{round(height)} px)"
        )
    return round(left + ox), round(top + oy)


def _check_screen_point(x: int, y: int) -> None:
    __tracebackhide__ = True
    screen = win32.virtual_screen_rect()
    if not (screen.left <= x < screen.right and screen.top <= y < screen.bottom):
        raise ActionError(f"Drag destination ({x}, {y}) is outside the screen")


def _wpf_mouse_target(
    el: WpfElement,
    role: str | None = None,
    offset: Offset | None = None,
    *,
    guard: bool = True,
    header: bool = False,
    header_height: float | None = None,
) -> tuple[int, int]:
    """Resolve stable agent-verified physical-pixel geometry.

    ``offset`` replaces the default point by a position relative to the element's top-left corner.
    ``guard=False`` skips window activation and ownership checks (drag destinations).
    """
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
        if header:
            rect = state.bounds
            if (
                state.visible
                and not state.offscreen
                and rect
                and rect.width > 0
                and rect.height > 0
            ):
                dx, dy = _header_offset(rect.width, rect.height, header_height)
                return round(rect.x + dx), round(rect.y + dy)
        elif role is None:
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
    if guard:
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
    if offset is not None and bounds is not None:
        x, y = _offset_point(_short(el), bounds.x, bounds.y, bounds.width, bounds.height, offset)
    if bounds is None or not (
        bounds.x <= x < bounds.x + bounds.width and bounds.y <= y < bounds.y + bounds.height
    ):
        raise ActionError(f"{_short(el)} has no on-screen rectangle to click")
    if guard:
        hwnd = _wpf_window(el)
        if hwnd != state.window_handle:
            raise ActionError(
                "Target window ownership or foreground changed; refusing global input"
            )
        _validate_point(hwnd, el.process_id, x, y)
    return x, y


def _click_kwargs(button: MouseButton, count: int, modifiers: tuple[int, ...]) -> dict[str, Any]:
    __tracebackhide__ = True
    kwargs: dict[str, Any] = {"button": button, "count": count}
    if modifiers:
        kwargs["modifiers"] = modifiers
    return kwargs


def _header_offset(width: float, height: float, header_height: float | None) -> tuple[float, float]:
    """A point on the header row of a tree item whose rectangle also covers its children."""
    __tracebackhide__ = True
    row = height if header_height is None else max(1.0, min(height, header_height))
    return min(width / 2, _HEADER_X), row / 2


def click_header(el: TargetElement, header_height: float | None = None) -> None:
    """Click the header row of a tree item (its rectangle includes the expanded children).

    ``header_height`` is the height of that row; without it the whole rectangle is the row.
    """
    __tracebackhide__ = True
    if isinstance(el, WpfElement):
        x, y = _wpf_mouse_target(el, header=True, header_height=header_height)
        input.click(x, y, button="left", count=1)
        return
    uia = uia_of(el)
    rect = uia.rect
    if rect is None:
        raise ActionError(f"{_short(uia)} has no on-screen rectangle to click")
    dx, dy = _header_offset(rect.width, rect.height, header_height)
    _mouse_click(uia, offset=(int(dx), int(dy)))


def _wpf_mouse_click(
    el: WpfElement,
    button: MouseButton = "left",
    count: int = 1,
    *,
    role: str | None = None,
    offset: Offset | None = None,
    modifiers: tuple[int, ...] = (),
) -> None:
    __tracebackhide__ = True
    x, y = _wpf_mouse_target(el, role, offset)
    input.click(x, y, **_click_kwargs(button, count, modifiers))


def _mouse_target(
    el: UIAElement, offset: Offset | None = None, *, guard: bool = True
) -> tuple[int, int]:
    __tracebackhide__ = True
    ensure_visible(el)
    if guard:
        _foreground(el)
    waits.wait_for_state(lambda: el, "stable", _STABLE_TIMEOUT, f"{_short(el)} to stop moving")
    rect = el.rect
    if rect is None:
        raise ActionError(f"{_short(el)} has no on-screen rectangle to click")
    if offset is not None:
        return _offset_point(_short(el), rect.left, rect.top, rect.width, rect.height, offset)
    return rect.center


def _mouse_click(
    el: UIAElement,
    button: MouseButton = "left",
    count: int = 1,
    *,
    offset: Offset | None = None,
    modifiers: tuple[int, ...] = (),
) -> None:
    __tracebackhide__ = True
    x, y = _mouse_target(el, offset)
    _validate_mouse_target(el, x, y)
    input.click(x, y, **_click_kwargs(button, count, modifiers))


def _validate_mouse_target(el: UIAElement, x: int, y: int) -> None:
    __tracebackhide__ = True
    hwnd = _validate_foreground(el)
    popup = _owned_popup_at(hwnd, el.process_id, x, y)
    if popup:
        # Submenus, context menus and drop-downs live in popup windows owned by the app's window.
        _window_guard(popup, el.process_id)
        return
    _validate_point(hwnd, el.process_id, x, y)


def _owned_popup_at(hwnd: int, process_id: int, x: int, y: int) -> int:
    """The root window under the point when it is a window of this process owned by ``hwnd``."""
    __tracebackhide__ = True
    hit = win32.WindowFromPoint(win32.POINT(x, y))
    if not hit:
        return 0
    top = win32.root_window(hit)
    if top == hwnd or win32.window_pid(top) != process_id:
        return 0
    seen = {top}
    owner = win32.window_owner(top)
    while owner and owner not in seen:
        if owner == hwnd:
            return top
        seen.add(owner)
        owner = win32.window_owner(owner)
    return 0


def _validate_point(hwnd: int, process_id: int, x: int, y: int) -> None:
    __tracebackhide__ = True
    deadline = operation_deadline(_STABLE_TIMEOUT)
    while True:
        hit = win32.WindowFromPoint(win32.POINT(x, y))
        if hit and win32.root_window(hit) == hwnd and win32.window_pid(hit) == process_id:
            _window_guard(hwnd, process_id)
            return
        remaining = deadline - time.monotonic()
        if (
            remaining <= 0
            or not hit
            or win32.window_pid(hit) != process_id
            or win32.root_window(hit) != win32.window_owner(hwnd)
            or not win32.IsWindowVisible(hwnd)
        ):
            raise ActionError("Target point belongs to another window; refusing global input")
        _window_guard(hwnd, process_id)
        time.sleep(min(waits.STABLE_INTERVAL, remaining))


def click(
    el: TargetElement,
    *,
    mode: InputMode = "pattern",
    button: MouseButton = "left",
    offset: Offset | None = None,
    modifiers: tuple[int, ...] = (),
) -> str:
    """Click the element; returns the strategy used (``invoke``, ``toggle``, ``mouse`` ...).

    A position, a non-left button or modifier keys always use the mouse.
    """
    __tracebackhide__ = True
    plain = button == "left" and offset is None and not modifiers
    if isinstance(el, WpfElement) and mode == "pattern" and plain:
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
        if plain:
            _wpf_mouse_click(el, button=button)
        else:
            _wpf_mouse_click(el, button=button, offset=offset, modifiers=modifiers)
        return "mouse"
    el = uia_of(el)
    if mode == "pattern" and plain:
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
    if plain:
        _mouse_click(el, button=button)
    else:
        _mouse_click(el, button=button, offset=offset, modifiers=modifiers)
    return "mouse"


def _repeat_click(
    el: TargetElement,
    button: MouseButton,
    count: int,
    offset: Offset | None,
    modifiers: tuple[int, ...],
) -> None:
    __tracebackhide__ = True
    if isinstance(el, WpfElement):
        _wpf_mouse_click(el, button=button, count=count, offset=offset, modifiers=modifiers)
        return
    _mouse_click(uia_of(el), button=button, count=count, offset=offset, modifiers=modifiers)


def double_click(
    el: TargetElement, *, offset: Offset | None = None, modifiers: tuple[int, ...] = ()
) -> None:
    __tracebackhide__ = True
    _repeat_click(el, "left", 2, offset, modifiers)


def right_click(
    el: TargetElement, *, offset: Offset | None = None, modifiers: tuple[int, ...] = ()
) -> None:
    __tracebackhide__ = True
    _repeat_click(el, "right", 1, offset, modifiers)


def middle_click(
    el: TargetElement, *, offset: Offset | None = None, modifiers: tuple[int, ...] = ()
) -> None:
    __tracebackhide__ = True
    _repeat_click(el, "middle", 1, offset, modifiers)


def _source_point(el: TargetElement, offset: Offset | None) -> tuple[int, int]:
    """A validated point on ``el``: its window is active and owns the point."""
    __tracebackhide__ = True
    if isinstance(el, WpfElement):
        return _wpf_mouse_target(el, None, offset)
    uia = uia_of(el)
    x, y = _mouse_target(uia, offset)
    _validate_mouse_target(uia, x, y)
    return x, y


def _destination_point(el: TargetElement, offset: Offset | None) -> tuple[int, int]:
    """A point on ``el`` that may belong to another window of the application."""
    __tracebackhide__ = True
    if isinstance(el, WpfElement):
        x, y = _wpf_mouse_target(el, None, offset, guard=False)
    else:
        x, y = _mouse_target(uia_of(el), offset, guard=False)
    _check_screen_point(x, y)
    return x, y


def hover(el: TargetElement) -> None:
    __tracebackhide__ = True
    x, y = _source_point(el, None)
    input.move_mouse(x, y)


def drag_to(
    el: TargetElement,
    destination: TargetElement,
    *,
    source_offset: Offset | None = None,
    target_offset: Offset | None = None,
    button: MouseButton = "left",
    modifiers: tuple[int, ...] = (),
) -> None:
    """Drag from ``el`` to ``destination`` (resolved first, so the source window ends up active)."""
    __tracebackhide__ = True
    x2, y2 = _destination_point(destination, target_offset)
    x1, y1 = _source_point(el, source_offset)
    input.drag(x1, y1, x2, y2, button=button, modifiers=modifiers)


def drag_by(
    el: TargetElement,
    dx: int,
    dy: int,
    *,
    source_offset: Offset | None = None,
    button: MouseButton = "left",
    modifiers: tuple[int, ...] = (),
) -> None:
    __tracebackhide__ = True
    x1, y1 = _source_point(el, source_offset)
    x2, y2 = x1 + int(dx), y1 + int(dy)
    _check_screen_point(x2, y2)
    input.drag(x1, y1, x2, y2, button=button, modifiers=modifiers)


def scroll(
    el: TargetElement, clicks: int, *, offset: Offset | None = None, horizontal: bool = False
) -> None:
    """Turn the mouse wheel over the element; positive scrolls up (or right if horizontal)."""
    __tracebackhide__ = True
    x, y = _source_point(el, offset)
    input.scroll_wheel(x, y, clicks, horizontal=horizontal)


# -- text -----------------------------------------------------------------------------------------


def is_password(el: TargetElement) -> bool:
    __tracebackhide__ = True
    if isinstance(el, WpfElement):
        return bool(_wpf_read(el, "is_password", fail_closed=True, independent_deadline=True))
    try:
        el = uia_of(el)
    except NoUiaPeerError:
        return True
    return el.get_property("IsPassword") == 1 or el.class_name == "PasswordBox"


class PasswordClassifier:
    """Remember completed WPF classifications for one action or expectation."""

    def __init__(self) -> None:
        __tracebackhide__ = True
        self._results: dict[tuple[object, str, str, int], bool] = {}

    def is_password(self, el: TargetElement) -> bool:
        __tracebackhide__ = True
        if not isinstance(el, WpfElement):
            return is_password(el)
        key = (el.client, el.ref.session_id, el.ref.object_id, el.ref.generation)
        if key not in self._results:
            self._results[key] = is_password(el)
        return self._results[key]


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
    """Return text, treating unavailable elements as empty."""
    __tracebackhide__ = True
    try:
        return _get_text(el)
    except UIAError as exc:
        if exc.element_gone:
            return ""
        raise


def _get_text(el: TargetElement) -> str:
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


def _new_dialog(el: TargetElement, previous: set[int]) -> str | None:
    __tracebackhide__ = True
    for hwnd in win32.top_level_windows({el.process_id}):
        if hwnd not in previous and win32.is_dialog_window(hwnd):
            return win32.window_text(hwnd) or "Untitled"
    return None


def set_checked(
    el: TargetElement, checked: bool, *, mode: InputMode = "pattern", timeout: float | None = None
) -> None:
    """Toggle a check box or toggle button until it reaches the requested state."""
    __tracebackhide__ = True
    if mode == "mouse":
        if is_checked(el) == checked:
            return
        windows = set(win32.top_level_windows({el.process_id}))
        click(el, mode="mouse")
        deadline = time.monotonic() + (runtime.get_config().timeout if timeout is None else timeout)
        while is_checked(el) != checked:
            dialog = _new_dialog(el, windows)
            if dialog is not None:
                raise ActionError(
                    f'The click opened a dialog "{dialog}"; the checked state did not change.'
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ActionError(
                    "The click did not change the checked state; it may have opened a dialog."
                )
            time.sleep(min(waits.POLL_INTERVAL, remaining))
        return
    if isinstance(el, WpfElement):
        target_name = "On" if checked else "Off"
        for _ in range(3):
            if _wpf_read(el, "toggle_state", "Toggle") == target_name:
                return
            windows = set(win32.top_level_windows({el.process_id}))
            try:
                _wpf_act(el, "toggle", "Toggle")
            except (InspectorError, UIAError) as exc:
                cause: BaseException | None = exc
                seen: set[int] = set()
                while cause is not None and id(cause) not in seen:
                    seen.add(id(cause))
                    if isinstance(cause, InspectorDeadlineError) or (
                        isinstance(cause, InspectorError) and cause.code == "dispatcherUnavailable"
                    ):
                        break
                    cause = cause.__cause__
                if isinstance(cause, InspectorDeadlineError) or (
                    isinstance(cause, InspectorError) and cause.code == "dispatcherUnavailable"
                ):
                    dialog = _new_dialog(el, windows)
                    if dialog is not None:
                        raise ActionError(
                            f'The toggle opened a dialog "{dialog}"; '
                            "the checked state did not change."
                        ) from exc
                raise
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


def toggle(el: TargetElement, *, mode: InputMode = "pattern", timeout: float | None = None) -> None:
    __tracebackhide__ = True
    if mode == "mouse":
        set_checked(el, not is_checked(el), mode=mode, timeout=timeout)
        return
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


def is_expanded(el: TargetElement) -> bool:
    """Whether the element reports the Expanded state (False when it has no such state)."""
    __tracebackhide__ = True
    try:
        if isinstance(el, WpfElement):
            return _wpf_read(el, "expand_state", "ExpandCollapse") == "Expanded"
        return patterns.expand_state(uia_of(el)) == ExpandCollapseState.Expanded
    except (ActionError, UIAError):
        return False


def _grid_selection(
    el: TargetElement, rows: list[GridRow] | None = None, *, for_removal: bool = False
) -> dict[str, list[TargetElement]]:
    """Group selected rows and cells by row identity without reading every cell."""
    __tracebackhide__ = True
    row_elements = {
        row.element.runtime_id: row.element
        for row in (rows if rows is not None else grid_data_rows(el))
    }
    selected: dict[str, list[TargetElement]] = {}
    for item in patterns.selection(el):
        try:
            row_id = item.runtime_id
            if row_id not in row_elements:
                parent = item.parent()
                row_id = parent.runtime_id if parent is not None else ""
            if row_id in row_elements:
                selected.setdefault(row_id, []).append(item)
        except UIAError as exc:
            if not exc.element_gone:
                raise
    if for_removal:
        for row_id in selected:
            row = row_elements[row_id]
            if is_selected(row):
                selected[row_id] = [row]
    return selected


def selected_items(el: TargetElement) -> list[str]:
    """Names of the selected items of a list-like element."""
    __tracebackhide__ = True
    if _is_grid(el):
        rows = grid_data_rows(el)
        selected = _grid_selection(el, rows)
        return [row.text for row in rows if row.element.runtime_id in selected]
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
    if _is_grid(el):
        rows = grid_data_rows(el, index + 1)
        return rows[index].element if index < len(rows) else None
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


def _wpf_realize(el: WpfElement, item: Item) -> WpfElement:
    """Realize one item of a container and return its element."""
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
    return WpfElement(el.client, result.handle, el.process_id)


def _wpf_select(el: WpfElement, item: Item, *, mode: InputMode, combo: bool) -> None:
    __tracebackhide__ = True
    if combo:
        expand(el, mode=mode)
    try:
        chosen = _wpf_realize(el, item)
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
    if _is_grid(el):
        chosen = _resolve_grid_item(el, item)
        if mode == "mouse":
            _click_item(el, chosen, ())
        else:
            _scroll_item(chosen)
            select_self(chosen)
        return
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


# -- multi-selection ------------------------------------------------------------------------------

Items = Sequence[Item]
_CTRL = input.parse_modifiers("Ctrl")


def _unique_items(items: Items) -> list[Item]:
    __tracebackhide__ = True
    unique: dict[str, Item] = {}
    for item in items:
        unique.setdefault(_describe_item(item), item)
    return list(unique.values())


def _multi_container(el: TargetElement, count: int) -> None:
    """Refuse a container that cannot select several items."""
    __tracebackhide__ = True
    if isinstance(el, WpfElement):
        available = _wpf_patterns(el)
        kind = str(_wpf_read(el, "control_type"))
    else:
        uia = uia_of(el)
        available = {"Selection"} if patterns.has_pattern(uia, "Selection") else set[str]()
        kind = uia.control_type
    if kind == "ComboBox" or "Selection" not in available:
        raise ActionError(f"Multi-selection is not supported on {_short(el)}")
    if count > 1 and not patterns.can_select_multiple(el):
        raise ActionError(
            f"{_short(el)} does not allow selecting more than one item (CanSelectMultiple is false)"
        )


def _resolve_item(el: TargetElement, item: Item, mode: InputMode) -> TargetElement:
    """The element of one item: an agent element for WPF mouse input, else its UIA peer.

    The agent has no add or remove selection verbs, so pattern input goes through the UIA tree.
    """
    __tracebackhide__ = True
    if _is_grid(el):
        return _resolve_grid_item(el, item)
    if isinstance(el, WpfElement) and mode == "mouse":
        return _wpf_realize(el, item)
    uia = uia_of(el)
    chosen = _item_by_index(uia, item) if isinstance(item, int) else _find_listed_item(uia, item)
    if chosen is None:
        available = [c for t in _ITEM_TYPES for c in query_all(uia, Locator(control_type=t))]
        raise _item_not_found(uia, item, available)
    return chosen


def _scroll_item(chosen: TargetElement) -> None:
    __tracebackhide__ = True
    if patterns.has_pattern(chosen, "ScrollItem"):
        patterns.scroll_into_view(chosen)


def _click_item(
    container: TargetElement, chosen: TargetElement, modifiers: tuple[int, ...]
) -> None:
    """Click an item with the mouse (a grid row at its row header)."""
    __tracebackhide__ = True
    if isinstance(chosen, WpfElement):
        if isinstance(container, WpfElement) and _wpf_read(container, "control_type") == "DataGrid":
            try:
                x, y = _wpf_mouse_target(chosen, "gridRowHeader")
            except ActionError:
                pass
            else:
                input.click(x, y, **_click_kwargs("left", 1, modifiers))
                return
        _wpf_mouse_click(chosen, modifiers=modifiers)
        return
    uia = uia_of(chosen)
    if uia.control_type == "DataItem":
        # The empty part of a grid row does not take clicks: use its row header, else a cell.
        cells = uia.children()
        header = next((c for c in cells if c.control_type == "HeaderItem"), None)
        uia = header or (cells[0] if cells else uia)
    _mouse_click(uia, modifiers=modifiers)


def _select_only(container: TargetElement, chosen: TargetElement, mode: InputMode) -> None:
    __tracebackhide__ = True
    if mode == "mouse":
        _click_item(container, chosen, ())
        return
    _scroll_item(chosen)
    select_self(chosen)


def _toggle_on(container: TargetElement, chosen: TargetElement, mode: InputMode) -> None:
    __tracebackhide__ = True
    if mode == "mouse":
        _click_item(container, chosen, _CTRL)
        return
    _scroll_item(chosen)
    patterns.add_to_selection(chosen)


def _toggle_off(container: TargetElement, chosen: TargetElement, mode: InputMode) -> None:
    __tracebackhide__ = True
    if mode == "mouse":
        _click_item(container, chosen, _CTRL)
        return
    _scroll_item(chosen)
    patterns.remove_from_selection(chosen)


def _verify_selection(el: TargetElement, expected: Counter[str], timeout: float) -> None:
    """Wait for the selection to equal ``expected``; ``ActionError`` naming both otherwise."""
    __tracebackhide__ = True
    try:
        waits.wait_until(
            lambda: Counter(selected_items(el)) == expected or None,
            timeout,
            description=f"the selection of {_short(el)}",
        )
    except waits.WaitTimeoutError:
        actual = selected_items(el)
        raise ActionError(
            f"The selection of {_short(el)} is {actual}, expected {list(expected.elements())}"
        ) from None


def select_items(
    el: TargetElement,
    items: Items,
    *,
    add: bool = False,
    mode: InputMode = "pattern",
    timeout: float = 2.0,
) -> None:
    """Select several items: replace the selection (``add=False``) or add to it.

    Pattern mode uses Select and AddToSelection, mouse mode a plain click and Ctrl+clicks. Fails
    with ``ActionError`` when the resulting selection differs from the requested one.
    """
    __tracebackhide__ = True
    unique = _unique_items(items)
    if not unique:
        raise ActionError("select() needs at least one item; use clear_selection() to select none")
    _multi_container(el, len(unique))
    expected = Counter(selected_items(el)) if add else Counter[str]()
    for position, item in enumerate(unique):
        chosen = _resolve_item(el, item, mode)
        name = _grid_row_text(el, chosen) if _is_grid(el) else chosen.name
        if position == 0 and not add:
            _select_only(el, chosen, mode)
            expected = Counter({name: 1})
        elif not is_selected(chosen):
            _toggle_on(el, chosen, mode)
            expected[name] += 1
    _verify_selection(el, expected, timeout)


_MOUSE_DESELECT_LIMIT = 256


def _selection_ids(items: Sequence[TargetElement]) -> tuple[str, ...]:
    """Runtime ids of a fresh selection read; an item that vanished meanwhile is skipped."""
    __tracebackhide__ = True
    ids: list[str] = []
    for item in items:
        try:
            ids.append(item.runtime_id)
        except UIAError as exc:
            if not exc.element_gone:
                raise
    return tuple(ids)


def _selected_grid_row_targets(el: TargetElement, row: TargetElement) -> list[TargetElement]:
    """Read the current selection for one freshly resolved grid row."""
    __tracebackhide__ = True
    if is_selected(row):
        return [row]
    row_id = row.runtime_id
    targets: list[TargetElement] = []
    for selected in patterns.selection(el):
        try:
            parent = selected.parent()
            if selected.runtime_id == row_id or (
                parent is not None and parent.runtime_id == row_id
            ):
                targets.append(selected)
        except UIAError as exc:
            if not exc.element_gone:
                raise
    return targets


def deselect_items(
    el: TargetElement, items: Items, *, mode: InputMode = "pattern", timeout: float = 2.0
) -> None:
    """Remove items from the selection (RemoveFromSelection, or Ctrl+click in mouse mode)."""
    __tracebackhide__ = True
    unique = _unique_items(items)
    if not unique:
        raise ActionError("deselect() needs at least one item; use clear_selection() to clear")
    _multi_container(el, 1)
    expected = Counter(selected_items(el))
    grid = _is_grid(el)
    selected = _grid_selection(el, for_removal=True) if grid and mode != "mouse" else {}
    for item in unique:
        chosen = _resolve_item(el, item, mode)
        name = _grid_row_text(el, chosen) if grid else chosen.name
        if grid and mode == "mouse":
            removed = False
            previous: tuple[str, ...] | None = None
            for _ in range(_MOUSE_DESELECT_LIMIT):
                chosen = _resolve_item(el, item, mode)
                targets = _selected_grid_row_targets(el, chosen)
                current = _selection_ids(targets)
                # Stop when the last click changed nothing; _verify_selection reports it.
                if not targets or current == previous:
                    break
                previous = current
                _toggle_off(el, chosen, mode)
                removed = True
            if removed:
                expected[name] -= 1
        else:
            targets = (
                selected.pop(chosen.runtime_id, [])
                if grid
                else ([chosen] if is_selected(chosen) else [])
            )
            for target in targets:
                _toggle_off(el, target, mode)
            if targets:
                expected[name] -= 1
    _verify_selection(el, +expected, timeout)


def clear_selection(
    el: TargetElement, *, mode: InputMode = "pattern", timeout: float = 2.0
) -> None:
    """Deselect every selected item."""
    __tracebackhide__ = True
    _multi_container(el, 1)
    if mode == "mouse":
        previous: tuple[str, ...] | None = None
        for _ in range(_MOUSE_DESELECT_LIMIT):
            if _is_grid(el):
                rows = grid_data_rows(el)
                selected = _grid_selection(el, rows, for_removal=True)
                chosen_items = [row.element for row in rows if row.element.runtime_id in selected]
                current = tuple(
                    value
                    for row in chosen_items
                    for value in (row.runtime_id, *_selection_ids(selected[row.runtime_id]))
                )
            else:
                chosen_items = patterns.selection(el)
                current = _selection_ids(chosen_items)
            # Stop when the last click changed nothing; _verify_selection reports it.
            if not chosen_items or current == previous:
                break
            previous = current
            try:
                _toggle_off(el, chosen_items[0], mode)
            except UIAError as exc:
                if not exc.element_gone:
                    raise
    else:
        chosen_items = (
            [item for items in _grid_selection(el, for_removal=True).values() for item in items]
            if _is_grid(el)
            else patterns.selection(el)
        )
        for chosen in chosen_items:
            try:
                _toggle_off(el, chosen, mode)
            except UIAError as exc:
                if not exc.element_gone:
                    raise
    _verify_selection(el, Counter[str](), timeout)


# -- grid contents --------------------------------------------------------------------------------


def grid_headers(el: TargetElement) -> list[str]:
    """The column header names of a grid (empty when it exposes none)."""
    __tracebackhide__ = True
    try:
        return [header.name for header in patterns.column_headers(el)]
    except (ActionError, UIAError):
        return []


def _is_grid(el: TargetElement) -> bool:
    """Whether selection uses grid rows rather than generic list items."""
    __tracebackhide__ = True
    if isinstance(el, WpfElement):
        return str(_wpf_read(el, "control_type")) == "DataGrid"
    return el.control_type == "DataGrid"


class GridRow:
    """A data row whose cells and display text are fetched on demand."""

    def __init__(
        self,
        raw_index: int,
        element: UIAElement,
        grid: UIAElement,
        first: UIAElement,
        columns: int,
        hidden: set[int],
        headers: list[str],
    ) -> None:
        __tracebackhide__ = True
        self.raw_index = raw_index
        self.element = element
        self._grid = grid
        self._cells: list[UIAElement | None] = [first, *([None] * (columns - 1))]
        self._texts: list[str] | None = None
        self.hidden = hidden
        self.headers = headers

    @property
    def column_count(self) -> int:
        __tracebackhide__ = True
        return len(self._cells)

    def cell(self, column: int) -> UIAElement:
        """One cell, fetched on first use (the other cells are not touched)."""
        __tracebackhide__ = True
        found = self._cells[column]
        if found is None:
            found = self._cells[column] = patterns.grid_item(self._grid, self.raw_index, column)
        return found

    @property
    def cells(self) -> list[UIAElement]:
        __tracebackhide__ = True
        return [self.cell(column) for column in range(len(self._cells))]

    @property
    def texts(self) -> list[str]:
        __tracebackhide__ = True
        if self._texts is None:
            self._texts = [self.cell_text(i) for i in range(len(self._cells))]
        return self._texts

    def cell_text(self, column: int) -> str:
        __tracebackhide__ = True
        if column in self.hidden:
            return ""
        try:
            cell = self.cell(column)
            if column >= len(self.headers) or not self.headers[column]:
                cell.get_property("IsPassword")
            value = get_text(cell).strip()
        except UIAError as exc:
            if not exc.element_gone:
                raise
            if column >= len(self.headers) or not self.headers[column]:
                self.hidden.add(column)
            return ""
        return value

    @property
    def text(self) -> str:
        __tracebackhide__ = True
        return " ".join(text for i, text in enumerate(self.texts) if i not in self.hidden)


def _managed_group_row(grid: WpfElement, row: UIAElement) -> bool | None:
    """Identify a WPF group item when the managed row can be mapped."""
    __tracebackhide__ = True
    try:
        rid, hwnd = runtime.managed_element_identity(row)
        mapping = grid.client.resolve(rid, hwnd, deadline=operation_deadline(2))
        if mapping.status != "exact" or mapping.object_ref is None:
            return None
        ref = mapping.object_ref
        values, _ = grid.client.read(
            ref.object_id,
            ref.generation,
            [(PathSegment("property", "Item"),)],
            deadline=operation_deadline(2),
        )
        value = values[0].value
        if value.status != "ok":
            return None
        info = value.type_info or (value.object_ref.type if value.object_ref else None)
        names = [value.runtime_type]
        if info is not None:
            names.extend(info.base_types)
        return any("CollectionViewGroup" in name for name in names)
    except (InspectorError, UIAError):
        return None


def grid_data_rows(el: TargetElement, limit: int | None = None) -> list[GridRow]:
    """Data rows (no group headers or placeholders), stopping after ``limit`` when it is given.

    Named rows are checked lazily until a readable nonempty cell is found. Without a limit,
    the whole grid is walked and refused beyond ``MAX_TABLE_ROWS`` rows.
    """
    __tracebackhide__ = True
    from wintestkit.engine.table import MAX_TABLE_ROWS

    grid = uia_of(el)
    count, columns = patterns.grid_size(grid)
    if limit is None and count > MAX_TABLE_ROWS:
        raise ActionError(
            f"{_short(el)} has {count} rows; reading a table is limited to {MAX_TABLE_ROWS} rows"
        )
    result: list[GridRow] = []
    headers = grid_headers(el)
    hidden: set[int] = set()
    if not columns or limit == 0:
        return result
    for index in range(count):
        for attempt in range(2):
            try:
                first = patterns.grid_item(grid, index, 0)
                row = first.parent()
                if row is None or row.control_type in ("Group", "Header", "HeaderItem"):
                    break
                if row.class_name in ("GroupItem", "DataGridColumnHeader"):
                    break
                if row.framework_id == "WPF" and row.class_name and row.class_name != "DataGridRow":
                    break
                if row.name in ("{NewItemPlaceholder}", "NewItemPlaceholder"):
                    break
                candidate = GridRow(index, row, grid, first, columns, hidden, headers)
                managed_group = _managed_group_row(el, row) if isinstance(el, WpfElement) else None
                if managed_group is True or (
                    managed_group is None
                    and row.name
                    and not any(candidate.cell_text(c) for c in range(columns))
                ):
                    break
                result.append(candidate)
                break
            except UIAError as exc:
                if not exc.element_gone:
                    raise
                if attempt == 1:
                    break
        if limit is not None and len(result) >= limit:
            break
    return result


def _resolve_grid_item(el: TargetElement, item: Item) -> UIAElement:
    __tracebackhide__ = True
    rows = (
        grid_data_rows(el, item + 1 if item >= 0 else None)
        if isinstance(item, int)
        else grid_data_rows(el)
    )
    if isinstance(item, int):
        found = rows[item] if 0 <= item < len(rows) else None
    else:
        found = next(
            (
                row
                for row in rows
                if _item_matches(item, row.text)
                or any(_item_matches(item, text) for text in row.texts)
            ),
            None,
        )
    if found is not None:
        return found.element
    names = [row.text for row in rows]
    shown = ", ".join(quote(name[:120]) for name in names[:10]) or "none"
    if len(names) > 10:
        shown += f", ... {len(names) - 10} more"
    raise ActionError(f"No grid row {_describe_item(item)} (available: {shown})")


def _grid_row_text(el: TargetElement, chosen: TargetElement) -> str:
    __tracebackhide__ = True
    for row in grid_data_rows(el):
        if row.element.same_as(uia_of(chosen)):
            return row.text
    raise ActionError("The selected grid row is no longer available")


def read_grid(el: TargetElement, columns: Sequence[int] | None = None) -> list[list[str]]:
    """Read cell texts of data rows, excluding group headers and placeholders."""
    __tracebackhide__ = True
    rows = grid_data_rows(el)
    if rows and columns is None:
        _ = rows[0].texts
    return [
        [
            row.cell_text(column)
            for column in (range(row.column_count) if columns is None else columns)
            if columns is not None or column not in row.hidden
        ]
        for row in rows
    ]
