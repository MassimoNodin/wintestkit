"""Validate repository write permissions and translate them to bootstrap entries."""

from __future__ import annotations

import re
from typing import cast

_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
_TYPE = rf"{_NAME}(?:[.+]{_NAME})+"
_ENTRY = re.compile(
    rf"(?P<type>{_TYPE})\.(?P<member>{_NAME})(?P<args>\((?:{_TYPE}(?:,{_TYPE})*)?\))?"
)


def parse_write_allowlist(value: object) -> tuple[tuple[str, ...], dict[str, list[dict[str, str]]]]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("expected a list of exact property or method names")
    entries: list[str] = []
    properties: list[dict[str, str]] = []
    methods: list[dict[str, str]] = []
    for item in cast("list[object] | tuple[object, ...]", value):
        if not isinstance(item, str) or len(item) > 1024:
            raise ValueError("invalid write allowlist entry")
        match = _ENTRY.fullmatch(item)
        if match is None or item in entries:
            raise ValueError("invalid or duplicate write allowlist entry")
        type_name, member, args = match.group("type", "member", "args")
        if args is None:
            properties.append({"typeFullName": type_name, "memberName": member})
        else:
            methods.append({"typeFullName": type_name, "memberKey": member + args})
        if len(properties) > 128 or len(methods) > 128:
            raise ValueError("at most 128 properties and 128 methods are allowed")
        entries.append(item)
    return tuple(entries), {"properties": properties, "methods": methods}
