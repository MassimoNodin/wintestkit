"""Low-level element queries shared by the resolver and the diagnostics."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from contextlib import suppress
from typing import Any

from wintestkit import runtime
from wintestkit.engine.locator import Locator
from wintestkit.engine.managed import ManagedCondition, locator_deadline, matches_value
from wintestkit.engine.properties import Condition, matches, native_value, read, resolve_where
from wintestkit.errors import (
    InspectorError,
    InspectorLimitError,
    InspectorMappingError,
    InspectorReadError,
    InvalidLocatorError,
)
from wintestkit.inspector.client import InspectorClient
from wintestkit.inspector.models import Value
from wintestkit.inspector.paths import PathSegment
from wintestkit.uia import com
from wintestkit.uia.constants import CONTROL_TYPES, TreeScope
from wintestkit.uia.element import UIAElement

log = logging.getLogger(__name__)

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
    if managed and deadline is None:
        deadline = locator_deadline()
    if managed:
        assert deadline is not None
        reason = "inspector.query is postfilter"
        if runtime.get_config().inspector.query == "agent":
            result, reason = _agent_query(root, locator, constraints, deadline)
            if result is not None:
                return result
        log.debug("WPF query fallback: %s", reason)
        if any(c.key == "type:Is" for c in managed):
            raise InvalidLocatorError(f"type:Is requires an agent query; {reason}")
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
    return filter_managed(found, managed, deadline)


def _agent_query(
    root: UIAElement,
    locator: Locator,
    constraints: tuple[Condition | ManagedCondition, ...],
    deadline: float,
) -> tuple[list[UIAElement] | None, str]:
    __tracebackhide__ = True
    from dataclasses import replace

    from wintestkit.backends.mapping import map_runtime_ids
    from wintestkit.engine.wpf_query import UnsupportedQuery, translate
    from wintestkit.inspector.models import Scope

    try:
        wire = translate(locator, constraints, None)
    except UnsupportedQuery as error:
        return None, str(error)
    if time.monotonic() >= deadline:
        raise InspectorLimitError("Managed query deadline expired", code="limitExceeded")
    client = runtime.managed_client_for(
        root.process_id, deadline=deadline, target_hwnd=root_handle(root)
    )
    if not {"query", "geometry", "exactUiaMapping"} <= set(client.session.features):
        return None, "agent lacks query, geometry or exact mapping"
    try:
        rid, hwnd = runtime.managed_element_identity(root)
    except InspectorMappingError:
        return None, "root has no usable UIA identity"
    mapping = client.resolve(rid, hwnd, deadline=deadline)
    if mapping.status != "exact" or mapping.object_ref is None:
        return None, f"root mapping is {mapping.status}"
    refs = [mapping.object_ref]
    try:
        wire = replace(wire, scope=Scope("object", mapping.object_ref))
        timeout = max(1, min(2000, int((deadline - time.monotonic()) * 1000)))
        result = client.query_find_all(wire, timeout_ms=timeout, deadline=deadline)
        refs.extend(result.matches)
        if not result.complete and len(result.matches) < wire.limit:
            raise InspectorLimitError(
                "WPF query exhausted its budget before traversal completed", code="limitExceeded"
            )
        groups: dict[int, list[tuple[int, ...]]] = {}
        ordered: list[tuple[int, tuple[int, ...]]] = []
        for ref in result.matches:
            timeout = max(1, min(2000, int((deadline - time.monotonic()) * 1000)))
            state = client.state_get(ref, timeout_ms=timeout, deadline=deadline)
            if (
                state.handle == mapping.object_ref
                or not state.window_handle
                or not state.uia_runtime_id
            ):
                continue
            key = (state.window_handle, state.uia_runtime_id)
            ordered.append(key)
            groups.setdefault(key[0], []).append(key[1])
        mapped = map_runtime_ids(groups)
        missing = len(result.matches) - sum(key in mapped for key in ordered)
        if missing:
            log.debug("Skipped %d WPF matches without a mapped UIA element", missing)
        return _unique([mapped[key] for key in ordered if key in mapped]), ""
    finally:
        with suppress(InspectorError):
            client.release(
                list(dict.fromkeys(ref.object_id for ref in refs)),
                deadline=min(deadline, time.monotonic() + 0.25),
            )


def relaxed_descendants(root: UIAElement, control_type: str | None) -> list[UIAElement]:
    """Descendants for diagnostics: of one control type when given, otherwise everything."""
    __tracebackhide__ = True
    props: dict[str, int] = {"control_type": CONTROL_TYPES[control_type]} if control_type else {}
    found = root.find_all(TreeScope.Descendants, make_condition(**props), cached=True)
    return found[:MAX_RELAXED_CANDIDATES]


def filter_managed(
    found: list[UIAElement], constraints: list[ManagedCondition], deadline: float | None
) -> list[UIAElement]:
    __tracebackhide__ = True
    from wintestkit.uia.element import from_handle

    if any(c.key == "type:Is" for c in constraints):
        raise InvalidLocatorError("type:Is requires an agent query; postfilter is required here")
    count = len(found)
    if count > 1000:
        raise InspectorLimitError(
            f"{count} UIA candidates exceed the managed limit of 1000; use a tighter UIA scope",
            code="limitExceeded",
        )
    if deadline is None:
        deadline = locator_deadline()
    paths = list({c.path.segments: c.path for c in constraints}.values())
    by_pid: dict[int, list[UIAElement]] = {}
    for element in found:
        by_pid.setdefault(element.process_id, []).append(element)
    batches = [
        (pid, elements[offset : offset + 32])
        for pid, elements in by_pid.items()
        for offset in range(0, len(elements), 32)
    ]
    remaining_batches = len(batches) * ((len(paths) + 31) // 32)
    clients: dict[int, InspectorClient] = {}
    accepted: set[tuple[int, str]] = set()
    elapsed_batch = 0.0
    completed = 0
    for pid, elements in batches:
        _check_budget(count, deadline, remaining_batches, elapsed_batch, completed)
        if pid not in clients:
            clients[pid] = runtime.managed_client_for(
                pid, deadline=deadline, target_hwnd=root_handle(elements[0])
            )
        requests: list[tuple[tuple[int, ...], int | None]] = []
        for element in elements:
            hwnd = element.native_window_handle
            own = hwnd if hwnd and element.same_as(from_handle(hwnd)) else None
            requests.append((tuple(int(part) for part in element.runtime_id.split(".")), own))
        values_by_id: dict[tuple[int, ...], dict[tuple[PathSegment, ...], Value]] = {}
        stale: set[tuple[int, ...]] = set()
        for path_offset in range(0, len(paths), 32):
            _check_budget(count, deadline, remaining_batches, elapsed_batch, completed)
            batch_paths = paths[path_offset : path_offset + 32]
            started = time.monotonic()
            results = clients[pid].read_batch(requests, batch_paths, deadline=deadline)
            elapsed_batch += time.monotonic() - started
            completed += 1
            remaining_batches -= 1
            if len(results) != len(requests):
                raise InspectorReadError("Incomplete managed candidate results", code="partial")
            for request, result in zip(requests, results, strict=True):
                rid = request[0]
                if result.runtime_id != rid or result.mapping.runtime_id != rid:
                    raise InspectorReadError("Mismatched managed candidate results", code="partial")
                status = result.mapping.status
                if status == "stale":
                    stale.add(rid)
                    continue
                if status == "limitExceeded":
                    raise InspectorLimitError("Managed mapping scan limit reached", code=status)
                if status != "exact":
                    raise InspectorMappingError(f"Cannot map UIA candidate: {status}", code=status)
                if tuple(v.path for v in result.values) != tuple(p.segments for p in batch_paths):
                    raise InspectorReadError("Incomplete managed path results", code="partial")
                if any(v.value.status == "stale" for v in result.values):
                    stale.add(rid)
                values_by_id.setdefault(rid, {}).update((v.path, v.value) for v in result.values)
        for element, (rid, _) in zip(elements, requests, strict=True):
            if rid in stale:
                continue
            values = values_by_id[rid]
            # Do not short circuit: a mismatch must not hide a failed or redacted read.
            outcomes = [matches_value(c, values[c.path.segments]) for c in constraints]
            if all(outcomes):
                accepted.add((pid, element.runtime_id))
    return [element for element in found if (element.process_id, element.runtime_id) in accepted]


def _check_budget(
    count: int, deadline: float, remaining: int, elapsed: float, completed: int
) -> None:
    __tracebackhide__ = True
    available = deadline - time.monotonic()
    if available <= 0 or (completed and elapsed / completed * remaining > available):
        raise InspectorLimitError(
            f"Cannot evaluate {count} UIA candidates within the deadline; use a tighter UIA scope",
            code="limitExceeded",
        )


def root_handle(element: UIAElement) -> int | None:
    """Find an ancestor HWND for attachment without using a title heuristic."""
    __tracebackhide__ = True
    node: UIAElement | None = element
    while node is not None:
        if node.native_window_handle:
            return node.native_window_handle
        node = node.parent()
    return None
