# pyright: basic
"""DPI awareness: every coordinate WinTestKit sees is a physical pixel."""

from __future__ import annotations

import ctypes
import logging
import threading
from ctypes import wintypes

log = logging.getLogger("wintestkit.uia.dpi")

DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4

_lock = threading.Lock()
_done = False


def ensure_per_monitor_aware() -> None:
    """Opt the process into per-monitor-v2 DPI awareness (once; ignores "already set")."""
    global _done
    with _lock:
        if _done:
            return
        _done = True
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        func = user32.SetProcessDpiAwarenessContext
        func.restype = wintypes.BOOL
        func.argtypes = [ctypes.c_void_p]
        if not func(ctypes.c_void_p(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)):
            # ERROR_ACCESS_DENIED means awareness was already set (manifest or earlier call).
            log.debug("SetProcessDpiAwarenessContext failed: %s", ctypes.get_last_error())


def scale_for_window(hwnd: int) -> float:
    """Scale factor of the monitor showing ``hwnd`` (1.0 = 96 dpi)."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    func = user32.GetDpiForWindow
    func.restype = wintypes.UINT
    func.argtypes = [wintypes.HWND]
    dpi = func(hwnd)
    return dpi / 96 if dpi else 1.0
