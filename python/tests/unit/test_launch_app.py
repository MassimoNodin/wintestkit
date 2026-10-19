"""Launch mode owns the app: a running copy is closed first, and the launched one is closed after."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from wintestkit.app import App
from wintestkit.errors import AppNotRunningError
from wintestkit.pytest_plugin import launch_app
from wintestkit.uia import win32


def _config(process: str | None = "Demo.exe") -> Any:
    return SimpleNamespace(
        app=SimpleNamespace(
            path=Path("C:/Apps/Demo.exe"),
            args=(),
            cwd=None,
            env={},
            process=process,
            startup_timeout=5.0,
            close_timeout=3.0,
        )
    )


class _Calls:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, running: list[int]) -> None:
        self.events: list[str] = []
        self.running = running
        launched = SimpleNamespace(
            launched=True,
            is_running=lambda: True,
            close=lambda timeout: self.events.append(f"close launched ({timeout:g}s)"),
        )
        previous = SimpleNamespace(
            close=lambda timeout: self.events.append(f"close running copy ({timeout:g}s)")
        )

        def launch(path: Any, **kwargs: Any) -> Any:
            self.events.append("launch " + str(kwargs["process"]))
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


def test_a_running_copy_is_closed_before_the_fresh_one_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _Calls(monkeypatch, running=[2600])
    launch_app(_config())
    assert calls.events == [
        "attach Demo.exe",
        "close running copy (3s)",
        "launch Demo.exe",
    ]


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


def test_a_copy_that_exits_while_closing_does_not_stop_the_launch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _Calls(monkeypatch, running=[2600])

    def vanished(**kwargs: Any) -> Any:
        raise AppNotRunningError("gone")

    monkeypatch.setattr(App, "attach", staticmethod(vanished))
    assert launch_app(_config()) is calls.launched
    assert calls.events == ["launch Demo.exe"]
