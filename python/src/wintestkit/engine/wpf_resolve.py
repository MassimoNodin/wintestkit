"""Window mapping and bounded WPF-tree locator queries."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from dataclasses import replace
from typing import cast

from wintestkit import runtime
from wintestkit.backends.element import WpfElement, uia_of
from wintestkit.engine.diagnose import Diagnostic
from wintestkit.engine.locator import Locator, Matcher, match_value
from wintestkit.engine.managed import ManagedCondition, locator_deadline
from wintestkit.engine.properties import Condition, matches, read, resolve_where
from wintestkit.engine.query import root_handle
from wintestkit.engine.wpf_query import UnsupportedQuery, predicate, translate
from wintestkit.errors import (
    InspectorDeadlineError,
    InspectorError,
    InspectorLimitError,
    InspectorMappingError,
    InspectorReadError,
    NoUiaPeerError,
)
from wintestkit.inspector.models import QueryUnreadable
from wintestkit.inspector.paths import PathSegment
from wintestkit.uia.element import UIAElement

log = logging.getLogger(__name__)
_IDENTITY = {"automation_id", "name", "class_name", "control_type"}


class QueryMatches(list[WpfElement]):
    indexed = False
    complete = True
    total_count: int | None = None
    #: Candidates the agent could not read: they were non-matches, not failures of the search.
    unreadable: QueryUnreadable | None = None

    def __len__(self) -> int:
        return self.total_count if self.total_count is not None else super().__len__()


def to_managed(element: UIAElement) -> WpfElement:
    """The WPF object behind a UI Automation element, for the elements UIA hands out itself.

    Rows, cells and the other helpers of a grid come from UI Automation; this maps one of them
    to the agent's object so managed keys can be read and matched on it like on any element found
    in the object tree.
    """
    __tracebackhide__ = True
    deadline = locator_deadline()
    try:
        client = runtime.managed_client_for(
            element.process_id, deadline=deadline, target_hwnd=root_handle(element)
        )
        rid, hwnd = runtime.managed_element_identity(element)
        mapping = client.resolve(rid, hwnd, deadline=deadline)
        if mapping.status != "exact" or mapping.object_ref is None:
            raise InspectorMappingError(f"Element mapping is {mapping.status}", code=mapping.status)
    except InspectorError as error:
        kind = "WinForms" if is_winforms_element(element) else "WPF"
        raise error.copy_with_message(
            f"{element.info().short()} cannot be read through the {kind} inspector "
            f"({error.code}): {str(error).rstrip('.')}."
        ) from error
    return WpfElement(client, mapping.object_ref, element.process_id)


#: UI Automation's FrameworkId of a WinForms window or control.
WINFORMS_FRAMEWORKS = frozenset({"WinForm", "WinForms"})


def is_winforms_element(element: object) -> bool:
    """Whether a UI Automation element is a WinForms window or control.

    A control hosted in a WPF ``WindowsFormsHost`` counts: it is a WinForms control whatever
    window holds it. UI Automation names the framework ``WinForm``; a control whose provider
    reports a plain window (``Win32``) is told by its ``WindowsForms10`` class name.
    """
    if isinstance(element, WpfElement):
        return element.ref.is_winforms
    framework = getattr(element, "framework_id", None)
    if framework in WINFORMS_FRAMEWORKS:
        return True
    class_name = getattr(element, "class_name", "") if framework == "Win32" else ""
    return isinstance(class_name, str) and class_name.startswith("WindowsForms")


def wpf_capable(element: object) -> bool:
    """Whether an element is a UI Automation element of a WPF window the inspector can map."""
    return (
        not isinstance(element, WpfElement)
        and runtime.get_config().backend == "auto"
        and getattr(element, "framework_id", None) == "WPF"
    )


def managed_capable(element: object) -> bool:
    """Whether the inspector can map a UI Automation element to its managed object.

    That is an element of a WPF window or a WinForms window or control (also one hosted in WPF):
    the agent maps it by its UI Automation runtime ID or window handle and reads its native
    members on the thread that owns it.
    """
    return wpf_capable(element) or (
        not isinstance(element, WpfElement)
        and runtime.get_config().backend == "auto"
        and is_winforms_element(element)
    )


def merge_unreadable(parts: Iterable[QueryUnreadable | None]) -> QueryUnreadable | None:
    """The unreadable candidates of several searches as one count by reason."""
    totals: dict[str, int] = {}
    for part in parts:
        if part is not None:
            for reason, number in part.reasons:
                totals[reason] = totals.get(reason, 0) + number
    if not totals:
        return None
    return QueryUnreadable(sum(totals.values()), tuple(sorted(totals.items())))


def with_unreadable(diagnostic: Diagnostic, unreadable: QueryUnreadable | None) -> Diagnostic:
    """A not-found diagnostic that also says how many candidates could not be read."""
    if unreadable is None:
        return diagnostic
    return replace(diagnostic, message=f"{diagnostic.message}; {unreadable.describe()}")


def winforms_form(link: Locator) -> Locator:
    """The link as it is searched below a WinForms control.

    The migration object tree is WPF's. Below a WinForms control a migrated link is searched as UI
    Automation counts it (``Control.Controls`` levels, name and zero-based index): its UIA form.
    A link without one (a declared locator that asks for ``tree="objects"``) keeps its keys and
    drops the tree, which the agent walks by ``Control.Controls`` whatever the kind.
    """
    if link.tree is None:
        return link
    return link.for_uia() if link.uia_form is not None else replace(link, tree=None)


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
        from wintestkit.engine.waits import set_waker, wants_waker

        waiter = (
            runtime.inspector_sessions().event_waiter(client)
            if wants_waker() and "events" in client.session.features
            else None
        )
        if waiter is not None:
            window_ref = mapping.object_ref
            set_waker(
                lambda remaining: waiter.wait(
                    remaining,
                    fallback=0.5,
                    matches=lambda event: (
                        event.kind in {"windowOpened", "windowClosed"}
                        or (event.kind == "treeChanged" and event.handle == window_ref)
                    ),
                )
            )
        return WpfElement(client, mapping.object_ref, window.process_id)
    except InspectorError as error:
        from wintestkit.inspector.hints import inspector_error_hint

        hint = (
            inspector_error_hint(error.code, error.details, error.method)
            if error.code in {"timeout", "dispatcherUnavailable", "busy"}
            else "Enable the inspector, attach to the process, or set backend: uia."
        )
        message = f"WPF backend unavailable ({error.code}): {str(error).rstrip('.')}. {hint}"
        raise error.copy_with_message(message) from error


def _query_budget_exhausted() -> InspectorDeadlineError:
    error = InspectorDeadlineError("WPF query exhausted its budget", code="limitExceeded")
    error.details = {"reason": "queryBudget"}
    return error


def matches_root(root: WpfElement, conditions: list[ManagedCondition]) -> bool:
    """Evaluate the same agent predicates as element locators, on the window itself."""
    wire = replace(translate(Locator(index=0), tuple(conditions), root.ref), depth=0)
    deadline = locator_deadline()
    timeout = max(1, min(2000, int((deadline - time.monotonic()) * 1000)))
    result = root.client.query_find_all(wire, timeout_ms=timeout, deadline=deadline)
    if not result.complete:
        raise _query_budget_exhausted()
    return root.ref in result.matches


def x_name(element: WpfElement) -> str:
    """The element's x:Name; empty when it has none or it cannot be read."""
    values, _ = element.client.read(
        element.ref.object_id,
        element.ref.generation,
        [(PathSegment("property", "Name"),)],
        deadline=locator_deadline(),
    )
    value = values[0].value
    return value.scalar if value.status == "ok" and isinstance(value.scalar, str) else ""


