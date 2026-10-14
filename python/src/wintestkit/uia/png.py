"""Minimal pure-Python PNG writer (8-bit RGB, no interlacing)."""

from __future__ import annotations

import struct
import zlib

_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def encode_png(width: int, height: int, rgb_rows: bytes) -> bytes:
    """Encode ``width * height`` RGB pixels (row after row, 3 bytes each) as a PNG."""
    if width <= 0 or height <= 0:
        raise ValueError("PNG dimensions must be positive")
    stride = width * 3
    if len(rgb_rows) != stride * height:
        raise ValueError(f"expected {stride * height} bytes of RGB data, got {len(rgb_rows)}")
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type 0 (None)
        raw += rgb_rows[y * stride : (y + 1) * stride]
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        _SIGNATURE
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + _chunk(b"IEND", b"")
    )
