# pyright: basic
"""Lossless WebP screen capture using GDI, with explicit PNG export."""

from __future__ import annotations

import ctypes
from io import BytesIO
from pathlib import Path

from PIL import Image

from wintestkit.backends.element import TargetElement
from wintestkit.errors import EnvironmentNotReadyError
from wintestkit.uia import win32
from wintestkit.uia.element import Rect
from wintestkit.uia.png import encode_png
from wintestkit.uia.webp import encode_webp

DWMWA_EXTENDED_FRAME_BOUNDS = 9


def clip(rect: Rect, bounds: Rect) -> Rect | None:
    """Intersection of two rectangles, ``None`` when they do not overlap."""
    left, top = max(rect.left, bounds.left), max(rect.top, bounds.top)
    right, bottom = min(rect.right, bounds.right), min(rect.bottom, bounds.bottom)
    if right <= left or bottom <= top:
        return None
    return Rect(left, top, right - left, bottom - top)


def capture(rect: Rect) -> bytes:
    """Capture a screen rectangle (physical pixels, virtual-screen coordinates) as WebP bytes."""
    return _capture_bitmap(rect)


Pixels = tuple[int, int, bytes]
"""Width, height and RGB rows of an uncompressed capture."""


def _capture_bitmap(rect: Rect, hwnd: int | None = None, crop: Rect | None = None) -> bytes:
    return encode_webp(*_capture_pixels(rect, hwnd, crop))


def _capture_pixels(rect: Rect, hwnd: int | None = None, crop: Rect | None = None) -> Pixels:
    if rect.is_empty():
        raise ValueError("cannot capture an empty rectangle")
    width, height = rect.width, rect.height
    screen_dc = win32.GetDC(None)
    if not screen_dc:
        raise EnvironmentNotReadyError("could not get the screen device context")
    memory_dc = None
    bitmap = None
    previous = None
    try:
        memory_dc = win32.CreateCompatibleDC(screen_dc)
        if not memory_dc:
            raise EnvironmentNotReadyError("could not create the capture device context")
        bitmap = win32.CreateCompatibleBitmap(screen_dc, width, height)
        if not bitmap:
            raise EnvironmentNotReadyError("could not create the capture bitmap")
        previous = win32.SelectObject(memory_dc, bitmap)
        if not previous or previous == ctypes.c_void_p(-1).value:
            previous = None
            raise EnvironmentNotReadyError("could not select the capture bitmap")
        if hwnd is None:
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
        else:
            clear = win32.gdi32.PatBlt
            clear.argtypes = [
                win32.HANDLE,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_ulong,
            ]
            clear.restype = ctypes.c_int
            if not clear(memory_dc, 0, 0, width, height, 0x00000042):
                raise EnvironmentNotReadyError("could not clear the window capture bitmap")
            print_window = win32.user32.PrintWindow
            print_window.argtypes = [win32.HWND, win32.HANDLE, ctypes.c_uint]
            print_window.restype = ctypes.c_int
            ok = print_window(hwnd, memory_dc, 2)
        if not ok:
            raise EnvironmentNotReadyError(
                "window or screen capture failed (is the application responding?)"
            )
        header = win32.BITMAPINFOHEADER()
        header.biSize = ctypes.sizeof(win32.BITMAPINFOHEADER)
        header.biWidth = width
        header.biHeight = -height  # top-down rows
        header.biPlanes = 1
        header.biBitCount = 32
        header.biCompression = win32.BI_RGB
        buffer = ctypes.create_string_buffer(width * height * 4)
        win32.SelectObject(memory_dc, previous)
        previous = None
        lines = win32.GetDIBits(
            memory_dc, bitmap, 0, height, buffer, ctypes.byref(header), win32.DIB_RGB_COLORS
        )
        if lines != height:
            raise EnvironmentNotReadyError("could not read the captured screen bitmap")
    finally:
        if previous is not None:
            win32.SelectObject(memory_dc, previous)
        if bitmap:
            win32.DeleteObject(bitmap)
        if memory_dc:
            win32.DeleteDC(memory_dc)
        win32.ReleaseDC(None, screen_dc)
    bgra = buffer.raw
    if crop is not None and (crop.width, crop.height) != (width, height):
        stride = width * 4
        bgra = b"".join(
            bgra[row * stride + crop.left * 4 : row * stride + crop.right * 4]
            for row in range(crop.top, crop.bottom)
        )
        width, height = crop.width, crop.height
    rgb = bytearray(width * height * 3)
    rgb[0::3] = bgra[2::4]
    rgb[1::3] = bgra[1::4]
    rgb[2::3] = bgra[0::4]
    return width, height, bytes(rgb)


def capture_screen() -> bytes:
    """Capture the whole virtual screen."""
    return encode_webp(*capture_screen_pixels())


def capture_screen_pixels() -> Pixels:
    """Capture uncompressed desktop pixels so replay can deduplicate before encoding."""
    return _capture_pixels(win32.virtual_screen_rect())


def capture_element(el: TargetElement) -> bytes | None:
    """Capture an element's visible area; ``None`` if it has no on-screen rectangle."""
    rect = el.rect
    if rect is None:
        return None
    clipped = clip(rect, win32.virtual_screen_rect())
    return capture(clipped) if clipped is not None else None


