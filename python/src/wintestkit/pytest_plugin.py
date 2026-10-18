"""pytest plugin: options, fixtures, application lifecycle, failure artifacts, event stream.

The plugin is loaded for every pytest run once ``wintestkit`` is installed, so it must stay
inert for projects that do not use WinTestKit: nothing heavy is imported at module level, and the
hook implementations live on a controller object that is only registered when the project has a
``[tool.wintestkit]`` table, a ``WTK_*`` environment variable is set, or a ``--wtk-*`` option was
passed.
"""

from __future__ import annotations

import contextlib
import dataclasses
import logging
import os
import time
from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from wintestkit import __version__, runtime
from wintestkit import artifacts as artifact_files
from wintestkit.config import (
    INPUT_MODES,
    LAUNCH_MODES,
    SCREENSHOT_MODES,
    WtkConfig,
    find_project_root,
    load_config,
)
from wintestkit.errors import ConfigError, WtkError
from wintestkit.events import EventSink, open_sink
from wintestkit.report.html import write_report
from wintestkit.report.results import RunRecorder, prepare_directory
from wintestkit.trace import TraceRecorder

if TYPE_CHECKING:
    from wintestkit.app import App

log = logging.getLogger("wintestkit.pytest")

_MARKER_KEYS = {"launch", "timeout"}
_MAX_MESSAGE = 2000
_ENV_VARS = (
    "WTK_APP_PATH",
    "WTK_LAUNCH",
    "WTK_TIMEOUT",
    "WTK_INPUT_MODE",
    "WTK_SCREENSHOTS",
    "WTK_TRACE",
    "WTK_TRACE_FPS",
    "WTK_TRACE_SCOPE",
    "WTK_TRACE_MAX_FRAMES",
    "WTK_TRACE_MAX_BYTES",
)


def _funcarg(item: Any, name: str) -> Any:
    """A fixture value already set up for ``item`` (``None`` when not requested)."""
    funcargs: dict[str, Any] = getattr(item, "funcargs", None) or {}
    return funcargs.get(name)


def _marker_kwargs(node: Any, name: str) -> dict[str, Any]:
    marker: Any = node.get_closest_marker(name)
    return dict(marker.kwargs) if marker is not None else {}


def launch_app(config: WtkConfig, progress: Callable[[str], None] | None = None) -> App:
    """Start the application described by ``[tool.wintestkit.app]``.

    Launching owns the application's lifecycle: a copy that is already running is closed first, so
    the tests get a fresh one and nothing is left running once the launched app is closed.
    ``progress`` reports the launch stages (see :meth:`App.launch`).
    """
    from wintestkit.app import App
    from wintestkit.errors import AppNotRunningError
    from wintestkit.uia import win32

    settings = config.app
    if settings is None or settings.path is None:
        raise ConfigError(
            "no application to launch: set path in [tool.wintestkit.app] (or pass --wtk-app PATH)",
            key="app.path",
        )
    name = settings.process or Path(settings.path).name
    if win32.pids_by_name(name):
        log.info("closing the running %s before launching a fresh copy", name)
        with contextlib.suppress(AppNotRunningError):  # it may exit on its own meanwhile
            App.attach(process=name).close(timeout=settings.close_timeout)
    return App.launch(
        settings.path,
        args=settings.args,
        cwd=settings.cwd,
        env=settings.env,
        process=settings.process,
        startup_timeout=settings.startup_timeout,
        progress=progress,
    )


class _SessionApp:
    """Launches the application once per session and relaunches it if a test killed it."""

    def __init__(self) -> None:
        self.app: App | None = None

    def get(self, config: WtkConfig) -> App:
        if self.app is None or not self.app.is_running():
            self.app = launch_app(config)
        return self.app

    def close(self, config: WtkConfig) -> None:
        if self.app is not None and self.app.launched and self.app.is_running():
            self.app.close(timeout=config.app.close_timeout if config.app else 10.0)
        self.app = None


# -- options and configuration --------------------------------------------------------------------

