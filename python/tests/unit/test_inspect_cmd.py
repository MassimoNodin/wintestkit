"""Inspection command selection, bounds, and output."""

import json
from pathlib import Path

import pytest
from fakes import FakeApp, FakeElement

from wintestkit.cli import main
from wintestkit.commands import common
from wintestkit.uia import element


@pytest.fixture
def inspection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, FakeElement]:
    (tmp_path / "pyproject.toml").write_text("[tool.wintestkit]\n", encoding="utf-8")
    button = FakeElement("Button", "Sign in")
    window = FakeElement("Window", "Demo", children=[button])
    app = FakeApp([window, FakeElement("Window", "Other")])
    monkeypatch.setattr(common, "attach_app", lambda cfg: app)
    monkeypatch.setattr(element, "from_point", lambda *coords: button)
    return tmp_path, button


def test_tree_selection(
    inspection: tuple[Path, FakeElement], capsys: pytest.CaptureFixture[str]
) -> None:
    root, _ = inspection
    assert main(["--root", str(root), "inspect", "--window", "/Dem/", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["children"][0]["info"]["name"] == "Sign in"
    assert main(["--root", str(root), "inspect", "--all-windows", "--depth", "0", "--json"]) == 0
    windows = json.loads(capsys.readouterr().out)["windows"]
    assert len(windows) == 2
    assert all(not window["children"] for window in windows)
    assert main(["--root", str(root), "inspect", "--window", "Missing"]) == 1
    assert "No matching" in capsys.readouterr().err
    assert main(["--root", str(root), "inspect", "--window", "/.*/"]) == 1
    assert "Ambiguous" in capsys.readouterr().err


def test_point_and_process_scope(
    inspection: tuple[Path, FakeElement], capsys: pytest.CaptureFixture[str]
) -> None:
    root, button = inspection
    assert main(["--root", str(root), "inspect", "--at=-20,30", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["element"]["controlType"] == "Button"
    assert data["ancestors"][0]["name"] == "Demo"
    button.process_id = 999
    assert main(["--root", str(root), "inspect", "--at", "1,2"]) == 1
    assert "configured app" in capsys.readouterr().err


@pytest.mark.parametrize(
    "options",
    [
        ["--depth", "-1"],
        ["--depth", "51"],
        ["--at", "1"],
        ["--at", "1,2,3"],
        ["--at", "2147483648,0"],
        ["--window", "/[/"],
        ["--window", "Demo", "--all-windows"],
    ],
)
def test_invalid_arguments(options: list[str]) -> None:
    assert main(["inspect", *options]) == 2
