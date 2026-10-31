"""Locator resolution: turn a ``Locator`` into live UI Automation elements.

Resolution is strict (exactly one match unless ``index`` is given) and never cached: every action
resolves again so elements are never stale.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import cast

from wintestkit import runtime
from wintestkit.app import App
from wintestkit.backends.element import TargetElement, WpfElement, uia_of
from wintestkit.engine.diagnose import (
    Diagnostic,
    diagnose_ambiguous,
    diagnose_index_out_of_range,
    diagnose_not_found,
    diagnose_window,
    diagnose_within_failed,
    quote,
)
from wintestkit.engine.locator import ItemSelector, Locator, WindowLocator, match_value
from wintestkit.engine.managed import diagnostic_query_budget, locator_deadline, query_budget
from wintestkit.engine.properties import Condition, read, resolve_where
from wintestkit.engine.properties import matches as matches_property
from wintestkit.engine.query import filter_managed, query_all
from wintestkit.engine.wpf_query import UnsupportedQuery, translate
from wintestkit.engine.wpf_resolve import query as wpf_query
from wintestkit.engine.wpf_resolve import route
from wintestkit.errors import (
    AmbiguousElementError,
    ElementNotFoundError,
    InspectorLimitError,
    LocatorError,
    NoUiaPeerError,
    WindowNotFoundError,
)
from wintestkit.inspector.models import WaitCondition
from wintestkit.uia import patterns
from wintestkit.uia.element import UIAElement

__all__ = ["Scope", "query_all", "resolve", "resolve_all", "resolve_window"]


@dataclass
class Scope:
    """Where a locator is resolved: an application and the window of its screen."""

    app: App
    window: WindowLocator | None = None


@query_budget()
def resolve_window(app: App, wl: WindowLocator | None) -> UIAElement:
    """Find the top-level window described by ``wl`` (``None``/empty → the main window)."""
    __tracebackhide__ = True
    if wl is None or wl.is_empty():
        return app.main_window()
    constraints = resolve_where(wl.where, wl.describe(), wl.taken())
    uia = [c for c in constraints if isinstance(c, Condition)]
    managed = [c for c in constraints if not isinstance(c, Condition)]
    source = app
    if wl.process is not None and wl.process.lower() != app.process_name.lower():
        source = App.attach(process=wl.process)
    only_process = (
        wl.title is None
        and wl.class_name is None
        and wl.automation_id is None
        and wl.index is None
        and not constraints
    )
    if only_process:
        return source.main_window()

    candidates = source.top_level_windows()
    matches = [
        w
        for w in candidates
        if (wl.title is None or match_value(wl.title, w.name))
        and (wl.class_name is None or match_value(wl.class_name, w.class_name))
        and (wl.automation_id is None or match_value(wl.automation_id, w.automation_id))
        and all(matches_property(c, read(w, c.spec)) for c in uia)
    ]
    if managed and matches:
        matches = filter_managed(matches, managed, None)
    if wl.index is not None:
        if wl.index < len(matches):
            return matches[wl.index]
        raise WindowNotFoundError(diagnose_window(source, wl, [], candidates))
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise WindowNotFoundError(diagnose_window(source, wl, [], candidates))
    raise AmbiguousElementError(diagnose_window(source, wl, matches, candidates))


def _popup_matches(
    scope: Scope, window_root: TargetElement, link: Locator, *, use_index: bool = False
) -> list[TargetElement]:
    """Matches inside the app's popup windows (WPF context menus, drop-downs, tool tips)."""
    __tracebackhide__ = True
    found: list[TargetElement] = []
    total_count = 0
    for window in scope.app.top_level_windows():
        if window_root.same_as(window):
            continue
        if window.class_name == "Popup" or window.control_type == "Menu":
            if isinstance(window_root, WpfElement):
                popup = route(window, force=True)
                assert isinstance(popup, WpfElement)
                local_index = (
                    link.index - total_count if use_index and link.index is not None else None
                )
                popup_link = replace(link, index=local_index) if local_index is not None else link
                results = wpf_query(popup, popup_link, use_index=use_index)
                if results.indexed:
                    return cast(list[TargetElement], results)
                if local_index is not None and local_index < len(results):
                    from wintestkit.engine.wpf_resolve import QueryMatches

                    selected = QueryMatches([results[local_index]])
                    selected.indexed = True
                    return cast(list[TargetElement], selected)
                found.extend(results)
                total_count += len(results)
                if use_index and not results.complete:
                    raise InspectorLimitError(
                        "Cannot determine the full popup match count within the query limit",
                        code="limitExceeded",
                    )
            else:
                found.extend(query_all(window, link))
    if use_index and isinstance(window_root, WpfElement) and total_count != len(found):
        from wintestkit.engine.wpf_resolve import QueryMatches

        counted = QueryMatches(cast(list[WpfElement], found))
        counted.total_count = total_count
        return cast(list[TargetElement], counted)
    return found


