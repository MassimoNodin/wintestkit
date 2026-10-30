"""Parse qualified managed paths without evaluating target code."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast

from wintestkit.errors import InvalidLocatorError

MANAGED_PREFIXES = ("type:", "clr:", "field:", "dp:")


@dataclass(frozen=True)
class PathSegment:
    kind: Literal["property", "field", "dependency", "type", "uia"]
    name: str
    declaring_type: str | None = None
    member_key: str | None = None
    owner_type: str | None = None
    owner_assembly: str | None = None

    @classmethod
    def from_json(cls, value: object) -> PathSegment:
        if not isinstance(value, dict):
            raise ValueError("Invalid path segment")
        data = cast(dict[str, Any], value)
        kind = data.get("kind")
        if kind in ("property", "field"):
            required, allowed = {"kind", "name"}, {"kind", "name", "declaringType", "memberKey"}
        elif kind == "dependency":
            required = allowed = {"kind", "name", "ownerType", "ownerAssembly"}
        elif kind in ("type", "uia"):
            required = allowed = {"kind", "name"}
        else:
            raise ValueError("Invalid path segment kind")
        if not required <= data.keys() or not data.keys() <= allowed:
            raise ValueError("Invalid path segment fields")
        for key in allowed - {"kind"}:
            if key in data and (not isinstance(data[key], str) or not 1 <= len(data[key]) <= 1024):
                raise ValueError("Invalid path segment string")
        if kind == "type" and data["name"] not in {
            "Name",
            "FullName",
            "AssemblyName",
            "AssemblyQualifiedName",
            "BaseTypes",
        }:
            raise ValueError("Invalid type metadata name")
        if kind == "uia" and data["name"] not in {
            "automation_id",
            "name",
            "class_name",
            "control_type",
        }:
            raise ValueError("Invalid UIA name")
        return cls(
            kind,
            data["name"],
            data.get("declaringType"),
            data.get("memberKey"),
            data.get("ownerType"),
            data.get("ownerAssembly"),
        )

    def to_json(self) -> dict[str, object]:
        result: dict[str, object] = {"kind": self.kind, "name": self.name}
        for key, value in (
            ("declaringType", self.declaring_type),
            ("memberKey", self.member_key),
            ("ownerType", self.owner_type),
            ("ownerAssembly", self.owner_assembly),
        ):
            if value is not None:
                result[key] = value
        return result


@dataclass(frozen=True)
class ManagedPath:
    canonical: str
    segments: tuple[PathSegment, ...]

    def to_json(self) -> list[dict[str, object]]:
        return [segment.to_json() for segment in self.segments]


def is_managed_key(key: str) -> bool:
    return key.startswith(MANAGED_PREFIXES)


def _split(text: str, separator: str, offset: int) -> list[str]:
    parts: list[str] = []
    part = ""
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\":
            if index + 1 >= len(text) or text[index + 1] not in (separator, "\\"):
                raise InvalidLocatorError(f"Invalid escape at position {offset + index}: {char!r}")
            index += 1
            part += text[index]
        elif char == separator:
            if not part:
                raise InvalidLocatorError(f"Empty segment at position {offset + index}")
            parts.append(part)
            part = ""
        elif char in "[]()*" or char.isspace():
            raise InvalidLocatorError(f"Invalid character {char!r} at position {offset + index}")
        else:
            part += char
        index += 1
    if not part:
        raise InvalidLocatorError(f"Empty segment at position {offset + len(text)}")
    parts.append(part)
    for part in parts:
        if part.isdecimal():
            raise InvalidLocatorError(f"Integer index {part!r} is not allowed")
    return parts


def parse_managed_key(key: str) -> ManagedPath:
    try:
        encoded = key.encode("utf-8")
    except UnicodeEncodeError as error:
        raise InvalidLocatorError("Managed path contains invalid Unicode") from error
    if len(encoded) > 1024:
        raise InvalidLocatorError("Managed path exceeds 1024 UTF-8 bytes")
    if not is_managed_key(key):
        raise InvalidLocatorError("Unknown managed path prefix at position 0")
    prefix, body = key.split(":", 1)
    offset = len(prefix) + 1
    if prefix == "type":
        if body not in {"Name", "FullName", "AssemblyName", "AssemblyQualifiedName", "BaseTypes"}:
            raise InvalidLocatorError(f"Invalid type name {body!r} at position {offset}")
        segments = [PathSegment("type", body)]
    elif prefix == "dp":
        if body.count("|") != 1 or body.count("::") != 1:
            raise InvalidLocatorError(f"Invalid dependency path delimiters at position {offset}")
        assembly, remainder = body.split("|", 1)
        owner, remainder = remainder.split("::", 1)
        first, _, nested = remainder.partition("/")
        for value in (assembly, owner, first):
            if not value:
                raise InvalidLocatorError(f"Empty dependency name at position {offset}")
            for char in value:
                if char in "|:/\\[]()*" or char.isspace():
                    raise InvalidLocatorError(
                        f"Invalid character {char!r} at position {key.index(char, offset)}"
                    )
        segments = [PathSegment("dependency", first, owner_type=owner, owner_assembly=assembly)]
        if "/" in remainder:
            start = len(key) - len(nested)
            segments.extend(PathSegment("property", name) for name in _split(nested, "/", start))
    else:
        names = _split(body, ".", offset)
        segments = [
            PathSegment("field" if prefix == "field" and i == 0 else "property", name)
            for i, name in enumerate(names)
        ]
    if len(segments) > 8:
        raise InvalidLocatorError("Managed path exceeds 8 segments")
    return ManagedPath(key, tuple(segments))