_OPTION_TO_KEY = {
    "wtk_launch": "launch",
    "wtk_timeout": "timeout",
    "wtk_app": "app.path",
    "wtk_input_mode": "input_mode",
    "wtk_screenshots": "screenshots",
    "wtk_highlight": "highlight_actions",
    "wtk_slowmo": "slow_mo_ms",
    "wtk_report": "report_dir",
    "wtk_trace": "trace",
    "wtk_trace_fps": "trace_fps",
    "wtk_trace_scope": "trace_scope",
}


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("wintestkit", "WinTestKit UI test automation")
    group.addoption("--wtk-launch", choices=LAUNCH_MODES, help="how to get the application")
    group.addoption("--wtk-timeout", type=float, metavar="SECONDS", help="default auto-wait")
    group.addoption("--wtk-app", metavar="PATH", help="path of the application executable")
    group.addoption("--wtk-input-mode", choices=INPUT_MODES, help="default click strategy")
    group.addoption("--wtk-screenshots", choices=SCREENSHOT_MODES, help="when to capture screens")
    group.addoption(
        "--wtk-trace", choices=("off", "on", "retain-on-failure"), help="record a trace"
    )
    group.addoption("--wtk-trace-fps", type=float, help="target trace frames per second (up to 30)")
    group.addoption("--wtk-trace-scope", choices=("window", "desktop"), help="trace capture area")
    group.addoption(
        "--wtk-highlight", action="store_true", default=None, help="flash elements before acting"
    )
    group.addoption("--wtk-slowmo", type=int, metavar="MS", help="pause after every action")
    group.addoption("--wtk-report", metavar="DIR", help="report directory")
    group.addoption("--wtk-no-report", action="store_true", help="do not write a report")
    group.addoption(
        "--wtk-events", metavar="URL", help="stream run events: tcp://HOST:PORT or file"
    )


def _overrides(config: pytest.Config) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for option, key in _OPTION_TO_KEY.items():
        value = config.getoption(option, None)
        if value is not None:
            overrides[key] = value
    return overrides


def _load(config: pytest.Config) -> WtkConfig:
    try:
        return load_config(config.rootpath, _overrides(config))
    except ConfigError as exc:
        raise pytest.UsageError(str(exc)) from exc


def _is_wintestkit_run(config: pytest.Config) -> bool:
    return (
        bool(_overrides(config))
        or bool(config.getoption("wtk_no_report", False))
        or bool(config.getoption("wtk_events", None))
        or any(os.environ.get(name) for name in _ENV_VARS)
        or find_project_root(config.rootpath) is not None
    )


CONTROLLER_KEY = pytest.StashKey["_Controller"]()


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "wtk(launch=None, timeout=None): override the WinTestKit launch mode or default "
        "timeout for one test",
    )
    if not _is_wintestkit_run(config):
        return  # not a WinTestKit project: stay inert
    controller = _Controller(config)
    config.stash[CONTROLLER_KEY] = controller
    config.pluginmanager.register(controller, "wintestkit-controller")


def pytest_unconfigure(config: pytest.Config) -> None:
    controller = config.stash.get(CONTROLLER_KEY, None)
    if controller is not None:
        controller.close()


# -- the controller: per-run state and hook implementations ---------------------------------------


@dataclass
class _Run:
    """What is known about one test, accumulated over its setup/call/teardown phases."""

    nodeid: str
    reports: dict[str, pytest.TestReport] = field(default_factory=lambda: {})
    exceptions: dict[str, pytest.ExceptionInfo[BaseException]] = field(default_factory=lambda: {})
    artifacts: artifact_files.ArtifactSet | None = None
    step_screenshots: list[Path] = field(default_factory=lambda: [])
    trace: TraceRecorder | None = None


@dataclass
class _Finished:
    nodeid: str
    outcome: str
    duration: float


