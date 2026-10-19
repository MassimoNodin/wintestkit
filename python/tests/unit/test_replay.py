"""Bounded screenshot recording, lifecycle and failure isolation."""

import threading
from pathlib import Path

import pytest

from wintestkit.replay import ReplayRecorder
from wintestkit.uia.png import encode_png


def test_frames_are_timestamped_deduplicated_and_portable(tmp_path: Path) -> None:
    frames = iter([b"first", b"first", b"second", b"first"])
    replay = ReplayRecorder(tmp_path / "artifacts/test", tmp_path, capture=lambda: next(frames))
    for _ in range(4):
        replay._sample()
    result = replay.stop()
    assert len(result["frames"]) == 3
    assert [frame["time"] for frame in result["frames"]] == sorted(
        frame["time"] for frame in result["frames"]
    )
    assert result["duration"] >= result["frames"][-1]["time"]
    assert result["frames"][0]["path"] == "artifacts/test/replay/000000.png"
    assert (tmp_path / result["frames"][1]["path"]).read_bytes() == b"second"
    assert replay.stop() is result


def test_unchanged_pixels_are_dropped_before_encoding(tmp_path: Path) -> None:
    red, blue = b"\xff\x00\x00", b"\x00\x00\xff"
    frames = iter([(1, 1, red), (1, 1, red), (1, 1, blue)])
    replay = ReplayRecorder(tmp_path, tmp_path, capture=lambda: next(frames))
    for _ in range(3):
        replay._sample()
    result = replay.stop()
    assert len(result["frames"]) == 2
    assert (tmp_path / result["frames"][1]["path"]).read_bytes() == encode_png(1, 1, blue)


@pytest.mark.parametrize("limits", [{"max_frames": 1}, {"max_bytes": 5}])
def test_recording_stops_at_storage_limits(tmp_path: Path, limits: dict[str, int]) -> None:
    frames = iter([b"first", b"second"])
    replay = ReplayRecorder(tmp_path, tmp_path, capture=lambda: next(frames), **limits)
    replay._sample()
    replay._sample()
    result = replay.stop()
    assert result["truncated"]
    assert len(result["frames"]) == 1
    assert len(list((tmp_path / "replay").glob("*.png"))) == 1


def test_oversized_first_frame_is_not_written(tmp_path: Path) -> None:
    replay = ReplayRecorder(tmp_path, tmp_path, max_bytes=1, capture=lambda: b"large")
    replay._sample()
    result = replay.stop()
    assert result["truncated"]
    assert not result["frames"]
    assert not (tmp_path / "replay").exists()


def test_successful_recording_can_be_discarded(tmp_path: Path) -> None:
    replay = ReplayRecorder(tmp_path, tmp_path, capture=lambda: b"png")
    replay._sample()
    result = replay.stop(discard=True)
    assert result["frames"] == []
    assert not list((tmp_path / "replay").glob("*.png"))


def test_no_window_does_not_capture_desktop(tmp_path: Path) -> None:
    replay = ReplayRecorder(tmp_path, tmp_path, capture=lambda: None)
    replay._sample()
    result = replay.stop()
    assert not result["frames"]
    assert "No visible application window" in result["error"]


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

    def capture() -> bytes:
        nonlocal samples
        samples += 1
        if samples == 3:
            captured.set()
        return bytes([samples])

    replay = ReplayRecorder(tmp_path, tmp_path, fps=30, capture=capture)
    replay.start()
    assert captured.wait(2)
    result = replay.stop()
    assert len(result["frames"]) >= 2
    assert not replay._thread.is_alive()


def test_inflight_capture_cannot_write_after_stop(tmp_path: Path) -> None:
    entered = threading.Event()
    release = threading.Event()

    def capture() -> bytes:
        entered.set()
        release.wait(5)
        return b"png"

    replay = ReplayRecorder(tmp_path, tmp_path, capture=capture)
    replay.start()
    assert entered.wait(2)
    try:
        result = replay.stop()
        assert "two seconds" in result["error"]
    finally:
        release.set()
        replay._thread.join(2)
    assert not list(tmp_path.rglob("*.png"))


def test_discard_file_error_does_not_break_tests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    replay = ReplayRecorder(tmp_path, tmp_path, capture=lambda: b"png")
    replay._sample()

    def denied(*args: object, **kwargs: object) -> None:
        raise PermissionError("file locked")

    monkeypatch.setattr(Path, "unlink", denied)
    assert replay.stop(discard=True)["frames"] == []
