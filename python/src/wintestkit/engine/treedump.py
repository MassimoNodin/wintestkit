"""Dump a UI Automation subtree as text or JSON (for `wtk inspect` and failure artifacts)."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import replace
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
    stack: list[tuple[int, Iterator[UIAElement]]] = [(0, iter((root,)))]
    yielded = 0
    while stack and yielded < max_nodes:
        depth, siblings = stack[-1]
        element = next(siblings, None)
        if element is None:
            stack.pop()
            continue
        yield depth, element
        yielded += 1
        if yielded < max_nodes and depth < max_depth:
            stack.append((depth + 1, element.iter_children()))


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
    max_bytes: int | None = None,
) -> str:
    """Indented text dump of a subtree (two spaces per level)."""
    lines: list[str] = []
    count = 0
    remaining = max_bytes

    def append_line(text: str) -> bool:
        nonlocal remaining
        if remaining is None:
            lines.append(text)
            return True
        separator = 1 if lines else 0
        available = max(0, remaining - separator)
        encoded = text[:available].encode("utf-8")
        clipped = encoded[:available].decode("utf-8", "ignore")
        if remaining >= separator:
            lines.append(clipped)
            remaining -= separator + len(clipped.encode("utf-8"))
        return len(encoded) <= available and remaining > 0 and len(text) <= available

    for depth, element in _walk_elements(root, max_depth, max_nodes):
        info = element.info()
        if remaining is not None:
            info = replace(
                info,
                name=info.name[:remaining],
                class_name=info.class_name[:remaining],
                automation_id=info.automation_id[:remaining],
                control_type=info.control_type[:remaining],
            )
        if not append_line("  " * depth + format_node(info)):
            return "\n".join(lines)
        if property_aliases is not None:
            for key, value in inspection_values(element, property_aliases).items():
                if value != "" and not append_line("  " * (depth + 1) + f"{key}: {value}"):
                    return "\n".join(lines)
        count += 1
    if count >= max_nodes:
        append_line(f"… (truncated at {max_nodes} nodes)")
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
