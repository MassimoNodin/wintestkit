import gc
from types import SimpleNamespace

import pytest

from wintestkit.backends import WpfElement, uia_of
from wintestkit.engine import actions
from wintestkit.errors import InspectorError, NoUiaPeerError
from wintestkit.inspector.models import ObjectRef, TypeInfo
from wintestkit.inspector.models import Rect as AgentRect
from wintestkit.uia.element import Rect, UIAElement


def test_peerless_password_detection_is_conservative(monkeypatch):
    def missing_peer(element):
        raise NoUiaPeerError("no peer")

    monkeypatch.setattr(actions, "uia_of", missing_peer)
    assert actions.is_password(object())


class Client:
    def __init__(self):
        self.reads = 0
        self.states = 0
        self.released = []
        self.values = ["id", "name", "ButtonClass", "Button"]
        self.state = SimpleNamespace(
            window_handle=123,
            uia_runtime_id=(1, 2),
            bounds=AgentRect(1.2, 2.7, 10.4, 4.4),
            visible_bounds=AgentRect(1.2, 2.7, 10.4, 4.4),
            enabled=True,
            visible=True,
            clipped=True,
            offscreen=False,
            focused=True,
        )
        self.error = None

    def read(self, object_id, generation, paths, *, deadline):
        self.reads += 1
        assert [path[0].name for path in paths] == [
            "automation_id",
            "name",
            "class_name",
            "control_type",
        ]
        return tuple(
            SimpleNamespace(
                value=SimpleNamespace(
                    status="ok" if value is not None else "unavailable", scalar=value
                )
            )
            for value in self.values
        ), "read"

    def state_get(self, ref, *, timeout_ms, deadline):
        self.states += 1
        if self.error:
            raise self.error
        return self.state

    def release(self, ids, *, deadline):
        self.released.extend(ids)


@pytest.fixture
def setup():
    client = Client()
    ref = ObjectRef("session", "object", 1, TypeInfo("T", "T", "A", "T, A", ()), "dispatcher")
    return client, WpfElement(client, ref, 42)


def test_identity_cache_refresh_and_state(setup):
    client, element = setup
    assert (element.automation_id, element.name, element.class_name, element.control_type) == (
        "id",
        "name",
        "ButtonClass",
        "Button",
    )
    assert client.reads == 1
    assert element.control_type_id and element.framework_id == "WPF" and element.process_id == 42
    assert element.rect == Rect(1, 3, 11, 4)
    assert element.is_enabled and not element.is_offscreen and element.has_keyboard_focus
    assert client.states == 1
    client.values = [None] * 4
    live = element.as_live()
    assert (live.name, live.control_type, live.control_type_id) == ("", "", 0)
    assert client.reads == 2
    assert live.runtime_id == "1.2" and client.states == 2
    client.state.uia_runtime_id = None
    assert live.as_live().runtime_id == "wpf:session:object:1"


def test_liveness_and_identity(setup):
    client, element = setup
    assert element.same_as(element.as_live())
    peer = UIAElement(SimpleNamespace(GetRuntimeId=lambda: [1, 2]))
    assert element.same_as(peer)
    client.error = InspectorError("stale", code="objectStale")
    assert not element.is_alive()
    client.error = InspectorError("bad", code="internalError")
    with pytest.raises(InspectorError):
        element.is_alive()


def test_mapping_and_delegation(setup, monkeypatch):
    client, element = setup
    peer = UIAElement(SimpleNamespace(GetRuntimeId=lambda: [1, 2]))
    monkeypatch.setattr(
        "wintestkit.backends.element.map_runtime_ids", lambda groups: {(123, (1, 2)): peer}
    )
    monkeypatch.setattr("wintestkit.uia.element.from_handle", lambda hwnd: peer)
    assert element.native_window_handle == 123
    assert element.as_uia() is peer and uia_of(element) is peer and uia_of(peer) is peer
    monkeypatch.setattr(
        "wintestkit.uia.com.get_uia",
        lambda: SimpleNamespace(CompareElements=lambda first, second: first is second),
    )
    assert peer.same_as(element)
    monkeypatch.setattr(
        "wintestkit.uia.element.from_handle",
        lambda hwnd: UIAElement(SimpleNamespace(GetRuntimeId=lambda: [9])),
    )
    assert element.native_window_handle == 0
    monkeypatch.setattr(UIAElement, "parent", lambda self: peer)
    monkeypatch.setattr(UIAElement, "children", lambda self: [peer])
    monkeypatch.setattr(UIAElement, "get_property", lambda self, name: name)
    monkeypatch.setattr(UIAElement, "supported_patterns", lambda self: ["Invoke"])
    monkeypatch.setattr(client, "parent", lambda *args, **kwargs: None, raising=False)
    assert element.parent() is None and element.children() == [peer]
    assert element.get_property("Name") == "Name"
    assert element.info(with_patterns=True).patterns == ("Invoke",)
    client.state.uia_runtime_id = None
    with pytest.raises(NoUiaPeerError, match="this operation needs one"):
        element.as_live().as_uia()


