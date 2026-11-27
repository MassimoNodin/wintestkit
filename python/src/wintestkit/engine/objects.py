"""Walk the object tree (WPF) and the child windows (UIA) in the terms of the label grammar.

The grammar itself lives in :mod:`wintestkit.labels`; this module reads the live tree into the
nodes that module reasons about: the object-tree children of a WPF element, the window nodes of
an application and the child windows of a Win32 window.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from wintestkit import labels, runtime
from wintestkit.backends.element import TargetElement, WpfElement
from wintestkit.engine.locator import Locator
from wintestkit.engine.managed import operation_deadline
from wintestkit.engine.wpf_resolve import query, route
from wintestkit.errors import InspectorLimitError, WtkError
from wintestkit.inspector.paths import PathSegment
from wintestkit.uia.element import UIAElement

if TYPE_CHECKING:
    from wintestkit.app import App

__all__ = [
    "Child",
    "children_of",
    "label_chain",
    "own_step",
    "parent_of",
    "window_nodes",
]

_ALL_CHILDREN = Locator(tree="objects", depth=1, allow_empty=True)


@dataclass(frozen=True)
class Child:
    """A live child with the node the grammar sees: object-tree child or child window."""

    element: TargetElement
    node: labels.ObjectNode | labels.WindowNode


def read_node(element: WpfElement, type_name: str | None = None) -> labels.ObjectNode:
    """The type, text and x:Name of an object. An unreadable text (redacted, a throwing getter)
    is ``None``: such an object can only be addressed by its ordinal."""
    __tracebackhide__ = True
    values, _ = element.client.read(
        element.ref.object_id,
        element.ref.generation,
        [(PathSegment("object", "Text"),), (PathSegment("property", "Name"),)],
        deadline=operation_deadline(5),
    )
    text, name = values[0].value, values[1].value
    return labels.ObjectNode(
        type_name or element.ref.type.name,
        text.scalar if text.status == "ok" and isinstance(text.scalar, str) else None,
        name.scalar if name.status == "ok" and isinstance(name.scalar, str) else "",
    )


def wpf_children(parent: WpfElement) -> list[Child]:
    """The object-tree children of ``parent`` in object-tree order."""
    __tracebackhide__ = True
    found = query(parent, _ALL_CHILDREN)
    if not found.complete:
        raise InspectorLimitError(
            "The element has more object-tree children than one query returns; "
            "address the child you want with a label or find_child",
            code="limitExceeded",
        )
    return [Child(element, read_node(element)) for element in found]


def window_nodes(app: App) -> list[Child]:
    """The window nodes of an application: one per top-level WPF window, in window order."""
    __tracebackhide__ = True
    nodes: list[Child] = []
    for window in app.top_level_windows():
        if window.framework_id != "WPF" or runtime.get_config().backend != "auto":
            continue
        root = route(window)
        if not isinstance(root, WpfElement):
            continue
        title = read_node(root, labels.WINDOW_NODE_PREFIX + root.ref.type.name)
        nodes.append(Child(root, labels.ObjectNode(title.type_name, title.text, "")))
    return nodes


def _is_window(element: UIAElement) -> bool:
    return bool(element.native_window_handle) and bool(element.class_name)


def uia_children(parent: UIAElement) -> list[Child]:
    """The child windows of a window: its children that own a window handle."""
    __tracebackhide__ = True
    return [
        Child(child, labels.WindowNode(child.class_name, child.name))
        for child in parent.children()
        if _is_window(child)
    ]


def top_level_windows(app: App) -> list[Child]:
    __tracebackhide__ = True
    return [
        Child(window, labels.WindowNode(window.class_name, window.name))
        for window in app.top_level_windows()
    ]


def children_of(
    app: App, element: TargetElement | None, *, window_node: bool = False
) -> list[Child]:
    """The children of ``element`` as the label grammar counts them.

    ``None`` is the application itself (its window nodes). A window node (``window_node``) is
    represented by its root visual and has that root visual as its only child.
    """
    __tracebackhide__ = True
    if element is None:
        return window_nodes(app)
    if isinstance(element, WpfElement):
        if window_node:
            return [Child(element, read_node(element))]
        return wpf_children(element)
    return uia_children(element)  # type: ignore[arg-type]


def parent_of(app: App, element: TargetElement) -> TargetElement | None:
    """The parent in the object tree (WPF) or the nearest enclosing window (UIA).

    ``None`` for a root visual (whose parent is its window node) and for a top-level window.
    """
    __tracebackhide__ = True
    if isinstance(element, WpfElement):
        ref = element.client.parent(
            element.ref.object_id,
            element.ref.generation,
            tree="objects",
            deadline=operation_deadline(5),
        )
        return WpfElement(element.client, ref, element.process_id) if ref else None
    if any(window.same_as(element) for window in app.top_level_windows()):  # type: ignore[arg-type]
        return None
    node: Any = element.parent()
    while node is not None and not _is_window(node):
        node = node.parent()
    return node  # type: ignore[no-any-return]


def _position(siblings: list[Child], element: TargetElement) -> int:
    for position, child in enumerate(siblings):
        if element.same_as(child.element):  # type: ignore[arg-type]
            return position
    raise WtkError(
        f"{element.info().short()} was not found among its parent's children: "
        "it may have moved or closed while its label was computed"
    )


def child_steps(children: list[Child]) -> list[labels.Step]:
    """The label step of every child, written against its siblings."""
    nodes = [child.node for child in children]
    return [
        labels.object_step(nodes, position)  # type: ignore[arg-type]
        if isinstance(node, labels.ObjectNode)
        else labels.window_step(nodes, position)  # type: ignore[arg-type]
        for position, node in enumerate(nodes)
    ]


def own_step(app: App, element: TargetElement, *, window_node: bool = False) -> labels.Step:
    """The label step of ``element`` among its siblings (or, for a window node, among the nodes)."""
    __tracebackhide__ = True
    if window_node:
        nodes = window_nodes(app)
        return labels.object_step([c.node for c in nodes], _position(nodes, element))  # type: ignore[misc]
    parent = parent_of(app, element)
    if isinstance(element, WpfElement) and parent is None:
        return labels.object_step([read_node(element)], 0)
    siblings = children_of(app, parent) if parent is not None else top_level_windows(app)
    position = _position(siblings, element)
    nodes = [child.node for child in siblings]
    if isinstance(element, WpfElement):
        return labels.object_step(nodes, position)  # type: ignore[arg-type]
    return labels.window_step(nodes, position)  # type: ignore[arg-type]


def label_chain(
    app: App, element: TargetElement, *, window_node: bool = False
) -> list[labels.Step]:
    """The steps from the application down to ``element``, outermost first.

    For a WPF root visual the chain starts with the step of its window node; the window node
    itself is the chain's only step when ``window_node`` is set.
    """
    __tracebackhide__ = True
    steps = [own_step(app, element, window_node=window_node)]
    if window_node:
        return steps
    node: TargetElement = element
    while True:
        parent = parent_of(app, node)
        if parent is None:
            if isinstance(node, WpfElement):
                steps.append(own_step(app, node, window_node=True))
            break
        steps.append(own_step(app, parent))
        node = parent
    steps.reverse()
    return steps
