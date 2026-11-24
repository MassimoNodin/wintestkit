"""Find and close processes holding an installed inspector, without importing it."""
import ctypes
from ctypes import wintypes
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import sysconfig
import time


def package_dir():
    try:
        spec = importlib.util.find_spec("wintestkit_inspector")
        if spec and spec.submodule_search_locations:
            return Path(next(iter(spec.submodule_search_locations)))
    except (ImportError, ValueError, OSError):
        pass
    return Path(sysconfig.get_path("purelib")) / "wintestkit_inspector"


def holders():
    if os.name != "nt":
        return []
    root = package_dir()
    files = [str(p) for p in root.rglob("*") if p.is_file()] if root.is_dir() else []
    if not files:
        return []
    class Unique(ctypes.Structure):
        _fields_ = [("pid", wintypes.DWORD), ("started", wintypes.FILETIME)]
    class Info(ctypes.Structure):
        _fields_ = [("process", Unique), ("name", wintypes.WCHAR * 256),
                    ("service", wintypes.WCHAR * 64), ("kind", ctypes.c_int),
                    ("status", wintypes.ULONG), ("session", wintypes.DWORD),
                    ("restartable", wintypes.BOOL)]
    rm = ctypes.WinDLL("rstrtmgr", use_last_error=True)
    session = wintypes.DWORD()
    key = ctypes.create_unicode_buffer(33)
    code = rm.RmStartSession(ctypes.byref(session), 0, key)
    if code:
        raise OSError(code, "RmStartSession failed")
    try:
        resources = (wintypes.LPCWSTR * len(files))(*files)
        code = rm.RmRegisterResources(session, len(files), resources, 0, None, 0, None)
        if code:
            raise OSError(code, "RmRegisterResources failed")
        needed, count, reason = wintypes.UINT(), wintypes.UINT(), wintypes.DWORD()
        code = rm.RmGetList(session, ctypes.byref(needed), ctypes.byref(count), None, ctypes.byref(reason))
        while code == 234:
            count.value = needed.value
            entries = (Info * count.value)()
            code = rm.RmGetList(session, ctypes.byref(needed), ctypes.byref(count), entries, ctypes.byref(reason))
        if code:
            raise OSError(code, "RmGetList failed")
        return [{"pid": x.process.pid, "name": x.name or str(x.process.pid),
                 "started": str((x.process.started.dwHighDateTime << 32) | x.process.started.dwLowDateTime)}
                for x in entries[:count.value]] if count.value else []
    finally:
        rm.RmEndSession(session)


def act(items, force=False):
    if os.name != "nt":
        return []
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    user = ctypes.WinDLL("user32", use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    handles = []
    for item in items:
        handle = kernel.OpenProcess(0x100000 | 0x1000 | (1 if force else 0), False, item["pid"])
        if not handle:
            # ERROR_INVALID_PARAMETER means the process has already exited.
            if ctypes.get_last_error() != 87:
                handles.append((item, None))
            continue
        created, exited, kerneltime, usertime = (wintypes.FILETIME() for _ in range(4))
        if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kerneltime), ctypes.byref(usertime)):
            kernel.CloseHandle(handle)
            handles.append((item, None))
            continue
        started = (created.dwHighDateTime << 32) | created.dwLowDateTime
        if str(started) != item["started"]:
            kernel.CloseHandle(handle)
            continue
        handles.append((item, handle))
    if force:
        for _, handle in handles:
            if handle:
                kernel.TerminateProcess(handle, 1)
    else:
        pids = {item["pid"] for item, handle in handles if handle}
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user.IsWindowVisible.argtypes = [wintypes.HWND]
        user.GetWindow.restype = wintypes.HWND
        user.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]

        def close_window(hwnd, _):
            pid = wintypes.DWORD()
            user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            # Only visible, unowned windows: the app's main windows, as if the user clicked X.
            if pid.value in pids and user.IsWindowVisible(hwnd) and not user.GetWindow(hwnd, 4):
                user.PostMessageW(hwnd, 0x10, 0, 0)
            return True
        callback = callback_type(close_window)
        user.EnumWindows(callback, 0)
    deadline = time.monotonic() + 15
    try:
        while time.monotonic() < deadline:
            if all(handle and kernel.WaitForSingleObject(handle, 0) == 0 for _, handle in handles):
                break
            time.sleep(0.1)
        return [item for item, handle in handles if not handle or kernel.WaitForSingleObject(handle, 0) != 0]
    finally:
        for _, handle in handles:
            if handle:
                kernel.CloseHandle(handle)


def cleanup():
    parent = package_dir().parent
    for path in parent.iterdir():
        if path.name.startswith("~") and "intestkit" in path.name.lower():
            try:
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                else:
                    path.unlink()
            except OSError:
                pass


if __name__ == "__main__":
    action = sys.argv[1]
    if action == "list":
        result = holders()
    elif action in ("close", "force"):
        result = act(json.loads(sys.argv[2]), action == "force")
    elif action == "cleanup":
        cleanup()
        result = []
    else:
        raise ValueError("unknown action")
    print(json.dumps(result))
