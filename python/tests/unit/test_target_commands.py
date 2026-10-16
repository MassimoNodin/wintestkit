"""CLI output, options and exit codes for highlight/check."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fakes import FakeElement

from wintestkit import targets
from wintestkit.cli import main
from wintestkit.commands import common
from wintestkit.engine import overlay
from wintestkit.targets import CheckResult, ElementResult, TargetError


@pytest.fixture
def command_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.wintestkit]\n[tool.wintestkit.app]\nprocess = 'Demo.exe'\n", encoding="utf-8"
    )
    record: dict[str, Any] = {"root": tmp_path, "flashes": [], "closed": []}
    app = SimpleNamespace(launched=False, close=lambda **kwargs: record["closed"].append(kwargs))
    record["app"] = app
    monkeypatch.setattr(common, "attach_app", lambda cfg, **kwargs: app)
    monkeypatch.setattr(targets.ModuleLoader, "get_element", lambda self, target: (object, "ok"))
    monkeypatch.setattr(targets.ModuleLoader, "get_page", lambda self, target: object)
    monkeypatch.setattr(targets.ModuleLoader, "pages_in", lambda self, file: {"Main": object})
    monkeypatch.setattr(
        overlay, "flash", lambda *args, **kwargs: record["flashes"].append((args, kwargs))
    )
    record["info"] = FakeElement("Button", "OK").info()
    return record


def invoke(record: dict[str, Any], *args: str) -> int:
    return main(["--root", str(record["root"]), *args])


def test_highlight_json_and_overlay_options(
    command_setup: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    record = command_setup
    seen: list[float] = []

    def resolve(app: Any, loader: Any, target: Any, timeout: float) -> ElementResult:
        seen.append(timeout)
        return ElementResult("found", 1.0, element=record["info"])

    monkeypatch.setattr(targets, "resolve_target", resolve)
    assert (
        invoke(
            record,
            "highlight",
            "main.py::Main.ok",
            "--duration",
            "25",
            "--timeout",
            "0.5",
            "--json",
        )
        == 0
    )
    assert seen == [0.5]
    assert record["flashes"] == [((record["info"].rect, 25), {"block": True})]
    assert json.loads(capsys.readouterr().out)["element"]["name"] == "OK"
    assert not record["closed"]


@pytest.mark.parametrize("status", ["not_found", "ambiguous", "error"])
def test_highlight_failed_resolution(
    command_setup: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: str,
) -> None:
    monkeypatch.setattr(
        targets,
        "resolve_target",
        lambda *args: ElementResult(status, 2.0, message="cannot find it"),
    )
    assert invoke(command_setup, "highlight", "main.py::Main.ok") == 1
    assert "cannot find it" in capsys.readouterr().out
    assert not command_setup["flashes"]


def test_launch_cleanup_even_when_overlay_fails(
    command_setup: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    record = command_setup
    record["app"].launched = True
    monkeypatch.setattr(
        targets, "resolve_target", lambda *args: ElementResult("found", 0, element=record["info"])
    )

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("overlay failure")

    monkeypatch.setattr(overlay, "flash", fail)
    assert invoke(record, "highlight", "main.py::Main.ok", "--launch") == 4
    assert record["closed"] == [{"timeout": 10.0}]


@pytest.mark.parametrize(
    "option,value",
    [("--duration", "-1"), ("--timeout", "-1"), ("--timeout", "nan"), ("--timeout", "inf")],
)
def test_highlight_bad_options(command_setup: dict[str, Any], option: str, value: str) -> None:
    assert invoke(command_setup, "highlight", "main.py::Main.ok", option, value) == 2


def test_bad_target_exits_usage_before_attaching(
    command_setup: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def invalid(self: Any, target: Any) -> None:
        raise TargetError("invalid target")

    monkeypatch.setattr(targets.ModuleLoader, "get_element", invalid)
    assert invoke(command_setup, "highlight", "main.py::Missing") == 2
    assert invoke(command_setup, "highlight", "main.py") == 2


def test_missing_app_exits_environment(
    command_setup: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def absent(*args: Any, **kwargs: Any) -> None:
        raise common.CommandError("App is not running. Start it or pass --launch.", 3)

    monkeypatch.setattr(common, "attach_app", absent)
    assert invoke(command_setup, "highlight", "main.py::Main.ok") == 3
    assert "pass --launch" in capsys.readouterr().err


@pytest.mark.parametrize(
    "status,code", [("found", 0), ("not_found", 1), ("ambiguous", 1), ("error", 1)]
)
def test_check_json_and_exit_status(
    command_setup: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: str,
    code: int,
) -> None:
    result = CheckResult(status, 0, qualname="Main.ok", locator='Button[name="OK"]')
    monkeypatch.setattr(targets, "check_page", lambda *args: [result])
    assert invoke(command_setup, "check", "main.py::Main", "--json") == code
    assert json.loads(capsys.readouterr().out) == {"results": [result.to_dict()]}


def test_check_summary_counts_broken_moved_and_exits_nonzero(
    command_setup: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    results = [
        CheckResult("found", 0, qualname="Main.ok", locator="OK"),
        CheckResult("not_found", 0, qualname="Main.nav", locator="Nav", message="No element"),
        CheckResult(
            "not_found",
            0,
            qualname="Main.moved",
            locator="Moved",
            message="No element\nfound in Other",
        ),
    ]
    monkeypatch.setattr(targets, "check_page", lambda *args: results)
    assert invoke(command_setup, "check", "main.py::Main") == 1
    lines = capsys.readouterr().out.splitlines()
    assert lines[1].startswith("✗ Main.nav  No element")
    assert "    found in Other" in lines
    assert lines[-1] == "1 found, 2 broken/moved"


def test_check_summary_lists_other_errors_and_all_found() -> None:
    from wintestkit.commands.check import summary

    ok = CheckResult("found", 0, qualname="a")
    assert summary([ok, ok]) == "2 found, 0 broken/moved"
    mixed = [ok, CheckResult("ambiguous", 0), CheckResult("error", 0), CheckResult("not_found", 0)]
    assert summary(mixed) == "1 found, 1 broken/moved, 2 errors"


def test_check_human_output_and_no_pages(
    command_setup: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = CheckResult("found", 0, qualname="Main.ok", locator='Button[name="OK"]')
    monkeypatch.setattr(targets, "check_page", lambda *args: [result])
    assert invoke(command_setup, "check", "main.py") == 0
    assert 'Button[name="OK"]' in capsys.readouterr().out
    monkeypatch.setattr(targets.ModuleLoader, "pages_in", lambda *args: {})
    assert invoke(command_setup, "check", "main.py") == 2
