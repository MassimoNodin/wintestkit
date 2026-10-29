"""Windows named-pipe client with cancellable overlapped I/O."""

from __future__ import annotations

import ctypes
import math
import threading
import time
from collections.abc import Callable
from ctypes import wintypes
from typing import Any

from wintestkit.errors import InspectorUnavailableError
from wintestkit.inspector.models import ProcessIdentity
from wintestkit.inspector.probe import current_identity
from wintestkit.inspector.probe import win_libraries as _libraries


class _Overlapped(ctypes.Structure):
    _fields_ = [
        ("internal", ctypes.c_size_t),
        ("internal_high", ctypes.c_size_t),
        ("offset", wintypes.DWORD),
        ("offset_high", wintypes.DWORD),
        ("event", wintypes.HANDLE),
    ]


def _api() -> Any:
    kernel, _ = _libraries()
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
    kernel.WaitNamedPipeW.restype = wintypes.BOOL
    kernel.GetNamedPipeServerProcessId.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG)]
    kernel.GetNamedPipeServerProcessId.restype = wintypes.BOOL
    kernel.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateEventW.restype = wintypes.HANDLE
    kernel.ReadFile.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(_Overlapped),
    ]
    kernel.ReadFile.restype = wintypes.BOOL
    kernel.WriteFile.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(_Overlapped),
    ]
    kernel.WriteFile.restype = wintypes.BOOL
    kernel.GetOverlappedResult.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_Overlapped),
        ctypes.POINTER(wintypes.DWORD),
        wintypes.BOOL,
    ]
    kernel.GetOverlappedResult.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Overlapped)]
    kernel.CancelIoEx.restype = wintypes.BOOL
    return kernel


class WindowsPipe:
    def __init__(self, handle: Any) -> None:
        self._handle = handle
        self._condition = threading.Condition()
        self._active = 0
        self._closing = False

    @classmethod
    def connect(
        cls,
        pipe_name: str,
        identity: ProcessIdentity,
        deadline: float,
        *,
        check: Callable[[], None] | None = None,
    ) -> WindowsPipe:
        if (
            pipe_name != f"WinTestKit.Inspector.{identity.pid}." + pipe_name.rsplit(".", 1)[-1]
            or "\\" in pipe_name
            or "/" in pipe_name
        ):
            raise InspectorUnavailableError("Invalid inspector pipe name", code="invalidParams")
        kernel = _api()
        name = "\\\\.\\pipe\\" + pipe_name
        while time.monotonic() < deadline:
            if check is not None:
                check()
            handle = kernel.CreateFileW(name, 0xC0000000, 0, None, 3, 0x40000000, None)
            if handle != ctypes.c_void_p(-1).value:
                try:
                    server_pid = wintypes.ULONG()
                    if not kernel.GetNamedPipeServerProcessId(handle, ctypes.byref(server_pid)):
                        raise InspectorUnavailableError(
                            "Cannot verify inspector pipe server", code="accessDenied"
                        )
                    if (
                        server_pid.value != identity.pid
                        or current_identity(server_pid.value) != identity
                    ):
                        raise InspectorUnavailableError(
                            "Inspector pipe server identity mismatch", code="processReused"
                        )
                    return cls(handle)
                except BaseException:
                    kernel.CloseHandle(handle)
                    raise
            error = ctypes.get_last_error()
            if error not in (2, 231, 233):
                code = "accessDenied" if error == 5 else "attachFailed"
                raise InspectorUnavailableError(
                    f"Cannot open inspector pipe (Windows error {error})", code=code
                )
            if current_identity(identity.pid) != identity:
                raise InspectorUnavailableError(
                    "Target process identity changed", code="processReused"
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if error == 231:
                kernel.WaitNamedPipeW(name, max(1, min(100, math.ceil(remaining * 1000))))
            else:
                time.sleep(min(0.05, remaining))
        raise InspectorUnavailableError("Inspector readiness deadline expired", code="timeout")

    def _transfer(self, buffer: Any, size: int, deadline: float, *, write: bool) -> int:
        kernel = _api()
        with self._condition:
            if self._closing:
                raise EOFError("Inspector pipe is closed")
            self._active += 1
            handle = self._handle
        event = None
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Inspector pipe deadline expired")
            event = kernel.CreateEventW(None, True, False, None)
            if not event:
                raise OSError(ctypes.get_last_error(), "Cannot create pipe event")
            operation = _Overlapped(0, 0, 0, 0, event)
            transferred = wintypes.DWORD()
            function = kernel.WriteFile if write else kernel.ReadFile
            with self._condition:
                if self._closing:
                    raise EOFError("Inspector pipe is closed")
                success = function(
                    handle, buffer, size, ctypes.byref(transferred), ctypes.byref(operation)
                )
            if not success:
                error = ctypes.get_last_error()
                if error in (109, 232, 233):
                    raise EOFError("Inspector pipe closed")
                if error != 997:
                    raise OSError(error, "Inspector pipe I/O failed")
                wait_ms = max(0, min(0xFFFFFFFE, math.ceil((deadline - time.monotonic()) * 1000)))
                result = kernel.WaitForSingleObject(event, wait_ms)
                if result != 0:
                    kernel.CancelIoEx(handle, ctypes.byref(operation))
                    kernel.WaitForSingleObject(event, 0xFFFFFFFF)
                    if result == 258:
                        raise TimeoutError("Inspector pipe deadline expired")
                    raise OSError(ctypes.get_last_error(), "Inspector pipe wait failed")
            if not kernel.GetOverlappedResult(
                handle, ctypes.byref(operation), ctypes.byref(transferred), False
            ):
                error = ctypes.get_last_error()
                if error in (109, 232, 233, 995):
                    raise EOFError("Inspector pipe closed")
                raise OSError(error, "Inspector pipe I/O failed")
            return transferred.value
        finally:
            if event:
                kernel.CloseHandle(event)
            with self._condition:
                self._active -= 1
                self._condition.notify_all()

    def read_exact(self, size: int, deadline: float) -> bytes:
        if size < 0:
            raise ValueError("Invalid pipe read size")
        result = bytearray()
        while len(result) < size:
            buffer = ctypes.create_string_buffer(size - len(result))
            count = self._transfer(buffer, len(buffer), deadline, write=False)
            if not count:
                raise EOFError("Inspector pipe closed mid-frame")
            result.extend(buffer.raw[:count])
        return bytes(result)

    def write(self, data: bytes, deadline: float) -> None:
        offset = 0
        while offset < len(data):
            buffer = ctypes.create_string_buffer(data[offset:])
            count = self._transfer(buffer, len(data) - offset, deadline, write=True)
            if not count:
                raise EOFError("Inspector pipe closed mid-frame")
            offset += count

    def close(self) -> None:
        kernel = _api()
        with self._condition:
            if self._closing:
                return
            self._closing = True
            kernel.CancelIoEx(self._handle, None)
            while self._active:
                self._condition.wait()
            kernel.CloseHandle(self._handle)