class _Controller:
    """Hook implementations for one pytest run (registered only for WinTestKit projects)."""

    def __init__(self, config: pytest.Config) -> None:
        self.pytest_config = config
        self.config: WtkConfig = _load(config)
        runtime.set_config(self.config)
        self.sink: EventSink | None = None
        events_url = config.getoption("wtk_events", None)
        if events_url:
            try:
                self.sink = open_sink(events_url)
            except (OSError, ValueError) as exc:
                raise pytest.UsageError(f"--wtk-events: {exc}") from exc
        self.started = time.time()
        self.recorder = RunRecorder(self.config.report_dir)
        self.report_enabled = not config.getoption("wtk_no_report", False)
        self.report_path: str | None = None
        self.session_app = _SessionApp()
        self.runs: dict[str, _Run] = {}
        self.finished: list[_Finished] = []
        self.collect_errors: list[dict[str, str]] = []
        self.current: pytest.Item | None = None
        self.restore_timeout: float | None = None
        self.remove_listener = runtime.add_step_listener(self._on_step)

    def close(self) -> None:
        self.remove_listener()
        for run in self.runs.values():
            if run.trace is not None:
                run.trace.stop()
        if self.sink is not None:
            self.sink.close()
            self.sink = None

    # -- events ---------------------------------------------------------------------------------

    def _emit(self, event: dict[str, Any]) -> None:
        event = {**event, "time": time.time()}
        self.recorder.record(event)
        if self.sink is not None:
            self.sink.emit(event)

    @staticmethod
    def _posix(path: str | Path) -> str:
        return Path(path).as_posix()

    def pytest_sessionstart(self, session: pytest.Session) -> None:
        self.started = time.time()
        if self.report_enabled:
            prepare_directory(self.config.report_dir)
        self._emit(
            {
                "event": "session_start",
                "root": self._posix(self.config.root),
                "pid": os.getpid(),
                "wintestkitVersion": __version__,
            }
        )

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        if not report.failed:
            return
        lines = report.longreprtext.strip().splitlines() if report.longreprtext else []
        file = self.pytest_config.rootpath / report.nodeid.split("::", 1)[0]
        self.collect_errors.append(
            {"file": self._posix(file), "message": lines[-1] if lines else "collection error"}
        )

    @staticmethod
    def _parent_id(item: pytest.Item) -> str | None:
        if hasattr(item, "callspec"):
            return item.nodeid.split("[", 1)[0]
        if isinstance(item.parent, pytest.Class):
            return item.parent.nodeid
        return None

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        tests = [
            {
                "id": item.nodeid,
                "file": self._posix(item.path),
                "line": item.location[1] if item.location[1] is not None else 0,
                "name": item.name,
                "parent": self._parent_id(item),
            }
            for item in session.items
        ]
        self._emit({"event": "collected", "tests": tests, "errors": list(self.collect_errors)})

    def pytest_runtest_logstart(self, nodeid: str, location: tuple[str, int | None, str]) -> None:
        self._emit({"event": "test_start", "id": nodeid})

    def _on_step(self, record: runtime.StepRecord) -> None:
        test_id = runtime.current_test()
        if not test_id:
            return
        run = self.runs.get(test_id)
        if run is not None and run.trace is not None:
            if run.trace.window is None and self.current is not None:
                self._trace_window(run.trace, _funcarg(self.current, "app"))
            run.trace.request_frame()
        if self.config.screenshots == "every-step" and self.current is not None:
            app = _funcarg(self.current, "app")
            directory = artifact_files.artifacts_dir(self.config.report_dir, test_id)
            path = artifact_files.capture_step_screenshot(app, directory, record.seq)
            if path is not None:
                record.screenshot = artifact_files.relative_to_report(path, self.config.report_dir)
                run = self.runs.get(test_id)
                if run is not None:
                    run.step_screenshots.append(path)
        self._emit({"event": "step", "id": test_id, "step": record.to_dict()})

    # -- per-test lifecycle ---------------------------------------------------------------------

    @pytest.hookimpl(tryfirst=True)
    def pytest_runtest_setup(self, item: pytest.Item) -> None:
        runtime.begin_test(item.nodeid)
        self.current = item
        self.runs[item.nodeid] = _Run(item.nodeid)
        if self.report_enabled and self.config.trace != "off":
            trace = TraceRecorder(
                artifact_files.artifacts_dir(self.config.report_dir, item.nodeid),
                self.config.report_dir,
                fps=self.config.trace_fps,
                scope=self.config.trace_scope,
                max_frames=self.config.trace_max_frames,
                max_bytes=self.config.trace_max_bytes,
            )
            self.runs[item.nodeid].trace = trace
            trace.start()
        marker = item.get_closest_marker("wtk")
        if marker is None:
            return
        unknown = set(marker.kwargs) - _MARKER_KEYS
        if unknown:
            raise ConfigError(
                f"unknown wtk marker argument(s): {', '.join(sorted(unknown))}; "
                f"allowed: {', '.join(sorted(_MARKER_KEYS))}"
            )
        timeout = marker.kwargs.get("timeout")
        if timeout is not None:
            current = runtime.get_config()
            self.restore_timeout = current.timeout
            runtime.set_config(dataclasses.replace(current, timeout=float(timeout)))

    @staticmethod
    def _trace_window(trace: TraceRecorder, app: Any) -> None:
        if app is None or trace.scope != "window":
            return
        try:
            trace.set_window(int(app.main_window().native_window_handle))
        except Exception as exc:
            log.debug("trace window not available: %s", exc)

    @pytest.hookimpl(hookwrapper=True)
    def pytest_fixture_setup(
        self, fixturedef: pytest.FixtureDef[Any], request: pytest.FixtureRequest
    ) -> Generator[None, Any, None]:
        outcome = yield
        if fixturedef.argname != "app" or outcome.excinfo is not None:
            return
        run = self.runs.get(self.current.nodeid) if self.current is not None else None
        if run is not None and run.trace is not None:
            self._trace_window(run.trace, outcome.get_result())

    @pytest.hookimpl(trylast=True)
    def pytest_runtest_teardown(self, item: pytest.Item, nextitem: pytest.Item | None) -> None:
        runtime.end_test()
        if self.restore_timeout is not None:
            restored = dataclasses.replace(runtime.get_config(), timeout=self.restore_timeout)
            runtime.set_config(restored)
            self.restore_timeout = None

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(
        self, item: pytest.Item, call: pytest.CallInfo[None]
    ) -> Generator[None, Any, None]:
        outcome = yield
        report: pytest.TestReport = outcome.get_result()
        run = self.runs.setdefault(item.nodeid, _Run(item.nodeid))
        if report.when == "setup" and run.trace is not None:
            self._trace_window(run.trace, _funcarg(item, "app"))
        if call.excinfo is not None:
            run.exceptions[report.when or "call"] = call.excinfo
        if report.when == "call" and report.passed:
            # Retain only the latest bounded passing tree; report directory cleanup deliberately
            # leaves this single baseline in place between runs.
            tree = artifact_files.capture_tree_text(_funcarg(item, "app"))
            if tree is not None:
                baseline = self.config.report_dir / "ui-tree-baseline.txt"
                baseline.write_text(tree, encoding="utf-8")
        if not report.failed or report.when == "teardown" or self.config.screenshots == "off":
            return
        directory = artifact_files.artifacts_dir(self.config.report_dir, item.nodeid)
        app = _funcarg(item, "app")
        captured = artifact_files.capture_failure(app, directory)
        if captured.tree_dump is not None:
            baseline = self.config.report_dir / "ui-tree-baseline.txt"
            diff_path = directory / "tree-diff.txt"
            if artifact_files.write_tree_diff(baseline, captured.tree_dump, diff_path):
                captured.tree_diff = diff_path
        run.artifacts = captured
        item.stash[ARTIFACTS_KEY] = captured
        names = ", ".join(path.name for path in captured.screenshots) or "none"
        report.sections.append(
            ("wintestkit", f"artifacts: {directory.as_posix()} (screenshots: {names})")
        )

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        run = self.runs.setdefault(report.nodeid, _Run(report.nodeid))
        run.reports[report.when or "call"] = report
        if report.when != "teardown":
            return
        outcome = _outcome(run)
        duration = sum(r.duration for r in run.reports.values())
        self.finished.append(_Finished(report.nodeid, outcome, duration))
        # pytest accumulates captured sections on the item, so the teardown report already
        # contains the output of the setup and call phases.
        for stream, text in (
            ("stdout", report.capstdout),
            ("stderr", report.capstderr),
            ("log", report.caplog),
        ):
            if text:
                self._emit(
                    {"event": "test_output", "id": report.nodeid, "stream": stream, "text": text}
                )
        paths = (run.artifacts.screenshots if run.artifacts else []) + run.step_screenshots
        event: dict[str, Any] = {
            "event": "test_end",
            "id": report.nodeid,
            "outcome": outcome,
            "duration": duration,
            "screenshots": [self._posix(p) for p in paths],
        }
        if run.trace is not None:
            discard = self.config.trace == "retain-on-failure" and outcome not in (
                "failed",
                "error",
            )
            trace_result = run.trace.stop(discard=discard)
            if not discard:
                event["trace"] = trace_result
        exc = _failure_exception(run)
        if exc is not None:
            event["message"] = _message(exc)
            if isinstance(exc, WtkError):
                event["error"] = exc.to_dict()
        location = _location(run, self.config.root)
        if location is not None:
            event["location"] = location
        if run.artifacts is not None:
            event["artifactsDir"] = self._posix(run.artifacts.directory)
            if run.artifacts.tree_diff is not None:
                event["treeDiff"] = self._posix(run.artifacts.tree_diff)
        self._emit(event)

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        counts = {"passed": 0, "failed": 0, "skipped": 0, "error": 0}
        for finished in self.finished:
            counts[finished.outcome] += 1
        event: dict[str, Any] = {
            "event": "session_end",
            "exitCode": int(exitstatus),
            "summary": {
                "total": len(self.finished),
                "passed": counts["passed"],
                "failed": counts["failed"],
                "skipped": counts["skipped"],
                "errors": counts["error"],
                "duration": time.time() - self.started,
            },
        }
        if self.report_enabled:
            event["reportPath"] = self._posix((self.config.report_dir / "index.html").resolve())
        junit = self.pytest_config.getoption("xmlpath", None)
        if junit:
            event["junitPath"] = self._posix(Path(str(junit)).resolve())
        self._emit(event)
        if self.report_enabled:
            write_report(self.config.report_dir, self.recorder.results())
            self.report_path = str(event["reportPath"])

    def pytest_terminal_summary(self, terminalreporter: Any) -> None:
        if self.report_path:
            terminalreporter.write_line(f"Report: {self.report_path}")


