"""Translate supported locator links to the bounded WPF query protocol."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import cast

from wintestkit.engine.locator import Locator
from wintestkit.engine.managed import ManagedCondition
from wintestkit.engine.properties import AsText, Condition
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
        if value.flags & re.IGNORECASE and any(ord(c) > 127 and c.isalpha() for c in value.pattern):
            raise UnsupportedQuery("ignoreCase regex contains a non-ASCII letter")
        # Python uses \Z for the strict end anchor; the wire grammar uses \z.
        pattern = re.sub(
            r"\\\\.|\\Z", lambda m: r"\z" if m.group() == r"\Z" else m.group(), value.pattern
        )
        # The DTO validator checks literals, escapes, groups and numeric bounds. Python's
        # parser also rejects malformed nesting; these extra checks enforce agent grammar.
        try:
            result = Predicate.from_json(
                {
                    "kind": "regex",
                    "path": [p.to_json() for p in path],
                    "pattern": pattern,
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
    if isinstance(value, AsText):
        try:
            return Predicate.from_json(
                {"kind": "equalsText", "path": [p.to_json() for p in path], "value": value.text}
            )
        except ValueError as error:
            raise UnsupportedQuery("unsupported text") from error
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
    *,
    root_level: bool = False,
) -> WireLocator:
    """The wire query for one link.

    ``root_level`` marks an object-tree search whose root is the window's root visual: the window
    node above it is level 0, so the root visual is depth 1 and the agent's own depth is one less.
    """
    if locator.any_of:
        raise UnsupportedQuery("any_of alternatives cannot be expressed as one query")
    if locator.has is not None:
        raise UnsupportedQuery("has= filters cannot be expressed as one query")
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
    if locator.tree == "objects":
        depth = 256 if locator.depth is None else locator.depth - 1 if root_level else locator.depth
        return WireLocator(
            Scope("object", handle), "objects", tuple(predicates), depth, 200, "tree"
        )
    return WireLocator(
        Scope("object", handle),
        "combined",
        tuple(predicates),
        locator.depth if locator.depth is not None else 256,
        200,
        "peers",
    )
