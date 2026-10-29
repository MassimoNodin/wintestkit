"""S8 locator semantics with an in-memory UIA tree and typed managed responses."""

import re
import time
from dataclasses import replace

import pytest
from fakes import FakeApp, FakeElement

from wintestkit import runtime
from wintestkit.config import load_config
from wintestkit.engine import query, waits
from wintestkit.engine.locator import Locator, WindowLocator
from wintestkit.engine.managed import ManagedCondition, matches_value, query_budget
from wintestkit.engine.properties import resolve_where
from wintestkit.engine.resolve import Scope, resolve, resolve_all, resolve_window
from wintestkit.errors import (
    AmbiguousElementError,
    ConfigError,
    InspectorLimitError,
    InspectorMappingError,
    InspectorReadError,
    InspectorUnavailableError,
    InvalidLocatorError,
)
from wintestkit.inspector.models import CandidateResult, Mapping, PathValue, ProcessIdentity, Value
from wintestkit.inspector.paths import parse_managed_key


def scalar(kind="string", value="match", **kwargs):
    return Value("ok", kind, "", "", scalar=value, **kwargs)


def unavailable(status):
    return Value(status, "unavailable", "", "")


def condition(expected):
    return ManagedCondition("clr:Value", parse_managed_key("clr:Value"), expected)


@pytest.fixture(autouse=True)
def setup(monkeypatch, tmp_path):
    runtime.reset()
    runtime.set_config(load_config(tmp_path))
    monkeypatch.setattr(query, "make_condition", lambda **props: props)
    yield
    runtime.reset()


class Reader:
    def __init__(self, monkeypatch, nodes):
        self.nodes = nodes
        self.calls = []
        self.attaches = []
        self.values = {}
        self.statuses = {}
        self.mutate = lambda results: results
        self.after_read = lambda: None
        monkeypatch.setattr(runtime, "managed_client_for", self.client)
        from wintestkit.uia import element

        monkeypatch.setattr(
            element, "from_handle", lambda hwnd: next(n for n in nodes if n.native_window_handle == hwnd)
        )

    def client(self, pid, *, deadline, target_hwnd):
        self.attaches.append((pid, deadline, target_hwnd))
        return self

    def read_batch(self, candidates, paths, *, deadline):
        self.calls.append((candidates, paths, deadline))
        results = []
        for rid, _ in candidates:
            status = self.statuses.get(rid, "exact")
            values = tuple(
                PathValue(path.segments, self.values.get((rid, path.canonical), scalar()))
                for path in paths
            ) if status == "exact" else ()
            results.append(CandidateResult(
                rid, Mapping(status, ProcessIdentity(1, "2026-01-01T00:00:00Z"), rid), values
            ))
        self.after_read()
        return self.mutate(results)


def tree(monkeypatch, count):
    nodes = [FakeElement("Button", name="same") for _ in range(count)]
    root = FakeElement("Window", children=nodes)
    return root, nodes, Reader(monkeypatch, [root, *nodes])


def rid(node):
    return tuple(int(part) for part in node.runtime_id.split("."))


@pytest.mark.parametrize(("value", "expected", "matches"), [
    (scalar("boolean", True), True, True),
    (scalar("boolean", True), 1, False),
    (scalar("integer", 1), True, False),
    (scalar("integer", "9007199254740993"), 9007199254740993, True),
    (scalar("integer", 1), "1", False),
    (scalar("string", "1"), 1, False),
    (scalar("number", "1.5"), 1.5, True),
    (scalar("number", "0.1"), 0.1, False),
    (scalar("number", "2.0"), 2, True),
    (scalar("number", 2.5), 2.5, True),
    (scalar("string", "prefix-MATCH"), re.compile("match$", re.I), True),
    (scalar("integer", 1), re.compile("1"), False),
    (scalar("enum", "Active", numeric_value="2"), "Active", True),
    (scalar("enum", "Active", numeric_value="2"), 2, True),
    (scalar("enum", "Active", numeric_value="2"), 2.0, False),
    (scalar("enum", "Active", numeric_value="2"), True, False),
    (scalar("enum", "Active", numeric_value="2"), re.compile("ctiv"), True),
    (scalar("null", None), "", False),
    (unavailable("nullIntermediate"), "", False),
])
def test_type_aware_scalars(value, expected, matches):
    assert matches_value(condition(expected), value) is matches


