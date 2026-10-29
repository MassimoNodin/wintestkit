"""Bounded, non-disclosing validation for additional redaction names."""

from __future__ import annotations

from typing import cast


def validate_redact_names(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        raise ValueError("Invalid redaction names")
    entries = cast("list[object] | tuple[object, ...]", value)
    if len(entries) > 32:
        raise ValueError("Invalid redaction names")
    names: list[str] = []
    for name in entries:
        if (
            not isinstance(name, str)
            or not 1 <= len(name) <= 128
            or any(0xD800 <= ord(char) <= 0xDFFF for char in name)
        ):
            raise ValueError("Invalid redaction names")
        names.append(name)
    return tuple(names)
