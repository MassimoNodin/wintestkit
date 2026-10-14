# pyright: basic
"""ctypes declarations for the Win32 APIs WinTestKit needs (no pywin32 dependency)."""

from __future__ import annotations

import ctypes
import logging
import os
import time
from ctypes import wintypes
from typing import Any

from wintestkit.uia.element import Rect

log = logging.getLogger("wintestkit.uia.win32")

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

# -- basic types ---------------------------------------------------------------------------------

HANDLE = wintypes.HANDLE
HWND = wintypes.HWND
LRESULT = ctypes.c_ssize_t
WPARAM = wintypes.WPARAM
LPARAM = wintypes.LPARAM
ULONG_PTR = ctypes.c_size_t
POINT = wintypes.POINT
RECT = wintypes.RECT
MSG = wintypes.MSG

WNDPROC = ctypes.WINFUNCTYPE(LRESULT, HWND, wintypes.UINT, WPARAM, LPARAM)
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, WPARAM, LPARAM)
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, HWND, LPARAM)

# -- constants -----------------------------------------------------------------------------------

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

GW_OWNER = 4
SW_RESTORE = 9
ASFW_ANY = 0xFFFFFFFF

PROCESS_TERMINATE = 0x0001
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SYNCHRONIZE = 0x00100000
TH32CS_SNAPPROCESS = 0x00000002
TOKEN_QUERY = 0x0008
TOKEN_ELEVATION_CLASS = 20
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 0x102
STILL_ACTIVE = 259
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

SRCCOPY = 0x00CC0020
CAPTUREBLT = 0x40000000
DIB_RGB_COLORS = 0
BI_RGB = 0

WM_PAINT = 0x000F
WM_DESTROY = 0x0002
WM_QUIT = 0x0012
WM_APP = 0x8000

WS_POPUP = 0x80000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
LWA_COLORKEY = 0x1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
SWP_HIDEWINDOW = 0x0080
HWND_TOPMOST = -1
SW_HIDE = 0

WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
PM_REMOVE = 0x0001

DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4

VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_LWIN = 0x5B

# -- structures ----------------------------------------------------------------------------------


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hdc", wintypes.HDC),
        ("fErase", wintypes.BOOL),
        ("rcPaint", RECT),
        ("fRestore", wintypes.BOOL),
        ("fIncUpdate", wintypes.BOOL),
        ("rgbReserved", wintypes.BYTE * 32),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ULONG_PTR),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class TOKEN_ELEVATION(ctypes.Structure):
    _fields_ = [("TokenIsElevated", wintypes.DWORD)]


# -- function declarations -----------------------------------------------------------------------


def _declare(dll: Any, name: str, restype: Any, *argtypes: Any) -> Any:
    func = getattr(dll, name)
    func.restype = restype
    func.argtypes = list(argtypes)
    return func


_B, _U, _I, _D, _P = wintypes.BOOL, wintypes.UINT, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p
_S = wintypes.LPCWSTR

