"""Unit tests for the PNG encoder."""

import struct
import zlib

import pytest

from wintestkit.uia.png import encode_png


def decode(png: bytes) -> tuple[int, int, bytes]:
    """Minimal decoder for what encode_png produces (filter 0, 8-bit RGB)."""
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, header = 8, b"", b""
    kinds = []
    while pos < len(png):
        (length,) = struct.unpack(">I", png[pos : pos + 4])
        kind = png[pos + 4 : pos + 8]
        data = png[pos + 8 : pos + 8 + length]
        (crc,) = struct.unpack(">I", png[pos + 8 + length : pos + 12 + length])
        assert crc == zlib.crc32(kind + data)
        kinds.append(kind)
        if kind == b"IHDR":
            header = data
        elif kind == b"IDAT":
            idat += data
        pos += 12 + length
    assert kinds == [b"IHDR", b"IDAT", b"IEND"]
    width, height, depth, colour, comp, filt, interlace = struct.unpack(">IIBBBBB", header)
    assert (depth, colour, comp, filt, interlace) == (8, 2, 0, 0, 0)
    raw = zlib.decompress(idat)
    stride = width * 3
    rows = b""
    for y in range(height):
        row = raw[y * (stride + 1) : (y + 1) * (stride + 1)]
        assert row[0] == 0
        rows += row[1:]
    return width, height, rows


def test_two_by_two_round_trip() -> None:
    pixels = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 255])
    assert decode(encode_png(2, 2, pixels)) == (2, 2, pixels)


def test_known_bytes_for_single_pixel() -> None:
    png = encode_png(1, 1, bytes([1, 2, 3]))
    assert png.startswith(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
    assert png.endswith(b"\x00\x00\x00\x00IEND\xaeB`\x82")
    assert decode(png) == (1, 1, bytes([1, 2, 3]))


def test_wide_image() -> None:
    width, height = 256, 4
    pixels = bytes(i % 251 for i in range(width * height * 3))
    assert decode(encode_png(width, height, pixels)) == (width, height, pixels)


def test_rejects_bad_sizes() -> None:
    with pytest.raises(ValueError, match="positive"):
        encode_png(0, 1, b"")
    with pytest.raises(ValueError, match="expected 12"):
        encode_png(2, 2, b"\x00" * 11)
