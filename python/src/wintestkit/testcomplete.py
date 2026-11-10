"""Translate TestComplete property lists into WinTestKit locators.

This module provides property conversion only; it does not perform a search.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, cast

from wintestkit.engine.locator import Locator

# TestComplete property (lowercase) -> locator field or qualified where key.
PROPERTY_MAP = {
    "wpfcontrolname": "automation_id",
    "clrfullclassname": "type:FullName",
    "clrclassname": "class_name",
    "wpfcontroltext": "name",
    "wpfcontrolordinalno": "index",
    "visible": "clr:IsVisible",
    "enabled": "clr:IsEnabled",
}


def _matcher(value: Any) -> Any:
    if not isinstance(value, str) or not any(c in value for c in "*?"):
        return value
    # Only escape regex metacharacters: re.escape also escapes characters outside
    # the agent's shared regex grammar, such as spaces and #.
    special = r"\.^$|+()[]{}"
    pattern = "".join(
        ".*" if c == "*" else "." if c == "?" else "\\" + c if c in special else c for c in value
    )
    return re.compile(rf"^{pattern}\Z", re.DOTALL)


def to_locator(props: str | Sequence[str], values: Any, *, depth: int | None = None) -> Locator:
    """Convert a name/value pair or parallel sequences to a locator.

    Property names are case-insensitive; values are case-sensitive. Wildcards
    ``*`` and ``?`` match any run and one character, respectively. A plain
    string remains exact. WPFControlName uses AutomationId, whose WPF peer
    normally falls back to x:Name; an explicitly assigned AutomationId can
    differ. WPFControlText uses the peer/UIA Name, which may differ from the
    control's actual text. ClassName is the peer's short class name, which a
    custom peer can override. Visible and Enabled read managed WPF properties.

    Ordinals become zero-based indexes into all results of the locator in tree
    order, not indexes among siblings of the same type. Depth 1 means direct
    children; on WPF it counts automation-peer levels, not TestComplete's
    visual-tree levels. None leaves the library default in place.

    Wildcard regexes use strict whole-value matching, including for Unicode text.
    """
    if isinstance(props, str):
        names = [props]
        items = [values]
    else:
        names: list[Any] = list(props)
        if isinstance(values, str | bytes) or not isinstance(values, Sequence):
            raise ValueError("property names and values must be parallel sequences")
        items = list(cast("Sequence[Any]", values))
        if len(names) != len(items):
            raise ValueError("property names and values must have equal length")

    fields: dict[str, Any] = {"depth": depth}
    where: dict[str, Any] = {}
    seen: set[str] = set()
    for prop, value in zip(names, items, strict=True):
        if not isinstance(prop, str) or not all(part.isidentifier() for part in prop.split(".")):
            raise ValueError(f"invalid TestComplete property name: {prop!r}")
        key = prop.casefold()
        if key == "name":
            raise ValueError("TestComplete Name is an object name; use mapped properties instead")
        if key in seen:
            raise ValueError(f"duplicate TestComplete property: {prop!r}")
        seen.add(key)
        target = PROPERTY_MAP.get(key, f"clr:{prop}")
        if key in {"visible", "enabled"}:
            if isinstance(value, str) and value.casefold() in {"true", "false"}:
                value = value.casefold() == "true"
            if not isinstance(value, bool):
                raise ValueError(f"{prop} must be True or False")
        elif key == "wpfcontrolordinalno":
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{prop} must be a positive integer")
            value -= 1
        else:
            value = _matcher(value)
        if ":" in target:
            where[target] = value
        else:
            fields[target] = value
    return Locator(**fields, where=tuple(where.items()))