# user32
SendInput = _declare(user32, "SendInput", _U, _U, ctypes.POINTER(INPUT), _I)
GetCursorPos = _declare(user32, "GetCursorPos", _B, ctypes.POINTER(POINT))
SetCursorPos = _declare(user32, "SetCursorPos", _B, _I, _I)
GetSystemMetrics = _declare(user32, "GetSystemMetrics", _I, _I)
GetForegroundWindow = _declare(user32, "GetForegroundWindow", HWND)
SetForegroundWindow = _declare(user32, "SetForegroundWindow", _B, HWND)
AllowSetForegroundWindow = _declare(user32, "AllowSetForegroundWindow", _B, _D)
ShowWindow = _declare(user32, "ShowWindow", _B, HWND, _I)
IsWindowVisible = _declare(user32, "IsWindowVisible", _B, HWND)
GetWindow = _declare(user32, "GetWindow", HWND, HWND, _U)
GetWindowThreadProcessId = _declare(
    user32, "GetWindowThreadProcessId", _D, HWND, ctypes.POINTER(_D)
)
EnumWindows = _declare(user32, "EnumWindows", _B, WNDENUMPROC, LPARAM)
GetClassNameW = _declare(user32, "GetClassNameW", _I, HWND, wintypes.LPWSTR, _I)
GetWindowTextW = _declare(user32, "GetWindowTextW", _I, HWND, wintypes.LPWSTR, _I)
IsIconic = _declare(user32, "IsIconic", _B, HWND)
GetAsyncKeyState = _declare(user32, "GetAsyncKeyState", wintypes.SHORT, _I)
MapVirtualKeyW = _declare(user32, "MapVirtualKeyW", _U, _U, _U)
VkKeyScanW = _declare(user32, "VkKeyScanW", wintypes.SHORT, wintypes.WCHAR)
OpenInputDesktop = _declare(user32, "OpenInputDesktop", HANDLE, _D, _B, _D)
CloseDesktop = _declare(user32, "CloseDesktop", _B, HANDLE)
GetUserObjectInformationW = _declare(
    user32, "GetUserObjectInformationW", _B, HANDLE, _I, _P, _D, ctypes.POINTER(_D)
)
SetProcessDpiAwarenessContext = _declare(user32, "SetProcessDpiAwarenessContext", _B, _P)
GetDpiForWindow = _declare(user32, "GetDpiForWindow", _U, HWND)
GetDpiForSystem = _declare(user32, "GetDpiForSystem", _U)
SetWindowsHookExW = _declare(
    user32, "SetWindowsHookExW", HANDLE, _I, HOOKPROC, wintypes.HINSTANCE, _D
)
UnhookWindowsHookEx = _declare(user32, "UnhookWindowsHookEx", _B, HANDLE)
CallNextHookEx = _declare(user32, "CallNextHookEx", LRESULT, HANDLE, _I, WPARAM, LPARAM)
GetMessageW = _declare(user32, "GetMessageW", _I, ctypes.POINTER(MSG), HWND, _U, _U)
PeekMessageW = _declare(user32, "PeekMessageW", _B, ctypes.POINTER(MSG), HWND, _U, _U, _U)
TranslateMessage = _declare(user32, "TranslateMessage", _B, ctypes.POINTER(MSG))
DispatchMessageW = _declare(user32, "DispatchMessageW", LRESULT, ctypes.POINTER(MSG))
PostThreadMessageW = _declare(user32, "PostThreadMessageW", _B, _D, _U, WPARAM, LPARAM)
CreateWindowExW = _declare(
    user32,
    "CreateWindowExW",
    HWND,
    _D,
    _S,
    _S,
    _D,
    _I,
    _I,
    _I,
    _I,
    HWND,
    wintypes.HMENU,
    wintypes.HINSTANCE,
    _P,
)
DestroyWindow = _declare(user32, "DestroyWindow", _B, HWND)
RegisterClassExW = _declare(user32, "RegisterClassExW", wintypes.ATOM, ctypes.POINTER(WNDCLASSEXW))
UnregisterClassW = _declare(user32, "UnregisterClassW", _B, _S, wintypes.HINSTANCE)
DefWindowProcW = _declare(user32, "DefWindowProcW", LRESULT, HWND, _U, WPARAM, LPARAM)
SetLayeredWindowAttributes = _declare(
    user32, "SetLayeredWindowAttributes", _B, HWND, _D, wintypes.BYTE, _D
)
SetWindowPos = _declare(user32, "SetWindowPos", _B, HWND, HWND, _I, _I, _I, _I, _U)
InvalidateRect = _declare(user32, "InvalidateRect", _B, HWND, ctypes.POINTER(RECT), _B)
BeginPaint = _declare(user32, "BeginPaint", wintypes.HDC, HWND, ctypes.POINTER(PAINTSTRUCT))
EndPaint = _declare(user32, "EndPaint", _B, HWND, ctypes.POINTER(PAINTSTRUCT))
FillRect = _declare(user32, "FillRect", _I, wintypes.HDC, ctypes.POINTER(RECT), wintypes.HBRUSH)
GetDC = _declare(user32, "GetDC", wintypes.HDC, HWND)
ReleaseDC = _declare(user32, "ReleaseDC", _I, HWND, wintypes.HDC)
GetClientRect = _declare(user32, "GetClientRect", _B, HWND, ctypes.POINTER(RECT))
AttachThreadInput = _declare(user32, "AttachThreadInput", _B, _D, _D, _B)
BringWindowToTop = _declare(user32, "BringWindowToTop", _B, HWND)
PostQuitMessage = _declare(user32, "PostQuitMessage", None, _I)
LoadCursorW = _declare(user32, "LoadCursorW", wintypes.HANDLE, wintypes.HINSTANCE, _P)

