"""The Windows clipboard as text: read it, write it, clear it.

Migrated suites copy a value out of the application, compare it, and put text on the clipboard to
paste it back. ``get_text``, ``set_text`` and ``clear`` do that with Unicode text and show up in the
report as steps (``clipboard.get_text`` and so on) with the text, shortened, as an argument.

Another process can hold the clipboard open for a moment (a clipboard manager, remote desktop, the
application's own copy). Opening it is retried for ``timeout`` seconds before it fails with
:class:`~wintestkit.errors.ClipboardError`, which also names the holder when Windows says who it is.
"""

from __future__ import annotations

import ctypes
import logging
import time
from collections.abc import Callable
from contextlib import contextmanager
from typing import TYPE_CHECKING, Protocol

from wintestkit import runtime
from wintestkit.errors import ClipboardError

if TYPE_CHECKING:
    from collections.abc import Generator

log = logging.getLogger("wintestkit.clipboard")

#: Seconds an operation waits for another process to let go of the clipboard.
DEFAULT_TIMEOUT = 2.0
_RETRY_INTERVAL = 0.02
_PREVIEW_CHARS = 200

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

# Patched by unit tests.
_clock: Callable[[], float] = time.monotonic
_sleep: Callable[[float], None] = time.sleep


class ClipboardBackend(Protocol):
    """What the module needs of the system clipboard (the Win32 one, or a fake in tests)."""

    def open(self) -> bool:
        """Open the clipboard for this thread; ``False`` when another process holds it."""
        ...

    def close(self) -> None: ...

    def read_text(self) -> str | None:
        """The Unicode text on the clipboard, ``None`` when it holds no text."""
        ...

    def write_text(self, text: str) -> None:
        """Replace the clipboard content with ``text``; ``OSError`` when Windows refuses."""
        ...

    def empty(self) -> None: ...

    def holder(self) -> str | None:
        """A description of the process that holds the clipboard open, when known."""
        ...


class _Win32Clipboard:
    """The Win32 clipboard. A hidden window owns it while it is open, because ``SetClipboardData``
    fails for a clipboard opened without an owner."""

    def __init__(self) -> None:
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        void = ctypes.c_void_p
        uint = ctypes.c_uint
        for func, restype, argtypes in (
            (self._user32.OpenClipboard, ctypes.c_int, [void]),
            (self._user32.CloseClipboard, ctypes.c_int, []),
            (self._user32.EmptyClipboard, ctypes.c_int, []),
            (self._user32.GetClipboardData, void, [uint]),
            (self._user32.SetClipboardData, void, [uint, void]),
            (self._user32.IsClipboardFormatAvailable, ctypes.c_int, [uint]),
            (self._user32.GetOpenClipboardWindow, void, []),
            (
                self._user32.CreateWindowExW,
                void,
                [
                    ctypes.c_ulong,
                    ctypes.c_wchar_p,
                    ctypes.c_wchar_p,
                    ctypes.c_ulong,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_int,
                    void,
                    void,
                    void,
                    void,
                ],
            ),
            (self._user32.DestroyWindow, ctypes.c_int, [void]),
            (
                self._user32.GetWindowThreadProcessId,
                ctypes.c_ulong,
                [void, ctypes.POINTER(ctypes.c_ulong)],
            ),
            (self._kernel32.GlobalAlloc, void, [uint, ctypes.c_size_t]),
            (self._kernel32.GlobalLock, void, [void]),
            (self._kernel32.GlobalUnlock, ctypes.c_int, [void]),
            (self._kernel32.GlobalFree, void, [void]),
        ):
            func.restype = restype
            func.argtypes = argtypes
        self._owner: int | None = None

    def open(self) -> bool:
        owner = self._user32.CreateWindowExW(
            0, "STATIC", None, 0, 0, 0, 0, 0, None, None, None, None
        )
        if not owner:
            raise OSError(ctypes.get_last_error(), "could not create the clipboard owner window")
        if not self._user32.OpenClipboard(owner):
            self._user32.DestroyWindow(owner)
            return False
        self._owner = owner
        return True

    def close(self) -> None:
        self._user32.CloseClipboard()
        if self._owner is not None:
            self._user32.DestroyWindow(self._owner)
            self._owner = None

    def read_text(self) -> str | None:
        if not self._user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return None
        handle = self._user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        pointer = self._kernel32.GlobalLock(handle)
        if not pointer:
            raise OSError(ctypes.get_last_error(), "could not lock the clipboard text")
        try:
            return ctypes.wstring_at(pointer)
        finally:
            self._kernel32.GlobalUnlock(handle)

    def write_text(self, text: str) -> None:
        buffer = text.encode("utf-16-le") + b"\x00\x00"  # UTF-16, NUL-terminated
        size = len(buffer)
        handle = self._kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        if not handle:
            raise OSError(ctypes.get_last_error(), "could not allocate memory for the clipboard")
        pointer = self._kernel32.GlobalLock(handle)
        if not pointer:
            self._kernel32.GlobalFree(handle)
            raise OSError(ctypes.get_last_error(), "could not lock the clipboard memory")
        ctypes.memmove(pointer, buffer, size)
        self._kernel32.GlobalUnlock(handle)
        if not self._user32.EmptyClipboard():
            self._kernel32.GlobalFree(handle)
            raise OSError(ctypes.get_last_error(), "could not empty the clipboard")
        if not self._user32.SetClipboardData(CF_UNICODETEXT, handle):
            self._kernel32.GlobalFree(handle)  # ownership moves to Windows only on success
            raise OSError(ctypes.get_last_error(), "could not set the clipboard text")

    def empty(self) -> None:
        if not self._user32.EmptyClipboard():
            raise OSError(ctypes.get_last_error(), "could not empty the clipboard")

    def holder(self) -> str | None:
        window = self._user32.GetOpenClipboardWindow()
        if not window:
            return None
        pid = ctypes.c_ulong(0)
        self._user32.GetWindowThreadProcessId(window, ctypes.byref(pid))
        if not pid.value:
            return None
        from wintestkit.uia import win32

        name = next((n for p, n in win32.list_processes() if p == pid.value), None)
        return f"{name} (pid {pid.value})" if name else f"pid {pid.value}"


