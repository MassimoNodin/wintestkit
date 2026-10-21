"""Low-latency input hooks with UI Automation work isolated on an MTA worker."""

from __future__ import annotations

import ctypes
import logging
import os
import queue
import threading
import time
from collections.abc import Callable
from typing import Any

from wintestkit.engine.overlay import Overlay
from wintestkit.errors import EnvironmentNotReadyError
from wintestkit.uia import com, win32
from wintestkit.uia.element import UIAElement, from_point

log = logging.getLogger("wintestkit.spy")


class SpySession:
    def __init__(
        self,
        on_hover: Callable[[UIAElement], None],
        on_pick: Callable[[UIAElement], None],
        on_cancel: Callable[[], None],
        process_filter: Callable[[int], bool] | None = None,
        throttle_ms: int = 60,
    ) -> None:
        if throttle_ms <= 0:
            raise ValueError("throttle_ms must be positive")
        self._on_hover = on_hover
        self._on_pick = on_pick
        self._on_cancel = on_cancel
        self._process_filter = process_filter
        self._throttle = throttle_ms / 1000
        self._events: queue.SimpleQueue[tuple[str, int, int]] = queue.SimpleQueue()
        self._stop = threading.Event()
        self._hook_ready = threading.Event()
        self._worker_ready = threading.Event()
        self._failure: str | None = None
        self._hook_thread: threading.Thread | None = None
        self._worker_thread: threading.Thread | None = None
        self._thread_id = 0
        self._mouse_hook: Any = None
        self._keyboard_hook: Any = None
        self._mouse_proc = win32.HOOKPROC(self._mouse_event)
        self._keyboard_proc = win32.HOOKPROC(self._keyboard_event)
        self._swallow_up = False

    @property
    def running(self) -> bool:
        return bool(
            not self._stop.is_set()
            and self._hook_thread is not None
            and self._hook_thread.is_alive()
            and self._worker_thread is not None
            and self._worker_thread.is_alive()
        )

    def start(self) -> None:
        if self.running:
            return
        if any(
            thread is not None and thread.is_alive()
            for thread in (self._hook_thread, self._worker_thread)
        ):
            raise EnvironmentNotReadyError("the previous Spy session is still stopping")
        self._events = queue.SimpleQueue()
        self._stop.clear()
        self._hook_ready.clear()
        self._worker_ready.clear()
        self._failure = None
        self._swallow_up = False
        self._worker_thread = threading.Thread(
            target=self._work, name="wtk-spy-worker", daemon=True
        )
        self._hook_thread = threading.Thread(target=self._hook, name="wtk-spy-hooks", daemon=True)
        self._worker_thread.start()
        self._hook_thread.start()
        if not self._hook_ready.wait(5) or not self._worker_ready.wait(5) or self._failure:
            self.stop()
            raise EnvironmentNotReadyError(self._failure or "Spy threads did not start")

    def stop(self) -> None:
        self._stop.set()
        self._events.put(("stop", 0, 0))
        if self._thread_id:
            win32.PostThreadMessageW(self._thread_id, win32.WM_QUIT, 0, 0)
        for thread in (self._hook_thread, self._worker_thread):
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=5)

    def _mouse_event(self, code: int, message: int, address: int) -> int:
        if code >= 0 and not self._stop.is_set():
            event = ctypes.cast(address, ctypes.POINTER(win32.MSLLHOOKSTRUCT)).contents
            if message == 0x0200:
                self._events.put(("move", event.pt.x, event.pt.y))
            elif message == 0x0201 and win32.GetAsyncKeyState(0x11) & 0x8000:
                self._events.put(("pick", event.pt.x, event.pt.y))
                self._swallow_up = True
                return 1
            elif message == 0x0202 and self._swallow_up:
                self._swallow_up = False
                return 1
        return int(win32.CallNextHookEx(self._mouse_hook, code, message, address))

    def _keyboard_event(self, code: int, message: int, address: int) -> int:
        if code >= 0 and message in (0x0100, 0x0104) and not self._stop.is_set():
            event = ctypes.cast(address, ctypes.POINTER(win32.KBDLLHOOKSTRUCT)).contents
            if event.vkCode == 0x1B:
                self._events.put(("cancel", 0, 0))
        return int(win32.CallNextHookEx(self._keyboard_hook, code, message, address))

    def _hook(self) -> None:
        try:
            self._thread_id = int(win32.GetCurrentThreadId())
            message = win32.MSG()
            win32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)
            module = win32.GetModuleHandleW(None)
            self._mouse_hook = win32.SetWindowsHookExW(14, self._mouse_proc, module, 0)
            if not self._mouse_hook:
                raise ctypes.WinError(ctypes.get_last_error())
            self._keyboard_hook = win32.SetWindowsHookExW(13, self._keyboard_proc, module, 0)
            if not self._keyboard_hook:
                raise ctypes.WinError(ctypes.get_last_error())
            self._hook_ready.set()
            while not self._stop.is_set():
                result = win32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result == -1:
                    raise ctypes.WinError(ctypes.get_last_error())
                if result == 0:
                    break
                win32.TranslateMessage(ctypes.byref(message))
                win32.DispatchMessageW(ctypes.byref(message))
        except Exception as exc:
            self._failure = f"Could not run Spy input hooks: {exc}"
            log.exception("Spy hook failure")
        finally:
            for handle in (self._mouse_hook, self._keyboard_hook):
                if handle:
                    win32.UnhookWindowsHookEx(handle)
            self._mouse_hook = self._keyboard_hook = None
            self._thread_id = 0
            self._stop.set()
            self._hook_ready.set()
            self._events.put(("stop", 0, 0))

    def _callback(self, callback: Callable[..., None], *args: UIAElement) -> None:
        if self._stop.is_set():
            return
        try:
            callback(*args)
        except Exception:
            log.exception("Spy callback failed")

    def _element_at(self, horizontal: int, vertical: int) -> UIAElement | None:
        element = from_point(horizontal, vertical)
        if element is None or element.process_id == os.getpid():
            return None
        if self._process_filter is not None and not self._process_filter(element.process_id):
            return None
        if element.control_type == "Text":
            parent = element.parent()
            if parent is not None and parent.control_type == "Button":
                element = parent
        return element

    def _work(self) -> None:
        overlay: Overlay | None = None
        last: UIAElement | None = None
        pending: tuple[int, int] | None = None
        last_hover = 0.0
        try:
            com.ensure_com_initialized()
            overlay = Overlay()
            self._worker_ready.set()
            while not self._stop.is_set():
                timeout = (
                    max(0.001, self._throttle - (time.monotonic() - last_hover))
                    if pending
                    else self._throttle
                )
                try:
                    kind, horizontal, vertical = self._events.get(timeout=timeout)
                except queue.Empty:
                    kind, horizontal, vertical = "idle", 0, 0
                if kind == "stop":
                    break
                try:
                    if kind == "cancel":
                        self._callback(self._on_cancel)
                    elif kind == "pick":
                        element = self._element_at(horizontal, vertical)
                        if element is not None:
                            self._callback(self._on_pick, element)
                    elif kind == "move":
                        pending = (horizontal, vertical)
                    if pending is not None and time.monotonic() - last_hover >= self._throttle:
                        element = self._element_at(*pending)
                        pending = None
                        if self._stop.is_set():
                            break
                        last_hover = time.monotonic()
                        if element is None:
                            overlay.hide()
                            last = None
                        elif last is None or not element.same_as(last):
                            rect = element.rect
                            if rect is not None:
                                overlay.show(rect)
                            else:
                                overlay.hide()
                            last = element
                            self._callback(self._on_hover, element)
                except Exception:
                    log.exception("Spy element inspection failed")
        except Exception as exc:
            self._failure = f"Could not start Spy worker: {exc}"
            log.exception("Spy worker failure")
            self._stop.set()
            if self._thread_id:
                win32.PostThreadMessageW(self._thread_id, win32.WM_QUIT, 0, 0)
        finally:
            if overlay is not None:
                overlay.close()
            self._worker_ready.set()