@pytest.mark.parametrize("value", [
    unavailable(status) for status in (
        "redacted", "truncated", "exception", "timeout", "notReadable", "unsupported", "cycle"
    )
] + [Value("ok", kind, "", "") for kind in ("object", "array", "type")])
def test_unusable_values_are_explicit_errors(value):
    with pytest.raises(InspectorReadError):
        matches_value(condition("match"), value)


def test_uia_only_and_empty_results_never_use_inspector(monkeypatch):
    root, nodes, reader = tree(monkeypatch, 3)
    assert query.query_all(root, Locator(name="same")) == nodes
    assert query.query_all(root, Locator(name="absent", where=(("clr:Value", "match"),))) == []
    assert not reader.calls and not reader.attaches


def test_native_narrowing_regex_depth_and_distinct_paths(monkeypatch):
    root, nodes, reader = tree(monkeypatch, 4)
    nodes[0].properties["HelpText"] = "chosen"
    nodes[1].properties["HelpText"] = "chosen"
    nodes[1].name = "different"
    native = []
    monkeypatch.setattr(query, "make_condition", lambda **props: native.append(props) or props)
    locator = Locator(name=re.compile("^same$"), depth=1, where=(
        ("HelpText", "chosen"), ("clr:DataContext.Customer.Name", "match"),
        ("field:Public.Nested", re.compile("atch")),
        ("dp:Asm|Demo.Owner::Property/Name", "match"), ("type:FullName", "match"),
    ))
    assert query.query_all(root, locator) == [nodes[0]]
    assert native == [{"help_text": "chosen"}]
    assert len(reader.calls) == 1
    assert len(reader.calls[0][0]) == 1 and len(reader.calls[0][1]) == 4


