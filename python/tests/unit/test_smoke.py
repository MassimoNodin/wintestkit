"""Smoke tests for the initial Python package scaffold."""

import subprocess
import sys

import pytest

import wintestkit
from wintestkit.cli import main


def test_version() -> None:
    assert wintestkit.__version__ == "0.1.0"


def test_cli_main(capsys: pytest.CaptureFixture[str]) -> None:
    assert main() == 0
    assert capsys.readouterr().out == "wintestkit 0.1.0\n"


def test_module_entry_point() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "wintestkit"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout == "wintestkit 0.1.0\n"
    assert result.stderr == ""