_backend: ClipboardBackend | None = None


def _system() -> ClipboardBackend:
    global _backend
    if _backend is None:
        _backend = _Win32Clipboard()
    return _backend


@contextmanager
def _opened(timeout: float) -> Generator[ClipboardBackend]:
    """The clipboard, open; retried until ``timeout`` seconds have passed."""
    __tracebackhide__ = True
    backend = _system()
    deadline = _clock() + max(0.0, timeout)
    attempts = 0
    while not backend.open():
        attempts += 1
        if _clock() >= deadline:
            holder = backend.holder()
            by = f" by {holder}" if holder else " by another process"
            raise ClipboardError(
                f"The clipboard stayed locked{by} for {timeout:g}s ({attempts} attempts). "
                "Close the program that holds it, or raise timeout="
            )
        _sleep(_RETRY_INTERVAL)
    if attempts:
        log.debug("clipboard opened after %d retries", attempts)
    try:
        yield backend
    finally:
        backend.close()


def _preview(text: str, secret: bool) -> str:
    if secret:
        return runtime.REDACTED
    return text if len(text) <= _PREVIEW_CHARS else text[:_PREVIEW_CHARS] + "..."


def get_text(*, secret: bool = False, timeout: float = DEFAULT_TIMEOUT) -> str:
    """The Unicode text on the clipboard, as the application put it (line breaks included).

    Raises :class:`~wintestkit.errors.ClipboardError` when the clipboard holds something that is
    not text (an image, files) or nothing at all, and when another process keeps it locked for
    longer than ``timeout`` seconds. ``secret=True`` keeps the text out of the report.
    """
    __tracebackhide__ = True
    with runtime.step("clipboard.get_text", "clipboard", "", {}) as record:
        with _opened(timeout) as backend:
            try:
                text = backend.read_text()
            except OSError as exc:
                raise ClipboardError(f"The clipboard text could not be read: {exc}") from exc
        if text is None:
            raise ClipboardError(
                "The clipboard holds no text. Copy text in the application first; an image or "
                "files on the clipboard are not text."
            )
        record.args["length"] = len(text)
        record.args["text"] = _preview(text, secret)
        return text


def set_text(text: str, *, secret: bool = False, timeout: float = DEFAULT_TIMEOUT) -> None:
    """Replace the clipboard content with ``text`` (Unicode; stored exactly as given).

    ``secret=True`` keeps the text out of the report.
    """
    __tracebackhide__ = True
    if not isinstance(text, str):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise TypeError(f"clipboard text must be a str, not {type(text).__name__}")
    if "\0" in text:
        raise ValueError("clipboard text cannot contain a NUL character")
    args = {"length": len(text), "text": _preview(text, secret)}
    with runtime.step("clipboard.set_text", "clipboard", "", args), _opened(timeout) as backend:
        try:
            backend.write_text(text)
        except OSError as exc:
            raise ClipboardError(f"The clipboard text could not be set: {exc}") from exc


def clear(*, timeout: float = DEFAULT_TIMEOUT) -> None:
    """Empty the clipboard, so that a following :func:`get_text` fails until something is copied."""
    __tracebackhide__ = True
    with runtime.step("clipboard.clear", "clipboard", "", {}), _opened(timeout) as backend:
        try:
            backend.empty()
        except OSError as exc:
            raise ClipboardError(f"The clipboard could not be cleared: {exc}") from exc
