"""The application under test: launching, attaching, locating windows and closing."""

from __future__ import annotations

import logging
import os
import subprocess
import time
import weakref
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any, Literal, Protocol

from wintestkit.engine.diagnose import diagnose_window
from wintestkit.engine.locator import WindowLocator
from wintestkit.errors import (
    ActionError,
    AppError,
    AppNotRunningError,
    ElevationError,
    UIAError,
    WindowNotFoundError,
)
from wintestkit.uia import element, patterns, win32
from wintestkit.uia.element import UIAElement

if TYPE_CHECKING:
    from wintestkit.model import BoundElement

log = logging.getLogger("wintestkit.app")

_POLL_INTERVAL = 0.1

CloseMethod = Literal["wm_close", "alt_f4"]
CloseOutcome = Literal["exited", "killed", "running"]


class _Process(Protocol):
    """The part of ``subprocess.Popen`` the application uses to follow a process it started."""

    pid: int

    def poll(self) -> int | None: ...

    def wait(self, timeout: float | None = None) -> int: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...


class _HandleProcess:
    """A process started through the shell (an elevated launch), followed by its handle."""

    def __init__(self, handle: int, pid: int) -> None:
        __tracebackhide__ = True
        self.pid = pid
        self._handle: int | None = handle
        self._code: int | None = None

    def poll(self) -> int | None:
        __tracebackhide__ = True
        if self._handle is not None:
            code = win32.process_exit_code(self._handle)
            if code is not None:
                self._code = code
                win32.CloseHandle(self._handle)
                self._handle = None
        return self._code

    def wait(self, timeout: float | None = None) -> int:
        __tracebackhide__ = True
        deadline = None if timeout is None else time.monotonic() + timeout
        while (code := self.poll()) is None:
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(str(self.pid), timeout or 0.0)
            time.sleep(0.05)
        return code

    def terminate(self) -> None:
        __tracebackhide__ = True
        self.kill()

    def kill(self) -> None:
        __tracebackhide__ = True
        if self._handle is not None:
            win32.TerminateProcess(self._handle, 1)  # refused for a process we cannot touch


#: Every launched or attached application, to tell the processes of several instances apart.
_APPS: weakref.WeakSet[App] = weakref.WeakSet()


def _same_exe(left: str, right: str) -> bool:
    """Whether two process names are the same exe; ``notepad`` and ``notepad.exe`` are."""
    __tracebackhide__ = True

    def full(name: str) -> str:
        __tracebackhide__ = True
        lowered = name.casefold()
        return lowered if lowered.endswith(".exe") else lowered + ".exe"

    return full(left) == full(right)


def _register(app: App) -> App:
    __tracebackhide__ = True
    from wintestkit import runtime

    runtime.register_app(app)
    return app


def _running_name(process: str) -> str | None:
    """The exe name of ``process`` as it is running; a name without extension may be ``.exe``."""
    __tracebackhide__ = True
    candidates = [process] if process.casefold().endswith(".exe") else [process, process + ".exe"]
    return next((name for name in candidates if win32.pids_by_name(name)), None)


