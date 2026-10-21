"""Configuration contract for portable object previews."""

from pathlib import Path

import pytest

from wintestkit.config import LOCAL_IGNORE_PATTERNS, load_config
from wintestkit.errors import ConfigError


@pytest.fixture(autouse=True)
def clean_preview_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WTK_OBJECT_PREVIEWS", raising=False)


def test_object_previews_default_and_portable_location(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    assert config.object_previews is True
    assert not any("object-previews" in pattern for pattern in LOCAL_IGNORE_PATTERNS)


@pytest.mark.parametrize(
    "extension,body",
    [
        ("toml", "[tool.wintestkit]\nobject_previews = false\n"),
        ("yaml", "object_previews: false\n"),
    ],
)
def test_object_previews_project_setting(tmp_path: Path, extension: str, body: str) -> None:
    filename = "pyproject.toml" if extension == "toml" else "wintestkit.yaml"
    (tmp_path / filename).write_text(body, encoding="utf-8")
    assert load_config(tmp_path).object_previews is False


@pytest.mark.parametrize(
    "value,expected", [("true", True), ("FALSE", False), ("1", True), ("0", False)]
)
def test_object_previews_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str, expected: bool
) -> None:
    monkeypatch.setenv("WTK_OBJECT_PREVIEWS", value)
    assert load_config(tmp_path).object_previews is expected


def test_object_previews_environment_and_override_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "wintestkit.yaml").write_text("object_previews: true\n", encoding="utf-8")
    monkeypatch.setenv("WTK_OBJECT_PREVIEWS", "false")
    assert load_config(tmp_path).object_previews is False
    assert load_config(tmp_path, {"object_previews": True}).object_previews is True


@pytest.mark.parametrize("value", ["yes", "off", "arbitrary"])
def test_object_previews_rejects_invalid_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("WTK_OBJECT_PREVIEWS", value)
    with pytest.raises(ConfigError, match="WTK_OBJECT_PREVIEWS"):
        load_config(tmp_path)


@pytest.mark.parametrize("value", ["false", 0, []])
def test_object_previews_requires_boolean_override(tmp_path: Path, value: object) -> None:
    with pytest.raises(ConfigError, match="object_previews"):
        load_config(tmp_path, {"object_previews": value})


def test_object_previews_none_override_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WTK_OBJECT_PREVIEWS", "false")
    assert load_config(tmp_path, {"object_previews": None}).object_previews is False
