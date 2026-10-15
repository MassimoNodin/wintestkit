"""Actions on already-resolved elements.

The model layer re-resolves the locator and waits for the element before calling these, so every
function here assumes ``el`` is current. Each prefers a UI Automation pattern and falls back to
synthetic mouse and keyboard input.
"""

from __future__ import annotations

import logging
import re
from typing import Literal

from wintestkit.engine import waits
from wintestkit.engine.diagnose import Candidate, Diagnostic, quote
from wintestkit.engine.locator import Locator
from wintestkit.engine.query import query_all
from wintestkit.errors import ActionError, ElementNotFoundError, UIAError
from wintestkit.uia import element, input, patterns, win32
from wintestkit.uia.constants import ExpandCollapseState, ToggleState
from wintestkit.uia.element import UIAElement

log = logging.getLogger("wintestkit.actions")

InputMode = Literal["pattern", "mouse"]
MouseButton = input.MouseButton

_ITEM_TYPES = ("ListItem", "DataItem", "TreeItem", "TabItem")
_STABLE_TIMEOUT = 1.0
MAX_LISTED_ITEMS = 5


def _short(el: UIAElement) -> str:
    __tracebackhide__ = True
    try:
        return el.info().short()
    except UIAError:
        return repr(el)


# -- visibility and focus -------------------------------------------------------------------------


def ensure_visible(el: UIAElement) -> None:
    """Scroll a virtualized or scrolled-away element into view."""
    __tracebackhide__ = True
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


def bring_to_front(el: UIAElement) -> bool:
    """Raise the owning window without clicking or focusing the control itself."""
    __tracebackhide__ = True
    hwnd = _top_level_hwnd(el)
    if not hwnd:
        return False
    raised = win32.bring_to_foreground(hwnd)
    if not raised:
        log.debug("could not bring window %#x to the foreground", hwnd)
    return raised


def _foreground(el: UIAElement) -> None:
    __tracebackhide__ = True
    bring_to_front(el)


def focus(el: UIAElement) -> None:
    """Give the element keyboard focus (bringing its window forward first)."""
    __tracebackhide__ = True
    _foreground(el)
    try:
        el.set_focus()
    except UIAError as exc:
        raise ActionError(f"{_short(el)} cannot take keyboard focus: {exc}") from exc


# -- mouse ----------------------------------------------------------------------------------------


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
    input.click(x, y, button=button, count=count)


def click(el: UIAElement, *, mode: InputMode = "pattern", button: MouseButton = "left") -> str:
    """Click the element; returns the strategy used (``invoke``, ``toggle``, ``mouse`` ...)."""
    __tracebackhide__ = True
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


def double_click(el: UIAElement) -> None:
    __tracebackhide__ = True
    _mouse_click(el, count=2)


def right_click(el: UIAElement) -> None:
    __tracebackhide__ = True
    _mouse_click(el, button="right")


def hover(el: UIAElement) -> None:
    __tracebackhide__ = True
    x, y = _mouse_target(el)
    input.move_mouse(x, y)


# -- text -----------------------------------------------------------------------------------------


def _is_password(el: UIAElement) -> bool:
    __tracebackhide__ = True
    return el.class_name == "PasswordBox"


def _can_set_value(el: UIAElement) -> bool:
    __tracebackhide__ = True
    return patterns.has_pattern(el, "Value") and not patterns.is_read_only(el)


def type_text(el: UIAElement, text: str, *, clear: bool = True, keys: bool = False) -> str:
    """Enter text; returns ``"value"`` (ValuePattern) or ``"keys"`` (keyboard input)."""
    __tracebackhide__ = True
    if not keys and _can_set_value(el) and (clear or not _is_password(el)):
        try:
            patterns.set_value(el, text if clear else patterns.get_value(el) + text)
            return "value"
        except UIAError as exc:
            log.debug("ValuePattern.SetValue failed (%s); falling back to keys", exc)
    focus(el)
    # Appending needs the caret at the end: SetValue and focus changes can leave it at the start.
    input.press("Ctrl+A Delete" if clear else "Ctrl+End")
    input.type_text(text)
    return "keys"


def clear(el: UIAElement) -> None:
    """Remove all text from an edit control."""
    __tracebackhide__ = True
    if _can_set_value(el):
        try:
            patterns.set_value(el, "")
            return
        except UIAError as exc:
            log.debug("ValuePattern.SetValue failed (%s); falling back to keys", exc)
    focus(el)
    input.press("Ctrl+A Delete")


def press(el: UIAElement, keys: str) -> None:
    """Focus the element and press key combinations such as ``"Ctrl+S"``."""
    __tracebackhide__ = True
    focus(el)
    input.press(keys)


def get_text(el: UIAElement) -> str:
    """The element's text: its value, document text or UIA name."""
    __tracebackhide__ = True
    if patterns.has_pattern(el, "Value") and not _is_password(el):
        return patterns.get_value(el)
    if patterns.has_pattern(el, "Text"):
        return patterns.document_text(el)
    return el.name


def get_value(el: UIAElement) -> str:
    __tracebackhide__ = True
    return patterns.get_value(el)


# -- state ----------------------------------------------------------------------------------------


def set_checked(el: UIAElement, checked: bool) -> None:
    """Toggle a check box or toggle button until it reaches the requested state."""
    __tracebackhide__ = True
    target = ToggleState.On if checked else ToggleState.Off
    for _ in range(3):
        if patterns.toggle_state(el) == target:
            return
        patterns.toggle(el)
    if patterns.toggle_state(el) != target:
        raise ActionError(f"{_short(el)} did not reach the {target.name} state")


def is_checked(el: UIAElement) -> bool:
    __tracebackhide__ = True
    return patterns.toggle_state(el) == ToggleState.On


def expand(el: UIAElement) -> None:
    __tracebackhide__ = True
    patterns.expand(el)


def collapse(el: UIAElement) -> None:
    __tracebackhide__ = True
    patterns.collapse(el)


def selected_items(el: UIAElement) -> list[str]:
    """Names of the selected items of a list-like element."""
    __tracebackhide__ = True
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


def select(el: UIAElement, item: Item) -> None:
    """Select an item of a combo box, list, grid, tree or tab control by name, regex or index."""
    __tracebackhide__ = True
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