def _match_link(
    scope: Scope,
    root: TargetElement,
    link: Locator,
    full: Locator,
    first: bool,
    *,
    use_index: bool = False,
) -> list[TargetElement]:
    __tracebackhide__ = True
    matches: list[TargetElement]
    if isinstance(root, WpfElement):
        matches = cast(list[TargetElement], wpf_query(root, link, use_index=use_index))
    else:
        matches = list(query_all(uia_of(root), link))
    if not matches and first and full.window is None and scope.window is None:
        matches = _popup_matches(scope, root, link, use_index=use_index)
    return matches


def _resolve_link(
    scope: Scope,
    root: TargetElement,
    link: Locator,
    searched_in: str,
    full: Locator,
    first: bool,
    window_root: UIAElement,
) -> TargetElement:
    __tracebackhide__ = True
    matches = _match_link(scope, root, link, full, first, use_index=True)
    if link.index is not None:
        if getattr(matches, "indexed", False):
            return matches[0].as_live()
        if link.index >= len(matches):
            raise ElementNotFoundError(
                diagnose_index_out_of_range(matches, link, searched_in, full)
            )
        return matches[link.index].as_live()
    if len(matches) == 1:
        return matches[0].as_live()
    if not matches:
        try:
            diagnostic_root = uia_of(root)
        except NoUiaPeerError:
            diagnostic_root = window_root
        raise ElementNotFoundError(diagnose_not_found(diagnostic_root, link, searched_in, full))
    raise AmbiguousElementError(diagnose_ambiguous(matches, link, searched_in, full))


def _walk(scope: Scope, locator: Locator, final_all: bool) -> list[TargetElement]:
    __tracebackhide__ = True
    window_root = resolve_window(scope.app, locator.window or scope.window)
    links = locator.chain()
    root: TargetElement = route(window_root)
    searched_in = window_root.info().short()
    for position, link in enumerate(links):
        last = position == len(links) - 1
        first = position == 0
        if last and final_all:
            return [m.as_live() for m in _match_link(scope, root, link, locator, first)]
        try:
            element = _resolve_link(scope, root, link, searched_in, locator, first, window_root)
        except LocatorError as exc:
            if last:
                raise
            raise type(exc)(diagnose_within_failed(link, exc.diagnostic, locator)) from None
        if last:
            return [_apply_item(element, link, searched_in, locator)]
        searched_in = f"{element.info().short()} in {searched_in}"
        root = element
    raise AssertionError("a locator chain always has at least one link")  # pragma: no cover


