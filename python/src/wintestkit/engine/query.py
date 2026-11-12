"""Low-level element queries shared by the resolver and the diagnostics."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from wintestkit import runtime
from wintestkit.engine.locator import Locator
from wintestkit.engine.managed import ManagedCondition
from wintestkit.engine.properties import Condition, matches, native_value, read, resolve_where
from wintestkit.errors import InvalidLocatorError
from wintestkit.uia import com
from wintestkit.uia.constants import CONTROL_TYPES, TreeScope
from wintestkit.uia.element import UIAElement

MAX_RELAXED_CANDIDATES = 1000

# Builds a UIA condition from exact properties. Unit tests replace this with a factory that
# returns plain dicts so the resolver can run against an in-memory tree.
make_condition: Callable[..., Any] = com.create_condition


def _within_depth(element: UIAElement, root: UIAElement, limit: int) -> bool:
    """True if ``element`` is at most ``limit`` levels below ``root`` (children are depth 1)."""
    __tracebackhide__ = True
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
    __tracebackhide__ = True
    if len(elements) < 2:
        return elements
    seen: set[tuple[int, str]] = set()
    unique: list[UIAElement] = []
    for element in elements:
        runtime_id = element.runtime_id
        identity = (element.process_id, runtime_id)
        if runtime_id and identity in seen:
            continue
        seen.add(identity)
        unique.append(element)
    return unique


def query_all(root: UIAElement, locator: Locator) -> list[UIAElement]:
    """All elements under ``root`` matching the locator's own properties, in document order.

    Ignores ``index``, ``within``, ``window`` and ``item``. Returned elements carry cached
    property values; call ``as_live()`` before handing them to actions.
    """
    __tracebackhide__ = True
    constraints = resolve_where(locator.where, locator.describe_link(), locator.taken())
    uia = [c for c in constraints if isinstance(c, Condition)]
    managed = [c for c in constraints if not isinstance(c, Condition)]
    if managed:
        reject_managed(managed[0], root)
    props: dict[str, Any] = dict(locator.exact_props())
    for constraint in uia:
        if not constraint.is_regex:
            props[constraint.spec.condition] = native_value(constraint)
    condition = make_condition(**props)
    depth = locator.depth
    scope = TreeScope.Children if depth == 1 else TreeScope.Descendants
    found = root.find_all(scope, condition, cached=True)
    if depth is not None and depth > 1:
        found = [e for e in found if _within_depth(e, root, depth)]
    regexes = locator.regex_props()
    if regexes:
        found = [e for e in found if all(r.search(getattr(e, attr)) for attr, r in regexes.items())]
    for constraint in uia:
        if constraint.is_regex:
            found = [e for e in found if matches(constraint, read(e, constraint.spec))]
    return _unique(found)


def reject_managed(condition: ManagedCondition, root: UIAElement | None = None) -> None:
    __tracebackhide__ = True
    backend = runtime.get_config().backend
    framework = getattr(root, "framework_id", "unknown") if root is not None else "unknown"
    raise InvalidLocatorError(
        f"Managed key {condition.key!r} requires the WPF backend; "
        f"backend: {backend}, window framework: {framework}. "
        "Use backend: auto with a WPF window."
    )


def relaxed_descendants(root: UIAElement, control_type: str | None) -> list[UIAElement]:
    """Descendants for diagnostics: of one control type when given, otherwise everything."""
    __tracebackhide__ = True
    props: dict[str, int] = {"control_type": CONTROL_TYPES[control_type]} if control_type else {}
    found = root.find_all(TreeScope.Descendants, make_condition(**props), cached=True)
    return found[:MAX_RELAXED_CANDIDATES]


def root_handle(element: UIAElement) -> int | None:
    """Find an ancestor HWND for attachment without using a title heuristic."""
    __tracebackhide__ = True
    node: UIAElement | None = element
    while node is not None:
        if node.native_window_handle:
            return node.native_window_handle
        node = node.parent()
    return None
