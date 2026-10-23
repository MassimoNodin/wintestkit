"""Unit tests for the configuration loader."""

from pathlib import Path

import pytest

from wintestkit.config import find_project_root, load_config
from wintestkit.errors import ConfigError

ENV_VARS = [
    "WTK_APP_PATH",
    "WTK_LAUNCH",
    "WTK_TIMEOUT",
    "WTK_INPUT_MODE",
    "WTK_SCREENSHOTS",
    "WTK_REPLAY",
    "WTK_REPLAY_FPS",
    "WTK_REPLAY_SCOPE",
    "WTK_REPLAY_MAX_FRAMES",
    "WTK_REPLAY_MAX_BYTES",
]


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def write_pyproject(directory: Path, body: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "pyproject.toml").write_text(body, encoding="utf-8")
    return directory


FULL = """
[project]
name = "demo"

[tool.wintestkit]
launch = "per-test"
timeout = 5
input_mode = "mouse"
screenshots = "every-step"
report_dir = "out/report"
highlight_actions = true
slow_mo_ms = 250
python_paths = [".", "lib"]

[tool.wintestkit.app]
path = "bin/App.exe"
args = ["--fast", "x"]
cwd = "work"
env = { A = "1" }
process = "Other.exe"
startup_timeout = 12.5
close_timeout = 3
"""


