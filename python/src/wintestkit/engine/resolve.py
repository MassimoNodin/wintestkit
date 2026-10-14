"""Locator resolution: turn a ``Locator`` into live UI Automation elements.

Resolution is strict (exactly one match unless ``index`` is given) and never cached: every action
resolves again so elements are never stale.
"""

from __future__ import annotations

from dataclasses import dataclass

from wintestkit.app import App
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
from wintestkit.engine.query import query_all
from wintestkit.errors import (
    AmbiguousElementError,
    ElementNotFoundError,
    LocatorError,
    WindowNotFoundError,
)
from wintestkit.uia import patterns
from wintestkit.uia.element import UIAElement

__all__ = ["Scope", "query_all", "resolve", "resolve_all", "resolve_window"]


@dataclass
class Scope:
    """Where a locator is resolved: an application and the window of its screen."""

    app: App
    window: WindowLocator | None = None


def resolve_window(app: App, wl: WindowLocator | None) -> UIAElement:
    """Find the top-level window described by ``wl`` (``None``/empty → the main window)."""
    if wl is None or wl.is_empty():
        return app.main_window()
    source = app
    if wl.process is not None and wl.process.lower() != app.process_name.lower():
        source = App.attach(process=wl.process)
    only_process = (
        wl.title is None and wl.class_name is None and wl.automation_id is None and wl.index is None
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
    ]
    if wl.index is not None:
        if wl.index < len(matches):
            return matches[wl.index]
        raise WindowNotFoundError(diagnose_window(source, wl, [], candidates))
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise WindowNotFoundError(diagnose_window(source, wl, [], candidates))
    raise AmbiguousElementError(diagnose_window(source, wl, matches, candidates))


def _popup_matches(scope: Scope, window_root: UIAElement, link: Locator) -> list[UIAElement]:
    """Matches inside the app's popup windows (WPF context menus, drop-downs, tool tips)."""
    found: list[UIAElement] = []
    for window in scope.app.top_level_windows():
        if window.same_as(window_root):
            continue
        if window.class_name == "Popup" or window.control_type == "Menu":
            found.extend(query_all(window, link))
    return found


def _match_link(
    scope: Scope, root: UIAElement, link: Locator, full: Locator, first: bool
) -> list[UIAElement]:
    matches = query_all(root, link)
    if not matches and first and full.window is None:
        matches = _popup_matches(scope, root, link)
    return matches


def _resolve_link(
    scope: Scope, root: UIAElement, link: Locator, searched_in: str, full: Locator, first: bool
) -> UIAElement:
    matches = _match_link(scope, root, link, full, first)
    if link.index is not None:
        if link.index >= len(matches):
            raise ElementNotFoundError(
                diagnose_index_out_of_range(matches, link, searched_in, full)
            )
        return matches[link.index].as_live()
    if len(matches) == 1:
        return matches[0].as_live()
    if not matches:
        raise ElementNotFoundError(diagnose_not_found(root, link, searched_in, full))
    raise AmbiguousElementError(diagnose_ambiguous(matches, link, searched_in, full))


def _walk(scope: Scope, locator: Locator, final_all: bool) -> list[UIAElement]:
    window_root = resolve_window(scope.app, locator.window or scope.window)
    links = locator.chain()
    root = window_root
    searched_in = window_root.info().short()
    for position, link in enumerate(links):
        last = position == len(links) - 1
        first = position == 0
        if last and final_all:
            return [m.as_live() for m in _match_link(scope, root, link, locator, first)]
        try:
            element = _resolve_link(scope, root, link, searched_in, locator, first)
        except LocatorError as exc:
            if last:
                raise
            raise type(exc)(diagnose_within_failed(link, exc.diagnostic, locator)) from None
        if last:
            return [_apply_item(element, link, searched_in, locator)]
        searched_in = f"{element.info().short()} in {searched_in}"
        root = element
    raise AssertionError("a locator chain always has at least one link")  # pragma: no cover


def resolve(scope: Scope, locator: Locator) -> UIAElement:
    """Resolve ``locator`` to exactly one live element, or raise a ``LocatorError``."""
    return _walk(scope, locator, final_all=False)[0]


def resolve_all(scope: Scope, locator: Locator) -> list[UIAElement]:
    """All matches of the locator's final link (``index`` and ``item`` ignored); may be empty."""
    return _walk(scope, locator, final_all=True)


# -- grid rows and cells --------------------------------------------------------------------------


def _item_error(message: str, searched_in: str, full: Locator, count: int) -> ElementNotFoundError:
    return ElementNotFoundError(
        Diagnostic(
            kind="index_out_of_range",
            message=message,
            locator=full.describe(),
            searched_in=searched_in,
            match_count=count,
        )
    )


def _apply_item(element: UIAElement, link: Locator, searched_in: str, full: Locator) -> UIAElement:
    item: ItemSelector | None = link.item
    if item is None:
        return element
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
