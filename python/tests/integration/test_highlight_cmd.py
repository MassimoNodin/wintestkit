"""Highlight and check commands against the real WPF demo."""

import json
from pathlib import Path

import pytest
from support import DemoProcess

from wintestkit.app import App
from wintestkit.cli import main
from wintestkit.commands import common
from wintestkit.config import load_config
from wintestkit.targets import ModuleLoader, Target, resolve_target

pytestmark = pytest.mark.integration

SOURCE = (
    "from wintestkit import Screen, Window, Element, Elements\n"
    "class Main(Screen):\n"
    "    window = Window(title='WTK Demo')\n"
    "    sign_in = Element(control_type='Button', name='Sign in')\n"
    "    oks = Elements(control_type='Button', name='OK')\n"
    "class Failures(Screen):\n"
    "    window = Window(title='WTK Demo')\n"
    "    ambiguous = Element(control_type='Button', name='OK')\n"
    "    missing = Element(control_type='Button', name='Not a button')\n"
)


@pytest.fixture
def command_project(
    tmp_path: Path, demo_process: DemoProcess, monkeypatch: pytest.MonkeyPatch
) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.wintestkit]\n[tool.wintestkit.app]\nprocess = 'DemoApp.exe'\n", encoding="utf-8"
    )
    (tmp_path / "command_demo.py").write_text(SOURCE, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    app = App.attach(pid=demo_process.pid)
    monkeypatch.setattr(common, "attach_app", lambda *args, **kwargs: app)
    return tmp_path


@pytest.mark.parametrize(
    "target,status,code",
    [
        ("Main.sign_in", "found", 0),
        ("Failures.ambiguous", "ambiguous", 1),
        ("Failures.missing", "not_found", 1),
        ("Main", "found", 0),
    ],
)
def test_highlight_live_targets(
    command_project: Path, capsys: pytest.CaptureFixture[str], target: str, status: str, code: int
) -> None:
    assert (
        main(
            [
                "--root",
                str(command_project),
                "highlight",
                f"command_demo.py::{target}",
                "--duration",
                "30",
                "--json",
            ]
        )
        == code
    )
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == status
    if status == "found":
        assert result["element"]["rect"]["width"] > 0
    else:
        assert result["diagnostic"]["matchCount"] == (2 if status == "ambiguous" else 0)


def test_check_live_screen_and_failures(
    command_project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--root", str(command_project), "check", "command_demo.py::Main", "--json"]) == 0
    results = json.loads(capsys.readouterr().out)["results"]
    assert len(results) == 3
    assert all(result["status"] == "found" for result in results)
    assert (
        main(["--root", str(command_project), "check", "command_demo.py::Failures", "--json"]) == 1
    )
    assert [result["status"] for result in json.loads(capsys.readouterr().out)["results"]] == [
        "found",
        "ambiguous",
        "not_found",
    ]


def test_highlight_examples_target(
    demo_process: DemoProcess, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(__file__).resolve().parents[3] / "examples" / "demo-tests"
    monkeypatch.syspath_prepend(str(root))
    loader = ModuleLoader(load_config(root))
    target = Target(root / "screens" / "main.py", "MainScreen.sign_in")
    result = resolve_target(App.attach(pid=demo_process.pid), loader, target)
    assert result.status == "found"
    assert result.element is not None
    assert result.element.name == "Sign in"
