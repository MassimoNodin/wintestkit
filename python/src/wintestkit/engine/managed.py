"""Managed locator conditions and query budgets."""

from __future__ import annotations

import time
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wintestkit.engine.properties import WhereValue
    from wintestkit.inspector.paths import ManagedPath


_budget: ContextVar[tuple[float, float | None] | None] = ContextVar(
    "wintestkit_managed_query_budget", default=None
)


@contextmanager
def query_budget(deadline: float | None = None) -> Generator[None]:
    """Share the outer deadline across retries, window filters, and within links."""
    __tracebackhide__ = True
    previous = _budget.get()
    start = time.monotonic() if previous is None else previous[0]
    if previous is not None and previous[1] is not None:
        deadline = previous[1] if deadline is None else min(deadline, previous[1])
    token = _budget.set((start, deadline))
    try:
        yield
    finally:
        _budget.reset(token)


@contextmanager
def diagnostic_query_budget() -> Generator[None]:
    """Allow one final resolution to construct a diagnostic after the wait deadline."""
    __tracebackhide__ = True
    token = _budget.set(None)
    try:
        with query_budget():
            yield
    finally:
        _budget.reset(token)


def locator_deadline() -> float:
    """Compute a default only when a query actually needs managed inspection."""
    __tracebackhide__ = True
    from wintestkit import runtime

    budget = _budget.get()
    if budget is not None and budget[1] is not None:
        return budget[1]
    start = time.monotonic() if budget is None else budget[0]
    return start + runtime.get_config().timeout


def in_query_budget() -> bool:
    return _budget.get() is not None


def operation_deadline(timeout: float) -> float:
    deadline = time.monotonic() + timeout
    budget = _budget.get()
    if budget is not None and budget[1] is not None:
        deadline = min(deadline, budget[1])
    return deadline


@dataclass(frozen=True, slots=True)
class ManagedCondition:
    key: str
    path: ManagedPath
    value: WhereValue
    alias: str | None = None
