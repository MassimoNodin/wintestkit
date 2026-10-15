"""Application error cases that do not require a fixture app."""

from pathlib import Path

import pytest

from wintestkit.app import App
from wintestkit.errors import AppError, AppNotRunningError

pytestmark = pytest.mark.integration


def test_attach_errors() -> None:
    with pytest.raises(AppNotRunningError):
        App.attach(process="definitely-not-running-wtk.exe")
    with pytest.raises(AppNotRunningError):
        App.attach(pid=2**22 - 4)
    with pytest.raises(ValueError, match="process name or a pid"):
        App.attach()


def test_launch_missing_executable_raises(tmp_path: Path) -> None:
    with pytest.raises(AppError, match="not found"):
        App.launch(tmp_path / "missing.exe")