# gdi32
CreateSolidBrush = _declare(gdi32, "CreateSolidBrush", wintypes.HBRUSH, wintypes.COLORREF)
DeleteObject = _declare(gdi32, "DeleteObject", _B, wintypes.HGDIOBJ)
CreateCompatibleDC = _declare(gdi32, "CreateCompatibleDC", wintypes.HDC, wintypes.HDC)
CreateCompatibleBitmap = _declare(
    gdi32, "CreateCompatibleBitmap", wintypes.HBITMAP, wintypes.HDC, _I, _I
)
SelectObject = _declare(gdi32, "SelectObject", wintypes.HGDIOBJ, wintypes.HDC, wintypes.HGDIOBJ)
BitBlt = _declare(gdi32, "BitBlt", _B, wintypes.HDC, _I, _I, _I, _I, wintypes.HDC, _I, _I, _D)
GetDIBits = _declare(
    gdi32,
    "GetDIBits",
    _I,
    wintypes.HDC,
    wintypes.HBITMAP,
    _U,
    _U,
    _P,
    ctypes.POINTER(BITMAPINFOHEADER),
    _U,
)
DeleteDC = _declare(gdi32, "DeleteDC", _B, wintypes.HDC)

# kernel32
GetCurrentThreadId = _declare(kernel32, "GetCurrentThreadId", _D)
OpenProcess = _declare(kernel32, "OpenProcess", HANDLE, _D, _B, _D)
CloseHandle = _declare(kernel32, "CloseHandle", _B, HANDLE)
WaitForSingleObject = _declare(kernel32, "WaitForSingleObject", _D, HANDLE, _D)
GetExitCodeProcess = _declare(kernel32, "GetExitCodeProcess", _B, HANDLE, ctypes.POINTER(_D))
TerminateProcess = _declare(kernel32, "TerminateProcess", _B, HANDLE, _U)
CreateToolhelp32Snapshot = _declare(kernel32, "CreateToolhelp32Snapshot", HANDLE, _D, _D)
Process32FirstW = _declare(kernel32, "Process32FirstW", _B, HANDLE, ctypes.POINTER(PROCESSENTRY32W))
Process32NextW = _declare(kernel32, "Process32NextW", _B, HANDLE, ctypes.POINTER(PROCESSENTRY32W))
QueryFullProcessImageNameW = _declare(
    kernel32, "QueryFullProcessImageNameW", _B, HANDLE, _D, wintypes.LPWSTR, ctypes.POINTER(_D)
)
ProcessIdToSessionId = _declare(kernel32, "ProcessIdToSessionId", _B, _D, ctypes.POINTER(_D))
GetModuleHandleW = _declare(kernel32, "GetModuleHandleW", wintypes.HMODULE, _S)

# user32 (continued)
WaitForInputIdle = _declare(user32, "WaitForInputIdle", _D, HANDLE, _D)

# advapi32
OpenProcessToken = _declare(advapi32, "OpenProcessToken", _B, HANDLE, _D, ctypes.POINTER(HANDLE))
GetTokenInformation = _declare(
    advapi32, "GetTokenInformation", _B, HANDLE, _I, _P, _D, ctypes.POINTER(_D)
)

