import importlib
import re
from types import SimpleNamespace

import pytest

from wintestkit.backends import WpfElement
from wintestkit.engine import actions, wpf_resolve
from wintestkit.engine.locator import ItemSelector, Locator
from wintestkit.errors import (
    AmbiguousElementError,
    ElementNotFoundError,
    InspectorLimitError,
    InspectorMappingError,
    InspectorUnavailableError,
    NoUiaPeerError,
)
from wintestkit.inspector.models import ObjectRef, TypeInfo


def ref(name):
    return ObjectRef("session", name, 1, TypeInfo("T", "T", "A", "T, A", ()), "dispatcher")


class Client:
    def __init__(self):
        self.session = SimpleNamespace(features=["query", "geometry", "exactUiaMapping"])
        self.mapping = SimpleNamespace(status="exact", object_ref=ref("root"))
        self.matches = (ref("child"),)
        self.complete = True
        self.locators = []

    def resolve(self, rid, hwnd, *, deadline):
        return self.mapping

    def query_find_all(self, locator, *, timeout_ms, deadline):
        self.locators.append(locator)
        return SimpleNamespace(matches=self.matches, complete=self.complete)

    def query_find(self, locator, *, timeout_ms, deadline):
        self.locators.append(locator)
        return SimpleNamespace(match=ref("indexed"))

    def release(self, ids, *, deadline):
        pass

    def read(self, object_id, generation, paths, *, deadline):
        values = ["id", "name", "class", "Button"]
        return tuple(
            SimpleNamespace(value=SimpleNamespace(status="ok", scalar=value)) for value in values
        ), "read"

    def state_get(self, obj, *, timeout_ms, deadline):
        return SimpleNamespace(
            window_handle=0,
            uia_runtime_id=None,
            bounds=None,
            enabled=True,
            offscreen=False,
            focused=False,
        )


@pytest.fixture
def setup(monkeypatch):
    client = Client()
    window = SimpleNamespace(framework_id="WPF", process_id=42)
    config = SimpleNamespace(backend="auto", timeout=10)
    monkeypatch.setattr(wpf_resolve.runtime, "get_config", lambda: config)
    monkeypatch.setattr(wpf_resolve.runtime, "managed_client_for", lambda *a, **kw: client)
    monkeypatch.setattr(wpf_resolve.runtime, "managed_element_identity", lambda window: ((1,), 12))
    monkeypatch.setattr(wpf_resolve, "root_handle", lambda window: 12)
    return config, client, window


def test_routing_and_failures(setup, monkeypatch):
    config, client, window = setup
    config.backend = "uia"
    assert wpf_resolve.route(window) is window
    config.backend = "auto"
    window.framework_id = "Win32"
    assert wpf_resolve.route(window) is window
    window.framework_id = "WPF"
    assert isinstance(wpf_resolve.route(window), WpfElement)
    client.mapping.status = "ambiguous"
    with pytest.raises(InspectorMappingError, match=r"ambiguous.*backend: uia"):
        wpf_resolve.route(window)
    client.mapping.status = "exact"
    client.session.features.remove("query")
    with pytest.raises(InspectorMappingError, match=r"query.*backend: uia"):
        wpf_resolve.route(window)

    def fail(*args, **kwargs):
        raise InspectorUnavailableError("blocked", code="blockedByPolicy")

    monkeypatch.setattr(wpf_resolve.runtime, "managed_client_for", fail)
    with pytest.raises(InspectorUnavailableError, match=r"blockedByPolicy.*backend: uia"):
        wpf_resolve.route(window)


@pytest.mark.parametrize("code", ["notAttached", "blockedByPolicy", "unsupportedTarget"])
def test_attach_failure_reports_cause_and_fix(setup, monkeypatch, code):
    _, _, window = setup

    def fail(*args, **kwargs):
        raise InspectorUnavailableError("cannot attach", code=code)

    monkeypatch.setattr(wpf_resolve.runtime, "managed_client_for", fail)
    with pytest.raises(InspectorUnavailableError) as error:
        wpf_resolve.route(window)
    assert error.value.code == code
    assert "Enable the inspector" in str(error.value)
    assert "attach" in str(error.value)
    assert "backend: uia" in str(error.value)


