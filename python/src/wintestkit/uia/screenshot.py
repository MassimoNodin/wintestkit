# pyright: basic
"""Screen capture to PNG using GDI."""

from __future__ import annotations

import ctypes
from pathlib import Path

from wintestkit.errors import EnvironmentNotReadyError
from wintestkit.uia import win32
from wintestkit.uia.element import Rect, UIAElement
from wintestkit.uia.png import encode_png


def clip(rect: Rect, bounds: Rect) -> Rect | None:
    """Intersection of two rectangles, ``None`` when they do not overlap."""
    left, top = max(rect.left, bounds.left), max(rect.top, bounds.top)
    right, bottom = min(rect.right, bounds.right), min(rect.bottom, bounds.bottom)
    if right <= left or bottom <= top:
        return None
    return Rect(left, top, right - left, bottom - top)


def capture(rect: Rect) -> bytes:
    """Capture a screen rectangle (physical pixels, virtual-screen coordinates) as PNG bytes."""
    if rect.is_empty():
        raise ValueError("cannot capture an empty rectangle")
    width, height = rect.width, rect.height
    screen_dc = win32.GetDC(None)
    if not screen_dc:
        raise EnvironmentNotReadyError("could not get the screen device context")
    memory_dc = win32.CreateCompatibleDC(screen_dc)
    bitmap = win32.CreateCompatibleBitmap(screen_dc, width, height)
    try:
        previous = win32.SelectObject(memory_dc, bitmap)
        ok = win32.BitBlt(
            memory_dc,
            0,
            0,
            width,
            height,
            screen_dc,
            rect.left,
            rect.top,
            win32.SRCCOPY | win32.CAPTUREBLT,
        )
        if not ok:
            raise EnvironmentNotReadyError(
                "screen capture failed (is the desktop locked or the session disconnected?)"
            )
        header = win32.BITMAPINFOHEADER()
        header.biSize = ctypes.sizeof(win32.BITMAPINFOHEADER)
        header.biWidth = width
        header.biHeight = -height  # top-down rows
        header.biPlanes = 1
        header.biBitCount = 32
        header.biCompression = win32.BI_RGB
        buffer = ctypes.create_string_buffer(width * height * 4)
        lines = win32.GetDIBits(
            memory_dc, bitmap, 0, height, buffer, ctypes.byref(header), win32.DIB_RGB_COLORS
        )
        win32.SelectObject(memory_dc, previous)
        if lines != height:
            raise EnvironmentNotReadyError("could not read the captured screen bitmap")
    finally:
        win32.DeleteObject(bitmap)
        win32.DeleteDC(memory_dc)
        win32.ReleaseDC(None, screen_dc)
    bgra = buffer.raw
    rgb = bytearray(width * height * 3)
    rgb[0::3] = bgra[2::4]
    rgb[1::3] = bgra[1::4]
    rgb[2::3] = bgra[0::4]
    return encode_png(width, height, bytes(rgb))


def capture_screen() -> bytes:
    """Capture the whole virtual screen."""
    return capture(win32.virtual_screen_rect())


def capture_element(el: UIAElement) -> bytes | None:
    """Capture an element's visible area; ``None`` if it has no on-screen rectangle."""
    rect = el.rect
    if rect is None:
        return None
    clipped = clip(rect, win32.virtual_screen_rect())
    return capture(clipped) if clipped is not None else None


def save(png: bytes, path: Path) -> Path:
    """Write PNG bytes to ``path``, creating parent directories."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    return path
