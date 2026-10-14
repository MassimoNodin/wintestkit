"""Inspect the real WPF demo tree and a physical point."""

import json
from pathlib import Path

import pytest
from support import DemoProcess

from wintestkit.app import App
from wintestkit.cli import main
from wintestkit.commands import common
from wintestkit.engine.locator import Locator
from wintestkit.engine.query import query_all

pytestmark = pytest.mark.integration


def test_inspect_demo(
    tmp_path: Path,
    demo_process: DemoProcess,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.wintestkit]\n", encoding="utf-8")
    app = App.attach(pid=demo_process.pid)
    monkeypatch.setattr(common, "attach_app", lambda cfg: app)
    prefix = ["--root", str(tmp_path), "inspect"]
    assert main(prefix) == 0
    text = capsys.readouterr().out
    assert 'Group "Credentials"' in text
    assert 'Button "Sign in"' in text
    assert main([*prefix, "--window", "/WTK/", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["info"]["name"] == "WTK Demo"
    assert main([*prefix, "--all-windows", "--depth", "0", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["windows"]
    button = query_all(app.main_window(), Locator(control_type="Button", name="Sign in"))[0]
    rect = button.rect
    assert rect is not None
    point = f"{rect.left + rect.width // 2},{rect.top + rect.height // 2}"
    assert main([*prefix, "--at", point, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["element"]["controlType"] == "Button"
    assert "Invoke" in data["element"]["patterns"]
    assert data["ancestors"]
