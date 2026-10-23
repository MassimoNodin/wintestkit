"""Configuration contract for portable object previews."""

from pathlib import Path

import pytest

from wintestkit.config import LOCAL_IGNORE_PATTERNS, load_config, sync_object_previews_ignore
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


def test_share_setting_is_off_by_default_and_read_from_the_repository_only(
    tmp_path: Path,
) -> None:
    (tmp_path / "wintestkit.yaml").write_text("timeout: 5\n", encoding="utf-8")
    assert load_config(tmp_path).object_previews_share is False
    (tmp_path / "wintestkit.yaml").write_text("object_previews_share: true\n", encoding="utf-8")
    assert load_config(tmp_path).object_previews_share is True
    # One machine's own file cannot decide for the whole repository.
    (tmp_path / "wintestkit.local.yaml").write_text(
        "object_previews_share: false\n", encoding="utf-8"
    )
    assert load_config(tmp_path).object_previews_share is True
    (tmp_path / "wintestkit.yaml").write_text("timeout: 5\n", encoding="utf-8")
    (tmp_path / "wintestkit.local.yaml").write_text(
        "object_previews_share: true\n", encoding="utf-8"
    )
    assert load_config(tmp_path).object_previews_share is False


def test_share_setting_must_be_boolean(tmp_path: Path) -> None:
    (tmp_path / "wintestkit.yaml").write_text("object_previews_share: maybe\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="object_previews_share"):
        load_config(tmp_path)


def test_sync_ignores_the_folder_unless_shared(tmp_path: Path) -> None:
    ignore = tmp_path / ".gitignore"
    sync_object_previews_ignore(tmp_path, False)
    assert ignore.read_text(encoding="utf-8").splitlines() == ["object-previews/"]
    sync_object_previews_ignore(tmp_path, False)
    assert ignore.read_text(encoding="utf-8").splitlines() == ["object-previews/"]
    sync_object_previews_ignore(tmp_path, True)
    assert ignore.read_text(encoding="utf-8").splitlines() == []


def test_sync_keeps_other_rules_and_respects_the_users_own_spelling(tmp_path: Path) -> None:
    ignore = tmp_path / ".gitignore"
    ignore.write_bytes(b".venv/\n/object-previews/")
    sync_object_previews_ignore(tmp_path, False)
    assert ignore.read_bytes() == b".venv/\n/object-previews/"
    sync_object_previews_ignore(tmp_path, True)
    assert ignore.read_bytes() == b".venv/\n/object-previews/"
    ignore.write_bytes(b".venv/\nwtk-report/")
    sync_object_previews_ignore(tmp_path, False)
    assert ignore.read_text(encoding="utf-8").splitlines() == [
        ".venv/",
        "wtk-report/",
        "object-previews/",
    ]
    sync_object_previews_ignore(tmp_path, True)
    assert ignore.read_text(encoding="utf-8").splitlines() == [".venv/", "wtk-report/"]