ARTIFACTS_KEY = pytest.StashKey[artifact_files.ArtifactSet]()


def _outcome(run: _Run) -> str:
    setup, call, teardown = (run.reports.get(name) for name in ("setup", "call", "teardown"))
    if setup is not None and setup.failed:
        return "error"
    if setup is not None and setup.skipped:
        return "skipped"
    if call is None:
        return "skipped"
    if call.failed:
        return "failed"
    if teardown is not None and teardown.failed:
        return "error"
    return "skipped" if call.skipped else "passed"


def _failure_exception(run: _Run) -> BaseException | None:
    for phase in ("setup", "call", "teardown"):
        report = run.reports.get(phase)
        info = run.exceptions.get(phase)
        if report is not None and report.failed and info is not None:
            return info.value
    return None


def _message(exc: BaseException) -> str:
    text = str(exc) if isinstance(exc, AssertionError | WtkError) else repr(exc)
    return text if len(text) <= _MAX_MESSAGE else text[: _MAX_MESSAGE - 1] + "…"


def _location(run: _Run, root: Path) -> dict[str, Any] | None:
    """Deepest traceback frame inside the project (not in wintestkit or site-packages)."""
    package_dir = Path(__file__).resolve().parent
    resolved_root = root.resolve()
    for phase in ("setup", "call", "teardown"):
        report = run.reports.get(phase)
        info = run.exceptions.get(phase)
        if report is None or not report.failed or info is None:
            continue
        for entry in reversed(list(info.traceback)):
            try:
                path = Path(str(entry.path)).resolve()
            except OSError:
                continue
            if "site-packages" in path.parts or package_dir in path.parents:
                continue
            if resolved_root in path.parents:
                return {"file": path.as_posix(), "line": entry.lineno}
    return None


