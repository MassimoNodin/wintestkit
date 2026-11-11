from dataclasses import replace
from pathlib import Path

import pytest

from wintestkit import runtime
from wintestkit.config import load_config
from wintestkit.errors import ConfigError
from wintestkit.inspector import bootstrap, probe, sessions
from wintestkit.inspector.models import ProcessIdentity
from wintestkit.inspector.write_policy import parse_write_allowlist


def test_repository_policy_translation(tmp_path: Path) -> None:
    (tmp_path / "wintestkit.yaml").write_text(
        "inspector:\n  writes:\n    allow:\n      - Example.View.Ready\n"
        "      - Example.View.Set(System.String,System.Int64)\n",
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    assert parse_write_allowlist(config.inspector.writes_allow)[1] == {
        "properties": [{"typeFullName": "Example.View", "memberName": "Ready"}],
        "methods": [
            {"typeFullName": "Example.View", "memberKey": "Set(System.String,System.Int64)"}
        ],
    }


@pytest.mark.parametrize(
    "value",
    [
        "Example.View.Name",
        [1],
        [""],
        ["Example.View.*"],
        ["Example.View.Set(System.String, System.Int64)"],
        ["Example.View.Set(System.String[])"],
        ["Example.View.Name", "Example.View.Name"],
        [f"Example.View.P{i}" for i in range(129)],
    ],
)
def test_reject_invalid_entries(value: object) -> None:
    with pytest.raises(ValueError):
        parse_write_allowlist(value)


def test_local_policy_rejected(tmp_path: Path) -> None:
    (tmp_path / "wintestkit.yaml").write_text("{}", encoding="utf-8")
    (tmp_path / "wintestkit.local.yaml").write_text(
        "inspector:\n  writes:\n    allow: [Example.View.Name]\n", encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="repository"):
        load_config(tmp_path)


def test_policy_change_replaces_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Registry:
        def __init__(self, **kwargs: object) -> None:
            self.options = kwargs
            self.closed = False

        def close_all(self) -> None:
            self.closed = True

    monkeypatch.setattr(sessions, "SessionRegistry", Registry)
    config = load_config(tmp_path)
    with runtime.config_scope(config):
        original = runtime.inspector_sessions()
    config = replace(
        config, inspector=replace(config.inspector, writes_allow=("Example.View.Name",))
    )
    with runtime.config_scope(config):
        updated = runtime.inspector_sessions()
        assert updated is not original
        assert original.closed
        assert updated.options["writes_allow"] == ("Example.View.Name",)


def test_bootstrap_includes_translated_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json
    import os

    if os.name != "nt":
        pytest.skip("Windows ACL API")
    monkeypatch.setattr(bootstrap, "_local_app_data", lambda: tmp_path)
    sid = probe.current_security()[0]
    settings = bootstrap.create_bootstrap(
        ProcessIdentity(42, "2026-10-29T00:00:00Z"),
        sid,
        "1",
        writes_allow=("Example.View.Name", "Example.View.Reset()"),
    )
    try:
        assert json.loads(settings.path.read_text(encoding="utf-8"))["writeAllowlist"] == {
            "properties": [{"typeFullName": "Example.View", "memberName": "Name"}],
            "methods": [{"typeFullName": "Example.View", "memberKey": "Reset()"}],
        }
    finally:
        settings.cleanup()
