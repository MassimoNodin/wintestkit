"""Paths through hierarchies: tree items ("Root|Child A|Leaf 1") and menus ("File|Recent|Report").

Both walk one level at a time. A level is searched until the segment appears (items of an expanded
node are generated asynchronously, and a submenu lives in a popup window of the application), then
the node is expanded and the next level is searched.
"""

# Popup discovery reuses the private helper that the combo box dropdown handling uses.
# pyright: reportPrivateUsage=false

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Sequence

from wintestkit.backends.element import TargetElement, WpfElement, uia_of
from wintestkit.engine import actions, waits
from wintestkit.engine.diagnose import Diagnostic, quote
from wintestkit.engine.locator import Locator
from wintestkit.engine.query import query_all
from wintestkit.errors import ActionError, ElementNotFoundError, UIAError
from wintestkit.uia import input

log = logging.getLogger("wintestkit.navigate")

Segment = str | re.Pattern[str]
PathSpec = str | Sequence[Segment]

MAX_LISTED = 20
DEFAULT_SEPARATOR = "|"

_TREE_ITEMS = Locator(control_type="TreeItem", depth=1)
_MENU_ITEMS = Locator(control_type="MenuItem", depth=1)
_POPUP_MENU_ITEMS = Locator(control_type="MenuItem")


# -- paths ----------------------------------------------------------------------------------------


def is_path(item: object, separator: str = DEFAULT_SEPARATOR) -> bool:
    """Whether ``item`` is a path: a list of segments, or a string containing the separator."""
    __tracebackhide__ = True
    if isinstance(item, list | tuple):
        return True
    return isinstance(item, str) and bool(separator) and separator in item


def split_path(path: PathSpec, separator: str = DEFAULT_SEPARATOR) -> list[Segment]:
    """The segments of a path; each is an exact name, or a compiled regex (lists only)."""
    __tracebackhide__ = True
    if isinstance(path, str):
        if not separator:
            raise ActionError("The path separator must not be empty")
        segments: list[Segment] = [*path.split(separator)]
    else:
        segments = list(path)
    if not segments:
        raise ActionError("The path is empty")
    for segment in list[object](segments):
        if isinstance(segment, str):
            if not segment:
                raise ActionError(f"The path {path!r} has an empty segment")
        elif not isinstance(segment, re.Pattern):
            raise ActionError(f"A path segment must be a string or a compiled regex: {segment!r}")
    return segments


def describe_segment(segment: Segment) -> str:
    __tracebackhide__ = True
    return quote(segment) if isinstance(segment, str) else f"/{segment.pattern}/"


def path_text(path: PathSpec, separator: str = DEFAULT_SEPARATOR) -> str:
    """The path as one string, for step arguments and messages."""
    __tracebackhide__ = True
    if isinstance(path, str):
        return path
    return separator.join(s if isinstance(s, str) else f"/{s.pattern}/" for s in path)


def _matches(segment: Segment, name: str) -> bool:
    __tracebackhide__ = True
    return segment == name if isinstance(segment, str) else segment.search(name) is not None


# -- finding one level ----------------------------------------------------------------------------


def _query(root: TargetElement, locator: Locator) -> list[TargetElement]:
    __tracebackhide__ = True
    if isinstance(root, WpfElement):
        from wintestkit.engine.wpf_resolve import query

        return list(query(root, locator))
    return list(query_all(uia_of(root), locator))


def _await_segment(
    fetch: Callable[[], list[TargetElement]], segment: Segment, timeout: float, what: str
) -> tuple[TargetElement | None, list[str]]:
    """Poll one level until an item matches ``segment``; also return the names last seen."""
    __tracebackhide__ = True
    names: list[str] = []

    def poll() -> TargetElement | None:
        __tracebackhide__ = True
        items = fetch()
        names[:] = [item.name for item in items]
        return next((item for item in items if _matches(segment, item.name)), None)

    try:
        return waits.wait_until(poll, timeout, description=what), names
    except waits.WaitTimeoutError:
        return None, names


