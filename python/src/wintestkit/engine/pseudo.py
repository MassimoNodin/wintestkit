"""Properties that are not UIA or managed properties: what a check or a wait can read from an
element besides them (existence, on-screen visibility, text, list items, child count).

``read_any`` is the one reader behind ``expect(...).to_have_property`` and the migration helpers
``finders.check_property`` and ``finders.wait_property``: a pseudo-property name is answered
here, any other name is a UIA property or a managed key (``clr:``, ``wpf:``, ``type:``...).
"""

from __future__ import annotations

from typing import Any

from wintestkit.backends.element import TargetElement
from wintestkit.engine import actions, waits
from wintestkit.engine.property_read import read_property
from wintestkit.errors import ActionError
from wintestkit.uia import patterns
from wintestkit.uia.constants import ToggleState

__all__ = ["ALLOW_MISSING", "ITEM_LIST_SEPARATOR", "PSEUDO", "is_pseudo", "read_any"]

#: The separator ``item_list`` joins the items with, one item per line.
ITEM_LIST_SEPARATOR = "\n"

PSEUDO: dict[str, str] = {
    "exists": "whether the element is found",
    "visible_on_screen": "whether the element is found and on screen",
    "enabled": "the element's enabled state (UIA)",
    "checked": "the toggle state: True, False, or None for indeterminate",
    "text": "the element's text: its value, document text or UIA name",
    "name": "the UIA name (the caption of a window)",
    "value": "the ValuePattern value",
    "items": "the item names of a list, combo box or tab control, as a list",
    "item_list": "the same items joined with one per line",
    "item_count": "how many items the list has",
    "child_count": "how many children the element has in the object tree",
}

#: Pseudo-properties that have an answer when no element is found.
ALLOW_MISSING = frozenset({"exists", "visible_on_screen"})


def is_pseudo(name: str) -> bool:
    return name in PSEUDO


def _items(element: TargetElement) -> list[str]:
    if element.control_type == "ComboBox":
        return actions.combo_item_names(element)
    return actions.listed_item_names(element)


def _checked(element: TargetElement) -> bool | None:
    state = patterns.toggle_state(element)
    if state == ToggleState.On:
        return True
    if state == ToggleState.Off:
        return False
    return None


def read_any(target: Any, element: TargetElement | None, name: str) -> Any:
    """Read ``name`` from ``element`` (``None`` when nothing was found), the bound ``target`` being
    where it was looked up. Pseudo-properties are answered here; anything else is read as a UIA
    property or managed key."""
    __tracebackhide__ = True
    if name == "exists":
        return element is not None
    if name == "visible_on_screen":
        return waits.element_state_ok(element, "visible")
    if element is None:
        raise ActionError(f"{name} cannot be read: no element was found")
    if name == "enabled":
        return element.is_enabled
    if name == "checked":
        return _checked(element)
    if name == "text":
        return actions.get_text(element)
    if name == "name":
        return element.name
    if name == "value":
        return actions.get_value(element)
    if name == "items":
        return _items(element)
    if name == "item_list":
        return ITEM_LIST_SEPARATOR.join(_items(element))
    if name == "item_count":
        return len(_items(element))
    if name == "child_count":
        from wintestkit import finders, model

        if not isinstance(target, model.BoundControl | model.BoundWindow):
            raise ActionError("child_count needs a single element or window")
        return finders.child_count_of(target)  # pyright: ignore[reportArgumentType]
    return read_property(element, name)
