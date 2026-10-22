"""Live preview of an inspected element: its crop and its window with the element outlined.

Unlike the test-time images in ``object_previews`` nothing is saved: the pictures go to the editor
for the object the user has selected in Spy, who is already looking at that application.
"""

from __future__ import annotations

import base64
from io import BytesIO
from typing import Any

from PIL import Image, ImageDraw

from wintestkit.uia import screenshot, win32
from wintestkit.uia.element import UIAElement

# Longest edge sent to the editor; larger captures are scaled down to keep messages small.
MAX_EDGE = 1600
_OUTLINE_WIDTH = 2


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


def _encode(image: Image.Image) -> dict[str, Any]:
    with BytesIO() as output:
        image.save(output, format="WEBP", lossless=True, method=1)
        data = output.getvalue()
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


def capture_live_preview(element: UIAElement) -> dict[str, Any]:
    """The element's crop and its top-level window with the element outlined, as WebP images.

    Returns ``{"reason": ...}`` instead when there is nothing to show. The window is rendered
    without being brought forward, so it may be covered; a minimized window cannot be rendered.
    """
    try:
        return _capture(element)
    except PreviewUnavailable as exc:
        return {"reason": str(exc)}
    except Exception as exc:
        return {"reason": f"The preview could not be captured: {exc}"}


def _capture(element: UIAElement) -> dict[str, Any]:
    element = element.as_live()
    bounds = element.rect
    if bounds is None:
        raise PreviewUnavailable(
            "This object has no on-screen rectangle. It may be hidden, collapsed, "
            "not laid out yet or in a minimized window."
        )
    hwnd = _top_level_window(element)
    frame = screenshot.capture_window_frame(hwnd)
    if frame is None:
        raise PreviewUnavailable(
            "The window cannot be captured. It may be minimized, hidden or not renderable."
        )
    window_bounds, pixels = frame
    if not any(pixels):
        raise PreviewUnavailable("The window rendered as a blank image.")
    visible = screenshot.clip(bounds, window_bounds)
    if visible is None:
        raise PreviewUnavailable("The object lies outside its window's visible area.")
    left, top = visible.left - window_bounds.left, visible.top - window_bounds.top
    with Image.frombytes("RGB", (window_bounds.width, window_bounds.height), pixels) as window:
        with window.crop((left, top, left + visible.width, top + visible.height)) as crop:
            crop, _ = _fit(crop)
            element_image = _encode(crop)
        outlined, scale = _fit(window)  # the crop is already taken, so drawing on it is safe
        ImageDraw.Draw(outlined).rectangle(
            (
                round(left * scale),
                round(top * scale),
                max(round(left * scale), round((left + visible.width) * scale) - 1),
                max(round(top * scale), round((top + visible.height) * scale) - 1),
            ),
            outline="red",
            width=_OUTLINE_WIDTH,
        )
        window_image = _encode(outlined)
    return {"element": element_image, "window": window_image}
