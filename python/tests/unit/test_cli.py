"""Unit tests for the CLI skeleton and the run / discover / doctor commands."""

import json
import os
from pathlib import Path
from typing import Any

import pytest

from wintestkit import doctor as doctor_module
from wintestkit.cli import main
from wintestkit.commands import common, run
from wintestkit.commands import discover as discover_command
from wintestkit.doctor import Check
from wintestkit.errors import AppNotRunningError, ConfigError


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.wintestkit]\nlaunch = "attach"\n[tool.wintestkit.app]\nprocess = "App.exe"\n',
        encoding="utf-8",
    )
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_a.py").write_text("def test_a():\n    pass\n", encoding="utf-8")
    screens = tmp_path / "screens"
    screens.mkdir()
    (screens / "main.py").write_text(
        "from wintestkit import Element, Screen, Window\n\n"
        "class Main(Screen):\n"
        '    window = Window(title="App")\n'
        '    ok = Element(control_type="Button", name="OK")\n'
        '    dyn = Element(control_type="Edit", name=NAME)\n',
        encoding="utf-8",
    )
    return tmp_path


class FakePytest:
    def __init__(self, code: int = 0) -> None:
        self.code = code
        self.calls: list[tuple[list[str], str]] = []

    def main(self, argv: list[str]) -> int:
        self.calls.append((list(argv), os.getcwd()))
        return self.code


@pytest.fixture
def fake_pytest(monkeypatch: pytest.MonkeyPatch) -> FakePytest:
    import pytest as real_pytest

    fake = FakePytest()
    monkeypatch.setattr(real_pytest, "main", fake.main)
    return fake


def ready_environment(monkeypatch: pytest.MonkeyPatch, failing: bool = False) -> list[bool]:
    quick_flags: list[bool] = []

    def fake_checks(cfg: Any, *, quick: bool = False, config_error: Any = None) -> list[Check]:
        quick_flags.append(quick)
        status = "fail" if failing else "ok"
        return [
            Check(
                "desktop_unlocked",
                "Desktop is unlocked",
                status,
                "the screen is locked",
                "Unlock it.",
            )
        ]

    monkeypatch.setattr(doctor_module, "run_checks", fake_checks)
    return quick_flags


# -- run ------------------------------------------------------------------------------------------


