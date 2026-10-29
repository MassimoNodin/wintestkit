"""Managed locator conditions and scalar matching."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from wintestkit.errors import InspectorReadError

if TYPE_CHECKING:
    from wintestkit.engine.properties import WhereValue
    from wintestkit.inspector.paths import ManagedPath


@dataclass(frozen=True, slots=True)
class ManagedCondition:
    key: str
    path: ManagedPath
    value: WhereValue
    alias: str | None = None


def matches_value(condition: ManagedCondition, value: Any) -> bool:
    """Compare a usable wire scalar without Python's bool/integer coercion."""
    if value.status in ("null", "nullIntermediate"):
        return False
    if value.status != "ok":
        raise InspectorReadError(f"Cannot read {condition.key}: {value.status}", code=value.status)
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