def _visible_frame(hwnd: int, window: Rect) -> Rect | None:
    """The window's visible frame inside its rectangle, without the invisible resize borders."""
    bounds = win32.RECT()
    try:
        failed = win32.dwmapi.DwmGetWindowAttribute(
            hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(bounds), ctypes.sizeof(bounds)
        )
    except OSError:
        return None
    if failed:
        return None
    visible = clip(
        Rect(bounds.left, bounds.top, bounds.right - bounds.left, bounds.bottom - bounds.top),
        window,
    )
    if visible is None:
        return None
    return Rect(visible.left - window.left, visible.top - window.top, visible.width, visible.height)


def capture_window(hwnd: int, expected_pid: int | None = None) -> bytes | None:
    """Render only the target HWND; never fall back to overlapping desktop pixels."""
    pixels = capture_window_pixels(hwnd, expected_pid)
    return encode_webp(*pixels) if pixels is not None else None


def capture_window_pixels(hwnd: int, expected_pid: int | None = None) -> Pixels | None:
    """Like :func:`capture_window` but uncompressed, so unchanged frames can skip encoding."""
    frame = capture_window_frame(hwnd, expected_pid)
    if frame is None:
        return None
    bounds, rgb = frame
    return bounds.width, bounds.height, rgb


def capture_window_frame(hwnd: int, expected_pid: int | None = None) -> tuple[Rect, bytes] | None:
    """Render one HWND, retaining the screen origin through frame cropping and black trim."""
    if expected_pid is not None and win32.window_pid(hwnd) != expected_pid:
        return None
    if not win32.IsWindowVisible(hwnd) or win32.IsIconic(hwnd):
        return None
    get_rect = win32.user32.GetWindowRect
    get_rect.argtypes = [win32.HWND, ctypes.POINTER(win32.RECT)]
    get_rect.restype = ctypes.c_int
    bounds = win32.RECT()
    if not get_rect(hwnd, ctypes.byref(bounds)):
        return None
    rect = Rect(bounds.left, bounds.top, bounds.right - bounds.left, bounds.bottom - bounds.top)
    if rect.is_empty():
        return None
    visible = _visible_frame(hwnd, rect)
    width, height, rgb = _capture_pixels(rect, hwnd, visible)
    if not get_rect(hwnd, ctypes.byref(bounds)):
        return None
    if rect != Rect(
        bounds.left, bounds.top, bounds.right - bounds.left, bounds.bottom - bounds.top
    ):
        return None
    if expected_pid is not None and win32.window_pid(hwnd) != expected_pid:
        return None
    trimmed, pixels = _trim_black_frame(width, height, rgb)
    if not win32.IsWindowVisible(hwnd) or win32.IsIconic(hwnd):
        return None
    return Rect(
        rect.left + (visible.left if visible else 0) + trimmed.left,
        rect.top + (visible.top if visible else 0) + trimmed.top,
        trimmed.width,
        trimmed.height,
    ), pixels


def trim_black_edges(width: int, height: int, rgb: bytes, limit: int = 2) -> Pixels:
    """Drop up to ``limit`` outer rows and columns that are pure black.

    A rendered window keeps a hairline of the invisible border on some edges; real content is
    almost never pure black along a whole edge, so this only removes that remnant.
    """
    bounds, pixels = _trim_black_frame(width, height, rgb, limit)
    return bounds.width, bounds.height, pixels


def _trim_black_frame(width: int, height: int, rgb: bytes, limit: int = 2) -> tuple[Rect, bytes]:
    stride = width * 3

    def row_black(y: int) -> bool:
        return not any(rgb[y * stride : (y + 1) * stride])

    def column_black(x: int) -> bool:
        return not any(rgb[y * stride + x * 3 + c] for y in range(top, bottom) for c in range(3))

    top, bottom = 0, height
    while top < min(limit, bottom - 1) and row_black(top):
        top += 1
    while height - bottom < limit and bottom - 1 > top and row_black(bottom - 1):
        bottom -= 1
    left, right = 0, width
    while left < min(limit, right - 1) and column_black(left):
        left += 1
    while width - right < limit and right - 1 > left and column_black(right - 1):
        right -= 1
    if (left, top, right, bottom) == (0, 0, width, height):
        return Rect(0, 0, width, height), rgb
    trimmed = b"".join(
        rgb[y * stride + left * 3 : y * stride + right * 3] for y in range(top, bottom)
    )
    return Rect(left, top, right - left, bottom - top), trimmed


def save(image: bytes, path: Path) -> Path:
    """Save to ``.webp`` (lossless) or explicitly export to ``.png`` without changing pixels."""
    path = Path(path)
    formats = {".webp": "WEBP", ".png": "PNG"}
    target_format = formats.get(path.suffix.lower())
    if target_format is None:
        raise ValueError("screenshot path must end in .webp or .png")
    with Image.open(BytesIO(image)) as source:
        if source.format != target_format:
            with source.convert("RGB") as pixels:
                encoder = encode_webp if target_format == "WEBP" else encode_png
                image = encoder(pixels.width, pixels.height, pixels.tobytes())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(image)
    return path
