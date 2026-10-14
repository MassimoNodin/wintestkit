# pyright: basic
"""Functional wrappers around UI Automation control patterns.

Every function takes a ``UIAElement`` and raises ``ActionError`` when the element does not
support the required pattern. COM failures surface as ``UIAError``.
"""

from __future__ import annotations

from typing import Any

import comtypes
import comtypes.automation

from wintestkit.errors import ActionError
from wintestkit.uia import com
from wintestkit.uia.constants import PATTERN_IDS, PROPERTY_IDS, ExpandCollapseState, ToggleState
from wintestkit.uia.element import UIAElement, array_to_list

_SCROLL_AMOUNTS = {
    "none": "ScrollAmount_NoAmount",
    "small_inc": "ScrollAmount_SmallIncrement",
    "small_dec": "ScrollAmount_SmallDecrement",
    "large_inc": "ScrollAmount_LargeIncrement",
    "large_dec": "ScrollAmount_LargeDecrement",
}
_WINDOW_STATES = {
    "normal": "WindowVisualState_Normal",
    "maximized": "WindowVisualState_Maximized",
    "minimized": "WindowVisualState_Minimized",
}


def _describe(el: UIAElement) -> str:
    __tracebackhide__ = True
    try:
        return el.info().short()
    except Exception:
        return repr(el)


def _raw_pattern(el: UIAElement, name: str) -> Any:
    __tracebackhide__ = True
    try:
        pattern = el.raw.GetCurrentPattern(PATTERN_IDS[name])
    except comtypes.COMError:
        return None
    return pattern or None


def _pattern(el: UIAElement, name: str) -> Any:
    __tracebackhide__ = True
    pattern = _raw_pattern(el, name)
    if pattern is None:
        raise ActionError(f"{_describe(el)} does not support the {name} pattern")
    interface = getattr(com.uia_module(), f"IUIAutomation{name}Pattern")
    return pattern.QueryInterface(interface)


def has_pattern(el: UIAElement, name: str) -> bool:
    __tracebackhide__ = True
    if name not in PATTERN_IDS:
        raise ValueError(f"unknown UIA pattern {name!r}")
    return _raw_pattern(el, name) is not None


# -- Invoke / Value / Toggle ----------------------------------------------------------------------


def invoke(el: UIAElement) -> None:
    __tracebackhide__ = True
    pattern = _pattern(el, "Invoke")
    with com.wrap_com_errors:
        pattern.Invoke()


def get_value(el: UIAElement) -> str:
    __tracebackhide__ = True
    pattern = _pattern(el, "Value")
    with com.wrap_com_errors:
        return pattern.CurrentValue or ""


def set_value(el: UIAElement, value: str) -> None:
    __tracebackhide__ = True
    pattern = _pattern(el, "Value")
    with com.wrap_com_errors:
        pattern.SetValue(value)


def is_read_only(el: UIAElement) -> bool:
    __tracebackhide__ = True
    pattern = _pattern(el, "Value")
    with com.wrap_com_errors:
        return bool(pattern.CurrentIsReadOnly)


def toggle(el: UIAElement) -> None:
    __tracebackhide__ = True
    pattern = _pattern(el, "Toggle")
    with com.wrap_com_errors:
        pattern.Toggle()


def toggle_state(el: UIAElement) -> ToggleState:
    __tracebackhide__ = True
    pattern = _pattern(el, "Toggle")
    with com.wrap_com_errors:
        return ToggleState(int(pattern.CurrentToggleState))


# -- Selection ------------------------------------------------------------------------------------


def select_item(el: UIAElement) -> None:
    __tracebackhide__ = True
    pattern = _pattern(el, "SelectionItem")
    with com.wrap_com_errors:
        pattern.Select()


def add_to_selection(el: UIAElement) -> None:
    __tracebackhide__ = True
    pattern = _pattern(el, "SelectionItem")
    with com.wrap_com_errors:
        pattern.AddToSelection()


def is_selected(el: UIAElement) -> bool:
    __tracebackhide__ = True
    pattern = _pattern(el, "SelectionItem")
    with com.wrap_com_errors:
        return bool(pattern.CurrentIsSelected)


def selection(el: UIAElement) -> list[UIAElement]:
    __tracebackhide__ = True
    pattern = _pattern(el, "Selection")
    with com.wrap_com_errors:
        return array_to_list(pattern.GetCurrentSelection())


# -- ExpandCollapse -------------------------------------------------------------------------------


def expand(el: UIAElement) -> None:
    __tracebackhide__ = True
    pattern = _pattern(el, "ExpandCollapse")
    with com.wrap_com_errors:
        pattern.Expand()


def collapse(el: UIAElement) -> None:
    __tracebackhide__ = True
    pattern = _pattern(el, "ExpandCollapse")
    with com.wrap_com_errors:
        pattern.Collapse()


def expand_state(el: UIAElement) -> ExpandCollapseState:
    __tracebackhide__ = True
    pattern = _pattern(el, "ExpandCollapse")
    with com.wrap_com_errors:
        return ExpandCollapseState(int(pattern.CurrentExpandCollapseState))


