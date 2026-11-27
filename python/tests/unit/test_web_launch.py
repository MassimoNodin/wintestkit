"""The WebView2 debugging port: the environment of a launch, the configuration and its plumbing."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from wintestkit import runtime, web
from wintestkit.app import App, Apps
from wintestkit.config import load_config
from wintestkit.errors import AppError, ConfigError
from wintestkit.pytest_plugin import launch_app
from wintestkit.uia import win32

VARIABLE = "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"


# -- the environment variable ---------------------------------------------------------------------


def test_the_switch_is_set_when_nothing_else_is() -> None:
    environment: dict[str, str] = {}
    web.apply_debug_port(environment, 9223)
    assert environment == {VARIABLE: "--remote-debugging-port=9223"}


def test_an_existing_value_is_kept_and_the_switch_is_appended() -> None:
    environment = {VARIABLE: "--disable-features=Foo --lang=en"}
    web.apply_debug_port(environment, 9223)
    assert environment[VARIABLE] == "--disable-features=Foo --lang=en --remote-debugging-port=9223"


def test_a_blank_value_is_replaced() -> None:
    environment = {VARIABLE: "  "}
    web.apply_debug_port(environment, 9223)
    assert environment[VARIABLE] == "--remote-debugging-port=9223"


def test_the_same_port_already_there_is_left_alone() -> None:
    environment = {VARIABLE: "--x --remote-debugging-port=9223"}
    web.apply_debug_port(environment, 9223)
    assert environment[VARIABLE] == "--x --remote-debugging-port=9223"


@pytest.mark.parametrize(
    "existing", ["--remote-debugging-port=9000", "--a --remote-debugging-port"]
)
def test_another_port_already_there_is_a_conflict(existing: str) -> None:
    environment = {VARIABLE: existing}
    with pytest.raises(AppError, match=r"already contains --remote-debugging-port.*9223"):
        web.apply_debug_port(environment, 9223)
    assert environment == {VARIABLE: existing}


def test_a_switch_that_only_looks_similar_is_not_the_switch() -> None:
    environment = {VARIABLE: "--remote-debugging-portal=1"}
    web.apply_debug_port(environment, 9223)
    assert environment[VARIABLE] == "--remote-debugging-portal=1 --remote-debugging-port=9223"


def test_the_variable_name_is_found_in_any_case() -> None:
    environment = {"Webview2_Additional_Browser_Arguments": "--x"}
    web.apply_debug_port(environment, 9223)
    assert environment == {
        "Webview2_Additional_Browser_Arguments": "--x --remote-debugging-port=9223"
    }


@pytest.mark.parametrize("port", [0, 65536, -5, True, "9223", None])
def test_a_port_must_be_a_real_port(port: Any) -> None:
    with pytest.raises(ValueError, match="webview_debug_port"):
        web.check_port(port)


# -- App.launch -----------------------------------------------------------------------------------


class Launch:
    """``App.launch`` with the process table and the window wait faked."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        self.popen_calls: list[dict[str, Any]] = []
        self.executed: list[Any] = []
        self.runner_elevated = False
        self.exe = tmp_path / "Host.exe"
        self.exe.write_bytes(b"")
        monkeypatch.setattr(win32, "pids_by_name", lambda name: [])
        monkeypatch.setattr(win32, "current_process_is_elevated", lambda: self.runner_elevated)
        monkeypatch.setattr(
            win32, "shell_execute", lambda *a, **k: self.executed.append(a) or (1, 1)
        )
        monkeypatch.setattr("wintestkit.app.subprocess.Popen", self.popen)
        monkeypatch.setattr(App, "_wait_for_startup", lambda *a, **k: None)
        runtime.reset()

    def popen(self, command: list[str], **kwargs: Any) -> Any:
        self.popen_calls.append({"command": command, **kwargs})
        return SimpleNamespace(pid=800, poll=lambda: None)


@pytest.fixture
def launch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Launch:
    monkeypatch.delenv(VARIABLE, raising=False)
    return Launch(monkeypatch, tmp_path)


def test_a_launch_sets_the_variable_for_the_process(launch: Launch) -> None:
    app = App.launch(launch.exe, webview_debug_port=9223)
    assert launch.popen_calls[0]["env"][VARIABLE] == "--remote-debugging-port=9223"
    assert app.webview_debug_port == 9223


