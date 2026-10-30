"""WPF query translation and UIA remapping."""

import re
import time
from types import SimpleNamespace

import pytest
from fakes import FakeElement

from wintestkit import runtime
from wintestkit.config import load_config
from wintestkit.engine import query
from wintestkit.engine.locator import Locator
from wintestkit.engine.properties import resolve_where
from wintestkit.engine.wpf_query import UnsupportedQuery, translate
from wintestkit.errors import InspectorError, InspectorLimitError, InvalidLocatorError
from wintestkit.inspector.models import ObjectRef, QueryFindAllResult, TypeInfo

TYPE = TypeInfo("T", "Demo.T", "Demo", "Demo.T, Demo", ())


def ref(i):
    return ObjectRef("session", str(i), 1, TYPE, "dispatcher")


def wire(locator):
    return translate(locator, resolve_where(locator.where, "test", locator.taken()), ref(0))


def test_translation_all_kinds():
    locator = Locator(
        automation_id="id",
        name=re.compile("a.*", re.I | re.M | re.S),
        class_name="Button",
        control_type="button",
        where=(
            ("clr:Name", "x"),
            ("field:State", True),
            ("dp:Asm|Demo.Owner::Value", 1),
            ("type:FullName", "Demo.T"),
            ("type:Is", "Demo.Base"),
        ),
    )
    result = wire(locator)
    assert result.scope.handle == ref(0) and result.depth == 256 and result.limit == 200
    assert [p.kind for p in result.predicates] == [
        "equals",
        "regex",
        "equals",
        "equals",
        "equals",
        "equals",
        "equals",
        "equals",
        "assignableTo",
    ]
    assert result.predicates[1].flags == ("ignoreCase", "multiline", "singleline")
    assert result.predicates[3].value == "Button"


@pytest.mark.parametrize("pattern", [r"\d", "(?=x)", "a{10001}", "é", "a++"])
def test_regex_rejected(pattern):
    with pytest.raises(UnsupportedQuery):
        wire(Locator(name=re.compile(pattern), where=(("clr:X", 1),)))


@pytest.mark.parametrize("pattern", ["a(?:b|c){1,3}?", "^[a-z]+$"])
def test_regex_accepted(pattern):
    assert (
        wire(Locator(name=re.compile(pattern), where=(("clr:X", 1),))).predicates[0].kind == "regex"
    )


def test_fallbacks_and_type_is_validation():
    for locator in (
        Locator(depth=1, where=(("clr:X", 1),)),
        Locator(where=(("HelpText", "x"), ("clr:X", 1))),
        Locator(name=re.compile("a", re.X), where=(("clr:X", 1),)),
        Locator(where=tuple((f"clr:P{i}", 1) for i in range(33))),
    ):
        with pytest.raises(UnsupportedQuery):
            wire(locator)
    with pytest.raises(InvalidLocatorError):
        Locator(where=(("type:Is", re.compile("X")),))


class Client:
    session = SimpleNamespace(features=("query", "geometry", "exactUiaMapping"))

    def __init__(self, refs, states, complete=True, error=None):
        self.refs, self.states, self.complete, self.error = refs, states, complete, error
        self.released = []

    def resolve(self, rid, hwnd, *, deadline):
        return SimpleNamespace(status="exact", object_ref=ref(0))

    def query_find_all(self, locator, *, timeout_ms, deadline):
        assert locator.limit == 200 and 1 <= timeout_ms <= 2000
        if self.error:
            raise self.error
        return QueryFindAllResult(tuple(self.refs[:200]), self.complete)

    def state_get(self, obj, *, timeout_ms, deadline):
        return self.states[obj.object_id]

    def release(self, ids, *, deadline):
        self.released.extend(ids)


def setup_agent(monkeypatch, tmp_path, count=3):
    runtime.set_config(load_config(tmp_path))
    nodes = [FakeElement("Button") for _ in range(count)]
    root = FakeElement("Window", children=nodes)
    refs = [ref(i + 1) for i in range(count)]
    states = {
        obj.object_id: SimpleNamespace(
            handle=obj, window_handle=1, uia_runtime_id=tuple(map(int, node.runtime_id.split(".")))
        )
        for obj, node in zip(refs, nodes, strict=True)
    }
    client = Client(refs, states)
    monkeypatch.setattr(runtime, "managed_client_for", lambda *a, **kw: client)
    monkeypatch.setattr(runtime, "managed_element_identity", lambda root: ((1, 1), None))
    monkeypatch.setattr(query.com, "create_runtime_ids_condition", lambda ids: {})
    from wintestkit.uia import element

    monkeypatch.setattr(element, "from_handle", lambda hwnd: root)
    return root, nodes, client


def test_agent_order_skip_and_release(monkeypatch, tmp_path):
    root, nodes, client = setup_agent(monkeypatch, tmp_path)
    client.refs.reverse()
    client.states[client.refs[1].object_id].uia_runtime_id = None
    assert query.query_all(root, Locator(where=(("clr:X", 1),))) == [nodes[2], nodes[0]]
    assert set(client.released) == {"0", "1", "2", "3"}


def test_agent_incomplete_and_error_propagation(monkeypatch, tmp_path):
    root, _, client = setup_agent(monkeypatch, tmp_path)
    client.complete = False
    with pytest.raises(InspectorLimitError) as exc:
        query.query_all(root, Locator(where=(("clr:X", 1),)))
    assert exc.value.code == "limitExceeded" and client.released
    client.error = InspectorError("stale", code="objectStale")
    with pytest.raises(InspectorError) as exc:
        query.query_all(root, Locator(where=(("clr:X", 1),)))
    assert exc.value.code == "objectStale"


def test_agent_no_candidate_cap(monkeypatch, tmp_path):
    root, _, client = setup_agent(monkeypatch, tmp_path, 1500)
    client.complete = False
    assert (
        len(query.query_all(root, Locator(where=(("clr:X", 1),)), deadline=time.monotonic() + 10))
        == 200
    )


def test_postfilter_rejects_type_is(monkeypatch, tmp_path):
    runtime.set_config(load_config(tmp_path, overrides={"inspector.query": "postfilter"}))
    with pytest.raises(InvalidLocatorError, match="postfilter"):
        query.query_all(FakeElement("Window"), Locator(where=(("type:Is", "Demo.Base"),)))


def test_query_config_default_override_and_validation(tmp_path):
    from wintestkit.errors import ConfigError

    assert load_config(tmp_path).inspector.query == "agent"
    assert (
        load_config(tmp_path, overrides={"inspector.query": "postfilter"}).inspector.query
        == "postfilter"
    )
    with pytest.raises(ConfigError):
        load_config(tmp_path, overrides={"inspector.query": "invalid"})