@pytest.mark.parametrize("feature", ["query", "geometry", "exactUiaMapping"])
def test_missing_required_feature_fails(setup, feature):
    _, client, window = setup
    client.session.features.remove(feature)
    with pytest.raises(InspectorMappingError, match=feature):
        wpf_resolve.route(window)


def test_query_depth_filter_and_limit(setup):
    _, client, window = setup
    root = wpf_resolve.route(window)
    assert isinstance(root, WpfElement)
    result = wpf_resolve.query(root, Locator(automation_id="id", depth=3))
    assert [item.ref.object_id for item in result] == ["child"]
    assert client.locators[-1].depth_mode == "peers"
    assert client.locators[-1].depth == 3
    wpf_resolve.query(root, Locator(name=re.compile("^name")))
    assert client.locators[-1].predicates[0].kind == "regex"
    assert wpf_resolve.query(root, Locator(name=re.compile("(?<=na)me")))
    assert client.locators[-1].predicates == ()
    client.complete = False
    with pytest.raises(InspectorLimitError, match="budget"):
        wpf_resolve.query(root, Locator(automation_id="id"))


def test_action_reports_peerless(setup):
    _, _, window = setup
    root = wpf_resolve.route(window)
    with pytest.raises(NoUiaPeerError):
        actions.click(root)


def test_index_beyond_cap(setup):
    _, client, window = setup
    root = wpf_resolve.route(window)
    client.matches = tuple(ref(str(index)) for index in range(200))
    client.complete = False
    result = wpf_resolve.query(root, Locator(automation_id="id", index=250), use_index=True)
    assert result.indexed and result[0].ref.object_id == "indexed"
    assert client.locators[-1].index == 250
    result = wpf_resolve.query(
        root, Locator(name=re.compile("(?<=na)me"), index=201), use_index=True
    )
    assert result.indexed and client.locators[-1].index == 201


def test_uia_where_filters_and_peerless_do_not_match(setup, monkeypatch):
    _, _, window = setup
    root = wpf_resolve.route(window)
    peer = SimpleNamespace(get_property=lambda key: "helpful")
    monkeypatch.setattr(wpf_resolve, "uia_of", lambda element: peer)
    assert wpf_resolve.query(root, Locator(where=(("HelpText", re.compile("help")),)))
    assert not wpf_resolve.query(root, Locator(where=(("HelpText", "other"),)))

    def no_peer(element):
        raise NoUiaPeerError("no peer")

    monkeypatch.setattr(wpf_resolve, "uia_of", no_peer)
    assert not wpf_resolve.query(root, Locator(where=(("HelpText", "helpful"),)))


def test_within_chain_uses_previous_handle(setup, monkeypatch):
    _, client, window = setup
    resolver = importlib.import_module("wintestkit.engine.resolve")
    root = wpf_resolve.route(window)
    window.info = lambda: SimpleNamespace(short=lambda: "window")
    monkeypatch.setattr(resolver, "resolve_window", lambda *args: window)
    monkeypatch.setattr(resolver, "route", lambda window: root)

    def find(locator, *, timeout_ms, deadline):
        client.locators.append(locator)
        child = "container" if locator.scope.handle == root.ref else "inner"
        return SimpleNamespace(matches=(ref(child),), complete=True)

    monkeypatch.setattr(client, "query_find_all", find)
    scope = resolver.Scope(SimpleNamespace(top_level_windows=lambda: []))
    found = resolver.resolve(scope, Locator(automation_id="inner", within=Locator(name="parent")))
    assert found.ref.object_id == "inner"
    assert client.locators[1].scope.handle.object_id == "container"