def test_a_launch_without_a_port_leaves_the_variable_alone(
    launch: Launch, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = App.launch(launch.exe)
    assert VARIABLE not in launch.popen_calls[0]["env"]
    assert app.webview_debug_port is None
    monkeypatch.setenv(VARIABLE, "--keep")
    App.launch(launch.exe)
    assert launch.popen_calls[1]["env"][VARIABLE] == "--keep"


def test_a_launch_merges_with_the_runners_own_value(
    launch: Launch, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(VARIABLE, "--from-runner")
    App.launch(launch.exe, webview_debug_port=9223)
    assert launch.popen_calls[0]["env"][VARIABLE] == "--from-runner --remote-debugging-port=9223"


def test_a_launch_merges_with_the_env_argument_without_changing_it(
    launch: Launch, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(VARIABLE, "--from-runner")
    env = {VARIABLE: "--from-env", "OTHER": "1"}
    App.launch(launch.exe, env=env, webview_debug_port=9223)
    seen = launch.popen_calls[0]["env"]
    assert seen[VARIABLE] == "--from-env --remote-debugging-port=9223" and seen["OTHER"] == "1"
    assert env == {VARIABLE: "--from-env", "OTHER": "1"}


def test_a_launch_that_conflicts_with_the_variable_fails_before_starting(
    launch: Launch, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(VARIABLE, "--remote-debugging-port=1234")
    with pytest.raises(AppError, match="already contains"):
        App.launch(launch.exe, webview_debug_port=9223)
    assert launch.popen_calls == []


def test_a_bad_port_fails_before_starting(launch: Launch) -> None:
    with pytest.raises(ValueError, match="webview_debug_port"):
        App.launch(launch.exe, webview_debug_port=70000)
    assert launch.popen_calls == []


def test_an_elevated_launch_through_the_shell_cannot_take_the_port(launch: Launch) -> None:
    with pytest.raises(AppError, match=r"elevated launch through the shell cannot take"):
        App.launch(launch.exe, elevated=True, webview_debug_port=9223)
    assert launch.executed == [] and launch.popen_calls == []


def test_an_elevated_runner_can_pass_the_port(launch: Launch) -> None:
    launch.runner_elevated = True
    App.launch(launch.exe, elevated=True, webview_debug_port=9223)
    assert launch.popen_calls[0]["env"][VARIABLE] == "--remote-debugging-port=9223"


def test_the_apps_group_passes_the_port_on(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: dict[str, Any] = {}

    def fake_launch(path: Any, args: Any = (), **kwargs: Any) -> Any:
        seen.update(kwargs)
        return SimpleNamespace(launched=False)

    monkeypatch.setattr(App, "launch", staticmethod(fake_launch))
    Apps().launch(tmp_path / "Host.exe", webview_debug_port=9224)
    assert seen["webview_debug_port"] == 9224


# -- the configuration ----------------------------------------------------------------------------


def write(tmp_path: Path, body: str, name: str = "pyproject.toml") -> None:
    (tmp_path / name).write_text(body, encoding="utf-8")


def test_the_port_is_read_from_the_app_table(tmp_path: Path) -> None:
    write(tmp_path, "[tool.wintestkit.app]\npath = 'Host.exe'\nwebview_debug_port = 9223\n")
    config = load_config(tmp_path)
    assert config.app is not None and config.app.webview_debug_port == 9223


def test_the_port_defaults_to_none(tmp_path: Path) -> None:
    write(tmp_path, "[tool.wintestkit.app]\npath = 'Host.exe'\n")
    config = load_config(tmp_path)
    assert config.app is not None and config.app.webview_debug_port is None


def test_the_port_can_be_set_in_local_yaml_and_overridden(tmp_path: Path) -> None:
    write(tmp_path, "[tool.wintestkit.app]\npath = 'Host.exe'\nwebview_debug_port = 9223\n")
    write(tmp_path, "app:\n  webview_debug_port: 9400\n", "wintestkit.local.yaml")
    config = load_config(tmp_path)
    assert config.app is not None and config.app.webview_debug_port == 9400
    config = load_config(tmp_path, {"app.webview_debug_port": 9500})
    assert config.app is not None and config.app.webview_debug_port == 9500


@pytest.mark.parametrize("value", ["0", "65536", "-1", "'9223'", "true", "1.5"])
def test_a_bad_port_in_the_configuration_names_the_key(tmp_path: Path, value: str) -> None:
    write(tmp_path, f"[tool.wintestkit.app]\npath = 'Host.exe'\nwebview_debug_port = {value}\n")
    with pytest.raises(ConfigError, match="webview_debug_port") as error:
        load_config(tmp_path)
    assert error.value.key == "app.webview_debug_port"


def test_a_configured_launch_passes_the_port(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    write(
        tmp_path,
        f"[tool.wintestkit.app]\npath = '{(tmp_path / 'Host.exe').as_posix()}'\n"
        "webview_debug_port = 9223\n",
    )
    seen: dict[str, Any] = {}
    monkeypatch.setattr(win32, "pids_by_name", lambda name: [])
    monkeypatch.setattr(
        App, "launch", staticmethod(lambda path, **kwargs: seen.update(kwargs) or "app")
    )
    assert launch_app(load_config(tmp_path)) == "app"  # type: ignore[comparison-overlap]
    assert seen["webview_debug_port"] == 9223
