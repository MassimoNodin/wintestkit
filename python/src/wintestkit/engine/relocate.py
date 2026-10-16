"""Relocation search: where did an element that no longer resolves go?

A box, dialog or input that moves to a different window of the application keeps its own
properties (class name, control name), only its container changes. After a not-found failure this
module looks for the element's *own* locator in every top-level window of the application and
reports what it finds. It only diagnoses: the found elements are never used for an action.
"""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING

from wintestkit.engine.locator import Locator
from wintestkit.engine.query import query_all
from wintestkit.errors import WtkError
from wintestkit.uia.element import UIAElement

if TYPE_CHECKING:
    from wintestkit.app import App

RELOCATE_BUDGET = 2.0
CHECK_BUDGET = 10.0
MAX_MATCHES = 5
MAX_WINDOWS = 20
MAX_ANCESTORS = 3
_ANCESTOR_STEPS = 12
_SEPARATOR = " \u203a "

# Injectable for unit tests.
_clock: Callable[[], float] = time.monotonic


@dataclass(frozen=True)
class Hit:
    """An exact match of the searched locator in some window."""

    window: str
    path: str
    window_element: UIAElement
    same_window: bool = False


def leaf_only(locator: Locator) -> Locator:
    """The locator's own properties: no ``within`` chain, window, index, depth or item."""
    __tracebackhide__ = True
    return dataclasses.replace(locator, within=None, window=None, index=None, depth=None, item=None)


_shared_deadline: ContextVar[float | None] = ContextVar("wtk_relocate_deadline", default=None)


@contextmanager
def shared_budget(budget: float = CHECK_BUDGET) -> Generator[None]:
    """Make every search inside the block stop at one common deadline.

    A page check with a missing window or component root would otherwise let each member burn a
    full ``RELOCATE_BUDGET`` on its own search.
    """
    __tracebackhide__ = True
    token = _shared_deadline.set(_clock() + budget)
    try:
        yield
    finally:
        _shared_deadline.reset(token)


def new_deadline(budget: float = RELOCATE_BUDGET) -> float:
    """The clock reading at which a search that starts now must stop."""
    __tracebackhide__ = True
    own = _clock() + budget
    shared = _shared_deadline.get()
    return own if shared is None else min(own, shared)


def _ancestor_labels(
    element: UIAElement, window: UIAElement, deadline: float, window_label: str
) -> list[str]:
    """Short labels of the named ancestors between ``window`` and ``element`` (nearest last).

    Ancestors that look like the window itself (apps often nest a second ``Window`` with the same
    title inside the frame) are skipped so the window is never shown twice.
    """
    __tracebackhide__ = True
    labels: list[str] = []
    node = element.parent()
    for _ in range(_ANCESTOR_STEPS):
        if node is None or node.same_as(window) or _clock() >= deadline:
            break
        if node.name or node.automation_id:
            label = node.info().short()
            if label != window_label:
                labels.append(label)
        node = node.parent()
    return list(reversed(labels[:MAX_ANCESTORS]))


def find_elsewhere(
    app: App,
    locator: Locator,
    *,
    exclude: UIAElement | None = None,
    declared: UIAElement | None = None,
    deadline: float | None = None,
    limit: int = MAX_MATCHES,
) -> list[Hit]:
    """Exact matches of ``locator``'s own properties in the application's top-level windows.

    The search is bounded: at most ``limit`` matches, ``MAX_WINDOWS`` windows and until
    ``deadline`` (default: ``RELOCATE_BUDGET`` seconds from now). The deadline is checked between
    windows and while building paths; a single UI Automation query is not interruptible.
    ``exclude`` skips one window, e.g. the one that was already searched. Matches in ``declared``
    (the window the locator is declared for, compared by runtime id) are flagged ``same_window``
    and their path omits the window.
    """
    __tracebackhide__ = True
    if deadline is None:
        deadline = new_deadline()
    own = leaf_only(locator)
    hits: list[Hit] = []
    try:
        windows = app.top_level_windows()
    except WtkError:
        return hits
    for window in windows[:MAX_WINDOWS]:
        if len(hits) >= limit or _clock() >= deadline:
            break
        if exclude is not None and window.same_as(exclude):
            continue
        try:
            found = query_all(window, own)
            label = window.info().short()
            for element in found[: limit - len(hits)]:
                if _clock() >= deadline:
                    break
                same = declared is not None and window.same_as(declared)
                parts = [
                    *_ancestor_labels(element, window, deadline, label),
                    element.info().short(),
                ]
                path = _SEPARATOR.join(parts if same else [label, *parts])
                hits.append(Hit(label, path, window, same))
        except WtkError:
            continue  # the window or element closed while searching
    return hits
