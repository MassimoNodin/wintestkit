"""Opt-in launch and detach lifecycle against the owned WPF fixture."""

import ctypes
import os
import threading
from pathlib import Path

import pytest
from live_dotnet import live_dotnet_root

from wintestkit import runtime
from wintestkit.app import App
from wintestkit.config import load_config
from wintestkit.inspector.pipe import WindowsPipe

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "wpf-inspector/tests/Fixtures/WpfFixture/bin/cells/net10.0-windows-x64"
pytestmark = pytest.mark.skipif(
    os.name != "nt" or os.environ.get("WTK_INSPECTOR_REAL") != "1",
    reason="requires explicitly enabled owned Windows fixture",
)


def _handle_open(handle: int) -> bool:
    flags = ctypes.c_ulong()
    kernel = ctypes.windll.kernel32
    kernel.GetHandleInformation.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    kernel.GetHandleInformation.restype = ctypes.c_int
    return bool(kernel.GetHandleInformation(handle, ctypes.byref(flags)))


def test_launch_close_cycles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(ROOT / "inspector-payload/src"))
    runtime.reset()
    identities = []
    closed_handles: list[bool] = []
    original_close = WindowsPipe.close

    def checked_close(pipe: WindowsPipe) -> None:
        handle = pipe._handle  # pyright: ignore[reportPrivateUsage]
        original_close(pipe)
        closed_handles.append(not _handle_open(handle))

    monkeypatch.setattr(WindowsPipe, "close", checked_close)
    baseline_threads = threading.active_count()
    with runtime.config_scope(load_config(tmp_path)):
        for _ in range(20):
            app = App.launch(
                FIXTURE / "WinTestKit.Fixture.exe",
                cwd=FIXTURE,
                env={"DOTNET_ROOT_X64": live_dotnet_root(), "DOTNET_MULTILEVEL_LOOKUP": "0"},
                owned_only=True,
            )
            try:
                identity = next(iter(app._inspector_identities))  # pyright: ignore[reportPrivateUsage]
                client = runtime.inspector_sessions().get(identity)
                assert client is not None and client.session.state == "ready"
                identities.append(identity)
            finally:
                app.close()
            assert client.session.state != "ready"
            assert not client._reader.is_alive()  # pyright: ignore[reportPrivateUsage]
            assert not runtime.inspector_sessions()._entries  # pyright: ignore[reportPrivateUsage]
    assert len(set(identities)) == 20
    assert len(closed_handles) >= 20 and all(closed_handles)
    assert threading.active_count() <= baseline_threads
    runtime.reset()
