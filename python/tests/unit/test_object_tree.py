"""The object-tree locator option, the ``wpf:`` keys and the migration finders built on them."""

from __future__ import annotations

import re
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest

from wintestkit import Element, Elements, Page
from wintestkit.backends import WpfElement
from wintestkit.controls import Button
from wintestkit.engine import resolve as resolver
from wintestkit.engine import wpf_resolve
from wintestkit.engine.locator import Locator
from wintestkit.engine.managed import ManagedCondition
from wintestkit.engine.properties import AsText, resolve_where
from wintestkit.engine.wpf_query import translate
from wintestkit.errors import InvalidLocatorError
from wintestkit.finders import find_child, to_locator
from wintestkit.inspector.models import ObjectRef, TypeInfo, parse_path
from wintestkit.inspector.paths import PathSegment


def ref(name: str, type_name: str = "Control") -> ObjectRef:
    return ObjectRef("session", name, 1, TypeInfo(type_name, type_name, "A", "A", ()), "dispatcher")


# -- the locator option ------------------------------------------------------------------------


def test_tree_is_validated_described_and_serialized():
    locator = Locator(automation_id="x", depth=2, tree="objects")
    assert locator.describe() == '*[id="x", depth=2, tree=objects]'
    assert locator.to_dict() == {"automationId": "x", "depth": 2, "tree": "objects"}
    assert Locator.from_dict(locator.to_dict()) == locator
    assert "tree" not in Locator(automation_id="x").to_dict()
    with pytest.raises(ValueError, match="tree must be 'objects'"):
        Locator(automation_id="x", tree="uia")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unknown locator key"):
        Locator.from_dict({"automationId": "x", "tree": "objects", "treee": 1})
    with pytest.raises(ValueError, match="take only properties"):
        Locator(automation_id="x", tree="objects").check_alternative()


def test_declarations_take_the_option():
    class Page1(Page):
        single = Element(automation_id="a", tree="objects")
        group = Elements(class_name="Row", tree="objects")
        typed = Button(name="OK", tree="objects")
        child = single.Button(name="Save", tree="objects")
        plain = Element(automation_id="b")

    assert Page1.single.locator().tree == "objects"
    assert Page1.group.locator().tree == "objects"
    assert Page1.typed.locator().tree == "objects"
    assert Page1.child.locator().tree == "objects"
    assert Page1.child.locator().depth == 1
    assert Page1.plain.locator().tree is None
    assert "tree=objects" in Page1.typed.locator().describe()


def test_uia_form_is_the_fallback_for_other_windows():
    plain = Locator(automation_id="x")
    assert plain.for_uia() is plain
    with pytest.raises(InvalidLocatorError, match="needs a WPF window"):
        Locator(automation_id="x", tree="objects").for_uia()
    migrated = to_locator(["WPFControlText", "WPFControlOrdinalNo"], ["OK", 3], depth=2)
    uia = migrated.for_uia()
    assert (uia.name, uia.index, uia.depth, uia.tree, uia.uia_form) == ("OK", 2, 2, None, None)
    # The UIA form is runtime-only and is not serialized.
    assert "uiaForm" not in migrated.to_dict()


def test_where_takes_the_object_tree_keys():
    locator = Locator(where=(("wpf:Text", "OK"), ("wpf:Ordinal", 2)), tree="objects")
    conditions = resolve_where(locator.where, "test")
    assert all(isinstance(condition, ManagedCondition) for condition in conditions)
    assert [condition.path.segments for condition in conditions] == [
        (PathSegment("object", "Text"),),
        (PathSegment("object", "Ordinal"),),
    ]
    wire = translate(locator, conditions, None)
    assert [(p.kind, p.path[0].kind, p.path[0].name, p.value) for p in wire.predicates] == [
        ("equals", "object", "Text", "OK"),
        ("equals", "object", "Ordinal", 2),
    ]
    assert wire.to_json()["predicates"][0]["path"] == [{"kind": "object", "name": "Text"}]
    texted = Locator(where=(("wpf:Text", AsText("7")), ("wpf:Ordinal", re.compile("^2$"))))
    kinds = [p.kind for p in translate(texted, resolve_where(texted.where, "t"), None).predicates]
    assert kinds == ["equalsText", "regex"]
    with pytest.raises(InvalidLocatorError):
        Locator(where=(("wpf:Name", "x"),))


def test_object_segments_are_validated():
    assert PathSegment.from_json({"kind": "object", "name": "Ordinal"}) == PathSegment(
        "object", "Ordinal"
    )
    for bad in (
        {"kind": "object", "name": "Other"},
        {"kind": "object", "name": "Text", "declaringType": "A"},
        {"kind": "object"},
    ):
        with pytest.raises(ValueError):
            PathSegment.from_json(bad)
    assert parse_path([{"kind": "object", "name": "Text"}])
    with pytest.raises(ValueError):
        parse_path([{"kind": "object", "name": "Text"}, {"kind": "property", "name": "Length"}])


# -- the wire query ---------------------------------------------------------------------------


