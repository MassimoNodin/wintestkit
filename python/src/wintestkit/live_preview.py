"""Live preview of an inspected element: its crop and its window with the element outlined.

Unlike the saved check images in ``object_previews`` nothing is saved: the pictures go to the editor
for the object the user has selected in Spy, who is already looking at that application.
"""

from __future__ import annotations

import base64
from io import BytesIO
from typing import Any, cast

from PIL import Image, ImageDraw

from wintestkit.backends.element import TargetElement, WpfElement
from wintestkit.uia import screenshot, win32
from wintestkit.uia.element import UIAElement

# Longest edge sent to the editor. Captures are sent at their real size: scaling a window down
# turns small text to mush, and lossless WebP of a UI is small anyway (about 150 KB for a whole
# 3440x1440 screen). Only a capture past this edge (the editor accepts 16384) is scaled down.
MAX_EDGE = 7680
# The editor refuses images over 16 MiB; a busier capture is scaled down until it fits.
MAX_BYTES = 12 * 1024 * 1024
_OUTLINE_WIDTH = 2
_OUTLINE_STEP = 500  # one more pixel of outline per this many pixels of window
_MIN_EDGE = 256  # never shrink below this just to fit the byte limit


class PreviewUnavailable(Exception):
    """The element cannot be previewed right now; the message tells the user why."""


def _top_level_window(element: UIAElement) -> int:
    current: UIAElement | None = element
    for _depth in range(64):
        if current is None:
            break
        current = current.as_live()
        hwnd = current.native_window_handle
        if hwnd:
            return win32.root_window(hwnd)
        current = current.parent()
    raise PreviewUnavailable("The object does not belong to a window that can be captured.")


def _webp(image: Image.Image) -> bytes:
    with BytesIO() as output:
        image.save(output, format="WEBP", lossless=True, method=1)
        return output.getvalue()


def _encode(image: Image.Image) -> dict[str, Any]:
    data = _webp(image)
    while len(data) > MAX_BYTES and max(image.size) > _MIN_EDGE:
        smaller = (max(1, round(image.width * 0.7)), max(1, round(image.height * 0.7)))
        image = image.resize(smaller, Image.Resampling.LANCZOS)  # pyright: ignore[reportUnknownMemberType]
        data = _webp(image)
    return {
        "data": base64.b64encode(data).decode("ascii"),
        "width": image.width,
        "height": image.height,
    }


def _fit(image: Image.Image) -> tuple[Image.Image, float]:
    scale = min(1.0, MAX_EDGE / max(image.width, image.height))
    if scale == 1.0:
        return image, 1.0
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    resized = image.resize(size, Image.Resampling.LANCZOS)  # pyright: ignore[reportUnknownMemberType]
    return resized, scale


def capture_live_preview(element: TargetElement, *, whole_window: bool = False) -> dict[str, Any]:
    """The element's crop and its top-level window with the element outlined, as WebP images.

    A top-level window (or ``whole_window``) is shown whole as its own element image. Returns
    ``{"reason": ...}`` instead when there is nothing to show. The window is rendered without being
    brought forward, so it may be covered; a minimized window cannot be rendered.
    """
    try:
        return _capture(element, whole_window=whole_window)
    except PreviewUnavailable as exc:
        return {"reason": str(exc)}
    except Exception as exc:
        return {"reason": f"The preview could not be captured: {exc}"}


def capture_process_preview(pid: int) -> dict[str, Any]:
    """A process row's preview: its main visible top-level window, whole."""
    from wintestkit.uia.element import from_handle

    try:
        windows = win32.top_level_windows({pid})
        if not windows:
            return {"reason": "The process has no visible top-level window to capture."}
        # Prefer a titled window that is not minimized; z-order breaks ties.
        hwnd = min(
            windows,
            key=lambda handle: (bool(win32.IsIconic(handle)), not win32.window_text(handle)),
        )
        return capture_live_preview(from_handle(hwnd), whole_window=True)
    except Exception as exc:
        return {"reason": f"The preview could not be captured: {exc}"}


def _owner_window(element: TargetElement) -> int:
    """The top-level window an object is drawn in."""
    if isinstance(element, WpfElement):
        hwnd = element.state().window_handle
        if not hwnd:
            raise PreviewUnavailable("The object does not belong to a window that can be captured.")
        return win32.root_window(hwnd)
    return _top_level_window(cast(UIAElement, element))


def _is_top_level(element: TargetElement, hwnd: int) -> bool:
    """Whether the object is the top-level window itself rather than something inside it."""
    try:
        return bool(hwnd) and element.native_window_handle == hwnd
    except Exception:
        return False


def _not_captured(hwnd: int) -> str:
    if win32.IsIconic(hwnd):
        return "The window is minimized, so it cannot be captured. Restore it and select it again."
    if not win32.IsWindowVisible(hwnd):
        return "The window is hidden, so it cannot be captured."
    return (
        "The window cannot be captured. It may be covered by a protected window or not renderable."
    )


def _capture(element: TargetElement, *, whole_window: bool = False) -> dict[str, Any]:
    element = element.as_live()
    hwnd = _owner_window(element)
    whole = whole_window or _is_top_level(element, hwnd)
    bounds = None if whole else element.rect
    if not whole and bounds is None:
        raise PreviewUnavailable(
            "This object has no on-screen rectangle. It may be hidden, collapsed, "
            "not laid out yet or in a minimized window."
        )
    frame = screenshot.capture_window_frame(hwnd)
    if frame is None:
        raise PreviewUnavailable(_not_captured(hwnd))
    window_bounds, pixels = frame
    if not any(pixels):
        raise PreviewUnavailable("The window rendered as a blank image.")
    with Image.frombytes("RGB", (window_bounds.width, window_bounds.height), pixels) as frame_image:
        extrema = cast("tuple[tuple[int, int], ...]", frame_image.getextrema())
        if all(low == high for low, high in extrema):
            raise PreviewUnavailable(
                "The window rendered as a single colour; it may not be painted yet"
            )
    if bounds is None:
        with Image.frombytes("RGB", (window_bounds.width, window_bounds.height), pixels) as window:
            fitted, _ = _fit(window)
            encoded = _encode(fitted)
        return {"element": encoded, "window": encoded}
    visible = screenshot.clip(bounds, window_bounds)
    if visible is None:
        raise PreviewUnavailable("The object lies outside its window's visible area.")
    left, top = visible.left - window_bounds.left, visible.top - window_bounds.top
    with Image.frombytes("RGB", (window_bounds.width, window_bounds.height), pixels) as window:
        with window.crop((left, top, left + visible.width, top + visible.height)) as crop:
            crop, _ = _fit(crop)
            element_image = _encode(crop)
        outlined, scale = _fit(window)  # the crop is already taken, so drawing on it is safe
        # Keep the outline visible however large the window is, without covering a small element.
        width = min(
            max(_OUTLINE_WIDTH, round(max(outlined.size) / _OUTLINE_STEP)),
            max(_OUTLINE_WIDTH, min(visible.width, visible.height) // 6),
        )
        ImageDraw.Draw(outlined).rectangle(
            (
                round(left * scale),
                round(top * scale),
                max(round(left * scale), round((left + visible.width) * scale) - 1),
                max(round(top * scale), round((top + visible.height) * scale) - 1),
            ),
            outline="red",
            width=width,
        )
        window_image = _encode(outlined)
    return {"element": element_image, "window": window_image}