class App:
    """A running application under test: the set of processes sharing an exe name.

    Instances are created with :meth:`launch` or :meth:`attach`. A test can hold several: each
    one has its own processes, its own pages and its own inspector sessions. Instances of the
    same exe that were launched by this process do not see each other's processes.
    """

    def __init__(
        self,
        process_name: str,
        *,
        launched: bool = False,
        popen: _Process | None = None,
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
        self._known_pids: set[int] = set()
        self._inspector_identities: set[Any] = set()
        self._startup_complete = False
        self._drivable: set[int] = set()
        self.elevated = False
        _APPS.add(self)

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
        progress: Callable[[str], None] | None = None,
        owned_only: bool = False,
        elevated: bool = False,
    ) -> App:
        """Start ``path`` and wait until it shows a main window.

        ``progress`` is called with ``"process"`` once the process has started and with
        ``"window"`` once it is waiting for the main window. Launch the same exe again with other
        ``args`` for a second instance; pass ``owned_only=True`` to follow only the process that
        was started, not every process of that exe name.

        ``elevated=True`` starts it with administrator rights. A runner that is already elevated
        starts it as usual (the child inherits the rights and ``env`` applies). Otherwise the
        shell's ``runas`` verb asks for consent on the secure desktop, which a test cannot answer:
        someone has to click it, or the runner has to be started elevated. A non-elevated runner
        cannot drive an elevated application (Windows blocks it, see :class:`ElevationError`),
        so that App is only a handle for waiting and for ``kill``/``close`` errors to say why.
        ``env`` cannot be passed to that kind of launch.
        """
        __tracebackhide__ = True
        exe = Path(path)
        if not exe.is_file():
            raise AppError(f"Application executable not found: {exe}")
        process_name = process or exe.name
        baseline = frozenset(win32.pids_by_name(process_name))
        through_shell = elevated and not win32.current_process_is_elevated()
        popen: _Process
        if through_shell:
            popen = cls._start_elevated(exe, args, cwd, env)
        else:
            try:
                popen = subprocess.Popen(
                    [str(exe), *args],
                    cwd=str(cwd) if cwd is not None else None,
                    env={**os.environ, **(env or {})},
                    creationflags=0,
                )
            except OSError as exc:
                raise AppError(f"Could not start {exe}: {exc}") from exc
        app = cls(
            process_name, launched=True, popen=popen, baseline=baseline, by_name=not owned_only
        )
        app.elevated = elevated
        _register(app)
        log.info("launched %s (pid %d)%s", exe, popen.pid, " elevated" if elevated else "")
        if progress is not None:
            progress("process")
        if through_shell:
            # The window of an elevated process is out of reach (UIPI): only follow the process.
            if popen.poll() is not None:
                raise AppError(
                    f"{process_name} exited right after starting (exit code {popen.poll()})"
                )
            log.warning(
                "%s runs elevated and this test runner does not: Windows blocks input, window "
                "messages and UI Automation towards it. Start the runner elevated to drive it.",
                process_name,
            )
            return app
        try:
            app._wait_for_startup(startup_timeout, progress)
        except BaseException:
            from wintestkit import runtime

            runtime.detach_inspector_pids([popen.pid])
            if popen.poll() is None:
                popen.terminate()
                try:
                    popen.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    popen.kill()
                    popen.wait()
            raise
        return app

    @classmethod
    def attach(cls, process: str | None = None, pid: int | None = None) -> App:
        """Attach to a running application by exe name or process id."""
        __tracebackhide__ = True
        if pid is not None:
            names = {p: name for p, name in win32.list_processes()}
            if pid not in names:
                raise AppNotRunningError(f"No process with id {pid} is running")
            return _register(cls(process or names[pid], pinned_pid=pid, by_name=False))
        if process is None:
            raise ValueError("attach() needs a process name or a pid")
        running = _running_name(process)
        if running is None:
            raise AppNotRunningError(f"No running process named {process}")
        return _register(cls(running))

    @staticmethod
    def _start_elevated(
        exe: Path, args: Sequence[str], cwd: str | Path | None, env: Mapping[str, str] | None
    ) -> _Process:
        __tracebackhide__ = True
        if env:
            raise AppError(
                "An elevated launch cannot take env: Windows starts the process with the user's "
                "own environment. Set the variables for the whole test session instead."
            )
        try:
            handle, pid = win32.shell_execute(
                str(exe),
                subprocess.list2cmdline([str(arg) for arg in args]),
                str(cwd) if cwd is not None else os.getcwd(),
            )
        except OSError as exc:
            if getattr(exc, "winerror", None) == win32.ERROR_CANCELLED:
                raise AppError(
                    f"The elevation prompt for {exe.name} was declined. It appears on the secure "
                    "desktop, where a test cannot answer it: start the test runner from an "
                    "elevated terminal and no prompt is shown."
                ) from exc
            raise AppError(f"Could not start {exe} elevated: {exc}") from exc
        return _HandleProcess(handle, pid)

    def matches_process(self, name: str) -> bool:
        """Whether ``name`` (``notepad`` or ``notepad.exe``) is this application's exe."""
        __tracebackhide__ = True
        return _same_exe(self.process_name, name)

    # -- label steps: ``app.WPFObject("HwndSource: MainView", "Title*").Window("Edit")`` ---------

    def wpf_object(
        self,
        cls: str,
        text: str | int | None = None,
        index: int | None = None,
        *,
        strict: bool = False,
    ) -> BoundElement:
        """``WPFObject(cls, text, index)`` below the application: a window node.

        ``cls`` is ``"HwndSource: <label>"`` where ``<label>`` is the root visual's x:Name (its
        short type name when it has none); the type spelling of a window that has an x:Name
        resolves it too. ``text`` is the window title and ``index`` the 1-based position among the
        window nodes with that label. Chain the root visual and the objects below it:
        ``app.wpf_object("HwndSource: MainView").wpf_object("MainView")``.
        """
        __tracebackhide__ = True
        from wintestkit import finders

        return finders.wpf_object(self, cls, text, index, strict=strict)

    def window(
        self,
        cls: str,
        caption: str | int | None = "*",
        index: int | None = None,
        *,
        strict: bool = False,
    ) -> BoundElement:
        """``Window(cls, caption, index)``: a top-level window of the application."""
        __tracebackhide__ = True
        from wintestkit import finders

        return finders.window(self, cls, caption, index, strict=strict)

    #: The spelling of existing suites. An ``App`` also takes it because a ported chain starts at
    #: the process (``Sys.Process("x").WPFObject(...)``), which this object stands for.
    WPFObject = wpf_object
    Window = window

    # -- state ----------------------------------------------------------------------------------

    @property
    def pids(self) -> list[int]:
        """Live process ids belonging to the application."""
        __tracebackhide__ = True
        found: set[int] = set()
        if self._by_name:
            found.update(
                set(win32.pids_by_name(self.process_name)) - self._baseline - self._peer_pids()
            )
        if self._pinned_pid is not None and self._pinned_pid in dict(win32.list_processes()):
            found.add(self._pinned_pid)
        if self._popen is not None and self._popen.poll() is None:
            found.add(self._popen.pid)
        self._known_pids.update(found)
        return sorted(found)

    def _peer_pids(self) -> set[int]:
        """Processes of the same exe that belong to another launched instance of it."""
        __tracebackhide__ = True
        peers: set[int] = set()
        for other in list(_APPS):
            if other is self or not other.launched or not other.matches_process(self.process_name):
                continue
            peers |= other._known_pids
            if other._popen is not None:
                peers.add(other._popen.pid)
            if other._pinned_pid is not None:
                peers.add(other._pinned_pid)
        if self._popen is not None:
            peers.discard(self._popen.pid)
        if self._pinned_pid is not None:
            peers.discard(self._pinned_pid)
        return peers

    def is_running(self) -> bool:
        __tracebackhide__ = True
        return bool(self.pids)

    def ensure_drivable(self) -> None:
        """Raise :class:`ElevationError` when the application runs elevated and the runner does not.

        Windows (UIPI) lets a process send input and window messages to another one, and use UI
        Automation on it, only when its own integrity level is at least as high. Without this
        check such a test fails with timeouts and unexplained "not found" errors.
        """
        __tracebackhide__ = True
        pids = [pid for pid in self.pids if pid not in self._drivable]
        if not pids:
            return
        if not win32.current_process_is_elevated():
            for pid in pids:
                if win32.process_is_elevated(pid):
                    raise ElevationError(
                        f"{self.process_name} (pid {pid}) runs elevated and this test runner "
                        "does not. Windows (UIPI) blocks input, window messages and UI "
                        "Automation from a lower-integrity process, so it cannot be driven or "
                        "closed from here. Start the test runner from an elevated terminal "
                        "(or run the application without elevation)."
                    )
        self._drivable.update(pids)

    def top_level_windows(self) -> list[UIAElement]:
        """Visible top-level windows of the application in z-order (owned windows included).

        Uses ``EnumWindows`` rather than the UIA desktop root, whose children can take seconds to
        enumerate on machines with slow UIA providers.
        """
        __tracebackhide__ = True
        pids = set(self.pids)
        if not pids:
            return []
        self.ensure_drivable()
        windows: list[UIAElement] = []
        for hwnd in win32.top_level_windows(pids):
            try:
                windows.append(element.from_handle(hwnd))
            except UIAError:
                continue  # the window closed while enumerating
        return windows

    def _wait_for_window_change(self, deadline: float) -> None:
        __tracebackhide__ = True
        from wintestkit import runtime

        waiter = runtime.inspector_sessions().event_waiter_for_pids(set(self.pids))
        if waiter is None:
            time.sleep(_POLL_INTERVAL)
        else:
            waiter.wait(
                max(0.0, deadline - time.monotonic()),
                fallback=0.5,
                matches=lambda event: event.kind in {"windowOpened", "windowClosed"},
            )

    def main_window(self, timeout: float = 0.0) -> UIAElement:
        """The first unowned top-level ``Window`` in z-order; polls up to ``timeout`` seconds."""
        __tracebackhide__ = True
        deadline = time.monotonic() + timeout
        while True:
            if not self.is_running():
                raise AppNotRunningError(f"{self.process_name} is not running")
            self.ensure_drivable()
            for hwnd in win32.top_level_windows(set(self.pids)):
                if win32.window_owner(hwnd) != 0:
                    continue
                try:
                    window = element.from_handle(hwnd)
                    if window.control_type == "Window":
                        if self._startup_complete:
                            from wintestkit.inspector.probe import current_identity

                            if (
                                not self._inspector_identities
                                or current_identity(window.process_id)
                                not in self._inspector_identities
                            ):
                                self._attach_window(window, time.monotonic() + max(timeout, 10.0))
                        return window
                except UIAError:
                    continue
            if time.monotonic() >= deadline:
                break
            self._wait_for_window_change(deadline)
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
        """Ask every window to close; force termination only for launched instances."""
        __tracebackhide__ = True
        self.detach_inspector()
        windows = self.top_level_windows()
        windows.sort(key=lambda w: 0 if win32.window_owner(w.native_window_handle) else 1)
        for window in windows:
            try:
                patterns.window_close(window)
            except (ActionError, UIAError):
                win32.PostMessageW(window.native_window_handle, win32.WM_CLOSE, 0, 0)
            time.sleep(0.05)
        if not self.wait_for_exit(timeout):
            if self.launched:
                log.warning("%s did not exit within %.1fs; killing it", self.process_name, timeout)
                self.kill()
            else:
                log.warning("%s did not exit within %.1fs", self.process_name, timeout)

    def request_close(self, method: CloseMethod = "wm_close") -> None:
        """Ask the main window to close and return at once, without waiting for the app to exit.

        ``"wm_close"`` posts ``WM_CLOSE`` to the main window, which works without the window being
        in front. ``"alt_f4"`` activates the window and presses Alt+F4, as a user would; it
        refuses when the window cannot be brought to the foreground, because the keys would go
        elsewhere. The application may answer with a prompt ("save changes?"); see
        :meth:`close_gracefully`.
        """
        __tracebackhide__ = True
        self._post_close(self.main_window().native_window_handle, method)

    def _post_close(self, hwnd: int, method: CloseMethod) -> None:
        __tracebackhide__ = True
        if method == "wm_close":
            win32.PostMessageW(hwnd, win32.WM_CLOSE, 0, 0)
        elif method == "alt_f4":
            from wintestkit.uia import input as uia_input

            win32.bring_to_foreground(hwnd)
            foreground = win32.GetForegroundWindow()
            if not foreground or win32.window_pid(foreground) not in set(self.pids):
                raise ActionError(
                    f"The main window of {self.process_name} could not be brought to the "
                    "foreground, so Alt+F4 would go to another window. Use method='wm_close'."
                )
            uia_input.press("Alt+F4")
        else:
            raise ValueError(f"unknown close method {method!r}; use 'wm_close' or 'alt_f4'")

    def close_gracefully(
        self,
        *,
        method: CloseMethod = "wm_close",
        on_prompt: Callable[[App], None] | None = None,
        prompt_timeout: float = 3.0,
        exit_timeout: float = 30.0,
        kill: bool = False,
    ) -> CloseOutcome:
        """Close the application the way a user does, answering a prompt it raises, then wait.

        The main window is asked to close (``method``, see :meth:`request_close`). With
        ``on_prompt``, the call waits up to ``prompt_timeout`` seconds for a window that was not
        there before ("save changes?") and calls ``on_prompt(app)`` once it shows; the callback
        answers it with the usual pages and clicks. Then it waits up to ``exit_timeout`` seconds
        for every process to exit. With ``kill=True`` a process that is still there is killed.

        Returns ``"exited"`` (it closed by itself), ``"killed"`` or ``"running"`` (still there:
        nothing was forced), which a test usually asserts. Unlike :meth:`close` it asks the main
        window only and never force-kills unless told to, whoever launched the app.
        """
        __tracebackhide__ = True
        from wintestkit import runtime

        args = {"method": method, "prompt_timeout": prompt_timeout, "exit_timeout": exit_timeout}
        with runtime.step("app.close", self.process_name, method, args) as record:
            hwnd = self.main_window().native_window_handle
            before = set(win32.top_level_windows(set(self.pids)))
            self._post_close(hwnd, method)
            if on_prompt is not None:
                prompted = self._wait_for_prompt(before, prompt_timeout)
                record.args["prompt"] = prompted
                if prompted:
                    on_prompt(self)
            outcome: CloseOutcome = "exited"
            if not self.wait_for_exit(exit_timeout):
                outcome = "running"
                if kill:
                    self.kill()
                    outcome = "killed" if not self.is_running() else "running"
            record.args["outcome"] = outcome
            if outcome != "running":
                self.detach_inspector()
            return outcome

    def _wait_for_prompt(self, before: set[int], timeout: float) -> bool:
        """Wait up to ``timeout`` seconds for a window that was not open before; ``False`` if the
        application exits or none shows."""
        __tracebackhide__ = True
        deadline = time.monotonic() + timeout
        while self.is_running():
            if set(win32.top_level_windows(set(self.pids))) - before:
                return True
            if time.monotonic() >= deadline:
                break
            time.sleep(0.05)
        return False

    def detach_inspector(self) -> None:
        """Release inspector sessions without closing the application."""
        __tracebackhide__ = True
        from wintestkit import runtime

        runtime.detach_inspector_pids(set(self.pids) | self._known_pids)
        for identity in self._inspector_identities:
            runtime.detach_inspector(identity)
        self._inspector_identities.clear()

    def kill(self) -> None:
        """Forcefully terminate every process of the application (and their children).

        Every process of the exe name, whoever started it, so it also stops a helper that a test
        attached to by name (``finders.process("helper.exe").kill()``).
        """
        __tracebackhide__ = True
        pids = self.pids
        for pid in pids:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
        self.wait_for_exit(5.0)
        if self._popen is not None:
            self._popen.poll()
        if pids and self.is_running():
            self.ensure_drivable()  # a refused kill of an elevated process says why
        self.detach_inspector()

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

    def _wait_for_startup(
        self, startup_timeout: float, progress: Callable[[str], None] | None = None
    ) -> None:
        __tracebackhide__ = True
        assert self._popen is not None
        deadline = time.monotonic() + startup_timeout
        self._wait_for_input_idle(self._popen.pid, min(10.0, startup_timeout))
        if progress is not None:
            progress("window")
        while True:
            try:
                window = self.main_window()
                self._attach_window(window, deadline)
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
            self._wait_for_window_change(deadline)

    def _attach_window(self, window: UIAElement, deadline: float) -> None:
        __tracebackhide__ = True
        from wintestkit import runtime

        identity = runtime.attach_on_launch(window, deadline=deadline)
        self._startup_complete = True
        if identity is not None:
            for old in self._inspector_identities - {identity}:
                runtime.detach_inspector(old)
            self._inspector_identities = {identity}

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