# -- fixtures -------------------------------------------------------------------------------------


def _effective_config(request: pytest.FixtureRequest) -> WtkConfig:
    controller = request.config.stash.get(CONTROLLER_KEY, None)
    if controller is not None:
        return controller.config
    config = _load(request.config)
    runtime.set_config(config)
    return config


@pytest.fixture(scope="session")
def wtk_config(request: pytest.FixtureRequest) -> WtkConfig:
    """The effective WinTestKit configuration."""
    return _effective_config(request)


@pytest.fixture(scope="session")
def _wtk_session_app(request: pytest.FixtureRequest) -> Generator[_SessionApp, None, None]:
    holder = _SessionApp()
    yield holder
    holder.close(_effective_config(request))


@pytest.fixture
def app(
    request: pytest.FixtureRequest, _wtk_session_app: _SessionApp
) -> Generator[App, None, None]:
    """The application under test, launched or attached according to the launch mode."""
    from wintestkit.app import App

    config = _effective_config(request)
    node: Any = request.node  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    mode: Any = _marker_kwargs(node, "wtk").get("launch", config.launch)
    if mode not in LAUNCH_MODES:
        raise ConfigError(f"invalid launch mode {mode!r} in the wtk marker", key="launch")
    if mode == "attach":
        if config.app is None:
            raise ConfigError("no application to attach to: set [tool.wintestkit.app]", key="app")
        yield App.attach(process=config.app.process_name)
    elif mode == "per-session":
        yield _wtk_session_app.get(config)
    else:
        launched = launch_app(config)
        try:
            yield launched
        finally:
            launched.close(timeout=config.app.close_timeout if config.app else 10.0)


@pytest.fixture
def page(app: App) -> Callable[[type[Any]], Any]:
    """Factory binding a ``Page`` subclass to the application: ``page(MainPage)``."""

    def make(page_class: type[Any]) -> Any:
        return page_class(app)

    return make
