"""Bounded framing and strict JSON for the inspector pipe."""

from __future__ import annotations

import json
import math
import struct
from typing import Any, Protocol, cast

MAX_FRAME_BYTES = 1_048_576
MAX_JSON_DEPTH = 32


class ByteTransport(Protocol):
    def read_exact(self, size: int, deadline: float) -> bytes: ...
    def write(self, data: bytes, deadline: float) -> None: ...
    def close(self) -> None: ...


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _depth(value: Any, depth: int = 0) -> None:
    if isinstance(value, (dict, list)):
        if depth >= MAX_JSON_DEPTH:
            raise ValueError("JSON depth exceeds 32")
        items: list[Any] = (
            list(cast(dict[str, Any], value).values())
            if isinstance(value, dict)
            else cast(list[Any], value)
        )
        for item in items:
            _depth(item, depth + 1)
        if isinstance(value, dict):
            for key in cast(dict[str, Any], value):
                _depth(key, depth + 1)
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Non-finite JSON number")
    elif isinstance(value, str) and any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise ValueError("Invalid Unicode string")


def read_frame(transport: ByteTransport, deadline: float) -> Any:
    header = transport.read_exact(4, deadline)
    if len(header) != 4:
        raise EOFError("EOF in frame header")
    size = struct.unpack("<I", header)[0]
    if not 0 < size <= MAX_FRAME_BYTES:
        raise ValueError("Invalid frame size")
    payload = transport.read_exact(size, deadline)
    if len(payload) != size:
        raise EOFError("EOF in frame payload")
    text = payload.decode("utf-8")
    depth = 0
    quoted = False
    escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise ValueError("JSON depth exceeds 32")
        elif char in "]}":
            depth -= 1
    value = json.loads(
        text,
        object_pairs_hook=_object,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
    )
    _depth(value)
    return value


def write_frame(transport: ByteTransport, value: object, deadline: float) -> None:
    _depth(value)
    payload = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    if len(payload) > MAX_FRAME_BYTES:
        raise ValueError("Frame exceeds maximum size")
    transport.write(struct.pack("<I", len(payload)) + payload, deadline)


class MemoryTransport:
    """In-memory transport for tests, with a separate write buffer."""

    def __init__(self, data: bytes = b"") -> None:
        self.data = data
        self.written = b""
        self.closed = False

    def read_exact(self, size: int, deadline: float) -> bytes:
        result, self.data = self.data[:size], self.data[size:]
        return result

    def write(self, data: bytes, deadline: float) -> None:
        self.written += data

    def close(self) -> None:
        self.closed = True
