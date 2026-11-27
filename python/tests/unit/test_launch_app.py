"""Launch mode never closes or kills an app instance WinTestKit did not start, unless opted in."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from wintestkit.app import App
from wintestkit.errors import AppError, AppNotRunningError
from wintestkit.pytest_plugin import launch_app
from wintestkit.uia import win32


def _config(process: str | None = "Demo.exe", close_existing: bool = False) -> Any:
    return SimpleNamespace(
        app=SimpleNamespace(
            path=Path("C:/Apps/Demo.exe"),
            args=(),
            cwd=None,
            env={},
            process=process,
            startup_timeout=5.0,
            close_timeout=3.0,
            close_existing=close_existing,
            elevated=False,
        )
    )


class _Calls:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, running: list[int]) -> None:
        self.events: list[str] = []
        self.launch_kwargs: list[dict[str, Any]] = []
        self.running = running
        launched = SimpleNamespace(
            launched=True,
            is_running=lambda: True,
            close=lambda timeout: self.events.append(f"close launched ({timeout:g}s)"),
        )
        self.alive = True
        previous = SimpleNamespace(
            launched=False,
            is_running=lambda: self.alive,
            close=lambda timeout: self.close_previous(timeout),
        )
        self.previous = previous
        self.closes = True

        def launch(path: Any, **kwargs: Any) -> Any:
            self.events.append("launch " + str(kwargs["process"]))
            self.launch_kwargs.append(kwargs)
            return launched

        def attach(**kwargs: Any) -> Any:
            if not self.running:
                raise AppNotRunningError("not running")
            self.events.append("attach " + kwargs["process"])
            return previous

        monkeypatch.setattr(win32, "pids_by_name", lambda name: self.running)
        monkeypatch.setattr(App, "launch", staticmethod(launch))
        monkeypatch.setattr(App, "attach", staticmethod(attach))
        self.launched = launched

    def close_previous(self, timeout: float) -> None:
        self.events.append(f"close running copy ({timeout:g}s)")
        if self.closes:
            self.alive = False


def test_a_running_copy_is_attached_and_never_closed_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _Calls(monkeypatch, running=[2600])
    app = launch_app(_config())
    assert app is calls.previous
    assert app.launched is False
    assert calls.events == ["attach Demo.exe"]


def test_close_existing_closes_the_running_copy_gracefully_then_launches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _Calls(monkeypatch, running=[2600])
    assert launch_app(_config(close_existing=True)) is calls.launched
    assert calls.events == [
        "attach Demo.exe",
        "close running copy (3s)",
        "launch Demo.exe",
    ]


def test_close_existing_fails_instead_of_launching_when_the_copy_stays_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _Calls(monkeypatch, running=[2600])
    calls.closes = False
    with pytest.raises(AppError, match="did not close"):
        launch_app(_config(close_existing=True))
    assert calls.events == ["attach Demo.exe", "close running copy (3s)"]


def test_launch_arguments_are_passed_on_every_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _Calls(monkeypatch, running=[])
    config = _config()
    config.app.args = ("/sandbox", "--flag")
    launch_app(config)
    launch_app(config)
    assert [kwargs["args"] for kwargs in calls.launch_kwargs] == [("/sandbox", "--flag")] * 2
    assert all(kwargs["owned_only"] for kwargs in calls.launch_kwargs)


def test_nothing_is_closed_when_the_app_is_not_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _Calls(monkeypatch, running=[])
    launch_app(_config())
    assert calls.events == ["launch Demo.exe"]


def test_the_process_name_comes_from_the_executable_when_none_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []
    _Calls(monkeypatch, running=[])
    monkeypatch.setattr(win32, "pids_by_name", lambda name: seen.append(name) or [])
    launch_app(_config(process=None))
    assert seen == ["Demo.exe"]


def test_a_copy_that_exits_during_discovery_does_not_stop_the_launch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _Calls(monkeypatch, running=[2600])

    def vanished(**kwargs: Any) -> Any:
        raise AppNotRunningError("gone")

    monkeypatch.setattr(App, "attach", staticmethod(vanished))
    assert launch_app(_config()) is calls.launched
    assert calls.events == ["launch Demo.exe"]
