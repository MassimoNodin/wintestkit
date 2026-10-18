"""Bounded screenshot recording, lifecycle and failure isolation."""

import threading
from pathlib import Path

import pytest

from wintestkit.trace import TraceRecorder


def test_frames_are_timestamped_deduplicated_and_portable(tmp_path: Path) -> None:
    frames = iter([b"first", b"first", b"second", b"first"])
    trace = TraceRecorder(tmp_path / "artifacts/test", tmp_path, capture=lambda: next(frames))
    for _ in range(4):
        trace._sample()
    result = trace.stop()
    assert len(result["frames"]) == 3
    assert [frame["time"] for frame in result["frames"]] == sorted(
        frame["time"] for frame in result["frames"]
    )
    assert result["duration"] >= result["frames"][-1]["time"]
    assert result["frames"][0]["path"] == "artifacts/test/trace/000000.png"
    assert (tmp_path / result["frames"][1]["path"]).read_bytes() == b"second"
    assert trace.stop() is result


@pytest.mark.parametrize("limits", [{"max_frames": 1}, {"max_bytes": 5}])
def test_recording_stops_at_storage_limits(tmp_path: Path, limits: dict[str, int]) -> None:
    frames = iter([b"first", b"second"])
    trace = TraceRecorder(tmp_path, tmp_path, capture=lambda: next(frames), **limits)
    trace._sample()
    trace._sample()
    result = trace.stop()
    assert result["truncated"]
    assert len(result["frames"]) == 1
    assert len(list((tmp_path / "trace").glob("*.png"))) == 1


def test_oversized_first_frame_is_not_written(tmp_path: Path) -> None:
    trace = TraceRecorder(tmp_path, tmp_path, max_bytes=1, capture=lambda: b"large")
    trace._sample()
    result = trace.stop()
    assert result["truncated"]
    assert not result["frames"]
    assert not (tmp_path / "trace").exists()


def test_successful_recording_can_be_discarded(tmp_path: Path) -> None:
    trace = TraceRecorder(tmp_path, tmp_path, capture=lambda: b"png")
    trace._sample()
    result = trace.stop(discard=True)
    assert result["frames"] == []
    assert not list((tmp_path / "trace").glob("*.png"))


def test_no_window_does_not_capture_desktop(tmp_path: Path) -> None:
    trace = TraceRecorder(tmp_path, tmp_path, capture=lambda: None)
    trace._sample()
    result = trace.stop()
    assert not result["frames"]
    assert "No visible application window" in result["error"]


def test_background_capture_failure_is_best_effort(tmp_path: Path) -> None:
    attempted = threading.Event()

    def capture() -> bytes:
        attempted.set()
        raise OSError("desktop locked")

    trace = TraceRecorder(tmp_path, tmp_path, capture=capture)
    trace.start()
    assert attempted.wait(2)
    result = trace.stop()
    assert "desktop locked" in result["error"]
    assert not trace._thread.is_alive()


def test_background_capture_continues_between_actions(tmp_path: Path) -> None:
    captured = threading.Event()
    samples = 0

    def capture() -> bytes:
        nonlocal samples
        samples += 1
        if samples == 3:
            captured.set()
        return bytes([samples])

    trace = TraceRecorder(tmp_path, tmp_path, fps=30, capture=capture)
    trace.start()
    assert captured.wait(2)
    result = trace.stop()
    assert len(result["frames"]) >= 2
    assert not trace._thread.is_alive()


def test_inflight_capture_cannot_write_after_stop(tmp_path: Path) -> None:
    entered = threading.Event()
    release = threading.Event()

    def capture() -> bytes:
        entered.set()
        release.wait(5)
        return b"png"

    trace = TraceRecorder(tmp_path, tmp_path, capture=capture)
    trace.start()
    assert entered.wait(2)
    try:
        result = trace.stop()
        assert "two seconds" in result["error"]
    finally:
        release.set()
        trace._thread.join(2)
    assert not list(tmp_path.rglob("*.png"))


def test_discard_file_error_does_not_break_tests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trace = TraceRecorder(tmp_path, tmp_path, capture=lambda: b"png")
    trace._sample()

    def denied(*args: object, **kwargs: object) -> None:
        raise PermissionError("file locked")

    monkeypatch.setattr(Path, "unlink", denied)
    assert trace.stop(discard=True)["frames"] == []