class Apps:
    """The applications a test starts or attaches to besides the main one, released together.

    Use it through the ``apps`` fixture, or as a context manager: everything launched through it is
    closed (and killed when it will not close) and everything attached is released, last first,
    when the test ends. Each application has its own pages and inspector sessions::

        def test_two_apps(app, apps):
            helper = apps.launch(HELPER_EXE, args=["--port", "9"])
            viewer = apps.attach("explorer.exe")
            main = MainPage(app)
            tool = ToolPage(helper)
    """

    def __init__(self, close_timeout: float = 10.0) -> None:
        __tracebackhide__ = True
        self.close_timeout = close_timeout
        self._apps: list[App] = []

    def launch(
        self,
        path: str | Path,
        args: Sequence[str] = (),
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        process: str | None = None,
        startup_timeout: float = 30.0,
        owned_only: bool = True,
        elevated: bool = False,
    ) -> App:
        """:meth:`App.launch` as a report step. ``owned_only`` defaults to ``True`` so that two
        launches of the same exe (with different ``args``) never see each other's processes."""
        __tracebackhide__ = True
        from wintestkit import runtime

        with runtime.step("app.start", process or Path(path).name, str(path)):
            app = App.launch(
                path,
                args,
                cwd=cwd,
                env=env,
                process=process,
                startup_timeout=startup_timeout,
                owned_only=owned_only,
                elevated=elevated,
            )
        self._apps.append(app)
        return app

    def attach(self, process: str | None = None, pid: int | None = None) -> App:
        """:meth:`App.attach` as a report step; the application is only released at the end."""
        __tracebackhide__ = True
        from wintestkit import runtime

        with runtime.step("app.attach", process or f"pid {pid}", process or ""):
            app = App.attach(process=process, pid=pid)
        self._apps.append(app)
        return app

    def close_all(self) -> None:
        """Close what was launched, release what was attached; every one is tried, the first
        failure is raised at the end."""
        __tracebackhide__ = True
        failure: BaseException | None = None
        while self._apps:
            app = self._apps.pop()
            try:
                if app.launched:
                    app.close(timeout=self.close_timeout)
                else:
                    app.detach_inspector()
            except Exception as exc:
                log.warning("could not close %s: %s", app.process_name, exc)
                failure = failure or exc
        if failure is not None:
            raise failure

    def __enter__(self) -> Apps:
        __tracebackhide__ = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        __tracebackhide__ = True
        self.close_all()
