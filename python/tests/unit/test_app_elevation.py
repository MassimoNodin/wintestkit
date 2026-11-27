"""Elevated launches (``runas``) and the UIPI check, on a fake Win32 and shell layer."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from wintestkit import app as app_module
from wintestkit import runtime
from wintestkit.app import App, _HandleProcess  # pyright: ignore[reportPrivateUsage]
from wintestkit.config import load_config
from wintestkit.errors import AppError, ConfigError, ElevationError
from wintestkit.pytest_plugin import launch_app
from wintestkit.uia import win32


class Shell:
    """What the shell and the process table do; every Win32 call the code makes goes through it."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.runner_elevated = False
        self.target_elevated: bool | None = True
        self.exit_code: int | None = None
        self.cancelled = False
        self.fail: OSError | None = None
        self.executed: list[tuple[str, str, str | None]] = []
        self.popen_calls: list[dict[str, Any]] = []
        self.closed_handles: list[int] = []
        self.terminated: list[int] = []
        self.running: list[tuple[int, str]] = []
        monkeypatch.setattr(win32, "current_process_is_elevated", lambda: self.runner_elevated)
        monkeypatch.setattr(win32, "process_is_elevated", lambda pid: self.target_elevated)
        monkeypatch.setattr(win32, "shell_execute", self.shell_execute)
        monkeypatch.setattr(win32, "process_exit_code", lambda handle: self.exit_code)
        monkeypatch.setattr(win32, "CloseHandle", self.closed_handles.append)
        monkeypatch.setattr(win32, "TerminateProcess", lambda h, c: self.terminated.append(h))
        monkeypatch.setattr(win32, "list_processes", lambda: list(self.running))
        monkeypatch.setattr(app_module.subprocess, "Popen", self.popen)
        monkeypatch.setattr(
            App, "_wait_for_startup", lambda *a, **k: self.popen_calls.append({"waited": True})
        )
        runtime.reset()

    def shell_execute(
        self, path: str, parameters: str = "", directory: str | None = None, *, verb: str = "runas"
    ) -> tuple[int, int]:
        assert verb == "runas"
        self.executed.append((path, parameters, directory))
        if self.cancelled:
            raise OSError(0, "The operation was canceled by the user", None, win32.ERROR_CANCELLED)
        if self.fail is not None:
            raise self.fail
        self.running.append((700, "Admin.exe"))
        return 55, 700

    def popen(self, command: list[str], **kwargs: Any) -> Any:
        self.popen_calls.append({"command": command, **kwargs})
        self.running.append((800, "Admin.exe"))
        return SimpleNamespace(pid=800, poll=lambda: None)


@pytest.fixture
def shell(monkeypatch: pytest.MonkeyPatch) -> Any:
    yield Shell(monkeypatch)
    runtime.reset()


@pytest.fixture
def exe(tmp_path: Path) -> Path:
    path = tmp_path / "Admin.exe"
    path.write_bytes(b"")
    return path


def test_a_non_elevated_runner_asks_the_shell_for_runas(shell: Shell, exe: Path) -> None:
    app = App.launch(exe, args=["--mode", "two words"], cwd=exe.parent, elevated=True)
    assert shell.executed == [(str(exe), '--mode "two words"', str(exe.parent))]
    assert shell.popen_calls == []  # no Popen, and no window wait: UIPI makes it unreachable
    assert app.launched and app.elevated and app.pids == [700]
    assert isinstance(app._popen, _HandleProcess)  # pyright: ignore[reportPrivateUsage]