def test_translate_selects_the_object_tree_and_levels():
    locator = Locator(name="x", tree="objects", depth=3)
    wire = translate(locator, (), None)
    assert (wire.tree, wire.depth, wire.depth_mode) == ("objects", 3, "tree")
    # From a window, the root visual is depth 1: the agent counts levels below it.
    assert translate(locator, (), None, root_level=True).depth == 2
    assert translate(replace(locator, depth=1), (), None, root_level=True).depth == 0
    assert translate(replace(locator, depth=None), (), None, root_level=True).depth == 256
    default = translate(replace(locator, tree=None), (), None, root_level=True)
    assert (default.tree, default.depth, default.depth_mode) == ("combined", 3, "peers")


class Client:
    def __init__(self, matches: tuple[ObjectRef, ...] = ()) -> None:
        self.session = SimpleNamespace(features=["query", "geometry", "exactUiaMapping"])
        self.matches = matches
        self.complete = True
        self.locators: list[Any] = []

    def query_find_all(self, locator: Any, *, timeout_ms: int, deadline: float) -> Any:
        self.locators.append(locator)
        return SimpleNamespace(matches=self.matches, complete=self.complete)

    def release(self, ids: Any, *, deadline: float) -> None:
        pass


def test_a_window_root_can_match_in_the_object_tree_only():
    root_ref, child_ref = ref("root", "MainWindow"), ref("child")
    client = Client((root_ref, child_ref))
    root = WpfElement(client, root_ref, 1)  # type: ignore[arg-type]
    objects = Locator(name="x", tree="objects", depth=2)
    found = wpf_resolve.query(root, objects, root_level=True)
    assert [element.ref for element in found] == [root_ref, child_ref]
    assert client.locators[-1].depth == 1
    # From an element, the root is the search root and never a match.
    found = wpf_resolve.query(root, objects)
    assert [element.ref for element in found] == [child_ref]
    assert client.locators[-1].depth == 2
    # The default trees never include the root, whatever the caller says.
    default = wpf_resolve.query(root, Locator(name="x", depth=2), root_level=True)
    assert [element.ref for element in default] == [child_ref]
    assert client.locators[-1].tree == "combined"


# -- application level: window nodes -------------------------------------------------------------


@pytest.fixture
def app_walk(monkeypatch):
    """Two WPF windows; records the searches the walk makes below the root visuals."""
    main_ref, dialog_ref = ref("main", "MainWindow"), ref("dialog", "Dialog")
    client = Client()
    roots = {1: WpfElement(client, main_ref, 1), 2: WpfElement(client, dialog_ref, 1)}  # type: ignore[arg-type]
    windows = [
        SimpleNamespace(framework_id="WPF", key=1),
        SimpleNamespace(framework_id="WPF", key=2),
    ]
    app = SimpleNamespace(top_level_windows=lambda: windows)
    searched: list[tuple[int, Locator]] = []
    root_checks: list[list[str]] = []
    descendants = {1: [ref("main-child")], 2: []}

    monkeypatch.setattr(
        resolver.runtime, "get_config", lambda: SimpleNamespace(backend="auto", timeout=5)
    )
    monkeypatch.setattr(resolver, "route", lambda window: roots[window.key])
    monkeypatch.setattr(resolver, "identity_value", lambda root, name: "x")

    def matches_root(root: WpfElement, conditions: list[ManagedCondition]) -> bool:
        root_checks.append([condition.key for condition in conditions])
        return True

    def wpf_query(root: WpfElement, locator: Locator, **kwargs: Any) -> list[WpfElement]:
        key = 1 if root.ref == main_ref else 2
        searched.append((key, locator))
        return [WpfElement(client, item, 1) for item in descendants[key]]  # type: ignore[arg-type]

    monkeypatch.setattr(resolver, "matches_root", matches_root)
    monkeypatch.setattr(resolver, "wpf_query", wpf_query)
    return SimpleNamespace(
        app=app, scope=resolver.Scope(app), searched=searched, checks=root_checks, roots=roots
    )  # type: ignore[arg-type]


def walk(setup: Any, locator: Locator) -> list[Any]:
    return [
        element.ref.object_id
        for element in resolver._walk(  # pyright: ignore[reportPrivateUsage]
            setup.scope, replace(locator, app_scope=True), True
        )
    ]


def test_depth_from_an_application_counts_window_nodes_then_root_visuals(app_walk):
    label = Locator(
        where=(("type:Name", re.compile("^HwndSource: ")),), tree="objects", app_scope=True
    )
    # Depth 1: the window nodes only (a node is labelled with its root visual's type).
    assert walk(app_walk, replace(label, depth=1)) == ["main", "dialog"]
    assert app_walk.searched == []
    # The root visuals are the second level and carry their own, unprefixed type names.
    plain = Locator(automation_id="x", tree="objects", depth=1)
    assert walk(app_walk, plain) == ["main", "dialog"]
    assert app_walk.searched == []
    # Depth 2 adds the root visuals; depth 3 their object-tree children.
    assert walk(app_walk, replace(plain, depth=2)) == ["main", "dialog"]
    assert app_walk.searched == []
    assert walk(app_walk, replace(plain, depth=3)) == ["main", "main-child", "dialog"]
    assert [(key, link.depth) for key, link in app_walk.searched] == [(1, 1), (2, 1)]
    app_walk.searched.clear()
    assert walk(app_walk, replace(plain, depth=None)) == ["main", "main-child", "dialog"]
    assert [link.depth for _, link in app_walk.searched] == [None, None]


