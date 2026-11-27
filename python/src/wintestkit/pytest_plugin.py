"""pytest plugin: options, fixtures, application lifecycle, failure artifacts, event stream.

The plugin is loaded for every pytest run once ``wintestkit`` is installed, so it must stay
inert for projects that do not use WinTestKit: nothing heavy is imported at module level, and the
hook implementations live on a controller object that is only registered when the project has a
``[tool.wintestkit]`` table, a ``WTK_*`` environment variable is set, or a ``--wtk-*`` option was
passed.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import subprocess
import time
from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from wintestkit import __version__, runtime
from wintestkit import artifacts as artifact_files
from wintestkit.config import (
    ACTIONABILITY_MODES,
    INPUT_MODES,
    LAUNCH_MODES,
    SCREENSHOT_MODES,
    WtkConfig,
    find_project_root,
    load_config,
)
from wintestkit.errors import (
    AppError,
    AppNotRunningError,
    AttachNotRunningError,
    ConfigError,
    WtkError,
)
from wintestkit.events import EventSink, open_sink
from wintestkit.replay import ReplayRecorder
from wintestkit.report.html import write_report
from wintestkit.report.results import RunRecorder, prepare_directory

if TYPE_CHECKING:
    from wintestkit.app import App, Apps

log = logging.getLogger("wintestkit.pytest")

_MARKER_KEYS = {"launch", "timeout", "actionability", "soft"}
_MAX_MESSAGE = 2000
_ENV_VARS = (
    "WTK_APP_PATH",
    "WTK_LAUNCH",
    "WTK_TIMEOUT",
    "WTK_INPUT_MODE",
    "WTK_ACTIONABILITY",
    "WTK_SCREENSHOTS",
    "WTK_REPLAY",
    "WTK_REPLAY_FPS",
    "WTK_REPLAY_SCOPE",
    "WTK_REPLAY_MAX_FRAMES",
    "WTK_REPLAY_MAX_BYTES",
    "WTK_OBJECT_PREVIEWS",
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

    A copy that is already running was not started by WinTestKit, so it is never closed or killed:
    the returned :class:`App` is attached to it and has ``launched == False``. Only with
    ``app.close_existing`` is it asked to close gracefully first; if it does not close (for example
    a save prompt), launching fails instead of force-killing it. ``progress`` reports the launch
    stages (see :meth:`App.launch`).
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
        try:
            existing = App.attach(process=name)
        except AppNotRunningError:
            pass  # It exited during discovery.
        else:
            if not settings.close_existing:
                return existing
            existing.close(timeout=settings.close_timeout)
            if existing.is_running():
                raise AppError(f"{name} did not close; resolve its prompt before launching")
    return App.launch(
        settings.path,
        args=settings.args,
        cwd=settings.cwd,
        env=settings.env,
        process=settings.process,
        startup_timeout=settings.startup_timeout,
        progress=progress,
        owned_only=True,
        elevated=settings.elevated,
    )


# -- options and configuration --------------------------------------------------------------------

_OPTION_TO_KEY = {
    "wtk_launch": "launch",
    "wtk_timeout": "timeout",
    "wtk_app": "app.path",
    "wtk_input_mode": "input_mode",
    "wtk_actionability": "actionability",
    "wtk_screenshots": "screenshots",
    "wtk_highlight": "highlight_actions",
    "wtk_slowmo": "slow_mo_ms",
    "wtk_report": "report_dir",
    "wtk_replay": "replay",
    "wtk_replay_fps": "replay_fps",
    "wtk_replay_scope": "replay_scope",
}


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("wintestkit", "WinTestKit UI test automation")
    group.addoption("--wtk-launch", choices=LAUNCH_MODES, help="how to get the application")
    group.addoption("--wtk-timeout", type=float, metavar="SECONDS", help="default auto-wait")
    group.addoption("--wtk-app", metavar="PATH", help="path of the application executable")
    group.addoption("--wtk-input-mode", choices=INPUT_MODES, help="default click strategy")
    group.addoption(
        "--wtk-actionability",
        choices=ACTIONABILITY_MODES,
        help="what actions wait for: the element to exist, or also to be enabled and visible",
    )
    group.addoption("--wtk-screenshots", choices=SCREENSHOT_MODES, help="when to capture screens")
    group.addoption(
        "--wtk-replay", choices=("off", "on", "retain-on-failure"), help="record a test replay"
    )
    group.addoption(
        "--wtk-replay-fps", type=float, help="target replay frames per second (up to 30)"
    )
    group.addoption("--wtk-replay-scope", choices=("window", "desktop"), help="replay capture area")
    group.addoption(
        "--wtk-highlight", action="store_true", default=None, help="flash elements before acting"
    )
    group.addoption("--wtk-slowmo", type=int, metavar="MS", help="pause after every action")
    group.addoption("--wtk-report", metavar="DIR", help="report directory")
    group.addoption(
        "--wtk-no-report",
        action="store_true",
        help="disable reports and automatic screenshots, replay, and object previews",
    )
    group.addoption(
        "--wtk-no-html", action="store_true", help="write results.json but not the HTML report"
    )
    group.addoption(
        "--wtk-ui-tree-diff", action="store_true", help="retain bounded per-test UI tree baselines"
    )
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
_EXISTING_APP = pytest.StashKey["App"]()


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "wtk(launch=None, timeout=None, actionability=None, soft=False): override the WinTestKit "
        "launch mode, default timeout or action waiting for one test; soft=True makes every "
        "expect() failure soft (the test continues and fails at its end)",
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


# -- soft errors: the test carries on after them and fails when it ends ---------------------------
#
# These hooks cost nothing when no error was recorded, so they run for every project.


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    from wintestkit import soft

    soft.clear()


def _soft_marker(item: pytest.Item) -> bool:
    marker = item.get_closest_marker("wtk")
    return marker is not None and bool(marker.kwargs.get("soft"))


def _finish_soft(failure: BaseException | None) -> None:
    """End of a phase: raise the soft errors, or list them on the failure the phase already has.

    A phase that was skipped or interrupted drops them: they belong to a test that did not finish.
    """
    __tracebackhide__ = True
    from wintestkit import soft

    found = soft.drain()
    if not found:
        return
    if failure is None:
        raise soft.SoftErrorsFailure(found)
    if isinstance(failure, Exception | pytest.fail.Exception):
        failure.add_note(soft.failure_message(found))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item: pytest.Item) -> Generator[None, Any, Any]:
    """Fail the test, with every soft error listed, when its body is done."""
    __tracebackhide__ = True
    from wintestkit import soft

    try:
        with soft.continue_on_error(_soft_marker(item)):
            result = yield
    except BaseException as exc:
        _finish_soft(exc)
        raise
    _finish_soft(None)
    return result


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(
    item: pytest.Item, nextitem: pytest.Item | None
) -> Generator[None, Any, Any]:
    """Also fail for errors recorded after the body, by fixture finalizers."""
    __tracebackhide__ = True
    try:
        result = yield
    except BaseException as exc:
        _finish_soft(exc)
        raise
    _finish_soft(None)
    return result


# -- the controller: per-run state and hook implementations ---------------------------------------


@dataclass
class _Run:
    """What is known about one test, accumulated over its setup/call/teardown phases."""

    nodeid: str
    reports: dict[str, pytest.TestReport] = field(default_factory=lambda: {})
    exceptions: dict[str, pytest.ExceptionInfo[BaseException]] = field(default_factory=lambda: {})
    artifacts: artifact_files.ArtifactSet | None = None
    tree_baseline: str | None = None
    step_screenshots: list[Path] = field(default_factory=lambda: [])
    replay: ReplayRecorder | None = None
    warnings: list[str] = field(default_factory=lambda: [])


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
        runtime.clear_inspector_history()
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
        self.write_html = not config.getoption("wtk_no_html", False)
        self.report_path: str | None = None
        self.runs: dict[str, _Run] = {}
        self.finished: list[_Finished] = []
        self.collect_errors: list[dict[str, str]] = []
        self.current: pytest.Item | None = None
        self.restore_config: WtkConfig | None = None
        self.remove_listener = runtime.add_step_listener(self._on_step)
        self.remove_log_listener = runtime.add_log_listener(self._on_log)

    def close(self) -> None:
        runtime.close_inspector_sessions()
        self.remove_listener()
        self.remove_log_listener()
        for run in self.runs.values():
            if run.replay is not None:
                run.replay.stop()
        if self.sink is not None:
            self.sink.close()
            self.sink = None

    # -- events ---------------------------------------------------------------------------------

    def pytest_report_header(self) -> str | None:
        if self.config.inspector.enabled:
            return f"WinTestKit managed inspector: {self.config.inspector.attach}"
        return None

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
                "command": subprocess.list2cmdline(
                    ["pytest", *self.pytest_config.invocation_params.args]
                ),
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
                "markers": sorted({marker.name for marker in item.iter_markers()}),
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
        if run is not None and run.replay is not None:
            if run.replay.window is None and self.current is not None:
                self._replay_window(run.replay, _funcarg(self.current, "app"))
            run.replay.request_frame()
        if (
            self.report_enabled
            and self.config.screenshots == "every-step"
            and self.current is not None
        ):
            app = _funcarg(self.current, "app")
            directory = artifact_files.artifacts_dir(self.config.report_dir, test_id)
            path = artifact_files.capture_step_screenshot(app, directory, record.seq)
            if path is not None:
                record.screenshot = artifact_files.relative_to_report(path, self.config.report_dir)
                run = self.runs.get(test_id)
                if run is not None:
                    run.step_screenshots.append(path)
        self._emit({"event": "step", "id": test_id, "step": record.to_dict()})

    def _on_log(self, entry: dict[str, Any]) -> None:
        test_id = runtime.current_test()
        if not test_id:
            return
        run = self.runs.get(test_id)
        if run is not None and entry["level"] == "warning":
            run.warnings.append(entry["text"])
        self._emit({"event": "log", "id": test_id, "entry": entry})

    # -- per-test lifecycle ---------------------------------------------------------------------

    @pytest.hookimpl(tryfirst=True)
    def pytest_runtest_setup(self, item: pytest.Item) -> None:
        runtime.begin_test(item.nodeid)
        self.current = item
        self.runs[item.nodeid] = _Run(item.nodeid)
        if self.report_enabled and self.config.replay != "off":
            replay = ReplayRecorder(
                artifact_files.artifacts_dir(self.config.report_dir, item.nodeid),
                self.config.report_dir,
                fps=self.config.replay_fps,
                scope=self.config.replay_scope,
                max_frames=self.config.replay_max_frames,
                max_bytes=self.config.replay_max_bytes,
            )
            self.runs[item.nodeid].replay = replay
            replay.start()
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
        actionability = marker.kwargs.get("actionability")
        if actionability is not None and actionability not in ACTIONABILITY_MODES:
            raise ConfigError(
                f"invalid actionability {actionability!r} in the wtk marker; "
                f"allowed: {', '.join(ACTIONABILITY_MODES)}",
                key="actionability",
            )
        if timeout is not None or actionability is not None:
            current = runtime.get_config()
            self.restore_config = current
            changes: dict[str, Any] = {}
            if timeout is not None:
                changes["timeout"] = float(timeout)
            if actionability is not None:
                changes["actionability"] = actionability
            runtime.set_config(dataclasses.replace(current, **changes))

    @staticmethod
    def _replay_window(replay: ReplayRecorder, app: Any) -> None:
        if app is None or replay.scope != "window":
            return
        try:
            replay.set_window(int(app.main_window().native_window_handle))
        except Exception as exc:
            log.debug("replay window not available: %s", exc)

    @pytest.hookimpl(hookwrapper=True)
    def pytest_fixture_setup(
        self, fixturedef: pytest.FixtureDef[Any], request: pytest.FixtureRequest
    ) -> Generator[None, Any, None]:
        outcome = yield
        if fixturedef.argname != "app" or outcome.excinfo is not None:
            return
        run = self.runs.get(self.current.nodeid) if self.current is not None else None
        if run is not None and run.replay is not None:
            self._replay_window(run.replay, outcome.get_result())

    @pytest.hookimpl(trylast=True)
    def pytest_runtest_teardown(self, item: pytest.Item, nextitem: pytest.Item | None) -> None:
        runtime.end_test()
        if self.restore_config is not None:
            runtime.set_config(self.restore_config)
            self.restore_config = None

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(
        self, item: pytest.Item, call: pytest.CallInfo[None]
    ) -> Generator[None, Any, None]:
        outcome = yield
        report: pytest.TestReport = outcome.get_result()
        run = self.runs.setdefault(item.nodeid, _Run(item.nodeid))
        if run.warnings:
            report.user_properties = [
                *item.user_properties,
                ("wintestkit warnings", "\n".join(run.warnings)),
            ]
        if report.when == "setup" and run.replay is not None:
            self._replay_window(run.replay, _funcarg(item, "app"))
        if call.excinfo is not None:
            run.exceptions[report.when or "call"] = call.excinfo
        tree_diff_enabled = bool(self.pytest_config.getoption("wtk_ui_tree_diff", False))
        evidence_enabled = self.report_enabled and self.config.screenshots != "off"
        if report.when == "call" and report.passed and tree_diff_enabled and evidence_enabled:
            run.tree_baseline = artifact_files.capture_tree_text(_funcarg(item, "app"))
        baseline = artifact_files.baseline_path(
            self.config.report_dir, repr(self.config.app), item.nodeid
        )
        if not evidence_enabled or not report.failed or report.when == "teardown":
            return
        directory = artifact_files.artifacts_dir(self.config.report_dir, item.nodeid)
        app = _funcarg(item, "app")
        captured = artifact_files.capture_failure(app, directory)
        if tree_diff_enabled and evidence_enabled and captured.tree_dump is not None:
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
        if (
            outcome == "passed"
            and self.report_enabled
            and self.config.screenshots != "off"
            and self.pytest_config.getoption("wtk_ui_tree_diff", False)
        ):
            baseline = artifact_files.baseline_path(
                self.config.report_dir, repr(self.config.app), report.nodeid
            )
            artifact_files.store_tree_text(run.tree_baseline, baseline)
        run.tree_baseline = None
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
        if run.replay is not None:
            discard = self.config.replay == "retain-on-failure" and outcome not in (
                "failed",
                "error",
            )
            replay_result = run.replay.stop(discard=discard)
            if not discard:
                event["replay"] = replay_result
        if outcome == "skipped":
            skipped = next((item for item in run.reports.values() if item.skipped), None)
            if skipped is not None:
                reason = skipped.longrepr
                event["message"] = str(reason[2] if isinstance(reason, tuple) else reason)
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
            write_report(self.config.report_dir, self.recorder.results(), html=self.write_html)
            self.report_path = str(event["reportPath"])

    def pytest_terminal_summary(self, terminalreporter: Any) -> None:
        if self.config.inspector.enabled:
            identities = runtime.inspector_attached_processes()
            terminalreporter.write_line(
                "WinTestKit inspector attached: "
                + (
                    ", ".join(f"PID {item.pid} ({item.creation_time_utc})" for item in identities)
                    if identities
                    else "none"
                )
            )
        if self.report_path:
            label = "Report" if self.write_html else "Results"
            path = (
                self.report_path
                if self.write_html
                else str(Path(self.report_path).with_name("results.json"))
            )
            terminalreporter.write_line(f"{label}: {path}")


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


@pytest.fixture
def app(request: pytest.FixtureRequest) -> Generator[App, None, None]:
    """The application under test, launched or attached according to the launch mode."""
    from wintestkit.app import App

    config = _effective_config(request)
    node: Any = request.node  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    mode: Any = _marker_kwargs(node, "wtk").get("launch", config.launch)
    if mode not in LAUNCH_MODES:
        raise ConfigError(f"invalid launch mode {mode!r} in the wtk marker", key="launch")
    name = _app_name(config)
    if mode == "attach":
        if config.app is None:
            raise ConfigError("no application to attach to: set [tool.wintestkit.app]", key="app")
        with runtime.step("app.attach", config.app.process_name, config.app.process_name):
            try:
                attached = App.attach(process=config.app.process_name)
            except AppNotRunningError:
                raise _AttachNotRunning(config.app.process_name) from None
            _verify_started(attached, config)
        runtime.set_current_app(attached)
        try:
            yield attached
        finally:
            runtime.set_current_app(None)
            attached.detach_inspector()
    else:
        with runtime.step("app.start", name, _app_path(config)):
            launched = request.config.stash.get(_EXISTING_APP, None)
            if launched is not None and not launched.is_running():
                launched = None
                del request.config.stash[_EXISTING_APP]
            if launched is None:
                launched = launch_app(config)
                if not launched.launched:
                    _announce(
                        request.config,
                        f"WinTestKit: attaching to the already-running {name} for this session "
                        "(set app.close_existing to launch a fresh copy instead).",
                    )
                    request.config.stash[_EXISTING_APP] = launched
                    request.session.addfinalizer(launched.detach_inspector)
            _verify_started(launched, config)
        runtime.set_current_app(launched)
        try:
            yield launched
        finally:
            runtime.set_current_app(None)
            if launched.launched:
                launched.close(timeout=config.app.close_timeout if config.app else 10.0)


def _announce(config: pytest.Config, message: str) -> None:
    """Print a line in the pytest output, even when output capture is on."""
    reporter: Any = config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_line(message)
    else:
        print(message)


def _app_name(config: WtkConfig) -> str:
    settings = config.app
    if settings is None:
        return "the app"
    return settings.process or (Path(settings.path).name if settings.path else "the app")


def _app_path(config: WtkConfig) -> str:
    return str(config.app.path) if config.app and config.app.path else ""


def _verify_started(app: App, config: WtkConfig) -> None:
    """The application is running and has shown its main window."""
    __tracebackhide__ = True
    timeout = config.app.startup_timeout if config.app else 10.0
    deadline = time.monotonic() + timeout
    window = app.main_window(timeout=timeout)
    if not app.launched:
        app._attach_window(window, deadline)  # pyright: ignore[reportPrivateUsage]


class _AttachNotRunning(AttachNotRunningError, pytest.fail.Exception):
    """Attach mode with the application not running, reported as just its message.

    The traceback of this setup failure would only point into WinTestKit's own fixture, so pytest
    is told to show the explanation alone. It stays a ``WtkError`` so the event stream carries
    its type and the editor can tell the user why nothing was launched.
    """

    def __init__(self, process: str) -> None:
        message = "\n".join(
            [
                'THE APP WAS NOT LAUNCHED: the launch mode is "attach".',
                "",
                "Attach mode only connects to an app that is already running; WinTestKit never "
                "starts it.",
                f"{process} is not running, so there was nothing to attach to and the tests did "
                "not run.",
                "",
                "To fix this, either:",
                f"  - start {process} yourself and run the tests again, or",
                '  - switch the launch mode to "Launch for tests" (Test Target in the editor, '
                "or launch: per-test in the settings) so WinTestKit starts the app for you.",
            ]
        )
        AttachNotRunningError.__init__(self, message)
        pytest.fail.Exception.__init__(self, message, pytrace=False)

    def to_dict(self) -> dict[str, Any]:
        return {"type": "AttachNotRunningError", "message": self.message}


@pytest.fixture
def apps(request: pytest.FixtureRequest) -> Generator[Apps, None, None]:
    """Further applications of one test (a second app, Notepad, a dialog of the shell): launched
    or attached through it, they are closed or released when the test ends."""
    from wintestkit.app import Apps

    config = _effective_config(request)
    group = Apps(close_timeout=config.app.close_timeout if config.app else 10.0)
    try:
        yield group
    finally:
        group.close_all()


@pytest.fixture
def page(app: App) -> Callable[[type[Any]], Any]:
    """Factory binding a ``Page`` subclass to the application: ``page(MainPage)``."""

    def make(page_class: type[Any]) -> Any:
        return page_class(app)

    return make