def test_the_working_directory_defaults_to_the_runners(
    shell: Shell, exe: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(exe.parent)
    App.launch(exe, elevated=True)
    assert shell.executed[0][2] == str(exe.parent)


def test_a_declined_prompt_says_why_and_what_to_do(shell: Shell, exe: Path) -> None:
    shell.cancelled = True
    with pytest.raises(AppError, match=r"declined.*secure desktop.*elevated terminal"):
        App.launch(exe, elevated=True)


def test_another_shell_failure_is_an_app_error(shell: Shell, exe: Path) -> None:
    shell.fail = OSError(0, "no association", None, 31)
    with pytest.raises(AppError, match=r"Could not start .*elevated"):
        App.launch(exe, elevated=True)


def test_env_cannot_reach_an_elevated_process(shell: Shell, exe: Path) -> None:
    with pytest.raises(AppError, match="cannot take env"):
        App.launch(exe, env={"A": "1"}, elevated=True)
    assert shell.executed == []


def test_a_process_that_dies_at_once_is_reported(shell: Shell, exe: Path) -> None:
    shell.exit_code = 5
    with pytest.raises(AppError, match=r"exited right after starting .*exit code 5"):
        App.launch(exe, elevated=True)


def test_an_elevated_runner_starts_it_directly_with_env_and_waits_for_the_window(
    shell: Shell, exe: Path
) -> None:
    shell.runner_elevated = True
    app = App.launch(exe, args=["-x"], env={"A": "1"}, elevated=True)
    assert shell.executed == []
    (call, waited) = shell.popen_calls
    assert call["command"] == [str(exe), "-x"] and call["env"]["A"] == "1"
    assert waited == {"waited": True}
    assert app.elevated


def test_not_elevated_is_the_plain_launch(shell: Shell, exe: Path) -> None:
    app = App.launch(exe)
    assert shell.executed == [] and not app.elevated and len(shell.popen_calls) == 2


def test_the_handle_process_follows_the_exit_and_closes_its_handle(shell: Shell) -> None:
    process = _HandleProcess(55, 700)
    assert process.poll() is None
    shell.exit_code = 3
    assert process.poll() == 3 and process.poll() == 3
    assert shell.closed_handles == [55]
    process.kill()  # nothing left to terminate
    assert shell.terminated == []


def test_the_handle_process_can_be_waited_for_and_killed(
    shell: Shell, monkeypatch: pytest.MonkeyPatch
) -> None:
    process = _HandleProcess(55, 700)
    monkeypatch.setattr(app_module.time, "sleep", lambda s: None)
    with pytest.raises(subprocess.TimeoutExpired):
        process.wait(timeout=0)
    process.terminate()
    assert shell.terminated == [55]
    shell.exit_code = 0
    assert process.wait(timeout=1) == 0


# -- driving an elevated app from a runner that is not elevated -------------------------------------


def test_a_lower_integrity_runner_gets_a_clear_error_for_every_window_lookup(shell: Shell) -> None:
    shell.running = [(700, "Admin.exe")]
    app = App.attach(process="Admin.exe")
    for call in (app.top_level_windows, app.main_window, app.close):
        with pytest.raises(ElevationError, match=r"runs elevated.*UIPI.*elevated terminal"):
            call()


def test_nothing_is_wrong_when_the_runner_is_elevated_or_the_target_is_not(shell: Shell) -> None:
    shell.running = [(700, "Admin.exe")]
    app = App.attach(process="Admin.exe")
    shell.runner_elevated = True
    app.ensure_drivable()
    shell.runner_elevated, shell.target_elevated = False, False
    app.ensure_drivable()
    shell.target_elevated = None  # token not readable: nothing proves a mismatch
    App.attach(process="Admin.exe").ensure_drivable()


def test_a_verified_process_is_not_asked_again(shell: Shell) -> None:
    shell.running = [(700, "Admin.exe")]
    app = App.attach(process="Admin.exe")
    shell.target_elevated = False
    app.ensure_drivable()
    shell.target_elevated = True
    app.ensure_drivable()  # cached for that pid


def test_a_refused_kill_of_an_elevated_process_says_why(
    shell: Shell, monkeypatch: pytest.MonkeyPatch
) -> None:
    shell.running = [(700, "Admin.exe")]
    app = App.attach(process="Admin.exe")
    monkeypatch.setattr(app_module.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(app, "wait_for_exit", lambda timeout: False)
    with pytest.raises(ElevationError):
        app.kill()


# -- configuration -------------------------------------------------------------------------------


def test_the_config_key_defaults_to_off_and_is_a_boolean(tmp_path: Path) -> None:
    assert load_config(tmp_path, {"app.path": "A.exe"}).app.elevated is False  # type: ignore[union-attr]
    assert load_config(tmp_path, {"app.path": "A.exe", "app.elevated": True}).app.elevated  # type: ignore[union-attr]
    with pytest.raises(ConfigError, match=r"app\.elevated"):
        load_config(tmp_path, {"app.path": "A.exe", "app.elevated": "yes"})


def test_the_config_key_is_read_from_the_project_file(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.wintestkit.app]\npath = "A.exe"\nelevated = true\n', encoding="utf-8"
    )
    config = load_config(tmp_path)
    assert config.app is not None and config.app.elevated is True


def test_the_configured_launch_is_elevated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(win32, "pids_by_name", lambda name: [])
    monkeypatch.setattr(App, "launch", staticmethod(lambda path, **kw: seen.append(kw)))
    config = load_config(tmp_path, {"app.path": "A.exe", "app.elevated": True})
    launch_app(config)
    assert seen[0]["elevated"] is True and seen[0]["owned_only"] is True