def test_window_node_matches_label_text_and_ordinal(app_walk):
    nodes = lambda **where: Locator(  # noqa: E731
        where=tuple(where.items()) if where else (), tree="objects", depth=1
    )
    # The label is "HwndSource: <root visual type>"; the root visual's own name does not match it.
    assert walk(app_walk, nodes(**{"type:Name": "HwndSource: Dialog"})) == ["dialog"]
    assert walk(app_walk, nodes(**{"type:Name": "Dialog"})) == []
    # The text is the window title, which the agent reads from the root visual.
    assert walk(app_walk, nodes(**{"wpf:Text": "Main title"})) == ["main", "dialog"]
    assert app_walk.checks[-1] == ["wpf:Text"]
    # The ordinal is the node's place among the application's windows.
    assert walk(app_walk, nodes(**{"wpf:Ordinal": 2})) == ["dialog"]
    # Any other managed key is a member of an element, which a window node is not.
    assert walk(app_walk, nodes(**{"clr:Title": "x"})) == []
    # The root visual (depth 2) is matched with the full predicate set.
    deep = Locator(where=(("clr:Title", "x"),), tree="objects", depth=2)
    assert walk(app_walk, deep) == ["main", "dialog"]
    assert app_walk.checks[-1] == ["clr:Title"]


def test_index_and_duplicates_follow_the_object_tree_order(app_walk):
    both = Locator(automation_id="x", tree="objects", depth=3, app_scope=True)
    # A window node and its root visual are one element: it is counted once, in pre-order.
    for index, expected in enumerate(("main", "main-child", "dialog")):
        result = resolver._walk(  # pyright: ignore[reportPrivateUsage]
            app_walk.scope, replace(both, index=index), False
        )
        assert result[0].ref.object_id == expected


# -- the migration finders -----------------------------------------------------------------------


def test_first_match_sets_the_index_in_both_forms():
    from wintestkit.finders import _explicit_ordinal, _first  # pyright: ignore[reportPrivateUsage]

    text = to_locator("WPFControlText", "OK")
    first = _first(text)
    assert first.index == 0 and first.uia_form is not None and first.uia_form.index == 0
    assert not _explicit_ordinal(text)
    ordinal = to_locator("WPFControlOrdinalNo", 2)
    assert _explicit_ordinal(ordinal)
    chosen = _first(ordinal)
    # The ordinal is a predicate on WPF windows; the UIA form keeps its own index.
    assert chosen.index == 0 and chosen.uia_form is not None and chosen.uia_form.index == 1


def test_find_child_on_a_uia_window_uses_the_uia_form(monkeypatch):
    from fakes import FakeElement

    from wintestkit import runtime
    from wintestkit.app import App
    from wintestkit.engine import query
    from wintestkit.errors import AmbiguousMatchWarning

    monkeypatch.setenv("WTK_BACKEND", "uia")
    runtime.reset()
    monkeypatch.setattr(query, "make_condition", lambda **props: props)
    ok = FakeElement("Button", "OK")
    other = FakeElement("Button", "OK")
    window = FakeElement("Window", "Demo", children=[ok, other])
    app = object.__new__(App)
    monkeypatch.setattr(app, "top_level_windows", lambda: [window])
    with pytest.warns(AmbiguousMatchWarning):
        assert find_child(app, "WPFControlText", "OK", 2).resolve_once() is ok
    # A UIA ordinal is the zero-based index into all results, as before.
    ordinal = find_child(app, ["WPFControlText", "WPFControlOrdinalNo"], ["OK", 2], 2)
    assert ordinal.resolve_once() is other
    runtime.reset()


def test_object_tree_without_a_wpf_window_is_an_error(monkeypatch):
    from fakes import FakeApp, FakeElement

    from wintestkit import runtime
    from wintestkit.engine import query

    monkeypatch.setenv("WTK_BACKEND", "uia")
    runtime.reset()
    monkeypatch.setattr(query, "make_condition", lambda **props: props)
    app = FakeApp([FakeElement("Window", "Demo", children=[FakeElement("Button", "OK")])])

    class Demo(Page):
        button = Element(name="OK", tree="objects")

    with pytest.raises(InvalidLocatorError, match="needs a WPF window"):
        Demo(app).button.resolve_once()
    runtime.reset()


def test_with_index_chooses_the_match_in_both_forms():
    locator = to_locator(["WPFControlText", "WPFControlOrdinalNo"], ["OK", 2])
    chosen = locator.with_index(3)
    assert chosen.index == 3
    assert chosen.uia_form is not None and chosen.uia_form.index == 3
    assert dict(chosen.where)["wpf:Ordinal"] == 2
