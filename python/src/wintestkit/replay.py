"""Bounded, best-effort screenshot recording without cross-thread UI Automation."""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from wintestkit.uia.png import encode_png

Pixels = tuple[int, int, bytes]

log = logging.getLogger("wintestkit.replay")


class ReplayRecorder:
    """Capture on one worker, dropping missed ticks rather than queueing screenshots."""

    def __init__(
        self,
        directory: Path,
        report_dir: Path,
        *,
        fps: float = 5,
        scope: str = "window",
        max_frames: int = 3000,
        max_bytes: int = 104857600,
        capture: Callable[[], bytes | Pixels | None] | None = None,
    ) -> None:
        self.directory = directory / "replay"
        self.report_dir = report_dir
        self.interval = 1 / fps
        self.scope = scope
        self.max_frames = max_frames
        self.max_bytes = max_bytes
        self.started_at = time.time()
        self.started = time.monotonic()
        self.frames: list[dict[str, Any]] = []
        self.truncated = False
        self.error: str | None = None
        self.window: int | None = None
        self.window_pid: int | None = None
        self._bytes = 0
        self._digest: bytes | None = None
        self._capture = capture or self._capture_window
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = threading.Thread(target=self._run, name="wtk-replay", daemon=True)
        self._result: dict[str, Any] | None = None

    def start(self) -> None:
        self._thread.start()

    def set_window(self, window: int) -> None:
        from wintestkit.uia import win32

        self.window = window
        self.window_pid = win32.window_pid(window)
        self.request_frame()

    def request_frame(self) -> None:
        self._wake.set()

    def _capture_window(self) -> bytes | Pixels | None:
        from wintestkit.uia import screenshot

        if self.scope == "desktop":
            return screenshot.capture_screen()
        if self.window is None:
            return None
        return screenshot.capture_window_pixels(self.window, self.window_pid)

    def _sample(self) -> None:
        timestamp = max(0.0, time.monotonic() - self.started)
        captured = self._capture()
        if not captured or self._stop.is_set():
            return
        if isinstance(captured, tuple):
            width, height, rgb = captured
            digest = hashlib.sha256(b"%d,%d," % (width, height) + rgb).digest()
        else:
            digest = hashlib.sha256(captured).digest()
        if digest == self._digest:
            return
        png = encode_png(*captured) if isinstance(captured, tuple) else captured
        if len(self.frames) >= self.max_frames or self._bytes + len(png) > self.max_bytes:
            self.truncated = True
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{len(self.frames):06d}.png"
        path.write_bytes(png)
        if self._stop.is_set():
            path.unlink(missing_ok=True)
            return
        self.frames.append(
            {"time": timestamp, "path": path.relative_to(self.report_dir).as_posix()}
        )
        self._bytes += len(png)
        self._digest = digest

    def _run(self) -> None:
        # Ticks keep a fixed cadence so capture time does not stretch the interval; a tick that
        # is already late is skipped rather than queued.
        due = time.monotonic()
        while not self._stop.is_set() and not self.truncated:
            self._wake.clear()
            try:
                self._sample()
            except Exception as exc:
                if self.error is None:
                    log.warning("replay capture failed: %s", exc)
                self.error = f"Screenshot capture failed: {exc}"
            now = time.monotonic()
            due = max(due + self.interval, now)
            self._wake.wait(due - now)

    def stop(self, *, discard: bool = False) -> dict[str, Any]:
        if self._result is not None:
            return self._result
        duration = max(0.0, time.monotonic() - self.started)
        self._stop.set()
        self._wake.set()
        if self._thread.ident is not None:
            self._thread.join(timeout=2)
        result: dict[str, Any] = {
            "startedAt": self.started_at,
            "duration": duration,
            "frames": list(self.frames),
            "truncated": self.truncated,
        }
        error = self.error
        if self._thread.is_alive():
            error = "Screenshot capture did not stop within two seconds; recording is incomplete."
        if not self.frames and error is None:
            error = "No visible application window was available for recording."
        if error:
            result["error"] = error
        if discard:
            for frame in self.frames:
                try:
                    (self.report_dir / frame["path"]).unlink(missing_ok=True)
                except OSError as exc:
                    log.warning("could not discard replay frame: %s", exc)
            result["frames"] = []
        self._result = result
        return result
