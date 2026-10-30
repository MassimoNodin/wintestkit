"""Translate supported locator links to the bounded WPF query protocol."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import cast

from wintestkit.engine.locator import Locator
from wintestkit.engine.managed import ManagedCondition
from wintestkit.engine.properties import Condition
from wintestkit.inspector.models import Locator as WireLocator
from wintestkit.inspector.models import ObjectRef, Predicate, Scope
from wintestkit.inspector.paths import PathSegment


class UnsupportedQuery(ValueError):
    """A locator cannot be expressed with phase 1 semantics."""


def predicate(path: tuple[PathSegment, ...], value: object) -> Predicate:
    if isinstance(value, re.Pattern):
        if not isinstance(value.pattern, str):  # pyright: ignore[reportUnknownMemberType]
            raise UnsupportedQuery("unsupported regex pattern")
        value = cast("re.Pattern[str]", value)
        allowed = re.UNICODE | re.IGNORECASE | re.MULTILINE | re.DOTALL
        if value.flags & ~allowed:
            raise UnsupportedQuery("unsupported regex flags")
        flags = tuple(
            name
            for bit, name in (
                (re.IGNORECASE, "ignoreCase"),
                (re.MULTILINE, "multiline"),
                (re.DOTALL, "singleline"),
            )
            if value.flags & bit
        )
        # The DTO validator checks ASCII, escapes, groups and numeric bounds. Python's
        # parser also rejects malformed nesting; these extra checks enforce agent grammar.
        try:
            result = Predicate.from_json(
                {
                    "kind": "regex",
                    "path": [p.to_json() for p in path],
                    "pattern": value.pattern,
                    "flags": list(flags),
                }
            )
        except ValueError as error:
            raise UnsupportedQuery("unsupported regex syntax") from error
        if re.search(r"(?<!\\\\)[\^$](?:[*+?]|\{)", value.pattern) or re.search(
            r"(?:[*+?]|\})\+", value.pattern
        ):
            raise UnsupportedQuery("unsupported regex quantifier")
        return result
    if isinstance(value, Decimal):
        value = float(value)
    try:
        return Predicate.from_json(
            {"kind": "equals", "path": [p.to_json() for p in path], "value": value}
        )
    except (ValueError, OverflowError) as error:
        raise UnsupportedQuery("unsupported scalar") from error


def translate(
    locator: Locator,
    constraints: tuple[Condition | ManagedCondition, ...],
    handle: ObjectRef | None,
) -> WireLocator:
    if locator.depth is not None:
        raise UnsupportedQuery("depth is set")
    predicates: list[Predicate] = []
    for name in ("automation_id", "name", "class_name", "control_type"):
        value = getattr(locator, name)
        if value is not None:
            predicates.append(predicate((PathSegment("uia", name),), value))
    for condition in constraints:
        if isinstance(condition, Condition):
            name = condition.spec.condition
            if name not in {"automation_id", "name", "class_name", "control_type"}:
                raise UnsupportedQuery(f"unsupported UIA property {condition.key}")
            predicates.append(predicate((PathSegment("uia", name),), condition.value))
        elif condition.key == "type:Is":
            predicates.append(
                Predicate.from_json({"kind": "assignableTo", "fullName": condition.value})
            )
        else:
            predicates.append(predicate(condition.path.segments, condition.value))
    if len(predicates) > 32:
        raise UnsupportedQuery("more than 32 predicates")
    return WireLocator(Scope("object", handle), "combined", tuple(predicates), 256, 200)
