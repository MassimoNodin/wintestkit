"""Locator resolution: turn a ``Locator`` into live UI Automation elements.

Resolution is strict (exactly one match unless ``index`` is given) and never cached: every action
resolves again so elements are never stale.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from typing import Any, cast

from wintestkit import runtime
from wintestkit.app import App
from wintestkit.backends.element import TargetElement, WpfElement, uia_of
from wintestkit.engine.diagnose import (
    Diagnostic,
    diagnose_ambiguous,
    diagnose_index_out_of_range,
    diagnose_no_has_match,
    diagnose_not_found,
    diagnose_window,
    diagnose_within_failed,
    quote,
)
from wintestkit.engine.locator import (
    ItemSelector,
    Locator,
    WindowLocator,
    expand_alternatives,
    match_value,
)
from wintestkit.engine.managed import diagnostic_query_budget, locator_deadline, query_budget
from wintestkit.engine.properties import Condition, read, resolve_where
from wintestkit.engine.properties import matches as matches_property
from wintestkit.engine.query import query_all, reject_managed
from wintestkit.engine.wpf_query import UnsupportedQuery, translate
from wintestkit.engine.wpf_resolve import identity_value, matches_root, route
from wintestkit.engine.wpf_resolve import query as wpf_query
from wintestkit.errors import (
    AmbiguousElementError,
    ElementNotFoundError,
    InspectorDeadlineError,
    InspectorLimitError,
    LocatorError,
    NoUiaPeerError,
    WindowNotFoundError,
    WtkError,
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

    def window_id_matches(window: UIAElement) -> bool:
        __tracebackhide__ = True
        if wl.automation_id is None:
            return True
        identifier = window.automation_id
        if (
            not identifier
            and window.framework_id == "WPF"
            and runtime.get_config().backend == "auto"
        ):
            root = route(window)
            if isinstance(root, WpfElement):
                identifier = identity_value(root, "automation_id")
        return identifier is not None and match_value(wl.automation_id, identifier)

    matches = [
        w
        for w in candidates
        if (wl.title is None or match_value(wl.title, w.name))
        and (wl.class_name is None or match_value(wl.class_name, w.class_name))
        and window_id_matches(w)
        and all(matches_property(c, read(w, c.spec)) for c in uia)
    ]
    managed_types: dict[int, str] = {}
    if managed:
        if runtime.get_config().backend == "uia":
            reject_managed(managed[0], matches[0] if matches else None)
        filtered: list[UIAElement] = []
        for window in matches:
            if window.framework_id == "WPF":
                root = route(window)
                assert isinstance(root, WpfElement)
                managed_types[id(window)] = root.ref.type.full_name
                if matches_root(root, managed):
                    filtered.append(window)
        matches = filtered
    if wl.index is not None:
        if wl.index < len(matches):
            return matches[wl.index]
        raise WindowNotFoundError(diagnose_window(source, wl, [], candidates, managed_types))
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise WindowNotFoundError(diagnose_window(source, wl, [], candidates, managed_types))
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
    if link.has is not None:
        return _match_has(scope, root, link, full, first, use_index=use_index)
    if link.any_of:
        return _match_alternatives(scope, root, link, full, first, use_index=use_index)
    matches: list[TargetElement]
    if isinstance(root, WpfElement):
        matches = cast(list[TargetElement], wpf_query(root, link, use_index=use_index))
    else:
        matches = list(query_all(uia_of(root), link))
    if not matches and first and full.window is None and scope.window is None:
        matches = _popup_matches(scope, root, link, use_index=use_index)
    return matches


#: At most this many candidates of one link are checked against its ``has=`` filter.
MAX_HAS_CANDIDATES = 200


class _HasMatches(list[TargetElement]):
    """Matches that passed a ``has=`` filter; ``prefiltered`` holds the ones before it."""

    prefiltered: list[TargetElement]

    def __init__(self, kept: list[TargetElement], prefiltered: list[TargetElement]) -> None:
        __tracebackhide__ = True
        super().__init__(kept)
        self.prefiltered = prefiltered


class _IndexedMatches(list[TargetElement]):
    """The single element chosen by ``index`` from the union of ``any_of`` alternatives."""

    indexed = True

    def __init__(
        self,
        selected: list[TargetElement],
        merged: list[TargetElement],
        prefiltered: list[TargetElement] | None = None,
    ) -> None:
        __tracebackhide__ = True
        super().__init__(selected)
        self.merged = merged
        #: Candidates before a ``has=`` filter (empty without one).
        self.prefiltered = prefiltered or []


def _contains(candidate: TargetElement, child: Locator) -> bool:
    """True when ``child`` (properties, where, any_of, depth) matches below ``candidate``."""
    __tracebackhide__ = True
    for alternative in expand_alternatives(child):
        if isinstance(candidate, WpfElement):
            if len(wpf_query(candidate, alternative)):
                return True
        elif query_all(uia_of(candidate), alternative):
            return True
    return False


def _match_has(
    scope: Scope,
    root: TargetElement,
    link: Locator,
    full: Locator,
    first: bool,
    *,
    use_index: bool,
) -> list[TargetElement]:
    """Matches of ``link`` that contain its ``has=`` child; ``index`` applies after filtering."""
    __tracebackhide__ = True
    assert link.has is not None
    base = replace(link, has=None, index=None)
    candidates = list(_match_link(scope, root, base, full, first))
    if len(candidates) > MAX_HAS_CANDIDATES:
        raise InspectorLimitError(
            f"has= query exceeded {MAX_HAS_CANDIDATES} candidates for local filtering; "
            "narrow the locator",
            code="limitExceeded",
        )
    kept = [candidate for candidate in candidates if _contains(candidate, link.has)]
    if use_index and link.index is not None:
        chosen = [kept[link.index]] if link.index < len(kept) else []
        return _IndexedMatches(chosen, kept, candidates)
    return _HasMatches(kept, candidates)


def _match_alternatives(
    scope: Scope,
    root: TargetElement,
    link: Locator,
    full: Locator,
    first: bool,
    *,
    use_index: bool,
) -> list[TargetElement]:
    """Union of the matches of every ``any_of`` alternative, deduplicated, in alternative order."""
    __tracebackhide__ = True
    alternatives = expand_alternatives(link)
    merged: list[TargetElement] = []

    def collect(found: list[TargetElement]) -> None:
        __tracebackhide__ = True
        for element in found:
            if not any(cast(Any, element).same_as(known) for known in merged):
                merged.append(element)

    for alternative in alternatives:
        if isinstance(root, WpfElement):
            collect(cast(list[TargetElement], list(wpf_query(root, alternative))))
        else:
            collect(list(query_all(uia_of(root), alternative)))
    if not merged and first and full.window is None and scope.window is None:
        for alternative in alternatives:
            collect(_popup_matches(scope, root, alternative))
    if use_index and link.index is not None:
        chosen = [merged[link.index]] if link.index < len(merged) else []
        return _IndexedMatches(chosen, merged)
    return merged


def _wpf_id_hint(
    scope: Scope, root: WpfElement, window_root: UIAElement, expected: str
) -> str | None:
    __tracebackhide__ = True
    from wintestkit.engine import diagnose, relocate
    from wintestkit.inspector.paths import PathSegment

    if diagnose.diagnostics_are_quiet():
        return None
    deadline = relocate.new_deadline()
    best: tuple[float, str, str, bool] | None = None
    try:
        windows = [
            window_root,
            *(
                window
                for window in scope.app.top_level_windows()[: relocate.MAX_WINDOWS]
                if not window.same_as(window_root)
            ),
        ]
        with diagnostic_query_budget(), query_budget(deadline):
            seen: set[str] = set()
            for window in windows:
                if time.monotonic() >= deadline:
                    break
                try:
                    managed = route(window)
                except WtkError:
                    continue
                if not isinstance(managed, WpfElement):
                    continue
                width = max(2, len(expected) // 3)
                fragments = [
                    expected[start : start + width] for start in range(0, len(expected), width)
                ]
                pattern = re.compile(
                    "|".join(re.escape(fragment) for fragment in fragments if fragment),
                    re.IGNORECASE,
                )
                candidates = wpf_query(managed, Locator(automation_id=pattern))
                candidates.extend(wpf_query(managed, Locator(where=(("clr:Name", pattern),))))
                for element in candidates:
                    if time.monotonic() >= deadline:
                        break
                    values, _ = element.client.read(
                        element.ref.object_id,
                        element.ref.generation,
                        [
                            (PathSegment("uia", "automation_id"),),
                            (PathSegment("property", "Name"),),
                        ],
                        deadline=deadline,
                    )
                    if values[0].value.status not in {"ok", "unavailable"}:
                        continue
                    for position, item in enumerate(values):
                        value = item.value
                        if value.status != "ok" or not isinstance(value.scalar, str):
                            continue
                        candidate = value.scalar
                        if not candidate or candidate in seen:
                            continue
                        seen.add(candidate)
                        score = SequenceMatcher(None, expected.lower(), candidate.lower()).ratio()
                        if score >= 0.6 and (best is None or score > best[0]):
                            best = (
                                score,
                                candidate,
                                window.name,
                                position == 1
                                and values[0].value.status == "ok"
                                and bool(values[0].value.scalar)
                                and values[0].value.scalar != candidate,
                            )
    except WtkError:
        pass
    if best is None:
        return None
    location = f" in window {quote(best[2])}" if best[2] else ""
    key = "clr:Name" if best[3] else "automation_id"
    return f"did you mean {key}={quote(best[1])}{location}?"


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
            if matches:
                return matches[0].as_live()
            # An empty indexed result: the union of any_of alternatives is shorter than the index.
            merged = cast(_IndexedMatches, matches).merged
            prefiltered = cast(_IndexedMatches, matches).prefiltered
            if not merged and prefiltered:
                raise ElementNotFoundError(
                    diagnose_no_has_match(prefiltered, link, searched_in, full)
                )
            raise ElementNotFoundError(diagnose_index_out_of_range(merged, link, searched_in, full))
        if link.index >= len(matches):
            raise ElementNotFoundError(
                diagnose_index_out_of_range(matches, link, searched_in, full)
            )
        return matches[link.index].as_live()
    if len(matches) == 1:
        return matches[0].as_live()
    if not matches and link.has is not None and getattr(matches, "prefiltered", None):
        raise ElementNotFoundError(
            diagnose_no_has_match(cast(_HasMatches, matches).prefiltered, link, searched_in, full)
        )
    if not matches:
        try:
            diagnostic_root = uia_of(root)
        except NoUiaPeerError:
            diagnostic_root = window_root
        diagnostic = diagnose_not_found(diagnostic_root, link, searched_in, full)
        if isinstance(root, WpfElement) and isinstance(link.automation_id, str):
            hint = _wpf_id_hint(scope, root, window_root, link.automation_id)
            if hint:
                diagnostic = replace(diagnostic, hint=hint)
        raise ElementNotFoundError(diagnostic)
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
    if any(candidate.any_of or candidate.has is not None for candidate in links):
        # One wire query cannot express alternatives or has= filters: poll normally.
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
    try:
        result = root.client.wait_until(
            WaitCondition("exists" if state == "attached" else state, wire),
            timeout_ms=max(1, min(chunk_ms, int((remaining - 0.15) * 1000))),
            deadline=deadline,
        )
    except InspectorDeadlineError as error:
        if error.code != "limitExceeded" or error.busy or time.monotonic() >= deadline:
            raise
        return True, resolve(scope, locator)
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
