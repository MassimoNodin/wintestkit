"""Select the closest outlineable element for highlighting."""

from __future__ import annotations

from wintestkit.backends.element import TargetElement, WpfElement
from wintestkit.errors import ActionError
from wintestkit.uia.element import Rect, UIAElement


def outline(element: TargetElement) -> tuple[Rect, TargetElement | None]:
    """Return the bounds and, if needed, the ancestor that supplied them."""
    current: TargetElement | None = element
    seen: set[str] = set()
    for _ in range(100):
        if current is None:
            break
        identity = current.runtime_id
        if identity and identity in seen:
            break
        if identity:
            seen.add(identity)
        rect = current.visible_rect if isinstance(current, WpfElement) else current.rect
        if rect is None and isinstance(current, UIAElement):
            rect = _window_rect(current)
        if rect is not None and not rect.is_empty():
            return rect, None if current is element else current
        current = current.parent()
    raise ActionError(f"{element.info().short()} has no on-screen rectangle to highlight")


def _window_rect(element: UIAElement) -> Rect | None:
    import ctypes

    from wintestkit.uia import win32

    handle = element.native_window_handle
    if handle and win32.IsWindowVisible(handle):
        bounds = win32.RECT()
        if win32.GetWindowRect(handle, ctypes.byref(bounds)):
            rect = Rect(
                bounds.left, bounds.top, bounds.right - bounds.left, bounds.bottom - bounds.top
            )
            return None if rect.is_empty() else rect
    return None
