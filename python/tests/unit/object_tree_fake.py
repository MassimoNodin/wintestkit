"""An in-memory WPF application for the label tests: windows, object trees and the agent calls
that read them. The resolver and the navigation helpers run unchanged on top of it; only the
requests to the agent are answered here, by a small interpreter of object-tree locators."""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any

from wintestkit import runtime
from wintestkit.app import App
from wintestkit.backends import WpfElement
from wintestkit.engine import objects
from wintestkit.engine import resolve as resolver
from wintestkit.engine.locator import Locator
from wintestkit.engine.wpf_resolve import QueryMatches
from wintestkit.inspector.models import ObjectRef, TypeInfo


class Node:
    """One object of the tree: its runtime type, the text it shows and its x:Name."""

    def __init__(
        self, type_name: str, text: str | None = "", name: str = "", *children: Node
    ) -> None:
        self.type_name = type_name
        self.text = text
        self.name = name
        self.children = list(children)
        self.parent: Node | None = None
        for child in children:
            child.parent = self

    def ordinal(self) -> int:
        if self.parent is None:
            return 1
        same = [c for c in self.parent.children if c.type_name == self.type_name]
        return same.index(self) + 1

    def preorder(self) -> list[Node]:
        found = [self]
        for child in self.children:
            found.extend(child.preorder())
        return found


def _value(status: str, scalar: object = None) -> SimpleNamespace:
    return SimpleNamespace(status=status, scalar=scalar)


class FakeInspector:
    """The agent's side: object ids, reads, parents."""

    def __init__(self) -> None:
        self.session = SimpleNamespace(features=["query", "geometry", "exactUiaMapping"])
        self.nodes: dict[str, Node] = {}
        self.ids: dict[int, str] = {}

    def ref(self, node: Node) -> ObjectRef:
        object_id = self.ids.setdefault(id(node), f"o{len(self.ids) + 1}")
        self.nodes[object_id] = node
        info = TypeInfo(node.type_name, f"Fixture.{node.type_name}", "A", "A", ())
        return ObjectRef("session", object_id, 1, info, "dispatcher")

    def element(self, node: Node) -> WpfElement:
        return WpfElement(self, self.ref(node), 1)  # type: ignore[arg-type]

    def node_of(self, element: WpfElement) -> Node:
        return self.nodes[element.ref.object_id]

    # -- the requests the library makes ---------------------------------------------------

    def release(self, ids: Any, *, deadline: float) -> None:
        pass

    def read(self, object_id: str, generation: int, paths: Any, *, deadline: float) -> Any:
        node = self.nodes[object_id]
        values = []
        for path in paths:
            segment = path[0]
            if segment.kind == "object" and segment.name == "Text":
                value = _value("ok", node.text) if node.text is not None else _value("redacted")
            elif segment.kind == "property" and segment.name == "Name":
                value = _value("ok", node.name)
            else:
                value = _value("ok", "")
            values.append(SimpleNamespace(path=path, value=value))
        return tuple(values), "read"

    def parent(self, object_id: str, generation: int, *, tree: str | None = None, deadline: float):
        assert tree == "objects"
        parent = self.nodes[object_id].parent
        return self.ref(parent) if parent is not None else None

    def state_get(self, ref: Any, *, timeout_ms: int, deadline: float) -> Any:
        return SimpleNamespace(
            bounds=None,
            visible_bounds=None,
            enabled=True,
            offscreen=False,
            focused=False,
            uia_runtime_id=(),
            window_handle=0,
        )


def _text_ok(expected: Any, text: str | None) -> bool:
    if text is None:
        return False
    if isinstance(expected, re.Pattern):
        return expected.search(text) is not None
    return expected == text


def condition_ok(node: Node, window_node: bool, key: str, expected: Any) -> bool:
    """Whether a node satisfies one ``where`` entry, as the agent evaluates it."""
    if key == "type:Name":
        actual = ("HwndSource: " if window_node else "") + node.type_name
        return _text_ok(expected, actual)
    if key == "wpf:Ordinal":
        return node.ordinal() == expected
    if key == "wpf:Text":
        return _text_ok(expected, node.text)
    if key == "clr:Name":
        return not window_node and _text_ok(expected, node.name)
    raise AssertionError(f"the fake agent does not know {key}")


class FakeApp:
    """Windows with their root visuals, patched into the resolver and the navigation helpers."""

    def __init__(self, monkeypatch: Any, *roots: Node, process_name: str = "Demo.exe") -> None:
        self.inspector = FakeInspector()
        self.windows = [
            SimpleNamespace(
                framework_id="WPF", root=root, info=lambda: SimpleNamespace(short=lambda: "window")
            )
            for root in roots
        ]
        app = object.__new__(App)
        app.process_name = process_name
        monkeypatch.setattr(app, "top_level_windows", lambda: self.windows)
        self.app = app
        self.queries: list[Locator] = []

        monkeypatch.setenv("WTK_BACKEND", "auto")
        monkeypatch.setenv("WTK_TIMEOUT", "0.3")
        runtime.reset()
        monkeypatch.setattr(resolver, "route", self.route)
        monkeypatch.setattr(objects, "route", self.route)
        monkeypatch.setattr(resolver, "wpf_query", self.query)
        monkeypatch.setattr(objects, "query", self.query)
        monkeypatch.setattr(resolver, "identity_value", lambda root, name: "")
        monkeypatch.setattr(resolver, "x_name", lambda root: self.inspector.node_of(root).name)
        monkeypatch.setattr(resolver, "matches_root", self.matches_root)
        monkeypatch.setattr(resolver, "_hosting_window", lambda scope, element: _window())
        monkeypatch.setattr(
            WpfElement,
            "info",
            lambda element, with_patterns=False: SimpleNamespace(
                short=lambda: f"<{element.ref.type.name}>"
            ),
        )

    def route(self, window: Any) -> WpfElement:
        return self.inspector.element(window.root)

    def matches_root(self, root: WpfElement, conditions: list[Any]) -> bool:
        node = self.inspector.node_of(root)
        return all(condition_ok(node, False, c.key, c.value) for c in conditions)

    def query(
        self, root: WpfElement, locator: Locator, *, use_index: bool = False, root_level=False
    ) -> QueryMatches:
        """The object-tree search of the agent: depth counts levels, matches are in pre-order."""
        self.queries.append(locator)
        start = self.inspector.node_of(root)
        limit = locator.depth if locator.depth is not None else 10**6
        levels: list[tuple[int, Node]] = []

        def walk(node: Node, depth: int) -> None:
            levels.append((depth, node))
            for child in node.children:
                walk(child, depth + 1)

        if root_level:
            walk(start, 1)
        else:
            for child in start.children:
                walk(child, 1)
        found = [
            node
            for depth, node in levels
            if depth <= limit
            and all(condition_ok(node, False, key, value) for key, value in locator.where)
        ]
        return QueryMatches(self.inspector.element(node) for node in found)

    # -- helpers for the tests ------------------------------------------------------------

    def resolve(self, bound: Any) -> Node:
        return self.inspector.node_of(bound.resolve_once())


def _window() -> Any:
    from fakes import FakeElement

    return FakeElement("Window", "Demo")
