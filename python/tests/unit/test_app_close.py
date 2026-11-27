"""Closing an application: ask the main window, answer a prompt, wait, optionally kill."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from wintestkit import finders, runtime
from wintestkit.app import App
from wintestkit.errors import ActionError
from wintestkit.uia import input as uia_input
from wintestkit.uia import win32

MAIN = 100
PROMPT = 200


class World:
    """One application with a main window, on a clock that moves only when somebody sleeps."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.now = 0.0
        self.running = True
        self.windows = [MAIN]
        self.posted: list[tuple[int, int]] = []
        self.keys: list[str] = []
        self.killed = 0
        self.foreground = MAIN
        self.schedule: list[tuple[float, Any]] = []
        self.app = App("Demo.exe", launched=True, by_name=False)
        monkeypatch.setattr(App, "pids", property(lambda app: [7] if self.running else []))
        monkeypatch.setattr(App, "ensure_drivable", lambda app: None)
        monkeypatch.setattr(self.app, "main_window", lambda timeout=0.0: self.main())
        monkeypatch.setattr(self.app, "kill", self.kill)
        monkeypatch.setattr(self.app, "detach_inspector", lambda: None)
        monkeypatch.setattr(
            win32, "top_level_windows", lambda pids=None, visible_only=True: list(self.windows)
        )
        monkeypatch.setattr(win32, "PostMessageW", lambda h, m, w, p: self.posted.append((h, m)))
        monkeypatch.setattr(win32, "bring_to_foreground", lambda h, timeout=0.5: True)
        monkeypatch.setattr(win32, "GetForegroundWindow", lambda: self.foreground)
        monkeypatch.setattr(win32, "window_pid", lambda h: 7 if h in (MAIN, PROMPT) else 99)
        monkeypatch.setattr(uia_input, "press", self.keys.append)
        clock = SimpleNamespace(monotonic=lambda: self.now, sleep=self.sleep)
        monkeypatch.setattr("wintestkit.app.time", clock)
        runtime.reset()
        self.steps: list[runtime.StepRecord] = []
        runtime.add_step_listener(self.steps.append)

    def main(self) -> Any:
        return SimpleNamespace(native_window_handle=MAIN)

    def at(self, when: float, action: Any) -> None:
        self.schedule.append((when, action))

    def sleep(self, seconds: float) -> None:
        self.now += seconds
        for item in list(self.schedule):
            if self.now >= item[0]:
                self.schedule.remove(item)
                item[1]()

    def kill(self) -> None:
        self.killed += 1
        self.running = False

    def show_prompt(self) -> None:
        self.windows.append(PROMPT)

    def exit(self) -> None:
        self.running = False
        self.windows = []


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Any:
    yield World(monkeypatch)
    runtime.reset()


def test_wm_close_posts_to_the_main_window_and_returns_at_once(world: World) -> None:
    world.app.request_close()
    assert world.posted == [(MAIN, win32.WM_CLOSE)] and world.now == 0.0


def test_alt_f4_activates_the_window_and_presses_the_keys(world: World) -> None:
    world.app.request_close("alt_f4")
    assert world.keys == ["Alt+F4"] and world.posted == []


def test_alt_f4_refuses_when_the_keys_would_go_elsewhere(world: World) -> None:
    world.foreground = 999
    with pytest.raises(ActionError, match="foreground"):
        world.app.request_close("alt_f4")
    assert world.keys == []


def test_unknown_methods_are_refused(world: World) -> None:
    with pytest.raises(ValueError, match="wm_close"):
        world.app.request_close("click")  # type: ignore[arg-type]


def test_a_clean_exit_is_reported_and_is_one_step(world: World) -> None:
    world.at(0.4, world.exit)
    assert world.app.close_gracefully() == "exited"
    assert world.posted == [(MAIN, win32.WM_CLOSE)] and world.killed == 0
    (record,) = world.steps
    assert record.action == "app.close" and record.target == "Demo.exe"
    assert record.args["outcome"] == "exited" and record.args["method"] == "wm_close"


def test_a_prompt_is_answered_by_the_callback_then_the_exit_is_awaited(world: World) -> None:
    answered: list[tuple[App, float]] = []

    def answer(app: App) -> None:
        answered.append((app, world.now))
        world.at(world.now + 2.0, world.exit)

    world.at(1.2, world.show_prompt)
    assert world.app.close_gracefully(method="alt_f4", on_prompt=answer) == "exited"
    assert len(answered) == 1 and answered[0][0] is world.app
    assert 1.2 <= answered[0][1] < 1.4
    assert world.steps[0].args["prompt"] is True and world.keys == ["Alt+F4"]