def test_ambiguity_and_not_found_use_uia_root(setup, monkeypatch):
    _, client, window = setup
    resolver = importlib.import_module("wintestkit.engine.resolve")
    root = wpf_resolve.route(window)
    window.info = lambda: SimpleNamespace(short=lambda: "window")
    monkeypatch.setattr(resolver, "resolve_window", lambda *args: window)
    monkeypatch.setattr(resolver, "route", lambda window: root)
    scope = resolver.Scope(SimpleNamespace(top_level_windows=lambda: []))
    client.matches = (ref("one"), ref("two"))
    with pytest.raises(AmbiguousElementError, match="add within= or index="):
        resolver.resolve(scope, Locator(automation_id="id"))
    client.matches = ()
    seen = []

    def diagnose(diagnostic_root, link, searched_in, full):
        seen.append(diagnostic_root)
        return resolver.Diagnostic("not_found", "not found", "locator", "window", 0)

    monkeypatch.setattr(resolver, "diagnose_not_found", diagnose)
    with pytest.raises(ElementNotFoundError, match="not found"):
        resolver.resolve(scope, Locator(automation_id="missing"))
    assert seen == [window]


def test_popup_uses_its_own_mapped_root(setup, monkeypatch):
    _, client, window = setup
    resolver = importlib.import_module("wintestkit.engine.resolve")
    root = wpf_resolve.route(window)
    popup_root = WpfElement(client, ref("popup"), 42)
    popup = SimpleNamespace(class_name="Popup", control_type="Menu")
    window.info = lambda: SimpleNamespace(short=lambda: "window")
    monkeypatch.setattr(resolver, "resolve_window", lambda *args: window)
    monkeypatch.setattr(
        resolver, "route", lambda target, **kwargs: root if target is window else popup_root
    )

    def find(locator, *, timeout_ms, deadline):
        client.locators.append(locator)
        matches = (ref("menuitem"),) if locator.scope.handle == popup_root.ref else ()
        return SimpleNamespace(matches=matches, complete=True)

    monkeypatch.setattr(client, "query_find_all", find)
    scope = resolver.Scope(SimpleNamespace(top_level_windows=lambda: [popup]))
    assert resolver.resolve(scope, Locator(name="item")).ref.object_id == "menuitem"
    assert client.locators[-1].scope.handle == popup_root.ref

    def find_many(locator, *, timeout_ms, deadline):
        matches = tuple(ref(str(index)) for index in range(200))
        return SimpleNamespace(
            matches=matches if locator.scope.handle == popup_root.ref else (),
            complete=locator.scope.handle != popup_root.ref,
        )

    monkeypatch.setattr(client, "query_find_all", find_many)
    assert resolver.resolve(scope, Locator(name="item", index=250)).ref.object_id == "indexed"


def test_grid_items_use_uia_peer(setup, monkeypatch):
    _, _, window = setup
    resolver = importlib.import_module("wintestkit.engine.resolve")
    root = wpf_resolve.route(window)
    peer = SimpleNamespace(info=lambda: SimpleNamespace(short=lambda: "grid"))
    cell = SimpleNamespace(as_live=lambda: "live cell")
    monkeypatch.setattr(resolver, "uia_of", lambda element: peer)
    monkeypatch.setattr(resolver.patterns, "grid_size", lambda element: (2, 2))
    monkeypatch.setattr(resolver.patterns, "grid_item", lambda element, row, column: cell)
    link = Locator(automation_id="grid", item=ItemSelector("cell", 1, 1))
    assert resolver._apply_item(root, link, "window", link) == "live cell"


def test_mapping_cache_fast_path_and_live_invalidation(setup, monkeypatch):
    from wintestkit.backends import element as backend
    from wintestkit.uia import element as uia_element

    _, client, window = setup
    root = wpf_resolve.route(window)
    state = SimpleNamespace(
        window_handle=12,
        uia_runtime_id=(1, 2),
        bounds=SimpleNamespace(x=10, y=20, width=20, height=10),
        visible=True,
        clipped=False,
        offscreen=False,
    )
    monkeypatch.setattr(client, "state_get", lambda *a, **kw: state)
    peer = SimpleNamespace(runtime_id="1.2", is_alive=lambda: True, parent=lambda: None)
    child = SimpleNamespace(runtime_id="9", parent=lambda: peer)
    points = []
    monkeypatch.setattr(uia_element, "from_point", lambda x, y: points.append((x, y)) or child)
    monkeypatch.setattr(backend, "map_runtime_ids", lambda groups: pytest.fail("unexpected scan"))
    assert root.as_uia() is peer
    assert root.as_uia() is peer
    assert points == [(20, 25)]
    assert root.as_live().as_uia() is peer
    assert len(points) == 2
    peer.is_alive = lambda: False
    replacement = SimpleNamespace(runtime_id="1.2", is_alive=lambda: True, parent=lambda: None)
    monkeypatch.setattr(uia_element, "from_point", lambda x, y: replacement)
    assert root.as_uia() is replacement
    state.offscreen = True
    monkeypatch.setattr(backend, "map_runtime_ids", lambda groups: {(12, (1, 2)): peer})
    assert root.as_live().as_uia() is peer


