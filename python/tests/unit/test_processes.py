"""``finders.process``, ``wait_process`` and the ``Sys`` namespace on a fake process list."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from wintestkit import finders, runtime
from wintestkit.app import App
from wintestkit.errors import AppNotRunningError
from wintestkit.uia import win32


class World:
    """The running processes and a clock that only moves when somebody sleeps."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.processes: list[tuple[int, str]] = []
        self.now = 0.0
        self.listings = 0
        self.on_sleep: Any = None
        monkeypatch.setattr(win32, "list_processes", self.list_processes)
        monkeypatch.setattr(
            finders, "time", SimpleNamespace(monotonic=lambda: self.now, sleep=self.sleep)
        )
        runtime.reset()

    def list_processes(self) -> list[tuple[int, str]]:
        self.listings += 1
        return list(self.processes)

    def sleep(self, seconds: float) -> None:
        self.now += seconds
        if self.on_sleep is not None:
            self.on_sleep(self.now)


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Any:
    yield World(monkeypatch)
    runtime.reset()


def test_process_returns_an_app_for_the_running_exe(world: World) -> None:
    world.processes = [(10, "Notepad.exe"), (11, "Other.exe")]
    app = finders.process("Notepad.exe")
    assert isinstance(app, App) and app.process_name == "Notepad.exe"
    assert app.pids == [10] and not app.launched


def test_process_raises_when_none_is_running(world: World) -> None:
    world.processes = [(11, "Other.exe")]
    with pytest.raises(AppNotRunningError, match=r"No running process named Notepad\.exe"):
        finders.process("Notepad.exe")


def test_a_name_without_extension_and_any_case_is_the_same_exe(world: World) -> None:
    world.processes = [(10, "Notepad.exe")]
    assert finders.process("notepad").process_name == "notepad.exe"
    assert finders.process("NOTEPAD.EXE").pids == [10]
    assert finders.process("  Notepad.exe ").pids == [10]
    assert finders.process("notepad").matches_process("notepad.exe")
    assert not finders.process("notepad").matches_process("note.exe")


@pytest.mark.parametrize("name", ["", "  ", None, 3])
def test_a_missing_name_is_refused(world: World, name: Any) -> None:
    with pytest.raises(ValueError, match="invalid process name"):
        finders.process(name)
    with pytest.raises(ValueError, match="invalid process name"):
        finders.wait_process(name, 0)


def test_wait_process_zero_checks_once(world: World) -> None:
    assert finders.wait_process("Notepad.exe", 0) is None
    assert world.listings == 1 and world.now == 0.0
    world.processes = [(10, "Notepad.exe")]
    app = finders.wait_process("Notepad.exe")
    assert app is not None and app.pids == [10]


def test_wait_process_returns_the_app_when_it_appears_in_time(world: World) -> None:
    def appears(now: float) -> None:
        if now >= 0.3 and not world.processes:
            world.processes = [(10, "Notepad.exe")]

    world.on_sleep = appears
    app = finders.wait_process("Notepad.exe", 5000)
    assert app is not None and app.pids == [10]
    assert 0.3 <= world.now < 0.5


def test_wait_process_gives_up_with_none_after_the_time(world: World) -> None:
    assert finders.wait_process("Notepad.exe", 1500) is None
    assert 1.5 <= world.now < 1.7


def test_wait_process_is_one_step_with_the_outcome(world: World) -> None:
    records: list[runtime.StepRecord] = []
    runtime.add_step_listener(records.append)
    finders.wait_process("Notepad.exe", 0)
    world.processes = [(10, "Notepad.exe")]
    finders.wait_process("Notepad.exe", 200)
    assert [(r.action, r.args) for r in records] == [
        ("wait_process", {"name": "Notepad.exe", "timeout_ms": 0, "found": False}),
        ("wait_process", {"name": "Notepad.exe", "timeout_ms": 200, "found": True}),
    ]


def test_sys_reads_like_the_migrated_calls(world: World) -> None:
    world.processes = [(10, "Notepad.exe")]
    assert finders.Sys.Process("Notepad.exe").pids == [10]
    assert finders.Sys.process("Notepad.exe").pids == [10]
    assert finders.Sys.WaitProcess("Notepad.exe", 0) is not None
    assert finders.Sys.wait_process("Missing.exe", 0) is None
    with pytest.raises(AppNotRunningError):
        finders.Sys.Process("Missing.exe")
    assert repr(finders.Sys) == "Sys"


def test_from_label_starts_at_the_same_process_app(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.processes = [(10, "Notepad.exe")]
    starts: list[Any] = []
    monkeypatch.setattr(finders, "_chain", lambda start, steps: starts.append(start) or "chain")
    assert finders.from_label(None, 'Process("notepad").Window("Edit")') == "chain"
    assert finders.from_label(None, 'Sys.Process("Notepad.exe").Window("Edit")') == "chain"
    assert all(isinstance(start, App) and start.pids == [10] for start in starts)
    # A parent that is that application is used as it is: no new attach (the process is gone).
    parent = starts[0]
    world.processes = []
    finders.from_label(parent, 'Process("NOTEPAD").Window("Edit")')
    assert starts[-1] is parent
    # Another process is attached by name, like finders.process does.
    with pytest.raises(AppNotRunningError):
        finders.from_label(parent, 'Process("Other.exe").Window("Edit")')


def test_from_label_without_a_process_still_needs_a_parent(world: World) -> None:
    with pytest.raises(ValueError, match="needs a parent"):
        finders.from_label(None, 'Window("Edit")')