# -- helpers -------------------------------------------------------------------------------------


def list_processes() -> list[tuple[int, str]]:
    """Return ``(pid, exe name)`` for every running process."""
    snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot is None or snapshot == INVALID_HANDLE_VALUE:
        return []
    processes: list[tuple[int, str]] = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            processes.append((int(entry.th32ProcessID), entry.szExeFile))
            ok = Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        CloseHandle(snapshot)
    return processes


def pids_by_name(exe: str) -> list[int]:
    """PIDs of processes whose exe name equals ``exe`` (case-insensitive)."""
    wanted = exe.lower()
    return [pid for pid, name in list_processes() if name.lower() == wanted]


def window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD(0)
    GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def top_level_windows(pid_set: set[int] | None = None, visible_only: bool = True) -> list[int]:
    """HWNDs of top-level windows in z-order (topmost first), optionally filtered by process."""
    found: list[int] = []

    @WNDENUMPROC
    def callback(hwnd: Any, _lparam: Any) -> bool:
        if visible_only and not IsWindowVisible(hwnd):
            return True
        if pid_set is None or window_pid(hwnd) in pid_set:
            found.append(int(hwnd))
        return True

    EnumWindows(callback, 0)
    return found


def window_owner(hwnd: int) -> int:
    """HWND of the owner window, or 0 when the window is unowned."""
    return int(GetWindow(hwnd, GW_OWNER) or 0)


def window_class_name(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    GetClassNameW(hwnd, buffer, len(buffer))
    return buffer.value


def window_text(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(512)
    GetWindowTextW(hwnd, buffer, len(buffer))
    return buffer.value


def process_is_elevated(pid: int) -> bool | None:
    """True/False for the process token's elevation, ``None`` if access was denied."""
    process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not process:
        return None
    try:
        token = HANDLE()
        if not OpenProcessToken(process, TOKEN_QUERY, ctypes.byref(token)):
            return None
        try:
            elevation = TOKEN_ELEVATION()
            returned = wintypes.DWORD(0)
            if not GetTokenInformation(
                token,
                TOKEN_ELEVATION_CLASS,
                ctypes.byref(elevation),
                ctypes.sizeof(elevation),
                ctypes.byref(returned),
            ):
                return None
            return bool(elevation.TokenIsElevated)
        finally:
            CloseHandle(token)
    finally:
        CloseHandle(process)


def current_process_is_elevated() -> bool:
    return bool(process_is_elevated(os.getpid()))


def virtual_screen_rect() -> Rect:
    return Rect(
        GetSystemMetrics(SM_XVIRTUALSCREEN),
        GetSystemMetrics(SM_YVIRTUALSCREEN),
        GetSystemMetrics(SM_CXVIRTUALSCREEN),
        GetSystemMetrics(SM_CYVIRTUALSCREEN),
    )


def _tap_alt() -> None:
    events = (INPUT * 2)()
    for i, flags in enumerate((0, KEYEVENTF_KEYUP)):
        events[i].type = INPUT_KEYBOARD
        events[i].ki.wVk = VK_MENU
        events[i].ki.dwFlags = flags
    SendInput(2, events, ctypes.sizeof(INPUT))


def bring_to_foreground(hwnd: int, timeout: float = 0.5) -> bool:
    """Make ``hwnd`` the foreground window; returns whether it succeeded."""
    if IsIconic(hwnd):
        ShowWindow(hwnd, SW_RESTORE)
    if GetForegroundWindow() == hwnd:
        return True
    AllowSetForegroundWindow(ASFW_ANY)
    SetForegroundWindow(hwnd)
    if GetForegroundWindow() != hwnd:
        # Documented workaround for the foreground lock: a synthetic Alt key press.
        _tap_alt()
        SetForegroundWindow(hwnd)
    BringWindowToTop(hwnd)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.02)
    return GetForegroundWindow() == hwnd