def _not_found(
    kind: str,
    root: TargetElement,
    segment: Segment,
    trail: Sequence[Segment],
    available: list[str],
) -> ElementNotFoundError:
    __tracebackhide__ = True
    names = ", ".join(quote(n) for n in available[:MAX_LISTED]) or "none"
    where = (
        f"under {' > '.join(describe_segment(s) for s in trail)}"
        if trail
        else f"in {actions._short(root)}"
    )
    return ElementNotFoundError(
        Diagnostic(
            kind="not_found",
            message=f"No {kind} {describe_segment(segment)} {where} (available: {names})",
            locator=f"path({describe_segment(segment)})",
            searched_in=actions._short(root),
            match_count=0,
        )
    )


# -- trees ----------------------------------------------------------------------------------------


def _tree_children(node: TargetElement) -> list[TargetElement]:
    __tracebackhide__ = True
    return _query(node, _TREE_ITEMS)


def _walk_tree(
    tree: TargetElement, segments: list[Segment], *, timeout: float, expand_last: bool
) -> TargetElement:
    """Find the node at ``segments``, expanding every ancestor (and the node if asked)."""
    __tracebackhide__ = True
    node = tree
    for index, segment in enumerate(segments):
        found, names = _await_segment(
            lambda parent=node: _tree_children(parent),
            segment,
            timeout,
            f"tree item {describe_segment(segment)}",
        )
        if found is None:
            raise _not_found("tree item", tree, segment, segments[:index], names)
        if index < len(segments) - 1 or expand_last:
            actions.expand(found, mode="pattern")
        node = found
    return node


def tree_item_names(
    tree: TargetElement, segments: list[Segment] | None = None, *, timeout: float = 1.0
) -> list[str]:
    """Names of the children of a node (the top level without ``segments``)."""
    __tracebackhide__ = True
    parent = _walk_tree(tree, segments, timeout=timeout, expand_last=False) if segments else tree
    return [child.name for child in _tree_children(parent)]


def _await_on_screen(node: TargetElement, timeout: float) -> TargetElement:
    """Scroll a just-expanded node into view and wait until it has an on-screen rectangle."""
    __tracebackhide__ = True

    def ready() -> TargetElement | None:
        __tracebackhide__ = True
        try:
            actions.ensure_visible(node)
            live = node.as_live()
            if live.rect is None or live.is_offscreen:
                return None
            return live
        except (ActionError, UIAError):
            return None

    try:
        return waits.wait_until(
            ready, timeout, description=f"{actions._short(node)} to be laid out"
        )
    except waits.WaitTimeoutError as error:
        raise ActionError(f"{actions._short(node)} has no on-screen rectangle to click") from error


def _header_height(node: TargetElement) -> float | None:
    """The height of a node's own row: its rectangle also covers its children when expanded."""
    __tracebackhide__ = True
    live = node.as_live()
    rect = live.rect
    if rect is None or not actions.is_expanded(live):
        return None
    for child in _tree_children(live):
        child_rect = child.rect
        if child_rect is not None:
            return child_rect.top - rect.top
    return None


def _confirm_selected(tree: TargetElement, node: TargetElement, timeout: float) -> None:
    """Wait until the clicked node is selected; otherwise the click landed on another item."""
    __tracebackhide__ = True
    try:
        waits.wait_until(
            lambda: actions.is_selected(node),
            timeout,
            description="the clicked item to be selected",
        )
    except waits.WaitTimeoutError as error:
        try:
            chosen = ", ".join(quote(name) for name in actions.selected_items(tree))
        except (ActionError, UIAError):
            chosen = ""
        where = f"; {chosen} is selected" if chosen else ""
        raise ActionError(f"The click on {actions._short(node)} landed elsewhere{where}") from error


