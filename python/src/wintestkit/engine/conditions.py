"""Comparison conditions of property checks: ``==``, ``!=``, ``<``, ``<=``, ``>``, ``>=``,
``contains`` and ``not contains``, and the spoken names migrated suites use for them."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any, Literal, cast

from wintestkit.engine.properties import AsText, as_text
from wintestkit.engine.property_read import property_matches

__all__ = ["CONDITIONS", "ComparisonError", "Condition", "compare", "parse_condition", "symbol"]

Condition = Literal["==", "!=", "<", "<=", ">", ">=", "contains", "not contains"]

CONDITIONS: tuple[Condition, ...] = ("==", "!=", "<", "<=", ">", ">=", "contains", "not contains")

_NAMES: dict[str, Condition] = {
    "==": "==",
    "=": "==",
    "equal": "==",
    "equals": "==",
    "!=": "!=",
    "<>": "!=",
    "notequal": "!=",
    "<": "<",
    "less": "<",
    "lessthan": "<",
    "<=": "<=",
    "lessorequal": "<=",
    ">": ">",
    "greater": ">",
    "greaterthan": ">",
    ">=": ">=",
    "greaterorequal": ">=",
    "contains": "contains",
    "notcontains": "not contains",
}


class ComparisonError(ValueError):
    """The two values cannot be put in the order the condition asks for."""


def parse_condition(condition: str) -> Condition:
    """The canonical condition for a symbol or a name such as ``"lessOrEqual"`` (any case)."""
    if not isinstance(condition, str):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise ValueError(f"condition must be a string, not {condition!r}")
    key = re.sub(r"[\s_-]+", "", condition).casefold()
    found = _NAMES.get(key)
    if found is None:
        raise ValueError(
            f"unknown condition {condition!r}; use one of {', '.join(CONDITIONS)} or "
            "equal, notEqual, less, lessOrEqual, greater, greaterOrEqual, contains, notContains"
        )
    return found


def symbol(condition: Condition) -> str:
    """How the condition reads in a failure message: ``=`` for equality, else the condition."""
    return "=" if condition == "==" else condition


def _number(value: object) -> float | None:
    if isinstance(value, AsText):
        value = value.text
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _contains(actual: Any, expected: Any) -> bool:
    if actual is None:
        return False
    if isinstance(actual, str):
        if isinstance(expected, re.Pattern):
            return cast("re.Pattern[str]", expected).search(actual) is not None
        needle = expected.text if isinstance(expected, AsText) else as_text(expected)
        if needle is None:
            raise ComparisonError(f"cannot look for {type(expected).__name__} inside text")
        return needle in actual
    if isinstance(actual, Iterable):
        return any(property_matches(item, expected) for item in cast("Iterable[Any]", actual))
    raise ComparisonError(f"{type(actual).__name__} has no members to look in")


def _ordered(actual: Any, expected: Any) -> tuple[Any, Any]:
    if actual is None:
        raise ComparisonError("the property has no value")
    left, right = _number(actual), _number(expected)
    if left is not None and right is not None:
        return left, right
    if isinstance(actual, str) and isinstance(expected, str):
        return actual, expected
    raise ComparisonError(
        f"{type(actual).__name__} cannot be ordered against {type(expected).__name__}"
    )


def compare(actual: Any, expected: Any, condition: Condition, *, lenient: bool = False) -> bool:
    """Whether ``actual`` meets ``condition`` against ``expected``.

    Equality is the one of ``expect(...).to_have_property``: exact, or by invariant text for an
    ``AsText``, or by search for a compiled regex. ``lenient=True`` compares a plain string,
    number or boolean ``expected`` by invariant text too (``"True"`` equals ``True``, ``"15"``
    equals 15), as migrated suites pass such values as strings. Order compares numbers
    numerically, also when one or both are numeric text, and two other strings alphabetically;
    ``contains`` looks for text in text or a member in a list. Values that cannot be ordered
    raise ``ComparisonError``.
    """
    if condition in ("==", "!="):
        if lenient and isinstance(expected, str | int | float) and not isinstance(expected, AsText):
            expected = AsText(cast(str, as_text(expected)))
        matches = property_matches(actual, expected)
        return matches if condition == "==" else not matches
    if condition == "contains":
        return _contains(actual, expected)
    if condition == "not contains":
        return not _contains(actual, expected)
    left, right = _ordered(actual, expected)
    if condition == "<":
        return left < right
    if condition == "<=":
        return left <= right
    if condition == ">":
        return left > right
    return left >= right
