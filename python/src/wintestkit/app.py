"""The application under test: launching, attaching, locating windows and closing."""

from __future__ import annotations

import logging
import os
import subprocess
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import TracebackType
from typing import Any

from wintestkit.engine.diagnose import diagnose_window
from wintestkit.engine.locator import WindowLocator
from wintestkit.errors import (
    ActionError,
    AppError,
    AppNotRunningError,
    UIAError,
    WindowNotFoundError,
)
from wintestkit.uia import element, patterns, win32
from wintestkit.uia.element import UIAElement

log = logging.getLogger("wintestkit.app")

_POLL_INTERVAL = 0.1


class App:
    """A running application under test: the set of processes sharing an exe name.

    Instances are created with :meth:`launch` or :meth:`attach`.
    """

    def __init__(
        self,
        process_name: str,
        *,
        launched: bool = False,
        popen: subprocess.Popen[bytes] | None = None,
        pinned_pid: int | None = None,
        by_name: bool = True,
        baseline: frozenset[int] = frozenset(),
    ) -> None:
        __tracebackhide__ = True
        self.process_name = process_name
        self.launched = launched
        self._popen = popen
        self._pinned_pid = pinned_pid
        self._by_name = by_name
        self._baseline = baseline

    # -- construction ---------------------------------------------------------------------------

    @classmethod
    def launch(
        cls,
        path: str | Path,
        args: Sequence[str] = (),
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        process: str | None = None,
        startup_timeout: float = 30.0,
    ) -> App:
        """Start ``path`` and wait until it shows a main window."""
        __tracebackhide__ = True
        exe = Path(path)
        if not exe.is_file():
            raise AppError(f"Application executable not found: {exe}")
        process_name = process or exe.name
        baseline = frozenset(win32.pids_by_name(process_name))
        try:
            popen = subprocess.Popen(
                [str(exe), *args],
                cwd=str(cwd) if cwd is not None else None,
                env={**os.environ, **(env or {})},
                creationflags=0,
            )
        except OSError as exc:
            raise AppError(f"Could not start {exe}: {exc}") from exc
        app = cls(process_name, launched=True, popen=popen, baseline=baseline)
        log.info("launched %s (pid %d)", exe, popen.pid)
        app._wait_for_startup(startup_timeout)
        return app

    @classmethod
    def attach(cls, process: str | None = None, pid: int | None = None) -> App:
        """Attach to a running application by exe name or process id."""
        __tracebackhide__ = True
        if pid is not None:
            names = {p: name for p, name in win32.list_processes()}
            if pid not in names:
                raise AppNotRunningError(f"No process with id {pid} is running")
            return cls(process or names[pid], pinned_pid=pid, by_name=False)
        if process is None:
            raise ValueError("attach() needs a process name or a pid")
        if not win32.pids_by_name(process):
            raise AppNotRunningError(f"No running process named {process}")
        return cls(process)

    # -- state ----------------------------------------------------------------------------------

    @property
    def pids(self) -> list[int]:
        """Live process ids belonging to the application."""
        __tracebackhide__ = True
        found: set[int] = set()
        if self._by_name:
            found.update(set(win32.pids_by_name(self.process_name)) - self._baseline)
        if self._pinned_pid is not None and self._pinned_pid in dict(win32.list_processes()):
            found.add(self._pinned_pid)
        if self._popen is not None and self._popen.poll() is None:
            found.add(self._popen.pid)
        return sorted(found)

    def is_running(self) -> bool:
        __tracebackhide__ = True
        return bool(self.pids)

    def top_level_windows(self) -> list[UIAElement]:
        """Visible top-level windows of the application in z-order (owned windows included).

        Uses ``EnumWindows`` rather than the UIA desktop root, whose children can take seconds to
        enumerate on machines with slow UIA providers.
        """
        __tracebackhide__ = True
        pids = set(self.pids)
        if not pids:
            return []
        windows: list[UIAElement] = []
        for hwnd in win32.top_level_windows(pids):
            try:
                windows.append(element.from_handle(hwnd))
            except UIAError:
                continue  # the window closed while enumerating
        return windows

    def main_window(self, timeout: float = 0.0) -> UIAElement:
        """The first unowned top-level ``Window`` in z-order; polls up to ``timeout`` seconds."""
        __tracebackhide__ = True
        deadline = time.monotonic() + timeout
        while True:
            if not self.is_running():
                raise AppNotRunningError(f"{self.process_name} is not running")
            for hwnd in win32.top_level_windows(set(self.pids)):
                if win32.window_owner(hwnd) != 0:
                    continue
                try:
                    window = element.from_handle(hwnd)
                    if window.control_type == "Window":
                        return window
                except UIAError:
                    continue
            if time.monotonic() >= deadline:
                break
            time.sleep(_POLL_INTERVAL)
        windows = self.top_level_windows()
        raise WindowNotFoundError(diagnose_window(self, WindowLocator(), [], windows))

    def wait_for_exit(self, timeout: float) -> bool:
        """Wait until no process of the application is left; ``False`` on timeout."""
        __tracebackhide__ = True
        deadline = time.monotonic() + timeout
        while self.is_running():
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)
        return True

    # -- shutdown -------------------------------------------------------------------------------

    def close(self, timeout: float = 10.0) -> None:
        """Ask every window to close (owned ones first), then kill if it does not exit."""
        __tracebackhide__ = True
        windows = self.top_level_windows()
        windows.sort(key=lambda w: 0 if win32.window_owner(w.native_window_handle) else 1)
        for window in windows:
            try:
                patterns.window_close(window)
            except (ActionError, UIAError):
                win32.PostMessageW(window.native_window_handle, win32.WM_CLOSE, 0, 0)
            time.sleep(0.05)
        if not self.wait_for_exit(timeout):
            log.warning("%s did not exit within %.1fs; killing it", self.process_name, timeout)
            self.kill()

    def kill(self) -> None:
        """Forcefully terminate every process of the application (and their children)."""
        __tracebackhide__ = True
        for pid in self.pids:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
        self.wait_for_exit(5.0)
        if self._popen is not None:
            self._popen.poll()

    def __enter__(self) -> App:
        __tracebackhide__ = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        __tracebackhide__ = True
        if self.launched:
            self.close()

    # -- internals ------------------------------------------------------------------------------

    def _wait_for_startup(self, startup_timeout: float) -> None:
        __tracebackhide__ = True
        assert self._popen is not None
        deadline = time.monotonic() + startup_timeout
        self._wait_for_input_idle(self._popen.pid, min(10.0, startup_timeout))
        while True:
            try:
                self.main_window()
                return
            except AppNotRunningError:
                code = self._popen.poll()
                raise AppError(
                    f"{self.process_name} exited before showing a window (exit code {code})"
                ) from None
            except WindowNotFoundError:
                pass
            if time.monotonic() >= deadline:
                self.kill()
                raise AppError(
                    f"{self.process_name} did not show a window within {startup_timeout:g}s"
                )
            time.sleep(_POLL_INTERVAL)

    @staticmethod
    def _wait_for_input_idle(pid: int, timeout: float) -> None:
        __tracebackhide__ = True
        access = win32.PROCESS_QUERY_LIMITED_INFORMATION | win32.SYNCHRONIZE | 0x0400
        handle: Any = win32.OpenProcess(access, False, pid)
        if not handle:
            return
        try:
            win32.WaitForInputIdle(
                handle, int(timeout * 1000)
            )  # fails harmlessly for non-GUI launchers
        finally:
            win32.CloseHandle(handle)
