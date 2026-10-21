from __future__ import annotations

import ctypes
from typing import Any

import pytest

from wintestkit.uia import win32


@pytest.mark.parametrize(("owner", "expected"), [(10, 123), (11, 123), (12, 123), (99, None)])
def test_foreground_window_must_belong_to_the_host_process_ancestry(
    monkeypatch: pytest.MonkeyPatch, owner: int, expected: int | None
) -> None:
    records = iter([(12, 11), (11, 10), (10, 0), (99, 0)])

    def advance(_snapshot: object, pointer: Any) -> bool:
        record = next(records, None)
        if record is None:
            return False
        entry = ctypes.cast(pointer, ctypes.POINTER(win32.PROCESSENTRY32W)).contents
        entry.th32ProcessID, entry.th32ParentProcessID = record
        return True

    closed: list[int] = []
    monkeypatch.setattr(win32, "GetForegroundWindow", lambda: 123)
    monkeypatch.setattr(win32, "window_pid", lambda _hwnd: owner)
    monkeypatch.setattr(win32, "CreateToolhelp32Snapshot", lambda *_args: 456)
    monkeypatch.setattr(win32, "Process32FirstW", advance)
    monkeypatch.setattr(win32, "Process32NextW", advance)
    monkeypatch.setattr(win32, "CloseHandle", closed.append)
    assert win32.foreground_window_for_process(12) == expected
    assert closed == [456]


def test_foreground_window_lookup_rejects_missing_window_or_process_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(win32, "GetForegroundWindow", lambda: 0)
    assert win32.foreground_window_for_process(12) is None
    monkeypatch.setattr(win32, "GetForegroundWindow", lambda: 123)
    monkeypatch.setattr(win32, "window_pid", lambda _hwnd: 10)
    monkeypatch.setattr(win32, "CreateToolhelp32Snapshot", lambda *_args: None)
    assert win32.foreground_window_for_process(12) is None
