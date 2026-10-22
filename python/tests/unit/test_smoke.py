"""Smoke tests for the package and its entry points."""

import re
import subprocess
import sys

import pytest

import wintestkit
from wintestkit.cli import main


def test_version() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+((a|b|rc)\d+|\.dev\d+)?", wintestkit.__version__)


def test_cli_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--version"]) == 0
    assert capsys.readouterr().out == f"wintestkit {wintestkit.__version__}\n"


def test_cli_without_a_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    out = capsys.readouterr().out
    assert out.startswith("usage: wtk")
    for command in ("run", "discover", "doctor"):
        assert command in out


def test_module_entry_point() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "wintestkit", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout == f"wintestkit {wintestkit.__version__}\n"
    assert result.stderr == ""
