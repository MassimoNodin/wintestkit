from pathlib import Path

import pytest

from wintestkit.config import find_project_root, load_config
from wintestkit.errors import ConfigError


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("WTK_APP_PATH", "WTK_LAUNCH", "WTK_TIMEOUT", "WTK_INPUT_MODE", "WTK_SCREENSHOTS"):
        monkeypatch.delenv(name, raising=False)


def test_yaml_only_project_and_local_path(tmp_path: Path) -> None:
    (tmp_path / "wintestkit.yaml").write_text(
        "timeout: 4\napp:\n  process: Target.exe\n", encoding="utf-8"
    )
    (tmp_path / "wintestkit.local.yaml").write_text(
        "app:\n  path: bin/Target.exe\n  args: ['--test']\n", encoding="utf-8"
    )
    nested = tmp_path / "tests"
    nested.mkdir()
    assert find_project_root(nested) == tmp_path
    config = load_config(nested)
    assert config.found
    assert config.timeout == 4
    assert config.app is not None
    assert config.app.process == "Target.exe"
    assert config.app.path == tmp_path / "bin" / "Target.exe"
    assert config.app.args == ("--test",)


def test_configuration_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.wintestkit]\ntimeout = 1\n", encoding="utf-8")
    (tmp_path / "wintestkit.yaml").write_text("timeout: 2\n", encoding="utf-8")
    (tmp_path / "wintestkit.local.toml").write_text(
        "[tool.wintestkit]\ntimeout = 3\n", encoding="utf-8"
    )
    assert load_config(tmp_path).timeout == 3
    (tmp_path / "wintestkit.local.yaml").write_text("timeout: 4\n", encoding="utf-8")
    assert load_config(tmp_path).timeout == 4
    monkeypatch.setenv("WTK_TIMEOUT", "5")
    assert load_config(tmp_path).timeout == 5
    assert load_config(tmp_path, {"timeout": 6}).timeout == 6


@pytest.mark.parametrize(
    "source",
    [
        "timeout: [",
        "- timeout",
        "timeout: 1\ntimeout: 2",
        "timeout: -1",
        "timeout: .inf",
        "unexpected: true",
        "!!python/object:os.system {}",
    ],
)
def test_invalid_shared_yaml_is_rejected(tmp_path: Path, source: str) -> None:
    (tmp_path / "wintestkit.yaml").write_text(source, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(tmp_path)


def test_bad_local_file_does_not_silently_fall_back(tmp_path: Path) -> None:
    (tmp_path / "wintestkit.yaml").write_text("{}", encoding="utf-8")
    (tmp_path / "wintestkit.local.yaml").write_text("timeout: wrong", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(tmp_path)


def test_shared_yaml_accepts_relative_app_path_and_args(tmp_path: Path) -> None:
    (tmp_path / "wintestkit.yaml").write_text(
        "app:\n  path: bin/Debug/App.exe\n  args: ['--test-mode']\n", encoding="utf-8"
    )
    config = load_config(tmp_path)
    assert config.app is not None
    assert config.app.path == tmp_path.resolve() / "bin" / "Debug" / "App.exe"
    assert config.app.args == ("--test-mode",)


@pytest.mark.parametrize("value", ["C:/Apps/App.exe", r"C:\Apps\App.exe", r"\\host\share\App.exe"])
def test_shared_yaml_accepts_an_absolute_app_path(tmp_path: Path, value: str) -> None:
    # Discouraged (it only works where the file is in the same place) and warned about by the
    # editor, but it is the user's choice, so it is not an error.
    (tmp_path / "wintestkit.yaml").write_text(f"app:\n  path: '{value}'\n", encoding="utf-8")
    config = load_config(tmp_path)
    assert config.app is not None
    assert config.app.path == Path(value)


def test_local_yaml_overrides_a_shared_relative_app_path(tmp_path: Path) -> None:
    (tmp_path / "wintestkit.yaml").write_text("app:\n  path: bin/App.exe\n", encoding="utf-8")
    (tmp_path / "wintestkit.local.yaml").write_text(
        "app:\n  path: 'C:/Apps/Mine.exe'\n", encoding="utf-8"
    )
    config = load_config(tmp_path)
    assert config.app is not None
    assert config.app.path == Path("C:/Apps/Mine.exe")


def test_highlight_color_is_normalised_and_an_unquoted_hash_is_explained(tmp_path: Path) -> None:
    (tmp_path / "wintestkit.yaml").write_text("highlight_color: '#00ff7f'\n", encoding="utf-8")
    assert load_config(tmp_path).highlight_color == "#00FF7F"
    (tmp_path / "wintestkit.yaml").write_text("highlight_color: #00ff7f\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="quote it in YAML") as error:
        load_config(tmp_path)
    assert error.value.key == "highlight_color"
