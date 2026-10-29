"""Read target identity and capabilities without modifying process state."""

from __future__ import annotations

import ctypes
import os
import re
from ctypes import wintypes
from functools import lru_cache
from pathlib import PureWindowsPath
from typing import Any, Literal, cast

from wintestkit.errors import InspectorUnavailableError
from wintestkit.inspector.models import ProcessFacts, ProcessIdentity, timestamp_from_filetime

_INVALID = ctypes.c_void_p(-1).value


class _FileTime(ctypes.Structure):
    _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]


class _ModuleEntry(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD),
        ("module_id", wintypes.DWORD),
        ("process_id", wintypes.DWORD),
        ("global_usage", wintypes.DWORD),
        ("process_usage", wintypes.DWORD),
        ("base", ctypes.c_void_p),
        ("base_size", wintypes.DWORD),
        ("module", wintypes.HMODULE),
        ("name", wintypes.WCHAR * 256),
        ("path", wintypes.WCHAR * 260),
    ]


@lru_cache(maxsize=1)
def _libraries() -> tuple[Any, Any]:
    if os.name != "nt":
        raise InspectorUnavailableError(
            "The WPF inspector requires Windows", code="unsupportedTarget"
        )
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    security = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_FileTime),
        ctypes.POINTER(_FileTime),
        ctypes.POINTER(_FileTime),
        ctypes.POINTER(_FileTime),
    ]
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    kernel.ProcessIdToSessionId.restype = wintypes.BOOL
    kernel.IsWow64Process2.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.USHORT),
        ctypes.POINTER(wintypes.USHORT),
    ]
    kernel.IsWow64Process2.restype = wintypes.BOOL
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Module32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ModuleEntry)]
    kernel.Module32FirstW.restype = wintypes.BOOL
    kernel.Module32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ModuleEntry)]
    kernel.Module32NextW.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [wintypes.HANDLE]
    kernel.LocalFree.restype = wintypes.HANDLE
    kernel.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.OpenMutexW.restype = wintypes.HANDLE
    security.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    security.OpenProcessToken.restype = wintypes.BOOL
    security.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    security.GetTokenInformation.restype = wintypes.BOOL
    security.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    security.ConvertSidToStringSidW.restype = wintypes.BOOL
    return kernel, security


win_libraries = _libraries


def _failure(action: str, *, exited: bool = False) -> InspectorUnavailableError:
    error = ctypes.get_last_error()
    code = "processExited" if exited and error in (6, 87, 1168) else "accessDenied"
    return InspectorUnavailableError(f"Cannot {action} (Windows error {error})", code=code)


def _open(pid: int) -> Any:
    if type(pid) is not int or not 0 < pid <= 4_294_967_295:
        raise InspectorUnavailableError("Invalid process ID", code="invalidParams")
    kernel, _ = _libraries()
    handle = kernel.OpenProcess(0x101000, False, pid)
    if not handle:
        raise _failure("open target process", exited=True)
    return handle


def _identity(handle: Any, pid: int) -> ProcessIdentity:
    kernel, _ = _libraries()
    created, exited, kernel_time, user_time = _FileTime(), _FileTime(), _FileTime(), _FileTime()
    if not kernel.GetProcessTimes(
        handle,
        ctypes.byref(created),
        ctypes.byref(exited),
        ctypes.byref(kernel_time),
        ctypes.byref(user_time),
    ):
        raise _failure("read target creation time", exited=True)
    wait = kernel.WaitForSingleObject(handle, 0)
    if wait == 0:
        raise InspectorUnavailableError("Target process exited", code="processExited")
    if wait != 258:
        raise _failure("check target process", exited=True)
    return ProcessIdentity(pid, timestamp_from_filetime((created.high << 32) | created.low))


def current_identity(pid: int) -> ProcessIdentity:
    kernel, _ = _libraries()
    handle = _open(pid)
    try:
        return _identity(handle, pid)
    finally:
        kernel.CloseHandle(handle)


def _sid(token: Any, information_class: int) -> str:
    kernel, security = _libraries()
    size = wintypes.DWORD()
    security.GetTokenInformation(token, information_class, None, 0, ctypes.byref(size))
    if not size.value:
        raise _failure("read process token")
    buffer = ctypes.create_string_buffer(size.value)
    if not security.GetTokenInformation(token, information_class, buffer, size, ctypes.byref(size)):
        raise _failure("read process token")
    pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
    text = wintypes.LPWSTR()
    if not security.ConvertSidToStringSidW(pointer, ctypes.byref(text)):
        raise _failure("read process SID")
    try:
        return str(text.value)
    finally:
        kernel.LocalFree(text)


def _security(handle: Any, pid: int) -> tuple[str, str, int]:
    kernel, security = _libraries()
    token = wintypes.HANDLE()
    if not security.OpenProcessToken(handle, 0x0008, ctypes.byref(token)):
        raise _failure("open process token")
    try:
        user, integrity = _sid(token, 1), _sid(token, 25)
    finally:
        kernel.CloseHandle(token)
    session = wintypes.DWORD()
    if not kernel.ProcessIdToSessionId(pid, ctypes.byref(session)):
        raise _failure("read Windows session", exited=True)
    return user, integrity, session.value


def current_security() -> tuple[str, str, int]:
    pid = os.getpid()
    kernel, _ = _libraries()
    handle = _open(pid)
    try:
        return _security(handle, pid)
    finally:
        kernel.CloseHandle(handle)


