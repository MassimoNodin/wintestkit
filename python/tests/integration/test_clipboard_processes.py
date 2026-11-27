"""Clipboard, process helpers and several apps against the real desktop (not run by CI unit jobs)."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from wintestkit import clipboard, finders
from wintestkit.app import App, Apps
from wintestkit.errors import AppNotRunningError, ClipboardError
from wintestkit.uia import win32

pytestmark = pytest.mark.integration

NOTEPAD = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "notepad.exe"


@pytest.fixture
def saved_clipboard() -> Iterator[None]:
    """Put back what the developer had copied."""
    try:
        before: str | None = clipboard.get_text()
    except ClipboardError:
        before = None
    yield
    if before is None:
        clipboard.clear()
    else:
        clipboard.set_text(before)


def test_clipboard_round_trips_unicode_and_clears(saved_clipboard: None) -> None:
    text = "caf\u00e9 \u65e5\u672c\u8a9e \U0001f600\r\nsecond line"
    clipboard.set_text(text)
    assert clipboard.get_text() == text
    clipboard.clear()
    with pytest.raises(ClipboardError, match="holds no text"):
        clipboard.get_text()


def test_process_and_wait_process_find_the_shell() -> None:
    assert finders.process("explorer").pids
    assert finders.Sys.Process("explorer.exe").is_running()
    assert finders.wait_process("explorer.exe", 0) is not None
    assert finders.wait_process("definitely-not-running-wtk.exe", 300) is None
    with pytest.raises(AppNotRunningError):
        finders.process("definitely-not-running-wtk.exe")


@pytest.mark.skipif(not NOTEPAD.is_file(), reason="needs notepad.exe")
def test_two_launched_apps_and_a_second_group_are_closed_at_the_end() -> None:
    with Apps(close_timeout=5) as apps:
        first = apps.launch(NOTEPAD, startup_timeout=15)
        second = apps.launch(NOTEPAD, startup_timeout=15)
        assert first.pids and second.pids and set(first.pids).isdisjoint(second.pids)
        assert first.main_window().native_window_handle != second.main_window().native_window_handle
    assert not first.is_running() and not second.is_running()


@pytest.mark.skipif(not NOTEPAD.is_file(), reason="needs notepad.exe")
def test_close_gracefully_and_kill_by_name() -> None:
    app = App.launch(NOTEPAD, startup_timeout=15)
    assert app.close_gracefully(exit_timeout=10) in {"exited", "running"}
    if app.is_running():
        app.kill()
    deadline = time.monotonic() + 5
    while app.is_running() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not app.is_running()


@pytest.mark.skipif(win32.current_process_is_elevated(), reason="needs a non-elevated runner")
def test_an_elevated_process_cannot_be_driven_from_a_standard_runner() -> None:
    """Needs an elevated process to be running (any admin tool); skipped when there is none."""
    elevated = [pid for pid, _ in win32.list_processes() if win32.process_is_elevated(pid)]
    if not elevated:
        pytest.skip("no elevated process is running")
    app = App.attach(pid=elevated[0])
    from wintestkit.errors import ElevationError

    with pytest.raises(ElevationError, match="UIPI"):
        app.top_level_windows()
