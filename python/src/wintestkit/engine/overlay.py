# pyright: basic
"""Click-through highlight outline drawn around UI elements."""

from __future__ import annotations

import ctypes
import itertools
import logging
import queue
import threading
import time
from types import TracebackType
from typing import Any

from wintestkit.errors import EnvironmentNotReadyError
from wintestkit.uia import win32
from wintestkit.uia.element import Rect

log = logging.getLogger("wintestkit.overlay")

RED = 0x000000FF  # COLORREF is 0x00BBGGRR
_MAGENTA = 0x00FF00FF  # colour key: painted magenta pixels are fully transparent

_WM_SHOW = win32.WM_APP + 1
_WM_HIDE = win32.WM_APP + 2
_WM_CLOSE = win32.WM_APP + 3

_class_counter = itertools.count(1)
_REQUEST_TIMEOUT = 2.0


class Overlay:
    """A topmost, click-through rectangle outline running on its own thread with a message loop.

    All public methods are thread-safe. The window never takes focus and never intercepts input.
    """

    def __init__(self, color: int = RED, thickness: int = 3) -> None:
        self._color = color
        self._thickness = thickness
        self._requests: queue.Queue[tuple[int, Rect | None, threading.Event]] = queue.Queue()
        self._ready = threading.Event()
        self._failure: str | None = None
        self._closed = False
        self._thread_id = 0
        self._hwnd = 0
        self._class_name = f"WtkOverlay{next(_class_counter)}"
        self._wndproc = win32.WNDPROC(self._window_proc)  # keep a reference alive
        self._brushes: dict[str, Any] = {}
        self._thread = threading.Thread(target=self._run, name="wtk-overlay", daemon=True)
        self._thread.start()
        if not self._ready.wait(5.0):
            raise EnvironmentNotReadyError("the highlight overlay thread did not start")
        if self._failure:
            raise EnvironmentNotReadyError(
                f"could not create the highlight overlay: {self._failure}"
            )

    # -- public API -----------------------------------------------------------------------------

    def show(self, rect: Rect) -> None:
        """Show (or move) the outline inside ``rect`` in screen coordinates."""
        self._request(_WM_SHOW, rect)

    def hide(self) -> None:
        self._request(_WM_HIDE, None)

    def close(self) -> None:
        """Destroy the window and stop the thread (idempotent)."""
        if self._closed:
            return
        self._closed = True
        self._request(_WM_CLOSE, None, wait=False)
        self._thread.join(timeout=_REQUEST_TIMEOUT)

    def __enter__(self) -> Overlay:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    @property
    def hwnd(self) -> int:
        return self._hwnd

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    # -- cross-thread requests ------------------------------------------------------------------

    def _request(self, message: int, rect: Rect | None, wait: bool = True) -> None:
        if self._closed and message != _WM_CLOSE:
            return
        done = threading.Event()
        self._requests.put((message, rect, done))
        if not win32.PostThreadMessageW(self._thread_id, message, 0, 0):
            return  # the thread is gone
        if wait:
            done.wait(_REQUEST_TIMEOUT)

    # -- overlay thread -------------------------------------------------------------------------

    def _window_proc(self, hwnd: Any, message: int, wparam: Any, lparam: Any) -> int:
        if message == win32.WM_PAINT:
            self._paint(hwnd)
            return 0
        if message == win32.WM_DESTROY:
            win32.PostQuitMessage(0)
            return 0
        return win32.DefWindowProcW(hwnd, message, wparam, lparam)

    def _paint(self, hwnd: Any) -> None:
        paint = win32.PAINTSTRUCT()
        hdc = win32.BeginPaint(hwnd, ctypes.byref(paint))
        try:
            client = win32.RECT()
            win32.GetClientRect(hwnd, ctypes.byref(client))
            win32.FillRect(hdc, ctypes.byref(client), self._brushes["key"])
            t, w, h = self._thickness, client.right, client.bottom
            for left, top, right, bottom in (
                (0, 0, w, t),
                (0, h - t, w, h),
                (0, 0, t, h),
                (w - t, 0, w, h),
            ):
                bar = win32.RECT(left, top, right, bottom)
                win32.FillRect(hdc, ctypes.byref(bar), self._brushes["outline"])
        finally:
            win32.EndPaint(hwnd, ctypes.byref(paint))

    def _run(self) -> None:
        self._thread_id = win32.GetCurrentThreadId()
        hinstance = win32.GetModuleHandleW(None)
        self._brushes["key"] = win32.CreateSolidBrush(_MAGENTA)
        self._brushes["outline"] = win32.CreateSolidBrush(self._color)
        registered = False
        try:
            wndclass = win32.WNDCLASSEXW()
            wndclass.cbSize = ctypes.sizeof(win32.WNDCLASSEXW)
            wndclass.lpfnWndProc = self._wndproc
            wndclass.hInstance = hinstance
            wndclass.lpszClassName = self._class_name
            if not win32.RegisterClassExW(ctypes.byref(wndclass)):
                self._failure = f"RegisterClassExW failed ({ctypes.get_last_error()})"
                return
            registered = True
            styles = (
                win32.WS_EX_LAYERED
                | win32.WS_EX_TRANSPARENT
                | win32.WS_EX_TOPMOST
                | win32.WS_EX_TOOLWINDOW
                | win32.WS_EX_NOACTIVATE
            )
            hwnd = win32.CreateWindowExW(
                styles,
                self._class_name,
                None,
                win32.WS_POPUP,
                0,
                0,
                1,
                1,
                None,
                None,
                hinstance,
                None,
            )
            if not hwnd:
                self._failure = f"CreateWindowExW failed ({ctypes.get_last_error()})"
                return
            self._hwnd = int(hwnd)
            win32.SetLayeredWindowAttributes(hwnd, _MAGENTA, 0, win32.LWA_COLORKEY)
            # Force creation of this thread's message queue before announcing readiness, so
            # PostThreadMessageW from other threads cannot fail.
            message = win32.MSG()
            win32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)
            self._ready.set()
            self._pump(hwnd)
        finally:
            if not self._ready.is_set():
                self._ready.set()
            for brush in self._brushes.values():
                win32.DeleteObject(brush)
            if registered:
                win32.UnregisterClassW(self._class_name, hinstance)

    def _pump(self, hwnd: Any) -> None:
        message = win32.MSG()
        while win32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            if message.hWnd is None and message.message in (_WM_SHOW, _WM_HIDE, _WM_CLOSE):
                self._handle(hwnd, message.message)
                continue
            win32.TranslateMessage(ctypes.byref(message))
            win32.DispatchMessageW(ctypes.byref(message))

    def _handle(self, hwnd: Any, message: int) -> None:
        try:
            kind, rect, done = self._requests.get_nowait()
        except queue.Empty:
            return
        try:
            assert kind == message
            if kind == _WM_SHOW and rect is not None:
                win32.SetWindowPos(
                    hwnd,
                    win32.HWND_TOPMOST,
                    rect.left,
                    rect.top,
                    rect.width,
                    rect.height,
                    win32.SWP_NOACTIVATE | win32.SWP_SHOWWINDOW,
                )
                win32.InvalidateRect(hwnd, None, True)
            elif kind == _WM_HIDE:
                win32.ShowWindow(hwnd, win32.SW_HIDE)
            elif kind == _WM_CLOSE:
                win32.DestroyWindow(hwnd)
        finally:
            done.set()


def flash(
    rect: Rect,
    duration_ms: int = 1500,
    *,
    color: int = RED,
    thickness: int = 3,
    blink: bool = True,
    block: bool = False,
) -> None:
    """Outline ``rect`` for ``duration_ms`` (blinking three times unless ``blink=False``).

    With ``block=False`` this returns immediately and the outline is managed by a daemon thread.
    """

    def run() -> None:
        try:
            with Overlay(color, thickness) as overlay:
                if not blink:
                    overlay.show(rect)
                    time.sleep(duration_ms / 1000)
                    return
                step = duration_ms / 1000 / 6
                for _ in range(3):
                    overlay.show(rect)
                    time.sleep(step)
                    overlay.hide()
                    time.sleep(step)
        except EnvironmentNotReadyError:
            log.warning("could not show the highlight overlay", exc_info=True)

    if block:
        run()
    else:
        threading.Thread(target=run, name="wtk-flash", daemon=True).start()
