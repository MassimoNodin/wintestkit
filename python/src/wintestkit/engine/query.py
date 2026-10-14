"""Low-level element queries shared by the resolver and the diagnostics."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from wintestkit.engine.locator import Locator
from wintestkit.uia import com
from wintestkit.uia.constants import CONTROL_TYPES, TreeScope
from wintestkit.uia.element import UIAElement

MAX_RELAXED_CANDIDATES = 1000

# Builds a UIA condition from exact properties. Unit tests replace this with a factory that
# returns plain dicts so the resolver can run against an in-memory tree.
make_condition: Callable[..., Any] = com.create_condition


def _within_depth(element: UIAElement, root: UIAElement, limit: int) -> bool:
    """True if ``element`` is at most ``limit`` levels below ``root`` (children are depth 1)."""
    node = element
    for _ in range(limit):
        parent = node.parent()
        if parent is None:
            return False
        if parent.same_as(root):
            return True
        node = parent
    return False


def _unique(elements: list[UIAElement]) -> list[UIAElement]:
    """Drop elements reached twice by the search (same runtime id), keeping document order.

    WPF menus and drop-downs live in ``Popup`` windows that UI Automation attaches to the tree in
    more than one place, so a plain ``FindAll`` can return the very same element twice.
    """
    if len(elements) < 2:
        return elements
    seen: set[str] = set()
    unique: list[UIAElement] = []
    for element in elements:
        runtime_id = element.runtime_id
        if runtime_id and runtime_id in seen:
            continue
        seen.add(runtime_id)
        unique.append(element)
    return unique


def query_all(root: UIAElement, locator: Locator) -> list[UIAElement]:
    """All elements under ``root`` matching the locator's own properties, in document order.

    Ignores ``index``, ``within``, ``window`` and ``item``. Returned elements carry cached
    property values; call ``as_live()`` before handing them to actions.
    """
    condition = make_condition(**locator.exact_props())
    depth = locator.depth
    scope = TreeScope.Children if depth == 1 else TreeScope.Descendants
    found = root.find_all(scope, condition, cached=True)
    if depth is not None and depth > 1:
        found = [e for e in found if _within_depth(e, root, depth)]
    regexes = locator.regex_props()
    if regexes:
        found = [e for e in found if all(r.search(getattr(e, attr)) for attr, r in regexes.items())]
    return _unique(found)


def relaxed_descendants(root: UIAElement, control_type: str | None) -> list[UIAElement]:
    """Descendants for diagnostics: of one control type when given, otherwise everything."""
    props: dict[str, int] = {"control_type": CONTROL_TYPES[control_type]} if control_type else {}
    found = root.find_all(TreeScope.Descendants, make_condition(**props), cached=True)
    return found[:MAX_RELAXED_CANDIDATES]