# -- Scrolling and virtualization -----------------------------------------------------------------


def scroll_into_view(el: UIAElement) -> None:
    __tracebackhide__ = True
    pattern = _pattern(el, "ScrollItem")
    with com.wrap_com_errors:
        pattern.ScrollIntoView()


def scroll(el: UIAElement, horizontal: str = "none", vertical: str = "none") -> None:
    """Scroll by ``none|small_inc|small_dec|large_inc|large_dec`` in each direction."""
    __tracebackhide__ = True
    for amount in (horizontal, vertical):
        if amount not in _SCROLL_AMOUNTS:
            raise ValueError(f"unknown scroll amount {amount!r}; use {sorted(_SCROLL_AMOUNTS)}")
    module = com.uia_module()
    pattern = _pattern(el, "Scroll")
    with com.wrap_com_errors:
        pattern.Scroll(
            getattr(module, _SCROLL_AMOUNTS[horizontal]),
            getattr(module, _SCROLL_AMOUNTS[vertical]),
        )


def scroll_percent(el: UIAElement) -> tuple[float, float]:
    """``(horizontal, vertical)`` scroll position in percent; -1 where not scrollable."""
    __tracebackhide__ = True
    pattern = _pattern(el, "Scroll")
    with com.wrap_com_errors:
        return (
            float(pattern.CurrentHorizontalScrollPercent),
            float(pattern.CurrentVerticalScrollPercent),
        )


def set_scroll_percent(el: UIAElement, h: float, v: float) -> None:
    __tracebackhide__ = True
    pattern = _pattern(el, "Scroll")
    with com.wrap_com_errors:
        pattern.SetScrollPercent(h, v)


def realize(el: UIAElement) -> None:
    __tracebackhide__ = True
    pattern = _pattern(el, "VirtualizedItem")
    with com.wrap_com_errors:
        pattern.Realize()


def find_item_by_property(
    container: UIAElement, start: UIAElement | None, prop: str | None, value: Any
) -> UIAElement | None:
    """Ask an ItemContainer for the next item (after ``start``) whose ``prop`` equals ``value``.

    With ``prop=None`` it returns the item following ``start`` (the first one for ``start=None``).
    """
    __tracebackhide__ = True
    pattern = _pattern(container, "ItemContainer")
    property_id = PROPERTY_IDS[prop] if prop is not None else 0
    with com.wrap_com_errors:
        found = pattern.FindItemByProperty(
            start.raw if start is not None else None,
            property_id,
            value if prop is not None else comtypes.automation.VARIANT(),
        )
    return UIAElement(found) if found else None


# -- Grid and Table -------------------------------------------------------------------------------


def grid_size(el: UIAElement) -> tuple[int, int]:
    """``(row count, column count)``."""
    __tracebackhide__ = True
    pattern = _pattern(el, "Grid")
    with com.wrap_com_errors:
        return (int(pattern.CurrentRowCount), int(pattern.CurrentColumnCount))


def grid_item(el: UIAElement, row: int, col: int) -> UIAElement:
    __tracebackhide__ = True
    pattern = _pattern(el, "Grid")
    with com.wrap_com_errors:
        return UIAElement(pattern.GetItem(row, col))


def column_headers(el: UIAElement) -> list[UIAElement]:
    __tracebackhide__ = True
    pattern = _pattern(el, "Table")
    with com.wrap_com_errors:
        return array_to_list(pattern.GetCurrentColumnHeaders())


# -- Text -----------------------------------------------------------------------------------------


def document_text(el: UIAElement) -> str:
    """The full text of an element supporting the Text pattern."""
    __tracebackhide__ = True
    pattern = _pattern(el, "Text")
    with com.wrap_com_errors:
        return pattern.DocumentRange.GetText(-1) or ""


# -- Window and legacy ----------------------------------------------------------------------------


def window_close(el: UIAElement) -> None:
    __tracebackhide__ = True
    pattern = _pattern(el, "Window")
    with com.wrap_com_errors:
        pattern.Close()


def window_set_state(el: UIAElement, state: str) -> None:
    __tracebackhide__ = True
    if state not in _WINDOW_STATES:
        raise ValueError(f"unknown window state {state!r}; use {sorted(_WINDOW_STATES)}")
    pattern = _pattern(el, "Window")
    with com.wrap_com_errors:
        pattern.SetWindowVisualState(getattr(com.uia_module(), _WINDOW_STATES[state]))


def window_is_modal(el: UIAElement) -> bool:
    __tracebackhide__ = True
    pattern = _pattern(el, "Window")
    with com.wrap_com_errors:
        return bool(pattern.CurrentIsModal)


def legacy_default_action(el: UIAElement) -> None:
    __tracebackhide__ = True
    pattern = _pattern(el, "LegacyIAccessible")
    with com.wrap_com_errors:
        pattern.DoDefaultAction()
