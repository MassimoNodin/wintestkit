"""Bounded screenshot recording, lifecycle and failure isolation."""

import threading
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from wintestkit.replay import ReplayRecorder, _encode_frame
from wintestkit.uia import screenshot
from wintestkit.uia.png import encode_png


@pytest.mark.parametrize("encoded_input", [False, True])
def test_webp_preserves_dimensions_and_every_rgb_pixel(encoded_input: bool) -> None:
    width, height = 31, 17
    pixels = bytes((index * 37 + index // 7) % 256 for index in range(width * height * 3))
    captured = encode_png(width, height, pixels) if encoded_input else (width, height, pixels)
    with Image.open(BytesIO(_encode_frame(captured))) as image:
        assert image.format == "WEBP"
        assert image.size == (width, height)
        assert image.convert("RGB").tobytes() == pixels


def test_frames_are_timestamped_deduplicated_and_portable(tmp_path: Path) -> None:
    first = encode_png(1, 1, b"\xff\x00\x00")
    second = encode_png(1, 1, b"\x00\x00\xff")
    frames = iter([first, first, second, first])
    replay = ReplayRecorder(tmp_path / "artifacts/test", tmp_path, capture=lambda: next(frames))
    for _ in range(4):
        replay._sample()
    result = replay.stop()
    assert len(result["frames"]) == 3
    assert [frame["time"] for frame in result["frames"]] == sorted(
        frame["time"] for frame in result["frames"]
    )
    assert result["duration"] >= result["frames"][-1]["time"]
    assert result["frames"][0]["path"] == "artifacts/test/replay/000000.webp"
    with Image.open(tmp_path / result["frames"][1]["path"]) as image:
        assert image.format == "WEBP"
        assert image.convert("RGB").tobytes() == b"\x00\x00\xff"
    assert replay.stop() is result


def test_unchanged_pixels_are_dropped_before_encoding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    red, blue = b"\xff\x00\x00", b"\x00\x00\xff"
    frames = iter([(1, 1, red), (1, 1, red), (1, 1, blue)])
    replay = ReplayRecorder(tmp_path, tmp_path, capture=lambda: next(frames))
    calls = 0

    def encode(captured: bytes | tuple[int, int, bytes]) -> bytes:
        nonlocal calls
        calls += 1
        return _encode_frame(captured)

    monkeypatch.setattr("wintestkit.replay._encode_frame", encode)
    for _ in range(3):
        replay._sample()
    result = replay.stop()
    assert len(result["frames"]) == 2
    assert calls == 2
    with Image.open(tmp_path / result["frames"][1]["path"]) as image:
        assert image.tobytes() == blue


@pytest.mark.parametrize("limit", ["max_frames", "max_bytes"])
def test_recording_stops_at_storage_limits(tmp_path: Path, limit: str) -> None:
    first = (1, 1, b"\xff\x00\x00")
    limits = {limit: 1 if limit == "max_frames" else len(_encode_frame(first))}
    frames = iter([first, (1, 1, b"\x00\x00\xff")])
    replay = ReplayRecorder(tmp_path, tmp_path, capture=lambda: next(frames), **limits)
    replay._sample()
    replay._sample()
    result = replay.stop()
    assert result["truncated"]
    assert len(result["frames"]) == 1
    saved = list((tmp_path / "replay").glob("*.webp"))
    assert len(saved) == 1
    assert replay._bytes == saved[0].stat().st_size


def test_oversized_first_frame_is_not_written(tmp_path: Path) -> None:
    replay = ReplayRecorder(
        tmp_path, tmp_path, max_bytes=1, capture=lambda: (1, 1, b"\xff\x00\x00")
    )
    replay._sample()
    result = replay.stop()
    assert result["truncated"]
    assert not result["frames"]
    assert not (tmp_path / "replay").exists()


def test_successful_recording_can_be_discarded(tmp_path: Path) -> None:
    replay = ReplayRecorder(tmp_path, tmp_path, capture=lambda: (1, 1, b"\xff\x00\x00"))
    replay._sample()
    result = replay.stop(discard=True)
    assert result["frames"] == []
    assert not list((tmp_path / "replay").glob("*.webp"))


def test_no_window_does_not_capture_desktop(tmp_path: Path) -> None:
    replay = ReplayRecorder(tmp_path, tmp_path, capture=lambda: None)
    replay._sample()
    result = replay.stop()
    assert not result["frames"]
    assert "No visible application window" in result["error"]


def test_desktop_replay_deduplicates_before_webp_encoding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(screenshot, "capture_screen_pixels", lambda: (1, 1, b"\xff\x00\x00"))
    calls = 0

    def encode(captured: bytes | tuple[int, int, bytes]) -> bytes:
        nonlocal calls
        calls += 1
        assert captured == (1, 1, b"\xff\x00\x00")
        return _encode_frame(captured)

    monkeypatch.setattr("wintestkit.replay._encode_frame", encode)
    replay = ReplayRecorder(tmp_path, tmp_path, scope="desktop")
    replay._sample()
    replay._sample()
    assert len(replay.stop()["frames"]) == 1
    assert calls == 1


def test_background_capture_failure_is_best_effort(tmp_path: Path) -> None:
    attempted = threading.Event()

    def capture() -> bytes:
        attempted.set()
        raise OSError("desktop locked")

    replay = ReplayRecorder(tmp_path, tmp_path, capture=capture)
    replay.start()
    assert attempted.wait(2)
    result = replay.stop()
    assert "desktop locked" in result["error"]
    assert not replay._thread.is_alive()


def test_background_capture_continues_between_actions(tmp_path: Path) -> None:
    captured = threading.Event()
    samples = 0

    def capture() -> tuple[int, int, bytes]:
        nonlocal samples
        samples += 1
        if samples == 3:
            captured.set()
        return (1, 1, bytes([samples % 256, 0, 0]))

    replay = ReplayRecorder(tmp_path, tmp_path, fps=30, capture=capture)
    replay.start()
    assert captured.wait(2)
    result = replay.stop()
    assert len(result["frames"]) >= 2
    assert not replay._thread.is_alive()


def test_background_encoding_failure_is_best_effort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempted = threading.Event()

    def encode(captured: bytes | tuple[int, int, bytes]) -> bytes:
        attempted.set()
        raise OSError("WebP encoder failed")

    monkeypatch.setattr("wintestkit.replay._encode_frame", encode)
    replay = ReplayRecorder(tmp_path, tmp_path, capture=lambda: (1, 1, b"\xff\x00\x00"))
    replay.start()
    assert attempted.wait(2)
    result = replay.stop()
    assert "WebP encoder failed" in result["error"]
    assert not result["frames"]
    assert not replay._thread.is_alive()


def test_inflight_capture_cannot_write_after_stop(tmp_path: Path) -> None:
    entered = threading.Event()
    release = threading.Event()

    def capture() -> bytes:
        entered.set()
        release.wait(5)
        return encode_png(1, 1, b"\xff\x00\x00")

    replay = ReplayRecorder(tmp_path, tmp_path, capture=capture)
    replay.start()
    assert entered.wait(2)
    try:
        result = replay.stop()
        assert "two seconds" in result["error"]
    finally:
        release.set()
        replay._thread.join(2)
    assert not list(tmp_path.rglob("*.webp"))


def test_discard_file_error_does_not_break_tests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    replay = ReplayRecorder(tmp_path, tmp_path, capture=lambda: (1, 1, b"\xff\x00\x00"))
    replay._sample()

    def denied(*args: object, **kwargs: object) -> None:
        raise PermissionError("file locked")

    monkeypatch.setattr(Path, "unlink", denied)
    assert replay.stop(discard=True)["frames"] == []