def test_local_index_continuation_is_bounded(setup):
    _, client, window = setup
    root = wpf_resolve.route(window)
    client.matches = tuple(ref(str(i)) for i in range(200))
    client.complete = False
    with pytest.raises(InspectorLimitError, match="narrow the locator"):
        wpf_resolve.query(root, Locator(name=re.compile("(?<=na)me"), index=300), use_index=True)
    assert len(client.locators) == 51


def test_popup_index_after_capped_popup_and_out_of_range(setup, monkeypatch):
    from wintestkit.errors import InspectorError

    _, client, window = setup
    resolver = importlib.import_module("wintestkit.engine.resolve")
    root = wpf_resolve.route(window)
    popups = [SimpleNamespace(class_name="Popup", control_type="Menu", number=i) for i in range(2)]
    roots = [WpfElement(client, ref("popup1"), 42), WpfElement(client, ref("popup2"), 42)]
    window.info = lambda: SimpleNamespace(short=lambda: "window")
    monkeypatch.setattr(resolver, "resolve_window", lambda *a: window)
    monkeypatch.setattr(
        resolver,
        "route",
        lambda target, **kw: root if target is window else roots[popups.index(target)],
    )

    def find_all(wire, **kw):
        if wire.scope.handle == root.ref:
            return SimpleNamespace(matches=(), complete=True)
        if wire.scope.handle == roots[0].ref:
            return SimpleNamespace(matches=tuple(ref(str(i)) for i in range(200)), complete=False)
        return SimpleNamespace(matches=(ref("later"),), complete=True)

    def find(wire, **kw):
        if wire.index >= 220:
            raise InspectorError("not found", code="notFound")
        return SimpleNamespace(match=ref(str(wire.index)))

    monkeypatch.setattr(client, "query_find_all", find_all)
    monkeypatch.setattr(client, "query_find", find)
    scope = resolver.Scope(SimpleNamespace(top_level_windows=lambda: popups))
    assert resolver.resolve(scope, Locator(name="item", index=220)).ref.object_id == "later"
    with pytest.raises(ElementNotFoundError, match=r"index=222 is out of range.*221"):
        resolver.resolve(scope, Locator(name="item", index=222))


def test_actions_and_patterns_accept_wpf_element(setup, monkeypatch):
    from wintestkit.uia import patterns

    _, _, window = setup
    root = wpf_resolve.route(window)
    peer = SimpleNamespace(name="text")
    monkeypatch.setattr(root, "as_uia", lambda: peer)
    seen = []
    monkeypatch.setattr(patterns, "has_pattern", lambda el, name: name in ("Invoke", "Value"))
    original_invoke = patterns.invoke
    monkeypatch.setattr(patterns, "invoke", lambda el: seen.append(("click", el)))
    monkeypatch.setattr(patterns, "is_read_only", lambda el: False)
    monkeypatch.setattr(patterns, "set_value", lambda el, value: seen.append((value, el)))
    monkeypatch.setattr(patterns, "get_value", lambda el: "value")
    monkeypatch.setattr(actions, "is_password", lambda el: False)
    assert actions.click(root) == "invoke"
    assert actions.type_text(root, "hello") == "value"
    assert actions.get_text(root) == "value"
    assert seen == [("click", peer), ("hello", peer)]
    called = []
    monkeypatch.setattr(
        patterns,
        "_pattern",
        lambda el, name: called.append(el) or SimpleNamespace(Invoke=lambda: None),
    )
    original_invoke(root)
    assert called == [peer]
