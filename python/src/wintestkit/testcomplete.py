"""Translate TestComplete property lists into WinTestKit locators.

The search helpers use the same lazy locators as page objects.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import replace
from typing import Any, cast

from wintestkit import model
from wintestkit.engine.locator import Locator
from wintestkit.engine.resolve import Scope, resolve_all
from wintestkit.model import (
    BoundControl,
    BoundElement,
    BoundElements,
    Elements,
    PageObject,
)

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


def _search(parent: BoundControl | PageObject | Scope, locator: Locator) -> BoundElements:
    if isinstance(parent, BoundControl):
        page = parent.page
        root = parent.locator
    elif isinstance(parent, PageObject):
        page = parent
        definition = cast(Any, parent)._effective_root()
        root = (
            cast(Any, model)._element_locator(parent, definition)
            if definition is not None
            else None
        )
    else:
        page = PageObject(parent.app)
        root = None
        locator = replace(locator, window=parent.window)
    if root is not None:
        locator = replace(locator, within=replace(root, window=None), window=root.window)
    definition = Elements(automation_id="__testcomplete_search__")
    return BoundElements(page, definition, locator)


def find_child(
    parent: BoundControl | PageObject | Scope,
    props: str | Sequence[str],
    values: Any,
    depth: int | None = 1,
    *,
    strict: bool = False,
) -> BoundElement:
    """Find a descendant lazily; depth 1 means direct children, None unlimited.

    By default the first match in tree order wins; strict requires one match.
    An explicit WPFControlOrdinalNo takes precedence over the default first match.
    """
    locator = to_locator(props, values, depth=depth)
    result = _search(parent, locator)
    if not strict and locator.index is None:
        locator = locator.with_index(0)
    return BoundElement(
        result.page, result.definition, replace(result.locator, index=locator.index)
    )


def find_all_children(
    parent: BoundControl | PageObject | Scope,
    props: str | Sequence[str],
    values: Any,
    depth: int | None = 1,
) -> list[BoundElement]:
    """Snapshot matching descendants as indexed, re-resolving bound elements.

    Changes in tree order after this call can change what an index identifies.
    """
    result = _search(parent, to_locator(props, values, depth=depth))
    return [result.nth(index) for index in range(len(result.resolve_all()))]


class _FindElement(BoundElement):
    def __init__(self, parent: BoundControl, descendant: BoundElement, locator: Locator) -> None:
        super().__init__(descendant.page, descendant.definition, descendant.locator)
        self.parent = parent
        self.match_locator = locator

    def resolve_once(self) -> Any:
        target = self.parent.resolve_once()
        locator = replace(
            self.match_locator, depth=None, index=None, window=self.parent.locator.window
        )
        candidates = resolve_all(cast(Any, model)._scope(self.parent.page), locator)
        if any(cast(Any, target).same_as(candidate) for candidate in candidates):
            return target
        return super().resolve_once()


def find(
    parent: BoundControl | PageObject | Scope,
    props: str | Sequence[str],
    values: Any,
    depth: int | None = 1,
) -> BoundElement:
    """Find the parent or its descendants, defaulting to TestComplete's depth 1.

    A bound parent is included. A Page or Scope without an element root starts at
    its window; the window itself cannot be included by the descendant resolver.
    """
    child = find_child(parent, props, values, depth)
    if isinstance(parent, PageObject):
        root = cast(Any, parent)._effective_root()
        if root is not None:
            parent = BoundElement(parent, root, cast(Any, model)._element_locator(parent, root))
    if isinstance(parent, BoundControl):
        return _FindElement(parent, child, to_locator(props, values, depth=depth))
    return child