def test_windows_that_were_open_before_are_not_a_prompt(world: World) -> None:
    world.windows = [MAIN, 300]  # a tool window that stays
    called: list[App] = []
    world.at(0.5, world.exit)
    assert world.app.close_gracefully(on_prompt=called.append) == "exited"
    assert called == [] and world.steps[0].args["prompt"] is False


def test_no_prompt_within_the_time_means_the_callback_is_not_called(world: World) -> None:
    called: list[App] = []
    world.at(10.0, world.exit)
    outcome = world.app.close_gracefully(on_prompt=called.append, prompt_timeout=3.0)
    assert outcome == "exited" and called == []
    assert 10.0 <= world.now < 10.2


def test_a_prompt_nobody_answers_times_out_without_forcing(world: World) -> None:
    world.at(0.1, world.show_prompt)
    assert world.app.close_gracefully(exit_timeout=5.0) == "running"
    assert world.killed == 0 and world.app.is_running()
    assert world.steps[0].args["outcome"] == "running"


def test_kill_is_only_used_when_asked_for(world: World) -> None:
    assert world.app.close_gracefully(exit_timeout=2.0, kill=True) == "killed"
    assert world.killed == 1 and 2.0 <= world.now < 2.2


def test_the_exit_wait_follows_the_prompt_wait(world: World) -> None:
    world.at(0.1, world.show_prompt)
    world.app.close_gracefully(on_prompt=lambda app: None, prompt_timeout=3.0, exit_timeout=30.0)
    assert 30.0 <= world.now < 31.0  # the 30 s start when the callback has returned


def test_an_app_that_exits_during_the_prompt_wait_ends_it(world: World) -> None:
    world.at(0.3, world.exit)
    assert world.app.close_gracefully(on_prompt=lambda app: None) == "exited"
    assert world.now < 1.0


# -- the helper process that is killed by name -----------------------------------------------------


def test_a_helper_is_killed_by_name_with_taskkill(monkeypatch: pytest.MonkeyPatch) -> None:
    alive = [(41, "helper.exe"), (42, "helper.exe"), (43, "other.exe")]
    commands: list[list[str]] = []

    def taskkill(command: list[str], **kwargs: Any) -> None:
        commands.append(command)
        alive[:] = [item for item in alive if str(item[0]) != command[2]]

    monkeypatch.setattr(win32, "list_processes", lambda: list(alive))
    monkeypatch.setattr("wintestkit.app.subprocess.run", taskkill)
    monkeypatch.setattr(App, "ensure_drivable", lambda app: None)
    monkeypatch.setattr(App, "detach_inspector", lambda app: None)
    runtime.reset()
    helper = finders.process("helper")
    helper.kill()
    assert commands == [
        ["taskkill", "/PID", "41", "/T", "/F"],
        ["taskkill", "/PID", "42", "/T", "/F"],
    ]
    assert alive == [(43, "other.exe")] and not helper.is_running()


@pytest.mark.parametrize("name", ["explorer.exe", "Explorer", "EXPLORER.EXE"])
def test_the_windows_shell_is_not_closed_without_force(world: World, name: str) -> None:
    world.app.process_name = name
    with pytest.raises(ActionError, match=r"Windows shell.*every File Explorer window.*force=True"):
        world.app.close_gracefully()
    with pytest.raises(ActionError, match="Windows shell"):
        world.app.close()
    assert world.posted == [] and world.killed == 0 and world.steps == []


def test_the_shell_is_closed_when_forced(world: World) -> None:
    world.app.process_name = "explorer.exe"
    world.at(0.4, world.exit)
    assert world.app.close_gracefully(force=True) == "exited"
    assert world.posted == [(MAIN, win32.WM_CLOSE)]
    world.running = True
    world.windows = [MAIN]
    world.at(world.now + 0.2, world.exit)
    world.app.close(force=True)
    assert (MAIN, win32.WM_CLOSE) in world.posted and world.killed == 0


def test_leaving_a_launched_shell_app_does_not_raise_or_close_it(world: World) -> None:
    world.app.process_name = "explorer.exe"
    with world.app:
        pass
    assert world.posted == [] and world.killed == 0 and world.running
