"""Shared inspector RuntimeId to UIA mapping."""

from wintestkit.inspector.models import ElementState
from wintestkit.uia import com
from wintestkit.uia.constants import TreeScope
from wintestkit.uia.element import UIAElement


def map_state_at_point(state: ElementState) -> UIAElement | None:
    """Try the visible centre and its control-view ancestors before a subtree scan."""
    from wintestkit.uia.element import from_point

    bounds = state.bounds
    if (
        bounds is None
        or bounds.width <= 0
        or bounds.height <= 0
        or state.offscreen
        or state.clipped
        or not state.visible
        or not state.uia_runtime_id
    ):
        return None
    expected = ".".join(map(str, state.uia_runtime_id))
    try:
        element = from_point(int(bounds.x + bounds.width / 2), int(bounds.y + bounds.height / 2))
        for _ in range(9):
            if element is None:
                break
            if element.runtime_id == expected:
                return element
            element = element.parent()
    except Exception:
        # Hit testing can race a disappearing window; fall back to exact subtree mapping.
        return None
    return None


def map_runtime_ids(
    groups: dict[int, list[tuple[int, ...]]],
) -> dict[tuple[int, tuple[int, ...]], UIAElement]:
    from wintestkit.uia.element import from_handle

    mapped: dict[tuple[int, tuple[int, ...]], UIAElement] = {}
    for hwnd, ids in groups.items():
        window = from_handle(hwnd)
        for offset in range(0, len(ids), 25):
            batch = ids[offset : offset + 25]
            found = window.find_all(
                TreeScope.Subtree, com.create_runtime_ids_condition(batch), cached=True
            )
            for element in [*found, window]:
                try:
                    identity = tuple(int(part) for part in element.runtime_id.split("."))
                except ValueError:
                    continue
                if identity in batch:
                    mapped.setdefault((hwnd, identity), element)
    return mapped