def test_run_builds_the_pytest_command_line(
    project: Path, fake_pytest: FakePytest, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready_environment(monkeypatch)
    code = main(
        [
            "--root",
            str(project),
            "run",
            "--launch",
            "per-test",
            "--timeout",
            "3.5",
            "--app",
            "x.exe",
            "--input-mode",
            "mouse",
            "--screenshots",
            "every-step",
            "--highlight",
            "--slowmo",
            "40",
            "--report",
            "out",
            "--junit",
            "junit.xml",
            "--events",
            "tcp://127.0.0.1:9",
            "-k",
            "login",
            "-m",
            "smoke",
            "-x",
            "--lf",
            "tests/test_a.py::test_a",
            "--",
            "-q",
            "--tb=short",
        ]
    )
    assert code == 0
    ((argv, cwd),) = fake_pytest.calls
    assert argv == [
        "--wtk-launch",
        "per-test",
        "--wtk-timeout",
        "3.5",
        "--wtk-app",
        "x.exe",
        "--wtk-input-mode",
        "mouse",
        "--wtk-screenshots",
        "every-step",
        "--wtk-slowmo",
        "40",
        "--wtk-report",
        "out",
        "--wtk-events",
        "tcp://127.0.0.1:9",
        "--wtk-highlight",
        "--junitxml=junit.xml",
        "-k",
        "login",
        "-m",
        "smoke",
        "-x",
        "--lf",
        "tests/test_a.py::test_a",
        "-q",
        "--tb=short",
    ]
    assert Path(cwd) == project.resolve()


def test_run_without_options_passes_nothing_extra(
    project: Path, fake_pytest: FakePytest, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready_environment(monkeypatch)
    assert main(["--root", str(project), "run"]) == 0
    assert fake_pytest.calls[0][0] == []


def test_run_no_report_flag(
    project: Path, fake_pytest: FakePytest, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready_environment(monkeypatch)
    main(["--root", str(project), "run", "--no-report"])
    assert fake_pytest.calls[0][0] == ["--wtk-no-report"]


def test_run_restores_the_working_directory(
    project: Path, fake_pytest: FakePytest, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready_environment(monkeypatch)
    before = os.getcwd()
    main(["--root", str(project), "run"])
    assert os.getcwd() == before


@pytest.mark.parametrize(
    ("pytest_code", "wtk_code"), [(0, 0), (1, 1), (2, 4), (3, 4), (4, 2), (5, 5), (99, 4)]
)
def test_run_maps_pytest_exit_codes(
    project: Path,
    fake_pytest: FakePytest,
    monkeypatch: pytest.MonkeyPatch,
    pytest_code: int,
    wtk_code: int,
) -> None:
    ready_environment(monkeypatch)
    fake_pytest.code = pytest_code
    assert main(["--root", str(project), "run"]) == wtk_code


def test_run_checks_the_environment_first(
    project: Path,
    fake_pytest: FakePytest,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    flags = ready_environment(monkeypatch, failing=True)
    assert main(["--root", str(project), "run"]) == 3
    assert flags == [True]  # only the quick checks
    assert fake_pytest.calls == []  # pytest never started
    err = capsys.readouterr().err
    assert "✗ Desktop is unlocked: the screen is locked" in err
    assert "Unlock it." in err
    assert "wtk doctor" in err


def test_run_can_skip_the_environment_check(
    project: Path, fake_pytest: FakePytest, monkeypatch: pytest.MonkeyPatch
) -> None:
    flags = ready_environment(monkeypatch, failing=True)
    assert main(["--root", str(project), "run", "--no-env-check"]) == 0
    assert flags == []
    assert len(fake_pytest.calls) == 1


def test_run_adds_the_plugin_when_autoload_is_disabled(
    project: Path, fake_pytest: FakePytest, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready_environment(monkeypatch)
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    main(["--root", str(project), "run"])
    assert fake_pytest.calls[0][0] == ["-p", "wintestkit.pytest_plugin"]


def test_build_pytest_args_is_pure() -> None:
    import argparse

    namespace = argparse.Namespace(
        tests=["a"],
        highlight=False,
        no_report=False,
        junit=None,
        keyword=None,
        marker=None,
        exitfirst=False,
        lf=False,
        pytest_args=["-q"],
    )
    assert run.build_pytest_args(namespace) == ["a", "-q"]


# -- discover -------------------------------------------------------------------------------------


def test_discover_prints_json_when_piped(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--root", str(project), "discover"]) == 0
    out = capsys.readouterr().out
    assert out.count("\n") == 1  # a single line
    data = json.loads(out)
    assert data["version"] == 1
    assert [t["id"] for t in data["tests"]] == ["tests/test_a.py::test_a"]
    assert data["screens"][0]["name"] == "Main"


def test_discover_pretty_and_json_flags(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--root", str(project), "discover", "--pretty"]) == 0
    pretty = capsys.readouterr().out
    assert pretty.count("\n") > 20
    assert json.loads(pretty)["version"] == 1
    assert main(["--root", str(project), "discover", "--json"]) == 0
    assert capsys.readouterr().out.count("\n") == 1


def test_discover_human_tree_on_a_terminal(
    project: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(common, "is_tty", lambda stream=None: True)
    assert main(["--root", str(project), "discover"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "Tests (1)"
    assert out[1] == "  tests/test_a.py::test_a  (line 1)"
    assert out[2] == "Screens (1)"
    assert out[3] == "  Main  screens/main.py:3"
    assert out[4] == '    window  Window[title="App"]'
    assert out[5] == '    ok      Button[name="OK"]'
    assert out[6] == "    dyn     Edit (dynamic)"


def test_discover_restricts_to_paths(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--root", str(project), "discover", str(project / "screens")]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["tests"] == []
    assert len(data["screens"]) == 1


def test_discover_human_output_shows_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "test_bad.py").write_text("def broken(:\n", encoding="utf-8")
    monkeypatch.setattr(common, "is_tty", lambda stream=None: True)
    assert main(["--root", str(tmp_path), "discover"]) == 0
    assert "error: test_bad.py:1:" in capsys.readouterr().out


def test_describe_element_handles_incomplete_locators() -> None:
    from wintestkit.discovery import ElementEntry, Position, Range

    zero = Range(Position(0, 0), Position(0, 0))
    entry = ElementEntry("i", "n", "S.n", "element", zero, zero, {"index": -5}, True)
    assert discover_command.describe_element(entry) == "<incomplete locator> (dynamic)"


# -- doctor ---------------------------------------------------------------------------------------


def test_doctor_table_and_exit_code(
    project: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    checks = [
        Check("a", "Alpha", "ok", "fine"),
        Check("b", "Beta", "warn", "careful", "Do this."),
        Check("c", "Gamma", "skip", "n/a"),
    ]
    monkeypatch.setattr(doctor_module, "run_checks", lambda cfg, **kw: checks)
    assert main(["--root", str(project), "doctor"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out == ["✓ Alpha: fine", "! Beta: careful", "    Do this.", "- Gamma: n/a"]
    checks.append(Check("d", "Delta", "fail", "broken", "Fix it."))
    assert main(["--root", str(project), "doctor"]) == 3
    assert "✗ Delta: broken" in capsys.readouterr().out


def test_doctor_json(
    project: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        doctor_module, "run_checks", lambda cfg, **kw: [Check("a", "Alpha", "ok", "fine")]
    )
    assert main(["--root", str(project), "doctor", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == [
        {"id": "a", "title": "Alpha", "status": "ok", "detail": "fine"}
    ]


def test_doctor_reports_a_broken_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.wintestkit]\nlaunch = "sometimes"\n', encoding="utf-8"
    )
    seen: list[Any] = []

    def fake(cfg: Any, **kwargs: Any) -> list[Check]:
        seen.append(kwargs.get("config_error"))
        return [Check("config", "Config", "fail", str(kwargs["config_error"]))]

    monkeypatch.setattr(doctor_module, "run_checks", fake)
    assert main(["--root", str(tmp_path), "doctor"]) == 3
    assert isinstance(seen[0], ConfigError)


# -- error handling -------------------------------------------------------------------------------


def test_usage_errors_exit_with_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", "--launch", "bogus"]) == 2
    assert "invalid choice" in capsys.readouterr().err
    assert main(["no-such-command"]) == 2


def test_unknown_log_level_is_a_usage_error(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--root", str(project), "--log-level", "LOUD", "discover"]) == 2
    assert "unknown log level" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (ConfigError("bad config", key="x"), 2),
        (AppNotRunningError("not running"), 3),
        (common.CommandError("custom", 7), 7),
        (RuntimeError("kaboom"), 4),
        (KeyboardInterrupt(), 130),
    ],
)
def test_exit_code_mapping(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: BaseException,
    code: int,
) -> None:
    def boom(args: Any) -> int:
        raise error

    monkeypatch.setattr(discover_command, "run", boom)
    assert main(["--root", str(project), "discover"]) == code
    # ``handler`` was bound at parser construction time, so re-point it through set_defaults.
    err = capsys.readouterr().err
    assert err or code == 130


def test_internal_errors_hint_at_debug_logging(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(args: Any) -> int:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(discover_command, "run", boom)
    assert main(["--root", str(project), "discover"]) == 4
    err = capsys.readouterr().err
    assert "wtk: internal error: kaboom" in err
    assert "--log-level DEBUG" in err
    assert "Traceback" not in err
    assert main(["--root", str(project), "--log-level", "DEBUG", "discover"]) == 4
    assert "Traceback" in capsys.readouterr().err