def select_tree_path(
    tree: TargetElement,
    segments: list[Segment],
    *,
    mode: actions.InputMode,
    timeout: float = 1.0,
) -> None:
    """Expand the ancestors and select the node at ``segments``."""
    __tracebackhide__ = True
    node = _walk_tree(tree, segments, timeout=timeout, expand_last=False)
    if mode == "mouse":
        target = _await_on_screen(node, timeout)
        actions.click_header(target, _header_height(target))
        _confirm_selected(tree, target, timeout)
    else:
        actions.select_self(node)


def expand_tree_path(tree: TargetElement, segments: list[Segment], *, timeout: float = 1.0) -> None:
    """Expand the whole chain, the node at ``segments`` included."""
    __tracebackhide__ = True
    _walk_tree(tree, segments, timeout=timeout, expand_last=True)


def collapse_tree_path(
    tree: TargetElement, segments: list[Segment], *, timeout: float = 1.0
) -> None:
    """Expand the ancestors of the node at ``segments`` and collapse the node itself."""
    __tracebackhide__ = True
    node = _walk_tree(tree, segments, timeout=timeout, expand_last=False)
    actions.collapse(node, mode="pattern")


# -- menus ----------------------------------------------------------------------------------------


def _popup_items(anchor: TargetElement) -> list[TargetElement]:
    """Menu items inside the application's popup windows (submenus and context menus)."""
    __tracebackhide__ = True
    found: list[TargetElement] = []
    for window in actions._popup_roots(anchor):  # type: ignore[arg-type]
        if isinstance(anchor, WpfElement):
            from wintestkit.engine.wpf_resolve import query, route

            root = route(window, force=True)
            if isinstance(root, WpfElement):
                found.extend(query(root, _POPUP_MENU_ITEMS))
                continue
        found.extend(query_all(window, _POPUP_MENU_ITEMS))
    return found


def _menu_items(parent: TargetElement) -> list[TargetElement]:
    """The items of a menu level: children of ``parent``, else those of the popup windows."""
    __tracebackhide__ = True
    return _query(parent, _MENU_ITEMS) or _popup_items(parent)


def _open_submenu(item: TargetElement, mode: actions.InputMode) -> None:
    __tracebackhide__ = True
    if mode == "mouse":
        actions.click(item, mode="mouse")
    else:
        actions.expand(item, mode="pattern")


def close_menus(levels: int) -> None:
    """Press Escape once per open menu level so that later steps are not blocked."""
    __tracebackhide__ = True
    for _ in range(levels):
        try:
            input.press("Escape")
        except Exception:
            log.debug("could not close an open menu", exc_info=True)
            return
        waits._sleep(waits.STABLE_INTERVAL)


def click_menu_path(
    anchor: TargetElement,
    segments: list[Segment],
    *,
    mode: actions.InputMode,
    timeout: float = 1.0,
    base_open: int = 0,
) -> None:
    """Open each menu level in turn and click the last item.

    ``anchor`` holds the first level as children (a menu bar), or else the popup windows do (a
    context menu). ``base_open`` counts the menus already open before the first segment, so that
    a failure presses Escape for them too.
    """
    __tracebackhide__ = True
    opened = base_open
    parent = anchor
    try:
        for index, segment in enumerate(segments):
            found, names = _await_segment(
                lambda level=parent: _menu_items(level),
                segment,
                timeout,
                f"menu item {describe_segment(segment)}",
            )
            if found is None:
                raise _not_found("menu item", anchor, segment, segments[:index], names)
            if index == len(segments) - 1:
                actions.click(found, mode=mode)
                return
            opened += 1
            if not actions.is_expanded(found):
                _open_submenu(found, mode)
            parent = found
    except Exception:
        close_menus(opened)
        raise


def open_context_menu(el: TargetElement, *, mode: actions.InputMode) -> None:
    """Open the element's context menu: right-click, or Shift+F10 in pattern mode."""
    __tracebackhide__ = True
    if mode == "mouse":
        actions.right_click(el)
    else:
        actions.press(el, "Shift+F10")
