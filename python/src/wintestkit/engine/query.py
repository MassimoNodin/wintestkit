"""Low-level element queries shared by the resolver and the diagnostics."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wintestkit.engine.managed import ManagedCondition
from typing import Any

from wintestkit.engine.locator import Locator
from wintestkit.engine.properties import Condition, matches, native_value, read, resolve_where
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
    seen: set[str] = set()
    unique: list[UIAElement] = []
    for element in elements:
        runtime_id = element.runtime_id
        if runtime_id and runtime_id in seen:
            continue
        seen.add(runtime_id)
        unique.append(element)
    return unique


def query_all(
    root: UIAElement, locator: Locator, *, deadline: float | None = None
) -> list[UIAElement]:
    """All elements under ``root`` matching the locator's own properties, in document order.

    Ignores ``index``, ``within``, ``window`` and ``item``. Returned elements carry cached
    property values; call ``as_live()`` before handing them to actions.
    """
    __tracebackhide__ = True
    constraints = resolve_where(locator.where, locator.describe_link(), locator.taken())
    uia = [c for c in constraints if isinstance(c, Condition)]
    managed = [c for c in constraints if not isinstance(c, Condition)]
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
    found = _unique(found)
    if not managed or not found:
        return found
    return _filter_managed(found, managed, deadline)


def relaxed_descendants(root: UIAElement, control_type: str | None) -> list[UIAElement]:
    """Descendants for diagnostics: of one control type when given, otherwise everything."""
    __tracebackhide__ = True
    props: dict[str, int] = {"control_type": CONTROL_TYPES[control_type]} if control_type else {}
    found = root.find_all(TreeScope.Descendants, make_condition(**props), cached=True)
    return found[:MAX_RELAXED_CANDIDATES]


def _filter_managed(
    found: list[UIAElement], constraints: list[ManagedCondition], deadline: float | None
) -> list[UIAElement]:
    from wintestkit import runtime
    from wintestkit.engine.managed import matches_value
    from wintestkit.errors import InspectorLimitError, InspectorMappingError, InspectorReadError
    from wintestkit.uia.element import from_handle

    count = len(found)
    if count > 1000:
        raise InspectorLimitError(
            f"{count} UIA candidates exceed the managed limit of 1000; use a tighter UIA scope",
            code="limitExceeded",
        )
    if deadline is None:
        deadline = time.monotonic() + runtime.get_config().timeout
    paths = list({c.key: c.path for c in constraints}.values())
    clients: dict[int, Any] = {}
    matched: list[UIAElement] = []
    elapsed_batch = 0.0
    completed = 0
    for offset in range(0, count, 32):
        group = found[offset : offset + 32]
        # A batch belongs to one process; preserve document order across mixed-process trees.
        for element in group:
            pid = element.process_id
            if pid not in clients:
                clients[pid] = runtime.managed_client_for(
                    pid, deadline=deadline, target_hwnd=root_handle(element)
                )
        by_pid: dict[int, list[UIAElement]] = {}
        for element in group:
            by_pid.setdefault(element.process_id, []).append(element)
        accepted: set[str] = set()
        for pid, elements in by_pid.items():
            requests = []
            for element in elements:
                hwnd = element.native_window_handle
                own = hwnd if hwnd and element.same_as(from_handle(hwnd)) else None
                requests.append((tuple(int(part) for part in element.runtime_id.split(".")), own))
            values_by_id: dict[tuple[int, ...], dict[Any, Any]] = {}
            stale: set[tuple[int, ...]] = set()
            for path_offset in range(0, len(paths), 32):
                remaining_batches = ((count - offset + 31) // 32) * ((len(paths) + 31) // 32)
                if time.monotonic() >= deadline or (completed and elapsed_batch / completed * remaining_batches > deadline - time.monotonic()):
                    raise InspectorLimitError(
                        f"Cannot evaluate {count} UIA candidates within the deadline; use a tighter UIA scope",
                        code="limitExceeded",
                    )
                batch_paths = paths[path_offset : path_offset + 32]
                started = time.monotonic()
                results = clients[pid].read_batch(requests, batch_paths, deadline=deadline)
                elapsed_batch += time.monotonic() - started
                completed += 1
                if len(results) != len(requests):
                    raise InspectorReadError("Incomplete managed candidate results", code="partial")
                for request, result in zip(requests, results, strict=True):
                    rid = request[0]
                    if result.runtime_id != rid:
                        raise InspectorReadError("Mismatched managed candidate results", code="partial")
                    status = result.mapping.status
                    if status in ("stale", "objectStale", "elementStale"):
                        stale.add(rid)
                        continue
                    if status != "exact":
                        raise InspectorMappingError(f"Cannot map UIA candidate: {status}", code=status)
                    returned = {v.path: v.value for v in result.values}
                    if len(returned) != len(batch_paths) or any(p.segments not in returned for p in batch_paths):
                        raise InspectorReadError("Incomplete managed path results", code="partial")
                    values_by_id.setdefault(rid, {}).update(returned)
            for request in requests:
                rid = request[0]
                if rid in stale:
                    continue
                values = values_by_id[rid]
                # Do not short circuit: every value must be usable even after a mismatch.
                outcomes = [matches_value(c, values[c.path.segments]) for c in constraints]
                if all(outcomes):
                    accepted.add(".".join(str(part) for part in rid))
        matched.extend(element for element in group if element.runtime_id in accepted)
    return matched


def root_handle(element: UIAElement) -> int | None:
    """Find an ancestor HWND for attachment without using a title heuristic."""
    node: UIAElement | None = element
    while node is not None:
        if node.native_window_handle:
            return node.native_window_handle
        node = node.parent()
    return None
