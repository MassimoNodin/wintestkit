"""Live Properties selection: the request sequence the extension host sends for one selected object.

The Properties sidebar attaches the tree, then for each selection resolves the object, binds it for Spy,
pages its members and reads values. The inspector withholds a few things about elements that have no
automation peer of their own (ContentPresenter, Border, Grid, ...), such as binding metadata. That must
never look like a blocked session: every call the sidebar depends on has to keep succeeding.
"""

import base64
import io
import json
import os
import queue
import subprocess
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any, Protocol

import pytest

from wintestkit.config import load_config
from wintestkit.server import Server

pytest_plugins = ("test_wpf_query_gate_real",)
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.name != "nt" or os.environ.get("WTK_INSPECTOR_REAL") != "1",
        reason="requires owned Windows fixture",
    ),
]

CAPABILITY = base64.b64encode(bytes(range(32))).decode("ascii")
PEERLESS = "ContentPresenter"
PEERED = "ScrollViewer"
PASSWORD = "PasswordBox"  # the only protected element


class Rpc(Protocol):
    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]: ...


class InProcess:
    def __init__(self, path: Path, app: Any) -> None:
        self.output = io.BytesIO()
        self.server = Server(self.output, spy_host_capability=CAPABILITY)
        self.call("initialize", {"root": str(path)})
        self.server.cfg = load_config(path, {"inspector.enabled": True})
        self.server.app = app

    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.output.seek(0)
        self.output.truncate()
        self.server.handle({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        return json.loads(self.output.getvalue().splitlines()[-1])


class Stdio:
    """The real `python -m wintestkit serve --stdio`, with the capability in its environment."""

    def __init__(self, path: Path) -> None:
        (path / "pyproject.toml").write_text(
            "[tool.wintestkit.inspector]\nenabled = true\n", encoding="utf-8"
        )
        env = {**os.environ, "WINTESTKIT_SPY_HOST_CAPABILITY": CAPABILITY, "PYTHONUTF8": "1"}
        self.process = subprocess.Popen(
            [sys.executable, "-m", "wintestkit", "serve", "--stdio"],
            cwd=path,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self.lines: queue.Queue[bytes] = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()
        self.sequence = 0
        self.call("initialize", {"root": str(path)})

    def _pump(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self.lines.put(line)

    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        assert self.process.stdin is not None
        self.sequence += 1
        request = {"jsonrpc": "2.0", "id": self.sequence, "method": method, "params": params}
        self.process.stdin.write((json.dumps(request) + "\n").encode())
        self.process.stdin.flush()
        while True:
            message = json.loads(self.lines.get(timeout=60))
            if message.get("id") == self.sequence:
                return message

    def close(self) -> None:
        with suppress(Exception):
            self.call("shutdown", {})
        self.process.kill()
        self.process.wait(timeout=10)


def result(rpc: Rpc, method: str, params: dict[str, Any]) -> Any:
    response = rpc.call(method, params)
    assert "result" in response, (method, response)
    return response["result"]


def pages(rpc: Rpc, method: str, base: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    token = None
    while True:
        page = result(rpc, method, {**base, **({"pageToken": token} if token else {})})
        items += page["items"]
        token = page.get("nextToken")
        if not token:
            return items


def find(rpc: Rpc, window: dict[str, Any], names: set[str]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    pending = [window]
    while pending and not names <= found.keys():
        node = pending.pop(0)
        children = result(rpc, "inspect.children", {"nodeId": node["nodeId"], "tree": "visual"})
        for child in children["nodes"]:
            pending.append(child)
            found.setdefault(child["info"]["className"].rsplit(".", 1)[-1], child)
    assert names <= found.keys(), sorted(found)
    return found


def select_like_the_host(rpc: Rpc, session: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    """The calls ManagedPanel.select makes, in the order it makes them."""
    cleared = result(rpc, "inspect.managed.spySelect", {"hostCapability": CAPABILITY})
    assert cleared == {"canInvoke": False}
    result(rpc, "inspect.properties", {"nodeId": node["nodeId"], "includeAncestors": True})
    facts = result(rpc, "inspect.managed.identify", {"nodeId": node["nodeId"]})
    assert facts["process"] == session["process"]
    mapping = result(
        rpc,
        "inspect.managed.resolve",
        {"sessionId": session["sessionId"], "nodeId": node["nodeId"]},
    )
    assert mapping["status"] == "exact"
    ref = mapping["object"]
    bound = result(
        rpc,
        "inspect.managed.spySelect",
        {"hostCapability": CAPABILITY, "sessionId": session["sessionId"], "nodeId": node["nodeId"]},
    )
    assert bound["canInvoke"] is True
    assert bound["mapping"]["object"] == ref
    return ref


@contextmanager
def attached(rpc: Rpc, pid: int) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    roots = result(rpc, "inspect.roots", {})
    window = next(node for node in roots if node["info"]["processId"] == pid)
    first = result(rpc, "inspect.children", {"nodeId": window["nodeId"], "tree": "visual"})
    assert first.get("attachRequired") is True
    facts = result(rpc, "inspect.managed.identify", {"nodeId": window["nodeId"]})
    session = result(
        rpc,
        "inspect.managed.attach",
        {"process": facts["process"], "hostCapability": CAPABILITY},
    )
    assert session["state"] == "ready"
    yield window, session


def read_value(rpc: Rpc, base: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    response = result(rpc, "inspect.managed.spyRead", {**base, "paths": [[row["pathSegment"]]]})
    return response["values"][0]["value"]


def check_selection(rpc: Rpc, pid: int) -> None:
    with attached(rpc, pid) as (window, session):
        found = find(rpc, window, {PEERLESS, PEERED, PASSWORD})
        for name, protected in ((PEERLESS, False), (PEERED, False), (PASSWORD, True)):
            node = found[name]
            ref = select_like_the_host(rpc, session, node)
            base = {
                "sessionId": session["sessionId"],
                "objectId": ref["objectId"],
                "generation": ref["generation"],
            }
            # The Standard rows: identity and ancestry from the UIA side.
            properties = result(
                rpc, "inspect.properties", {"nodeId": node["nodeId"], "includeAncestors": True}
            )
            assert properties["source"] == "wpf"
            assert properties["properties"]["ClrFullClassName"].endswith(name)
            assert properties["properties"]["Visible"] == "True"
            assert properties["ancestors"], "Parent needs the ancestors"
            # The Properties tab: members, then public getters read one by one after consent.
            members = pages(rpc, "inspect.managed.members", base)
            assert members
            by_name = {item["name"]: item for item in members if item["category"] == "clrProperty"}
            for member in ("ActualWidth", "ActualHeight", "Name", "IsEnabled", "Visibility"):
                value = read_value(rpc, base, by_name[member])
                assert value["status"] == "ok", (name, member, value)
            assert read_value(rpc, base, by_name["ActualWidth"])["scalar"] > 0
            others = [read_value(rpc, base, by_name[m])["status"] for m in ("Margin", "Cursor")]
            # Only a password field is protected; every other element returns its public getters.
            assert others == (["redacted"] * 2 if protected else ["ok"] * 2), (name, others)
            result(rpc, "inspect.managed.spyMethods", base)
            # Binding metadata is withheld for a password field: accessDenied for that one request only.
            keys = [
                item["memberKey"]
                for item in members
                if item["category"] in ("dependencyProperty", "attachedProperty")
            ][:32]
            bindings = rpc.call("inspect.managed.bindings", {**base, "memberKeys": keys})
            if protected:
                assert bindings["error"]["data"]["code"] == "accessDenied"
            else:
                assert "result" in bindings, bindings
            # The session and the bound selection are untouched, so nothing else is blocked.
            keepalive = result(
                rpc, "inspect.managed.keepalive", {"sessionId": session["sessionId"]}
            )
            assert keepalive == {"alive": True}
            assert result(rpc, "inspect.managed.members", base)["items"]
            rebound = result(
                rpc,
                "inspect.managed.spySelect",
                {
                    "hostCapability": CAPABILITY,
                    "sessionId": session["sessionId"],
                    "nodeId": node["nodeId"],
                },
            )
            assert rebound["canInvoke"] is True


def test_selection_sequence_in_process(owned: Any) -> None:
    scope, path = owned
    check_selection(InProcess(path, scope.app), scope.app.main_window().process_id)


def test_selection_sequence_over_stdio(owned: Any) -> None:
    scope, path = owned
    server = Stdio(path)
    try:
        check_selection(server, scope.app.main_window().process_id)
    finally:
        server.close()


def auto_eligible(member: dict[str, Any]) -> bool:
    """The rows ManagedPanel reads without a click: public CLR properties, dependency and attached properties."""
    segment = member.get("pathSegment")
    if not segment or not member["readable"] or member["visibility"] != "public":
        return False
    category = member["category"]
    return (
        (category == "clrProperty" and segment["kind"] == "property")
        or (
            category in ("dependencyProperty", "attachedProperty")
            and segment["kind"] == "dependency"
        )
        or (category == "typeMetadata" and segment["kind"] == "type")
    )


def check_every_row_is_read(rpc: Rpc, pid: int) -> None:
    """Each automatic row ends with a value, "timed out" or "threw X" - never left unread."""
    with attached(rpc, pid) as (window, session):
        found = find(rpc, window, {PEERLESS, PEERED, PASSWORD})
        for name, protected in ((PEERED, False), (PEERLESS, False), (PASSWORD, True)):
            node = found[name]
            ref = select_like_the_host(rpc, session, node)
            base = {
                "sessionId": session["sessionId"],
                "objectId": ref["objectId"],
                "generation": ref["generation"],
            }
            rows = [m for m in pages(rpc, "inspect.managed.members", base) if auto_eligible(m)]
            categories = {m["category"] for m in rows}
            assert {"clrProperty", "dependencyProperty", "attachedProperty"} <= categories, (
                categories
            )
            outcomes: dict[str, int] = {}
            unread: list[str] = []
            for member in rows:
                response = rpc.call(
                    "inspect.managed.spyRead", {**base, "paths": [[member["pathSegment"]]]}
                )
                if "error" in response:
                    # A getter over the 250 ms limit: the host shows "(timed out)" in that row.
                    code = response["error"].get("data", {}).get("code")
                    if code != "timeout":
                        unread.append(f"{member['category']}:{member['name']}: {response['error']}")
                    outcomes["timed out"] = outcomes.get("timed out", 0) + 1
                    continue
                value = response["result"]["values"][0]["value"]
                status = value["status"]
                outcomes[status] = outcomes.get(status, 0) + 1
                if status == "exception":
                    assert value.get("message"), "the row shows (threw X): X is the exception type"
                elif status == "redacted":
                    assert protected, (name, member["name"], value)
                    # a name rule ("PasswordChar") or the protected identity itself
                    assert value["redactionRule"] in ("identity", "password"), value
                elif status not in ("ok", "timeout", "truncated", "unsupported", "cycle"):
                    unread.append(f"{member['category']}:{member['name']}: {status}")
            assert not unread, (name, unread)
            assert sum(outcomes.values()) == len(rows)
            if protected:
                # Password field: most getters are redacted by design and say why; the base ones still read.
                assert outcomes.get("redacted", 0) > 0 and outcomes.get("ok", 0) > 0, outcomes
            else:
                assert outcomes.get("redacted", 0) == 0, outcomes
                assert outcomes.get("ok", 0) >= len(rows) * 0.9, outcomes


def test_every_property_row_is_read_in_process(owned: Any) -> None:
    scope, path = owned
    check_every_row_is_read(InProcess(path, scope.app), scope.app.main_window().process_id)


def test_every_property_row_is_read_over_stdio(owned: Any) -> None:
    scope, path = owned
    server = Stdio(path)
    try:
        check_every_row_is_read(server, scope.app.main_window().process_id)
    finally:
        server.close()


def check_method_call_can_be_prepared(rpc: Rpc, pid: int) -> None:
    """The sequence behind the Methods tab's Invoke...: the host's canInvoke is true and a ticket is issued.

    The method is not invoked; the confirmation dialog and the invocation itself are the host's and are
    covered by the writes tests.
    """
    with attached(rpc, pid) as (window, session):
        node = find(rpc, window, {"FixtureControl"})["FixtureControl"]
        # attach (above), resolve, spySelect: select_like_the_host asserts what ManagedInspector.bindSpy checks.
        ref = select_like_the_host(rpc, session, node)
        bound = result(
            rpc,
            "inspect.managed.spySelect",
            {
                "hostCapability": CAPABILITY,
                "sessionId": session["sessionId"],
                "nodeId": node["nodeId"],
            },
        )
        mapped = bound["mapping"]["object"]
        assert bound["canInvoke"] is True and bound["mapping"]["status"] == "exact"
        assert (mapped["sessionId"], mapped["objectId"], mapped["generation"]) == (
            ref["sessionId"],
            ref["objectId"],
            ref["generation"],
        )
        base = {
            "sessionId": session["sessionId"],
            "objectId": ref["objectId"],
            "generation": ref["generation"],
        }
        methods = pages(rpc, "inspect.managed.spyMethods", base)
        record = next(m for m in methods if m["name"] == "RecordWrite")
        assert [p["type"] for p in record["parameters"]] == ["System.String", "System.Int64"]
        assert not record.get("unsupportedReason")
        assert len(record["parameters"]) <= 16 and not any(p["isOut"] for p in record["parameters"])
        prepared = result(
            rpc,
            "inspect.managed.spyPrepareInvoke",
            {
                "hostCapability": CAPABILITY,
                "sessionId": session["sessionId"],
                "objectId": ref["objectId"],
                "generation": ref["generation"],
                "memberKey": record["key"],
                "arguments": [
                    {"type": "System.String", "value": "prepared-only"},
                    {"type": "System.Int64", "value": 3},
                ],
            },
        )
        assert isinstance(prepared["ticket"], str) and prepared["ticket"]


def test_method_call_can_be_prepared_in_process(owned: Any) -> None:
    scope, path = owned
    check_method_call_can_be_prepared(
        InProcess(path, scope.app), scope.app.main_window().process_id
    )


def test_method_call_can_be_prepared_over_stdio(owned: Any) -> None:
    scope, path = owned
    server = Stdio(path)
    try:
        check_method_call_can_be_prepared(server, scope.app.main_window().process_id)
    finally:
        server.close()


def find_by_automation_id(rpc: Rpc, window: dict[str, Any], ids: set[str]) -> dict[str, Any]:
    found: dict[str, dict[str, Any]] = {}
    pending = [window]
    while pending and not ids <= found.keys():
        node = pending.pop(0)
        for child in result(rpc, "inspect.children", {"nodeId": node["nodeId"], "tree": "visual"})[
            "nodes"
        ]:
            pending.append(child)
            automation_id = child["info"].get("automationId")
            if automation_id in ids:
                found.setdefault(automation_id, child)
    assert ids <= found.keys(), sorted(found)
    return found


def text_binding(
    rpc: Rpc, session: dict[str, Any], node: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    ref = select_like_the_host(rpc, session, node)
    base = {
        "sessionId": session["sessionId"],
        "objectId": ref["objectId"],
        "generation": ref["generation"],
    }
    members = pages(rpc, "inspect.managed.members", base)
    keys = [
        item["memberKey"]
        for item in members
        if item["category"] in ("dependencyProperty", "attachedProperty") and item["name"] == "Text"
    ]
    bindings = result(rpc, "inspect.managed.bindings", {**base, "memberKeys": keys[:32]})
    return base, next(item for item in bindings["bindings"] if item["kind"] != "none")


def check_binding_details(rpc: Rpc, pid: int) -> None:
    with attached(rpc, pid) as (window, session):
        ids = {"DetailedBinding", "MultiBinding", "PriorityBinding", "ElementNameBinding"}
        found = find_by_automation_id(rpc, window, ids)
        _base, detailed = text_binding(rpc, session, found["DetailedBinding"])
        print("DetailedBinding", json.dumps(detailed, indent=1))
        assert detailed["kind"] == "binding" and detailed["path"] == "Label"
        assert detailed["stringFormat"] == "[{0}]"
        assert detailed["fallbackValue"]["scalar"] == "fallback"
        assert detailed["targetNullValue"]["scalar"] == "(null)"
        assert detailed["converterParameter"]["scalar"] == "cp"
        assert detailed["converterCulture"] == ""
        assert detailed["bindingGroupName"] == "fixtureGroup"
        assert detailed["notifyOnTargetUpdated"] is True and detailed["isAsync"] is False
        assert detailed["validatesOnNotifyDataErrors"] is True
        assert detailed["hasError"] is False and detailed["hasValidationError"] is False
        # DataItem is the fixture's DataContext: a handle a follow-up members request accepts.
        item = detailed["dataItem"]
        assert item["kind"] == "object", item
        ref = item["object"]
        members = result(
            rpc,
            "inspect.managed.members",
            {
                "sessionId": session["sessionId"],
                "objectId": ref["objectId"],
                "generation": ref["generation"],
            },
        )["items"]
        assert any(member["name"] == "Label" for member in members)
        assert detailed["resolvedSource"]["object"]["objectId"] == ref["objectId"]
        assert detailed["resolvedSourcePropertyName"] == "Label"

        _, multi = text_binding(rpc, session, found["MultiBinding"])
        print("MultiBinding", json.dumps(multi, indent=1))
        assert multi["kind"] == "multiBinding" and len(multi["children"]) == 2
        assert multi["children"][0]["dataItem"]["kind"] == "object"
        assert multi["converterType"].endswith("MultiConverter")

        _, priority = text_binding(rpc, session, found["PriorityBinding"])
        print("PriorityBinding", json.dumps(priority, indent=1))
        assert priority["kind"] == "priorityBinding" and priority["activeChildIndex"] == 1

        _, element = text_binding(rpc, session, found["ElementNameBinding"])
        assert element["resolvedSourcePropertyName"] == "Text"
        assert element["resolvedSource"]["object"]


def test_binding_details_in_process(owned: Any) -> None:
    scope, path = owned
    check_binding_details(InProcess(path, scope.app), scope.app.main_window().process_id)


def test_binding_details_over_stdio(owned: Any) -> None:
    scope, path = owned
    server = Stdio(path)
    try:
        check_binding_details(server, scope.app.main_window().process_id)
    finally:
        server.close()


def test_pick_recovers_missing_parents_real(owned: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from wintestkit.uia import win32

    scope, path = owned
    rpc = InProcess(path, scope.app)
    pid = scope.app.main_window().process_id
    with attached(rpc, pid) as (window, _session):
        node = find(rpc, window, {PEERED})[PEERED]
        element = rpc.server.nodes[node["nodeId"]]
        bounds = element.state().bounds
        assert bounds is not None
        native = rpc.server.nodes[window["nodeId"]]
        monkeypatch.setattr(win32, "WindowFromPoint", lambda point: native.native_window_handle)
        picked = rpc.server._spy_resolve(  # pyright: ignore[reportPrivateUsage]
            native,
            int(bounds.x + bounds.width / 2),
            int(bounds.y + bounds.height / 2),
            True,
            "visual",
        )
        assert picked.node is not None
        original = result(
            rpc, "inspect.properties", {"nodeId": picked.node["nodeId"], "includeAncestors": True}
        )
        assert len(original["ancestors"]) > 1
        rpc.server._wpf_parents.clear()  # pyright: ignore[reportPrivateUsage]
        repaired = result(
            rpc, "inspect.properties", {"nodeId": picked.node["nodeId"], "includeAncestors": True}
        )
        assert [n["nodeId"] for n in repaired["ancestors"]] == [
            n["nodeId"] for n in original["ancestors"]
        ]
        assert repaired["ancestors"][0]["nodeId"] == window["nodeId"]


def test_pick_content_host_real(owned: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from wintestkit.uia import win32

    scope, path = owned
    rpc = InProcess(path, scope.app)
    pid = scope.app.main_window().process_id
    with attached(rpc, pid) as (window, _session):
        pending = [window]
        host = None
        while pending and host is None:
            node = pending.pop(0)
            children = result(rpc, "inspect.children", {"nodeId": node["nodeId"], "tree": "visual"})
            for child in children["nodes"]:
                if child.get("identity", {}).get("automationId") == "PickTextHost":
                    host = child
                    break
                pending.append(child)
        assert host is not None
        bounds = rpc.server.nodes[host["nodeId"]].state().bounds
        assert bounds is not None
        native = rpc.server.nodes[window["nodeId"]]
        monkeypatch.setattr(win32, "WindowFromPoint", lambda point: native.native_window_handle)
        picked = rpc.server._spy_resolve(  # pyright: ignore[reportPrivateUsage]
            native, int(bounds.x + 10), int(bounds.y + bounds.height / 2), True, "visual"
        )
        assert picked.node is not None
        assert picked.node["identity"]["type"].endswith("TextBlock")
        assert picked.extra["innerElement"]["type"] == "Run"
        assert picked.extra["innerElement"]["text"] == "Save"
        properties = result(
            rpc, "inspect.properties", {"nodeId": picked.node["nodeId"], "includeAncestors": True}
        )
        ancestors = properties["ancestors"]
        assert ancestors and ancestors[0]["nodeId"] == window["nodeId"]
        for parent, child in zip(ancestors, [*ancestors[1:], picked.node], strict=True):
            children = result(
                rpc, "inspect.children", {"nodeId": parent["nodeId"], "tree": "visual"}
            )
            assert any(item["nodeId"] == child["nodeId"] for item in children["nodes"])