@pytest.mark.parametrize("count", [32, 33, 1000])
def test_batches_preserve_order_and_never_truncate(monkeypatch, count):
    root, nodes, reader = tree(monkeypatch, count)
    assert query.query_all(root, Locator(where=(("clr:Value", "match"),))) == nodes
    assert [len(c[0]) for c in reader.calls] == [32] * (count // 32) + ([count % 32] if count % 32 else [])
    assert len(reader.attaches) == 1


def test_candidate_cap_precedes_attachment(monkeypatch):
    root, _, reader = tree(monkeypatch, 1001)
    with pytest.raises(InspectorLimitError, match=r"1001.*tighter UIA scope"):
        query.query_all(root, Locator(where=(("clr:Value", "match"),)))
    assert not reader.attaches and not reader.calls


def test_path_batches_and_index_apply_after_complete_filter(monkeypatch):
    root, nodes, reader = tree(monkeypatch, 35)
    where = tuple((f"clr:Property{i}", "match") for i in range(33))
    reader.values[rid(nodes[0]), "clr:Property0"] = scalar(value="different")
    locator = Locator(where=where, index=32)
    assert resolve(Scope(FakeApp([root])), locator) is nodes[33]
    assert [(len(c[0]), len(c[1])) for c in reader.calls] == [(32, 32), (32, 1), (3, 32), (3, 1)]


def test_ambiguity_and_late_failure_cannot_be_hidden_by_index(monkeypatch):
    root, nodes, reader = tree(monkeypatch, 33)
    locator = Locator(where=(("clr:Value", "match"),))
    with pytest.raises(AmbiguousElementError):
        resolve(Scope(FakeApp([root])), locator)
    reader.values[rid(nodes[-1]), "clr:Value"] = unavailable("redacted")
    with pytest.raises(InspectorReadError, match="redacted"):
        resolve(Scope(FakeApp([root])), replace(locator, index=0))


def test_mismatch_does_not_hide_other_path_failure(monkeypatch):
    root, nodes, reader = tree(monkeypatch, 1)
    reader.values[rid(nodes[0]), "clr:A"] = scalar(value="different")
    reader.values[rid(nodes[0]), "clr:B"] = unavailable("redacted")
    with pytest.raises(InspectorReadError, match="redacted"):
        query.query_all(root, Locator(where=(("clr:A", "match"), ("clr:B", "match"))))


@pytest.mark.parametrize("status", ["ambiguous", "unsupportedPeer", "notFound"])
def test_mapping_failures_are_errors(monkeypatch, status):
    root, nodes, reader = tree(monkeypatch, 1)
    reader.statuses[rid(nodes[0])] = status
    with pytest.raises(InspectorMappingError, match=status):
        query.query_all(root, Locator(where=(("clr:Value", "match"),)))


@pytest.mark.parametrize("stale_mapping", [True, False])
def test_stale_candidate_is_skipped_and_next_query_reads_fresh(monkeypatch, stale_mapping):
    root, nodes, reader = tree(monkeypatch, 2)
    if stale_mapping:
        reader.statuses[rid(nodes[0])] = "stale"
    else:
        reader.values[rid(nodes[0]), "clr:Value"] = unavailable("stale")
    locator = Locator(where=(("clr:Value", "match"),))
    assert query.query_all(root, locator) == [nodes[1]]
    reader.values.clear()
    reader.statuses.clear()
    assert query.query_all(root, locator) == nodes
    assert len(reader.calls) == 2


@pytest.mark.parametrize("mutation", [
    lambda rows: [],
    lambda rows: [replace(rows[0], runtime_id=(99,))],
    lambda rows: [replace(rows[0], values=())],
    lambda rows: [replace(rows[0], values=(*rows[0].values, *rows[0].values))],
])
def test_partial_or_mismatched_results_are_errors(monkeypatch, mutation):
    root, _, reader = tree(monkeypatch, 1)
    reader.mutate = mutation
    with pytest.raises(InspectorReadError):
        query.query_all(root, Locator(where=(("clr:Value", "match"),)))


def test_window_and_within_managed_filters(monkeypatch):
    button = FakeElement("Button")
    group = FakeElement("Group", children=[button])
    window = FakeElement("Window", children=[group])
    reader = Reader(monkeypatch, [window, group, button])
    app = FakeApp([window])
    wl = WindowLocator(where=(("type:FullName", "match"),))
    assert resolve_window(app, wl) is window
    locator = Locator(
        control_type="Button", where=(("clr:Value", "match"),),
        within=Locator(control_type="Group", where=(("clr:Value", "match"),)), window=wl,
    )
    assert resolve(Scope(app), locator) is button
    assert resolve_all(Scope(app), locator) == [button]
    assert len({c[2] for c in reader.calls[1:4]}) == 1


def test_mixed_process_order_and_runtime_ids(monkeypatch):
    root, nodes, reader = tree(monkeypatch, 4)
    for index, node in enumerate(nodes):
        node.process_id = index % 2 + 1
    nodes[1].runtime_id = nodes[0].runtime_id
    assert query.query_all(root, Locator(where=(("clr:Value", "match"),))) == nodes
    assert [a[0] for a in reader.attaches] == [1, 2]


def test_observed_cost_rejects_unaffordable_scan(monkeypatch):
    root, _, reader = tree(monkeypatch, 100)
    clock = [0.0]
    monkeypatch.setattr(query.time, "monotonic", lambda: clock[0])
    reader.after_read = lambda: clock.__setitem__(0, clock[0] + 0.4)
    with pytest.raises(InspectorLimitError, match=r"100.*tighter UIA scope"):
        query.query_all(root, Locator(where=(("clr:Value", "match"),)), deadline=1.0)
    assert len(reader.calls) == 1


def test_attach_and_uia_search_consume_original_poll_deadline(monkeypatch):
    root, _, reader = tree(monkeypatch, 1)
    clock = [0.0]
    monkeypatch.setattr(query.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(waits, "_clock", lambda: clock[0])
    monkeypatch.setattr(waits, "_sleep", lambda duration: clock.__setitem__(0, clock[0] + duration))
    original = reader.client

    def attach(pid, **kwargs):
        clock[0] += 0.8
        return original(pid, **kwargs)

    monkeypatch.setattr(runtime, "managed_client_for", attach)
    reader.values[rid(reader.nodes[1]), "clr:Value"] = scalar(value="different")
    locator = Locator(where=(("clr:Value", "match"),))
    with pytest.raises(InspectorLimitError):
        waits.wait_until(lambda: query.query_all(root, locator) or None, 1.0, description="managed")
    assert all(a[1] == 1.0 for a in reader.attaches)
    assert all(c[2] == 1.0 for c in reader.calls)
    assert len(reader.calls) == 1


def test_expired_deadline_never_attaches(monkeypatch):
    root, _, reader = tree(monkeypatch, 1)
    with query_budget(time.monotonic() - 1), pytest.raises(InspectorLimitError):
        query.query_all(root, Locator(where=(("clr:Value", "match"),)))
    assert not reader.attaches


def test_managed_aliases_are_explicit_and_uia_aliases_unchanged(tmp_path):
    cfg = load_config(tmp_path, {"property_aliases": {
        "ClrFullClassName": "type:FullName", "Hint": "HelpText"
    }})
    with runtime.config_scope(cfg):
        managed, uia = resolve_where((("ClrFullClassName", "Demo.Control"), ("Hint", "help")), "owner")
        assert isinstance(managed, ManagedCondition)
        assert managed.key == "type:FullName" and managed.alias == "ClrFullClassName"
        assert uia.spec.uia_name == "HelpText"
        with pytest.raises(InvalidLocatorError, match="twice"):
            resolve_where((("ClrFullClassName", "A"), ("type:FullName", "A")), "owner")
    with pytest.raises(ConfigError):
        load_config(tmp_path, {"property_aliases": {"A": "B", "B": "type:FullName"}})


def test_disabled_managed_alias_fails_without_probing(monkeypatch, tmp_path):
    root = FakeElement("Window", children=[FakeElement("Button")])
    cfg = load_config(tmp_path, {"property_aliases": {"ClrFullClassName": "type:FullName"}})
    from wintestkit.inspector import probe

    monkeypatch.setattr(probe, "current_identity", lambda pid: pytest.fail("disabled probe"))
    with runtime.config_scope(cfg), pytest.raises(InspectorUnavailableError, match=r"inspector\.enabled"):
        query.query_all(root, Locator(where=(("ClrFullClassName", "Demo.Control"),)))


@pytest.mark.parametrize("key", [
    "clr:", "clr:A..B", r"clr:A\q", "clr:A[0]", "clr:A()", "field:*", "field:0",
    "dp:Asm|Owner::P/", "dp:Asm|Owner::P/Q//R", "type:Missing",
])
def test_invalid_paths_fail_at_declaration(key):
    with pytest.raises(InvalidLocatorError):
        Locator(where=((key, "value"),))


@pytest.mark.parametrize("value", [None, [], {}, object()])
def test_object_and_null_literals_are_rejected(value):
    with pytest.raises(InvalidLocatorError):
        Locator(where=(("clr:Value", value),))


def test_locator_serialization_preserves_namespaces_and_escapes():
    locator = Locator(where=(
        (r"clr:DataContext.A\.B", re.compile("value$", re.I)),
        (r"dp:Asm|Demo.Owner::P/A\/B", 42), ("field:Value", True),
    ), window=WindowLocator(where=(("type:FullName", "Demo.Window"),)))
    assert Locator.from_dict(locator.to_dict()) == locator
    assert Locator.from_dict(locator.to_dict()).to_dict() == locator.to_dict()
