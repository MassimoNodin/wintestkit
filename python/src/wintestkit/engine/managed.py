"""Managed locator conditions and scalar matching."""

from __future__ import annotations

import re
import time
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from wintestkit.errors import InspectorReadError

if TYPE_CHECKING:
    from wintestkit.engine.properties import WhereValue
    from wintestkit.inspector.models import Value
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


@dataclass(frozen=True, slots=True)
class ManagedCondition:
    key: str
    path: ManagedPath
    value: WhereValue
    alias: str | None = None


def matches_value(condition: ManagedCondition, value: Value) -> bool:
    """Compare a usable wire scalar without Python's bool/integer coercion."""
    __tracebackhide__ = True
    if value.status == "nullIntermediate" or (value.status == "ok" and value.kind == "null"):
        return False
    if value.status != "ok":
        raise InspectorReadError(f"Cannot read {condition.key}: {value.status}", code=value.status)
    if value.kind not in {"string", "boolean", "integer", "number", "enum"}:
        raise InspectorReadError(f"Unsupported value for {condition.key}", code="unsupported")
    actual = value.as_python()
    expected = condition.value
    if value.kind == "enum":
        if isinstance(expected, int) and not isinstance(expected, bool):
            return value.numeric_value is not None and int(value.numeric_value) == expected
        if not isinstance(expected, str | re.Pattern):
            return False
    if actual is None:
        return False
    if not isinstance(actual, str | bool | int | float | Decimal):
        raise InspectorReadError(f"Unsupported value for {condition.key}", code="unsupported")
    if isinstance(expected, re.Pattern):
        return isinstance(actual, str) and expected.search(actual) is not None
    if isinstance(expected, bool) or isinstance(actual, bool):
        return isinstance(expected, bool) and isinstance(actual, bool) and expected == actual
    if isinstance(expected, str) or isinstance(actual, str):
        return isinstance(expected, str) and isinstance(actual, str) and expected == actual
    return actual == expected