def test_shared_lease_releases_once():
    client = Client()
    ref = ObjectRef("session", "object", 1, TypeInfo("T", "T", "A", "T, A", ()), "dispatcher")
    element = WpfElement(client, ref, 42)
    other = element.as_live()
    del element
    gc.collect()
    assert client.released == []
    del other
    gc.collect()
    assert client.released == ["object"]


def test_password_reads_are_redacted_on_both_backends(setup, monkeypatch):
    from wintestkit.errors import ActionError

    _, managed = setup
    uia = UIAElement(SimpleNamespace())
    monkeypatch.setattr(actions, "is_password", lambda element: True)
    monkeypatch.setattr(actions, "_wpf_patterns", lambda element: {"Text", "Value"})
    monkeypatch.setattr(actions.patterns, "has_pattern", lambda element, name: True)
    monkeypatch.setattr(UIAElement, "name", property(lambda self: ""))
    monkeypatch.setattr(WpfElement, "name", property(lambda self: ""))
    for element in (uia, managed):
        assert actions.get_text(element) == ""
        with pytest.raises(ActionError, match="Cannot read a password value"):
            actions.get_value(element)


def test_peerless_window_helpers_use_agent_handle(setup, monkeypatch):
    from wintestkit.uia import win32

    client, element = setup
    client.state.uia_runtime_id = None
    monkeypatch.setattr(win32, "root_window", lambda hwnd: hwnd + 1)
    monkeypatch.setattr(win32, "bring_to_foreground", lambda hwnd: hwnd == 124)
    monkeypatch.setattr(win32, "raise_window", lambda hwnd: hwnd == 124)
    monkeypatch.setattr(win32, "IsIconic", lambda hwnd: hwnd == 124)
    assert actions.bring_to_front(element)
    assert actions.raise_without_activating(element)
    assert actions.window_is_minimized(element)


def test_peerless_ancestor_outline_uses_managed_parent(setup, monkeypatch):
    from wintestkit.engine.highlight import outline

    client, element = setup
    client.state.uia_runtime_id = None
    client.state.bounds = None
    client.state.visible_bounds = None
    parent_ref = ObjectRef("session", "parent", 1, element.ref.type, "dispatcher")
    parent_state = SimpleNamespace(**vars(client.state))
    parent_state.bounds = AgentRect(5, 6, 20, 30)
    parent_state.visible_bounds = parent_state.bounds
    monkeypatch.setattr(
        client,
        "state_get",
        lambda ref, **kwargs: client.state if ref == element.ref else parent_state,
    )
    monkeypatch.setattr(client, "parent", lambda *args, **kwargs: parent_ref, raising=False)
    rect, ancestor = outline(element)
    assert rect == Rect(5, 6, 20, 30)
    assert isinstance(ancestor, WpfElement) and ancestor.ref == parent_ref


def test_outline_uses_visible_bounds_and_skips_scrolled_out_node(setup, monkeypatch):
    from wintestkit.engine.highlight import outline

    client, element = setup
    client.state.uia_runtime_id = None
    client.state.visible_bounds = AgentRect(3, 4, 5, 6)
    assert outline(element) == (Rect(3, 4, 5, 6), None)
    client.state.visible_bounds = None
    parent_ref = ObjectRef("session", "parent", 1, element.ref.type, "dispatcher")
    parent_state = SimpleNamespace(**vars(client.state))
    parent_state.visible_bounds = AgentRect(10, 20, 30, 40)
    monkeypatch.setattr(client, "parent", lambda *args, **kwargs: parent_ref, raising=False)
    monkeypatch.setattr(client, "state_get", lambda ref, **kwargs: parent_state)
    rect, ancestor = outline(element)
    assert rect == Rect(10, 20, 30, 40)
    assert isinstance(ancestor, WpfElement) and ancestor.ref == parent_ref


def test_peerless_bound_highlight_uses_agent(setup, monkeypatch):
    from wintestkit.engine import overlay
    from wintestkit.model import _BoundBase

    client, element = setup
    client.state.uia_runtime_id = None
    monkeypatch.setattr(WpfElement, "as_uia", lambda self: pytest.fail("unexpected UIA call"))
    monkeypatch.setattr(actions, "bring_to_front", lambda target: True)
    flashed = []
    monkeypatch.setattr(overlay, "flash", lambda rect, *args, **kwargs: flashed.append(rect))

    class Bound(_BoundBase):
        def resolve(self, timeout=None):
            return element

        def _description(self):
            return "peerless"

    Bound().highlight()
    assert flashed == [Rect(1, 3, 11, 4)]