def controller_supported() -> bool:
    if ctypes.sizeof(ctypes.c_void_p) != 8:
        return False
    kernel, _ = _libraries()
    handle = _open(os.getpid())
    try:
        process_machine, native_machine = wintypes.USHORT(), wintypes.USHORT()
        if not kernel.IsWow64Process2(
            handle, ctypes.byref(process_machine), ctypes.byref(native_machine)
        ):
            raise _failure("read controller architecture")
        return native_machine.value == 0x8664 and process_machine.value in (0, 0x8664)
    finally:
        kernel.CloseHandle(handle)


def _modules(pid: int) -> tuple[str, ...]:
    kernel, _ = _libraries()
    snapshot: Any = None
    for _ in range(3):
        snapshot = kernel.CreateToolhelp32Snapshot(0x18, pid)
        if snapshot != _INVALID:
            break
        if ctypes.get_last_error() != 24:
            raise _failure("enumerate target modules", exited=True)
    if snapshot == _INVALID:
        raise _failure("enumerate target modules", exited=True)
    try:
        entry = _ModuleEntry()
        entry.size = ctypes.sizeof(entry)
        if not kernel.Module32FirstW(snapshot, ctypes.byref(entry)):
            raise _failure("enumerate target modules", exited=True)
        result: list[str] = []
        while True:
            result.append(entry.path)
            if not kernel.Module32NextW(snapshot, ctypes.byref(entry)):
                if ctypes.get_last_error() != 18:
                    raise _failure("enumerate target modules", exited=True)
                return tuple(result)
    finally:
        kernel.CloseHandle(snapshot)


class _FixedFileInfo(ctypes.Structure):
    _fields_ = [
        (name, wintypes.DWORD)
        for name in (
            "signature",
            "structure_version",
            "file_version_ms",
            "file_version_ls",
            "product_version_ms",
            "product_version_ls",
            "flags_mask",
            "flags",
            "os",
            "file_type",
            "file_subtype",
            "date_ms",
            "date_ls",
        )
    ]


def _framework_version(path: PureWindowsPath) -> tuple[int, int]:
    version = ctypes.WinDLL("version", use_last_error=True)
    version.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p]
    version.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    version.GetFileVersionInfoW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    version.GetFileVersionInfoW.restype = wintypes.BOOL
    version.VerQueryValueW.argtypes = [
        ctypes.c_void_p,
        wintypes.LPCWSTR,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.UINT),
    ]
    version.VerQueryValueW.restype = wintypes.BOOL
    size = version.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        raise _failure("read CLR version")
    buffer = ctypes.create_string_buffer(size)
    pointer, length = ctypes.c_void_p(), wintypes.UINT()
    if (
        not version.GetFileVersionInfoW(str(path), 0, size, buffer)
        or not version.VerQueryValueW(buffer, "\\", ctypes.byref(pointer), ctypes.byref(length))
        or length.value < ctypes.sizeof(_FixedFileInfo)
    ):
        raise _failure("read CLR version")
    info = ctypes.cast(pointer, ctypes.POINTER(_FixedFileInfo)).contents
    if info.signature != 0xFEEF04BD:
        raise InspectorUnavailableError("Invalid CLR version metadata", code="unsupportedTarget")
    return info.file_version_ms >> 16, info.file_version_ms & 0xFFFF


def _runtime(modules: tuple[str, ...]) -> tuple[Literal["net48", "net8", "net10"] | None, bool]:
    paths = tuple(PureWindowsPath(path) for path in modules)
    core = [path for path in paths if path.name.lower() == "coreclr.dll"]
    framework = [path for path in paths if path.name.lower() == "clr.dll"]
    wpf = any(
        path.name.lower() in {"presentationframework.dll", "wpfgfx_v0400.dll", "wpfgfx_cor3.dll"}
        for path in paths
    )
    if len(core) + len(framework) != 1:
        return None, wpf
    if framework:
        return ("net48" if _framework_version(framework[0]) == (4, 8) else None), wpf
    path = core[0]
    if (
        path.parent.parent.name.lower() != "microsoft.netcore.app"
        or path.parent.parent.parent.name.lower() != "shared"
    ):
        return None, wpf
    match = re.fullmatch(r"(\d+)\.\d+\.\d+(?:[-+].*)?", path.parent.name)
    if not match:
        return None, wpf
    if match.group(1) == "8":
        return "net8", wpf
    if match.group(1) == "10":
        return "net10", wpf
    return None, wpf


def identify(pid: int) -> ProcessFacts:
    kernel, _ = _libraries()
    handle = _open(pid)
    try:
        identity = _identity(handle, pid)
        image = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(image))
        if not kernel.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size)):
            raise _failure("read target executable", exited=True)
        process_machine, native_machine = wintypes.USHORT(), wintypes.USHORT()
        if not kernel.IsWow64Process2(
            handle, ctypes.byref(process_machine), ctypes.byref(native_machine)
        ):
            raise _failure("read target architecture", exited=True)
        machine = process_machine.value or native_machine.value
        architecture = cast(
            Literal["x86", "x64", "arm64", "unknown"],
            {0x014C: "x86", 0x8664: "x64", 0xAA64: "arm64"}.get(machine, "unknown"),
        )
        user, integrity, session = _security(handle, pid)
        runtime, wpf = _runtime(_modules(pid))
        if _identity(handle, pid) != identity:
            raise InspectorUnavailableError("Target process identity changed", code="processReused")
        return ProcessFacts(
            identity, image.value, architecture, runtime, wpf, session, user, integrity
        )
    finally:
        kernel.CloseHandle(handle)


def agent_active(pid: int) -> bool:
    kernel, _ = _libraries()
    handle = kernel.OpenMutexW(0x00100000, False, f"Local\\WinTestKit.Inspector.Agent.{pid}")
    if handle:
        kernel.CloseHandle(handle)
        return True
    error = ctypes.get_last_error()
    if error == 2:
        return False
    if error == 5:
        return True
    raise _failure("check inspector session")
