"""Window mapping and bounded WPF-tree locator queries."""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from typing import cast

from wintestkit import runtime
from wintestkit.backends.element import WpfElement, uia_of
from wintestkit.engine.locator import Locator, Matcher, match_value
from wintestkit.engine.managed import ManagedCondition, locator_deadline
from wintestkit.engine.properties import Condition, matches, read, resolve_where
from wintestkit.engine.query import root_handle
from wintestkit.engine.wpf_query import UnsupportedQuery, predicate, translate
from wintestkit.errors import (
    InspectorError,
    InspectorLimitError,
    InspectorMappingError,
    NoUiaPeerError,
)
from wintestkit.inspector.paths import PathSegment
from wintestkit.uia.element import UIAElement

log = logging.getLogger(__name__)
_IDENTITY = {"automation_id", "name", "class_name", "control_type"}


class QueryMatches(list[WpfElement]):
    indexed = False
    complete = True
    total_count: int | None = None

    def __len__(self) -> int:
        return self.total_count if self.total_count is not None else super().__len__()


def route(window: UIAElement, *, force: bool = False) -> UIAElement | WpfElement:
    if not force and (runtime.get_config().backend != "auto" or window.framework_id != "WPF"):
        log.debug("Resolution backend: UIA")
        return window
    log.debug("Resolution backend: WPF")
    deadline = locator_deadline()
    try:
        client = runtime.managed_client_for(
            window.process_id, deadline=deadline, target_hwnd=root_handle(window)
        )
        missing = {"query", "geometry", "exactUiaMapping"} - set(client.session.features)
        if missing:
            raise InspectorMappingError(
                f"Inspector missing features: {', '.join(sorted(missing))}", code="unsupported"
            )
        rid, hwnd = runtime.managed_element_identity(window)
        mapping = client.resolve(rid, hwnd, deadline=deadline)
        if mapping.status != "exact" or mapping.object_ref is None:
            raise InspectorMappingError(f"Window mapping is {mapping.status}", code=mapping.status)
        return WpfElement(client, mapping.object_ref, window.process_id)
    except InspectorError as error:
        raise type(error)(
            f"WPF backend unavailable ({error.code}): {error}. "
            "Enable the inspector, attach to the process, or set backend: uia.",
            code=error.code,
        ) from error


def query(root: WpfElement, locator: Locator, *, use_index: bool = False) -> QueryMatches:
    constraints = resolve_where(locator.where, locator.describe_link(), locator.taken())
    pushed: list[Condition | ManagedCondition] = []
    local: list[Condition] = []
    identities: dict[str, Matcher] = {}
    for name in _IDENTITY:
        value = getattr(locator, name)
        if value is not None:
            try:
                predicate((PathSegment("uia", name),), value)
            except UnsupportedQuery:
                identities[name] = value
    for condition in constraints:
        if isinstance(condition, ManagedCondition):
            pushed.append(condition)
        elif condition.spec.condition not in _IDENTITY:
            local.append(condition)
        else:
            try:
                predicate((PathSegment("uia", condition.spec.condition),), condition.value)
            except UnsupportedQuery:
                identities[condition.spec.condition] = cast(Matcher, condition.value)
            else:
                pushed.append(condition)
    stripped = replace(locator, **dict.fromkeys(identities), index=0)
    wire = translate(stripped, tuple(pushed), root.ref)
    deadline = locator_deadline()
    timeout = max(1, min(2000, int((deadline - time.monotonic()) * 1000)))
    result = root.client.query_find_all(wire, timeout_ms=timeout, deadline=deadline)
    if not result.complete and len(result.matches) < wire.limit:
        raise InspectorLimitError("WPF query exhausted its budget", code="limitExceeded")
    elements = [
        WpfElement(root.client, ref, root.process_id) for ref in result.matches if ref != root.ref
    ]

    def accepts(element: WpfElement) -> bool:
        if not all(
            match_value(value, getattr(element, name)) for name, value in identities.items()
        ):
            return False
        try:
            return all(
                matches(condition, read(uia_of(element), condition.spec)) for condition in local
            )
        except NoUiaPeerError:
            return False

    filtered = QueryMatches(element for element in elements if accepts(element))
    filtered.complete = result.complete
    if (
        use_index
        and locator.index is not None
        and locator.index >= len(filtered)
        and not result.complete
    ):
        offset = int(root.ref in result.matches)
        raw_index = len(result.matches) if local or identities else locator.index + offset
        extra_queries = 0
        while raw_index <= 9999:
            if (local or identities) and extra_queries >= 50:
                raise InspectorLimitError(
                    "WPF query exceeded 50 additional indexed searches; narrow the locator",
                    code="limitExceeded",
                )
            if time.monotonic() >= deadline:
                raise InspectorLimitError("WPF query exhausted its budget", code="limitExceeded")
            indexed = replace(wire, index=raw_index)
            timeout = max(1, min(2000, int((deadline - time.monotonic()) * 1000)))
            try:
                extra_queries += 1
                found = root.client.query_find(indexed, timeout_ms=timeout, deadline=deadline)
            except InspectorError as error:
                if error.code == "notFound":
                    if not local and not identities:
                        # findAll has no offset; locate the exact end with logarithmic probes.
                        low, high = len(result.matches), raw_index
                        while low < high:
                            middle = (low + high) // 2
                            timeout = max(1, min(2000, int((deadline - time.monotonic()) * 1000)))
                            if time.monotonic() >= deadline:
                                raise InspectorLimitError(
                                    "WPF query exhausted its budget", code="limitExceeded"
                                ) from None
                            try:
                                probe = root.client.query_find(
                                    replace(wire, index=middle),
                                    timeout_ms=timeout,
                                    deadline=deadline,
                                )
                            except InspectorError as probe_error:
                                if probe_error.code != "notFound":
                                    raise
                                high = middle
                            else:
                                # Release the probe's lease through the normal wrapper lifecycle.
                                WpfElement(root.client, probe.match, root.process_id)
                                low = middle + 1
                        filtered.total_count = low - offset
                    filtered.complete = True
                    return filtered
                raise
            element = WpfElement(root.client, found.match, root.process_id)
            if accepts(element):
                if (not local and not identities) or len(filtered) == locator.index:
                    filtered = QueryMatches([element])
                    filtered.indexed = True
                    break
                filtered.append(element)
            raw_index += 1
        else:
            raise InspectorLimitError("WPF query index limit reached", code="limitExceeded")
    return filtered