def test_defaults_without_pyproject(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    assert config.found is False
    assert config.root == tmp_path.resolve()
    assert config.app is None
    assert config.launch == "per-test"
    assert config.timeout == 10.0
    assert config.input_mode == "pattern"
    assert config.screenshots == "on-failure"
    assert config.report_dir == tmp_path.resolve() / "wtk-report"
    assert config.highlight_actions is False
    assert config.highlight_color == "#FF0000"
    assert config.slow_mo_ms == 0
    assert config.python_paths == (tmp_path.resolve(),)
    assert (config.replay, config.replay_fps, config.replay_scope) == ("off", 15.0, "window")
    assert (config.replay_max_frames, config.replay_max_bytes) == (3000, 104857600)


def test_replay_config_and_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_pyproject(
        tmp_path,
        '[tool.wintestkit]\nreplay = "retain-on-failure"\nreplay_fps = 12\nreplay_scope = "desktop"\nreplay_max_frames = 40\nreplay_max_bytes = 4096\n',
    )
    cfg = load_config(tmp_path)
    assert (cfg.replay, cfg.replay_fps, cfg.replay_scope) == ("retain-on-failure", 12.0, "desktop")
    assert (cfg.replay_max_frames, cfg.replay_max_bytes) == (40, 4096)
    monkeypatch.setenv("WTK_REPLAY", "on")
    monkeypatch.setenv("WTK_REPLAY_FPS", "25")
    monkeypatch.setenv("WTK_REPLAY_SCOPE", "window")
    assert load_config(tmp_path).replay == "on"
    assert load_config(tmp_path).replay_fps == 25.0
    assert load_config(tmp_path).replay_scope == "window"


@pytest.mark.parametrize("mode", ["on", "off", "retain-on-failure"])
def test_replay_mode_in_yaml(tmp_path: Path, mode: str) -> None:
    (tmp_path / "wintestkit.yaml").write_text(f"replay: {mode}\n", encoding="utf-8")
    assert load_config(tmp_path).replay == mode


@pytest.mark.parametrize(
    "body", ["replay_fps = 31", "replay_fps = 0", "replay_max_frames = 0", "replay_max_bytes = -1"]
)
def test_bad_replay_limits(tmp_path: Path, body: str) -> None:
    write_pyproject(tmp_path, f"[tool.wintestkit]\n{body}\n")
    with pytest.raises(ConfigError):
        load_config(tmp_path)


def test_pyproject_without_wintestkit_table_is_not_found(tmp_path: Path) -> None:
    write_pyproject(tmp_path, '[project]\nname = "x"\n')
    config = load_config(tmp_path)
    assert config.found is False
    assert find_project_root(tmp_path) is None


def test_every_key(tmp_path: Path) -> None:
    root = write_pyproject(tmp_path, FULL).resolve()
    config = load_config(tmp_path)
    assert config.found is True
    assert config.root == root
    assert config.launch == "per-test"
    assert config.timeout == 5.0
    assert config.input_mode == "mouse"
    assert config.screenshots == "every-step"
    assert config.report_dir == root / "out" / "report"
    assert config.highlight_actions is True
    assert config.slow_mo_ms == 250
    assert config.python_paths == (root, root / "lib")
    assert config.app is not None
    assert config.app.path == root / "bin" / "App.exe"
    assert config.app.args == ("--fast", "x")
    assert config.app.cwd == root / "work"
    assert dict(config.app.env) == {"A": "1"}
    assert config.app.process == "Other.exe"
    assert config.app.process_name == "Other.exe"
    assert config.app.startup_timeout == 12.5
    assert config.app.close_timeout == 3.0


def test_process_name_falls_back_to_path_name(tmp_path: Path) -> None:
    write_pyproject(tmp_path, '[tool.wintestkit.app]\npath = "bin/DemoApp.exe"\n')
    config = load_config(tmp_path)
    assert config.app is not None
    assert config.app.process_name == "DemoApp.exe"
    assert config.app.startup_timeout == 30.0
    assert config.app.close_timeout == 10.0


def test_process_name_needs_process_or_path(tmp_path: Path) -> None:
    write_pyproject(tmp_path, "[tool.wintestkit.app]\nargs = []\n")
    config = load_config(tmp_path)
    assert config.app is not None
    with pytest.raises(ConfigError):
        _ = config.app.process_name


def test_load_from_subdirectory_and_file(tmp_path: Path) -> None:
    root = write_pyproject(tmp_path, FULL).resolve()
    nested = root / "tests" / "deep"
    nested.mkdir(parents=True)
    test_file = nested / "test_x.py"
    test_file.write_text("", encoding="utf-8")
    assert find_project_root(nested) == root
    assert load_config(nested).root == root
    assert load_config(test_file).root == root


def test_nearest_pyproject_with_table_wins(tmp_path: Path) -> None:
    write_pyproject(tmp_path, FULL)
    inner = write_pyproject(tmp_path / "inner", "[tool.wintestkit]\ntimeout = 2\n").resolve()
    assert load_config(inner).root == inner
    assert load_config(inner).timeout == 2.0


def test_environment_overrides_pyproject(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_pyproject(tmp_path, FULL)
    monkeypatch.setenv("WTK_TIMEOUT", "7.5")
    monkeypatch.setenv("WTK_LAUNCH", "attach")
    monkeypatch.setenv("WTK_INPUT_MODE", "pattern")
    monkeypatch.setenv("WTK_SCREENSHOTS", "off")
    monkeypatch.setenv("WTK_APP_PATH", "elsewhere/Other.exe")
    config = load_config(tmp_path)
    assert config.timeout == 7.5
    assert config.launch == "attach"
    assert config.input_mode == "pattern"
    assert config.screenshots == "off"
    assert config.app is not None
    assert config.app.path == tmp_path.resolve() / "elsewhere" / "Other.exe"
    assert config.app.args == ("--fast", "x")  # other app keys survive


def test_overrides_beat_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_pyproject(tmp_path, FULL)
    monkeypatch.setenv("WTK_TIMEOUT", "7.5")
    config = load_config(tmp_path, {"timeout": 1.5, "app.process": "Z.exe", "slow_mo_ms": None})
    assert config.timeout == 1.5
    assert config.slow_mo_ms == 250  # None overrides are ignored
    assert config.app is not None
    assert config.app.process == "Z.exe"


def test_env_app_path_creates_app_section(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WTK_APP_PATH", str(tmp_path / "A.exe"))
    config = load_config(tmp_path)
    assert config.app is not None
    assert config.app.path == tmp_path / "A.exe"


def test_absolute_paths_are_kept(tmp_path: Path) -> None:
    absolute = (tmp_path / "abs" / "App.exe").resolve()
    write_pyproject(
        tmp_path,
        f'[tool.wintestkit]\nreport_dir = "{absolute.parent.as_posix()}"\n'
        f'[tool.wintestkit.app]\npath = "{absolute.as_posix()}"\n',
    )
    config = load_config(tmp_path)
    assert config.report_dir == absolute.parent
    assert config.app is not None
    assert config.app.path == absolute


def test_unknown_top_level_key(tmp_path: Path) -> None:
    write_pyproject(tmp_path, "[tool.wintestkit]\nbogus = 1\n")
    with pytest.raises(ConfigError, match=r"unknown key tool\.wintestkit\.bogus") as exc_info:
        load_config(tmp_path)
    assert exc_info.value.key == "bogus"


def test_unknown_app_key(tmp_path: Path) -> None:
    write_pyproject(tmp_path, "[tool.wintestkit.app]\nbogus = 1\n")
    with pytest.raises(ConfigError, match=r"app\.bogus") as exc_info:
        load_config(tmp_path)
    assert exc_info.value.key == "app.bogus"


def test_unknown_override_key(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="nope"):
        load_config(tmp_path, {"nope": 1})
    with pytest.raises(ConfigError, match=r"app\.nope"):
        load_config(tmp_path, {"app.nope": 1})


def test_the_removed_per_session_launch_mode_means_a_fresh_app_per_test(tmp_path: Path) -> None:
    write_pyproject(tmp_path, 'launch = "per-session"')
    assert load_config(tmp_path).launch == "per-test"


@pytest.mark.parametrize(
    ("body", "key", "fragment"),
    [
        ('launch = "sometimes"', "launch", "'per-test', 'attach'"),
        ('input_mode = "touch"', "input_mode", "'pattern', 'mouse'"),
        ('screenshots = "always"', "screenshots", "'off', 'on-failure', 'every-step'"),
        ("timeout = 0", "timeout", "greater than 0"),
        ('timeout = "fast"', "timeout", "expected a number"),
        ("timeout = true", "timeout", "expected a number"),
        ("slow_mo_ms = -1", "slow_mo_ms", "non-negative integer"),
        ("slow_mo_ms = 1.5", "slow_mo_ms", "non-negative integer"),
        ('highlight_actions = "yes"', "highlight_actions", "true or false"),
        ('highlight_color = "red"', "highlight_color", "colour like '#FF0000'"),
        ('highlight_color = "#FFF"', "highlight_color", "colour like '#FF0000'"),
        ("highlight_color = 16711680", "highlight_color", "colour like '#FF0000'"),
        ("python_paths = [1]", "python_paths", "list of strings"),
        ('report_dir = ""', "report_dir", "non-empty string"),
    ],
)
def test_bad_values_name_the_key(tmp_path: Path, body: str, key: str, fragment: str) -> None:
    write_pyproject(tmp_path, f"[tool.wintestkit]\n{body}\n")
    with pytest.raises(ConfigError) as exc_info:
        load_config(tmp_path)
    assert exc_info.value.key == key
    assert fragment in str(exc_info.value)
    assert f"tool.wintestkit.{key}" in str(exc_info.value)


@pytest.mark.parametrize(
    ("body", "key"),
    [
        ('args = "x"', "app.args"),
        ("env = { A = 1 }", "app.env"),
        ("startup_timeout = -3", "app.startup_timeout"),
        ('path = ""', "app.path"),
    ],
)
def test_bad_app_values(tmp_path: Path, body: str, key: str) -> None:
    write_pyproject(tmp_path, f"[tool.wintestkit.app]\n{body}\n")
    with pytest.raises(ConfigError) as exc_info:
        load_config(tmp_path)
    assert exc_info.value.key == key


def test_app_must_be_a_table(tmp_path: Path) -> None:
    write_pyproject(tmp_path, '[tool.wintestkit]\napp = "x"\n')
    with pytest.raises(ConfigError, match="expected a table"):
        load_config(tmp_path)


def test_bad_environment_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WTK_TIMEOUT", "soon")
    with pytest.raises(ConfigError, match="WTK_TIMEOUT"):
        load_config(tmp_path)
    monkeypatch.setenv("WTK_TIMEOUT", "3")
    monkeypatch.setenv("WTK_LAUNCH", "maybe")
    with pytest.raises(ConfigError, match="launch"):
        load_config(tmp_path)


def test_attach_requires_app_process_or_path(tmp_path: Path) -> None:
    write_pyproject(tmp_path, '[tool.wintestkit]\nlaunch = "attach"\n')
    with pytest.raises(
        ConfigError, match=r"launch='attach' needs tool\.wintestkit\.app\.process or app\.path"
    ):
        load_config(tmp_path)
    config = load_config(tmp_path, {"app.process": "DemoApp.exe"})
    assert config.launch == "attach"
    assert config.app is not None
    assert config.app.process_name == "DemoApp.exe"


def test_invalid_toml_reports_file(tmp_path: Path) -> None:
    write_pyproject(tmp_path, "[tool.wintestkit\n")
    with pytest.raises(ConfigError, match=r"pyproject.toml"):
        find_project_root(tmp_path)
