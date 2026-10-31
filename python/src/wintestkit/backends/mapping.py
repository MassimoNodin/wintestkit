"""Shared inspector RuntimeId to UIA mapping."""

from wintestkit.uia import com
from wintestkit.uia.constants import TreeScope
from wintestkit.uia.element import UIAElement


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
