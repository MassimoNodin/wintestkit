"""COM bootstrap tests without invoking native COM initialization."""

import sys
import threading

import pytest

from wintestkit.uia import com


def test_each_worker_initializes_despite_process_sta_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr(sys, "coinit_flags", 2, raising=False)
    monkeypatch.setattr(com, "_local", threading.local())
    monkeypatch.setattr(com.comtypes, "CoInitializeEx", calls.append)

    def worker() -> None:
        com.ensure_com_initialized()
        com.ensure_com_initialized()

    workers = [threading.Thread(target=worker) for _ in range(3)]
    for thread in workers:
        thread.start()
    for thread in workers:
        thread.join(timeout=2)
        assert not thread.is_alive()
    assert calls == [0, 0, 0]


@pytest.mark.parametrize("hresult", [-2147417850, 2147549446, -2147024891])
def test_existing_apartment_only_ignores_changed_mode(
    monkeypatch: pytest.MonkeyPatch, hresult: int
) -> None:
    local = threading.local()
    monkeypatch.setattr(com, "_local", local)
    monkeypatch.setattr(com, "_warned_sta", False)
    calls: list[int] = []

    def initialize(flags: int) -> None:
        calls.append(flags)
        error = OSError("COM failure")
        error.winerror = hresult
        raise error

    monkeypatch.setattr(com.comtypes, "CoInitializeEx", initialize)
    if hresult in (-2147417850, 2147549446):
        com.ensure_com_initialized()
        com.ensure_com_initialized()
        assert local.initialized
        assert calls == [0]
    else:
        for _ in range(2):
            with pytest.raises(OSError, match="COM failure"):
                com.ensure_com_initialized()
        assert not getattr(local, "initialized", False)
        assert calls == [0, 0]
