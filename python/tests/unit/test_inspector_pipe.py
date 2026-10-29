"""Real local named-pipe deadline and cancellation behavior on Windows."""

from __future__ import annotations

import ctypes
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes

import pytest

from wintestkit.inspector.pipe import WindowsPipe
from wintestkit.inspector.probe import current_identity


def test_close_prevents_io_starting_after_cancellation(monkeypatch: pytest.MonkeyPatch) -> None:
    started = threading.Event()
    cancelled = threading.Event()
    reads: list[object] = []
    closed: list[object] = []

    class Kernel:
        def CreateEventW(self, *args: object) -> int:
            started.set()
            assert cancelled.wait(2)
            return 123

        def CancelIoEx(self, *args: object) -> None:
            cancelled.set()

        def CloseHandle(self, handle: object) -> None:
            closed.append(handle)

        def ReadFile(self, *args: object) -> bool:
            reads.append(args)
            raise AssertionError("I/O started after close cancelled pending operations")

    monkeypatch.setattr("wintestkit.inspector.pipe._api", lambda: Kernel())
    client = WindowsPipe(456)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(client.read_exact, 1, time.monotonic() + 2)
        assert started.wait(1)
        client.close()
        with pytest.raises(EOFError):
            future.result(timeout=1)
    assert not reads
    assert closed == [123, 456]


@pytest.mark.skipif(os.name != "nt", reason="Windows named pipes")
def test_overlapped_timeout_is_cancelled_and_pipe_remains_usable() -> None:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateNamedPipeW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    kernel.CreateNamedPipeW.restype = wintypes.HANDLE
    kernel.ConnectNamedPipe.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    kernel.ConnectNamedPipe.restype = wintypes.BOOL
    kernel.WriteFile.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    kernel.WriteFile.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    identity = current_identity(os.getpid())
    name = f"WinTestKit.Inspector.{identity.pid}.{uuid.uuid4()}"
    server = kernel.CreateNamedPipeW("\\\\.\\pipe\\" + name, 3, 8, 1, 4096, 4096, 0, None)
    assert server != ctypes.c_void_p(-1).value
    connected = threading.Event()

    def accept() -> None:
        if kernel.ConnectNamedPipe(server, None) or ctypes.get_last_error() == 535:
            connected.set()

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    client = None
    try:
        client = WindowsPipe.connect(name, identity, time.monotonic() + 2)
        assert connected.wait(1)
        start = time.monotonic()
        with pytest.raises(TimeoutError):
            client.read_exact(1, start + 0.1)
        assert time.monotonic() - start < 1
        count = wintypes.DWORD()
        data = ctypes.create_string_buffer(b"x")
        assert kernel.WriteFile(server, data, 1, ctypes.byref(count), None)
        assert count.value == 1 and client.read_exact(1, time.monotonic() + 1) == b"x"
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(client.read_exact, 1, time.monotonic() + 10)
            time.sleep(0.05)
            start = time.monotonic()
            client.close()
            with pytest.raises(EOFError):
                future.result(timeout=1)
            assert time.monotonic() - start < 1
    finally:
        if client is not None:
            client.close()
        kernel.CloseHandle(server)
        thread.join(timeout=1)
