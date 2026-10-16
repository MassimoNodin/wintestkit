"""Dump a UI Automation subtree as text or JSON (for `wtk inspect` and failure artifacts)."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from wintestkit.engine.diagnose import quote
from wintestkit.engine.properties import inspection_values
from wintestkit.uia.constants import TreeScope
from wintestkit.uia.element import ElementInfo, UIAElement


def _walk_elements(
    root: UIAElement, max_depth: int = 50, max_nodes: int = 5000
) -> Iterator[tuple[int, UIAElement]]:
    """Yield ``(depth, info)`` for ``root`` and its descendants in document order.

    Nodes at ``max_depth`` are yielded but not expanded; at most ``max_nodes`` are yielded.
    """
    stack: list[tuple[int, UIAElement]] = [(0, root)]
    yielded = 0
    while stack and yielded < max_nodes:
        depth, element = stack.pop()
        yield depth, element
        yielded += 1
        if depth < max_depth:
            children = element.find_all(TreeScope.Children, None, cached=True)
            stack.extend((depth + 1, child) for child in reversed(children))


def walk(
    root: UIAElement, max_depth: int = 50, max_nodes: int = 5000
) -> Iterator[tuple[int, ElementInfo]]:
    """Yield bounded subtree descriptions in document order."""
    for depth, element in _walk_elements(root, max_depth, max_nodes):
        yield depth, element.info()


def format_node(info: ElementInfo) -> str:
    """One-line description: ``Button "Sign in" [class=Button] (412,233 80x24) id=X disabled``."""
    text = info.control_type
    if info.name:
        text += f" {quote(info.name)}"
    if info.class_name:
        text += f" [class={info.class_name}]"
    if info.rect is not None:
        r = info.rect
        text += f" ({r.left},{r.top} {r.width}x{r.height})"
    if info.automation_id:
        text += f" id={info.automation_id}"
    if not info.is_enabled:
        text += " disabled"
    if info.is_offscreen:
        text += " offscreen"
    return text


def dump(
    root: UIAElement,
    max_depth: int = 12,
    max_nodes: int = 3000,
    property_aliases: Mapping[str, str] | None = None,
) -> str:
    """Indented text dump of a subtree (two spaces per level)."""
    lines: list[str] = []
    count = 0
    for depth, element in _walk_elements(root, max_depth, max_nodes):
        lines.append("  " * depth + format_node(element.info()))
        if property_aliases is not None:
            for key, value in inspection_values(element, property_aliases).items():
                if value != "":
                    lines.append("  " * (depth + 1) + f"{key}: {value}")
        count += 1
    if count >= max_nodes:
        lines.append(f"… (truncated at {max_nodes} nodes)")
    return "\n".join(lines)


def dump_json(
    root: UIAElement,
    max_depth: int = 12,
    max_nodes: int = 3000,
    property_aliases: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Nested ``{"info": ElementInfo, "children": [...]}`` dump of a subtree."""
    budget = [max_nodes]

    def build(element: UIAElement, depth: int) -> dict[str, Any] | None:
        if budget[0] <= 0:
            return None
        budget[0] -= 1
        node: dict[str, Any] = {"info": element.info().to_dict(), "children": []}
        if property_aliases is not None:
            node["properties"] = inspection_values(element, property_aliases)
        if depth < max_depth:
            for child in element.find_all(TreeScope.Children, None, cached=True):
                built = build(child, depth + 1)
                if built is None:
                    break
                node["children"].append(built)
        return node

    result = build(root, 0)
    assert result is not None or max_nodes <= 0
    return result or {"info": root.info().to_dict(), "children": []}