def wait_link(scope: Scope, locator: Locator, state: str) -> tuple[bool, TargetElement | None]:
    """Try an agent wait for one bounded chunk; return (eligible, element)."""
    __tracebackhide__ = True
    links = locator.chain()
    link = links[-1]
    if state not in ("attached", "visible", "enabled") or link.item is not None:
        return False, None
    try:
        constraints = resolve_where(link.where, link.describe_link(), link.taken())
        # Probe translation before resolving the window; unsupported filters keep polling.
        translate(link, tuple(constraints), None)
    except UnsupportedQuery:
        return False, None
    if runtime.get_config().backend == "auto" and locator_deadline() - time.monotonic() <= 0.2:
        with diagnostic_query_budget():
            return True, resolve(scope, locator)
    window = resolve_window(scope.app, locator.window or scope.window)
    root = route(window)
    if not isinstance(root, WpfElement) or "waits" not in root.client.session.features:
        return False, None
    searched_in = window.info().short()
    for position, outer in enumerate(links[:-1]):
        try:
            root = _resolve_link(scope, root, outer, searched_in, locator, position == 0, window)
        except LocatorError as exc:
            raise type(exc)(diagnose_within_failed(outer, exc.diagnostic, locator)) from None
        searched_in = f"{root.info().short()} in {searched_in}"
    if not isinstance(root, WpfElement):
        return False, None
    deadline = locator_deadline()
    remaining = deadline - time.monotonic()
    if remaining <= 0.2:
        with diagnostic_query_budget():
            return True, resolve(scope, locator)
    wire = replace(translate(link, tuple(constraints), root.ref), index=link.index)
    # Outer links and implicit popup search must be revisited at the polling cadence.
    chunk_ms = 100 if len(links) > 1 or (locator.window is None and scope.window is None) else 2000
    result = root.client.wait_until(
        WaitCondition("exists" if state == "attached" else state, wire),
        timeout_ms=max(1, min(chunk_ms, int((remaining - 0.15) * 1000))),
        deadline=deadline,
    )
    if result.satisfied and result.handle is not None:
        # Normal resolution enforces ambiguity, popup and index semantics.
        resolved = _resolve_link(scope, root, link, searched_in, locator, len(links) == 1, window)
        if isinstance(resolved, WpfElement) and resolved.ref == result.handle:
            return True, WpfElement(root.client, result.handle, root.process_id)
        return True, resolved
    # Resolve normally to preserve last-error diagnostics and popup fallback.
    element = _resolve_link(scope, root, link, searched_in, locator, len(links) == 1, window)
    return True, element


@query_budget()
def resolve(scope: Scope, locator: Locator) -> TargetElement:
    """Resolve ``locator`` to exactly one live element, or raise a ``LocatorError``."""
    __tracebackhide__ = True
    return _walk(scope, locator, final_all=False)[0]


@query_budget()
def resolve_all(scope: Scope, locator: Locator) -> list[TargetElement]:
    """All matches of the locator's final link (``index`` and ``item`` ignored); may be empty."""
    __tracebackhide__ = True
    return _walk(scope, locator, final_all=True)


# -- grid rows and cells --------------------------------------------------------------------------


def _item_error(message: str, searched_in: str, full: Locator, count: int) -> ElementNotFoundError:
    __tracebackhide__ = True
    return ElementNotFoundError(
        Diagnostic(
            kind="index_out_of_range",
            message=message,
            locator=full.describe(),
            searched_in=searched_in,
            match_count=count,
        )
    )


def _apply_item(
    element: TargetElement, link: Locator, searched_in: str, full: Locator
) -> TargetElement:
    __tracebackhide__ = True
    item: ItemSelector | None = link.item
    if item is None:
        return element
    element = uia_of(element)
    rows, columns = patterns.grid_size(element)
    short = element.info().short()
    if item.row >= rows:
        raise _item_error(
            f"row={item.row} is out of range: {short} has {rows} rows", searched_in, full, rows
        )
    if item.kind == "row":
        row = patterns.grid_item(element, item.row, 0).parent()
        if row is None:
            raise _item_error(
                f"row={item.row} of {short} has no row element", searched_in, full, rows
            )
        return row.as_live()

    column = item.column
    if isinstance(column, str):
        names = [header.name for header in patterns.column_headers(element)]
        if column not in names:
            listed = ", ".join(names) or "none"
            raise ElementNotFoundError(
                Diagnostic(
                    kind="not_found",
                    message=f"No column {quote(column)} in {short} (columns: {listed})",
                    locator=full.describe(),
                    searched_in=searched_in,
                    match_count=0,
                )
            )
        column = names.index(column)
    assert column is not None
    if column >= columns:
        raise _item_error(
            f"column={column} is out of range: {short} has {columns} columns",
            searched_in,
            full,
            columns,
        )
    return patterns.grid_item(element, item.row, column).as_live()
