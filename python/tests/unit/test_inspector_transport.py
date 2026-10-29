"""Frame boundaries and strict decoding."""

import struct

import pytest

from wintestkit.inspector.transport import MemoryTransport, read_frame, write_frame


def test_frame_roundtrip() -> None:
    transport = MemoryTransport()
    write_frame(transport, {"id": 1}, 1.0)
    assert read_frame(MemoryTransport(transport.written), 1.0) == {"id": 1}


@pytest.mark.parametrize("data", [b"\x01", struct.pack("<I", 9) + b"{}"])
def test_eof(data: bytes) -> None:
    with pytest.raises(EOFError):
        read_frame(MemoryTransport(data), 1.0)


def test_oversize() -> None:
    with pytest.raises(ValueError):
        read_frame(MemoryTransport(struct.pack("<I", 1_048_577)), 1.0)


def test_duplicate_keys() -> None:
    data = b'{"a":1,"a":2}'
    with pytest.raises(ValueError):
        read_frame(MemoryTransport(struct.pack("<I", len(data)) + data), 1.0)


@pytest.mark.parametrize(
    "data",
    [b"", b"\xff", b'{"x":NaN}', b'{"x":1e999}', b'{"x":"\\ud800"}', b"[" * 33 + b"0" + b"]" * 33],
)
def test_invalid_json_or_depth(data: bytes) -> None:
    with pytest.raises((ValueError, UnicodeError)):
        read_frame(MemoryTransport(struct.pack("<I", len(data)) + data), 1.0)


def test_depth_limit_accepts_32_containers() -> None:
    data = b"[" * 32 + b"0" + b"]" * 32
    assert read_frame(MemoryTransport(struct.pack("<I", len(data)) + data), 1.0)