def identity_value(element: WpfElement, name: str) -> str | None:
    value = getattr(element, name)
    if name != "automation_id" or value:
        return value
    values, _ = element.client.read(
        element.ref.object_id,
        element.ref.generation,
        [(PathSegment("uia", "automation_id"),), (PathSegment("property", "Name"),)],
        deadline=locator_deadline(),
    )
    identity = values[0].value
    if identity.status == "ok" and isinstance(identity.scalar, str) and identity.scalar:
        return identity.scalar
    if identity.status not in {"ok", "unavailable"}:
        raise InspectorReadError(
            f"Cannot read WPF AutomationId: {identity.status}", code="readFailed"
        )
    result = values[1].value
    framework_types = {"System.Windows.FrameworkElement", "System.Windows.FrameworkContentElement"}
    if (
        identity.status == "unavailable"
        and result.status == "redacted"
        and not framework_types.intersection(
            (element.ref.type.full_name, *element.ref.type.base_types)
        )
    ):
        return None
    if result.status == "ok" and isinstance(result.scalar, str):
        return result.scalar
    if result.status in {"unavailable", "nullIntermediate"}:
        return ""
    raise InspectorReadError(f"Cannot read WPF Name: {result.status}", code="readFailed")


def query(
    root: WpfElement, locator: Locator, *, use_index: bool = False, root_level: bool = False
) -> QueryMatches:
    """Matches of ``locator`` below ``root`` (``root`` itself is never a match, except see below).

    ``root_level`` is for an object-tree search from a window: the root visual is the window
    node's child, so it counts as depth 1 and may match; it is ignored for the UIA-like trees.
    """
    if root.ref.is_winforms:
        locator = winforms_form(locator)
    root_level = root_level and locator.tree == "objects"
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
    wire = translate(stripped, tuple(pushed), root.ref, root_level=root_level)
    deadline = locator_deadline()
    timeout = max(1, min(2000, int((deadline - time.monotonic()) * 1000)))
    result = root.client.query_find_all(wire, timeout_ms=timeout, deadline=deadline)
    if not result.complete and len(result.matches) < wire.limit:
        raise _query_budget_exhausted()
    if (local or identities) and not result.complete and (not use_index or locator.index is None):
        raise InspectorLimitError(
            "WPF query exceeded 200 candidates for local filtering; narrow the locator",
            code="limitExceeded",
        )
    elements = [
        WpfElement(root.client, ref, root.process_id)
        for ref in result.matches
        if root_level or ref != root.ref
    ]

    def accepts(element: WpfElement) -> bool:
        if not all(
            (actual := identity_value(element, name)) is not None and match_value(value, actual)
            for name, value in identities.items()
        ):
            return False
        try:
            return all(
                matches(
                    condition,
                    read(
                        element if condition.spec.name == "VisibleOnScreen" else uia_of(element),
                        condition.spec,
                    ),
                )
                for condition in local
            )
        except NoUiaPeerError:
            return False

    filtered = QueryMatches(element for element in elements if accepts(element))
    filtered.complete = result.complete
    filtered.unreadable = result.unreadable
    if (
        use_index
        and locator.index is not None
        and locator.index >= len(filtered)
        and not result.complete
    ):
        offset = int(root.ref in result.matches and not root_level)
        raw_index = len(result.matches) if local or identities else locator.index + offset
        extra_queries = 0
        while raw_index <= 9999:
            if (local or identities) and extra_queries >= 50:
                raise InspectorLimitError(
                    "WPF query exceeded 50 additional indexed searches; narrow the locator",
                    code="limitExceeded",
                )
            if time.monotonic() >= deadline:
                raise _query_budget_exhausted()
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
                                raise _query_budget_exhausted() from None
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
                                # The probe's handle is released when `probe` is collected.
                                del probe
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
