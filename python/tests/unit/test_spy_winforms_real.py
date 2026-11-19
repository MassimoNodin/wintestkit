"""Live WinForms Spy: attach, tree, Properties, Fields, Methods and redaction on the owned WinForms fixture.

Run with WTK_INSPECTOR_REAL=1 on a desktop session after `scripts/publish_fixtures.ps1`. It launches
`WinTestKit.WinFormsFixture.exe` itself, drives the same RPC sequence the extension host sends for a
selected object, and checks that a WinForms control behaves like a WPF object in every step.
"""

import base64
import io
import json
import os
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from live_dotnet import live_dotnet_root
from test_inspector_owned_integration import PAYLOAD

from wintestkit import runtime
from wintestkit.app import App
from wintestkit.config import load_config
from wintestkit.errors import InspectorUnavailableError
from wintestkit.inspector.probe import identify
from wintestkit.server import Server
from wintestkit.uia import win32

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "wpf-inspector/tests/Fixtures/WinFormsFixture/bin/cells/net10.0-windows-x64"
EXECUTABLE = FIXTURE / "WinTestKit.WinFormsFixture.exe"
CAPABILITY = base64.b64encode(bytes(range(32))).decode("ascii")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.name != "nt" or os.environ.get("WTK_INSPECTOR_REAL") != "1",
        reason="requires explicitly enabled owned Windows fixture",
    ),
    pytest.mark.skipif(not EXECUTABLE.exists(), reason="publish the WinForms fixture first"),
]


class Rpc:
    def __init__(self, path: Path, app: App) -> None:
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

    def result(self, method: str, params: dict[str, Any]) -> Any:
        response = self.call(method, params)
        assert "result" in response, (method, response)
        return response["result"]

    def pages(self, method: str, base: dict[str, Any]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        token = None
        while True:
            page = self.result(method, {**base, **({"pageToken": token} if token else {})})
            items += page["items"]
            token = page.get("nextToken")
            if not token:
                return items


def launch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *arguments: str) -> Iterator[Any]:
    runtime.reset()
    monkeypatch.syspath_prepend(str(PAYLOAD))
    env = os.environ.copy()
    env["DOTNET_ROOT_X64"] = live_dotnet_root()
    env["DOTNET_MULTILEVEL_LOOKUP"] = "0"
    target = subprocess.Popen(
        [str(EXECUTABLE), *arguments],
        cwd=FIXTURE,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        until = time.monotonic() + 30
        wanted = 2 if arguments else 1
        while True:
            assert target.poll() is None
            try:
                facts = identify(target.pid)
                if facts.winforms_loaded and len(win32.top_level_windows({target.pid})) >= wanted:
                    break
            except (OSError, InspectorUnavailableError):
                pass
            assert time.monotonic() < until
            time.sleep(0.1)
        yield Rpc(tmp_path, App.attach(pid=target.pid)), target.pid
    finally:
        runtime.reset()
        if target.poll() is None:
            target.terminate()
        target.wait(timeout=5)


@pytest.fixture
def fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    yield from launch(tmp_path, monkeypatch)


@pytest.fixture
def duplicates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    yield from launch(tmp_path, monkeypatch, "--scenario", "openDuplicateButtons")


def window_named(rpc: Rpc, pid: int, title: str) -> dict[str, Any]:
    roots = rpc.result("inspect.roots", {})
    window = next(
        node for node in roots if node["info"]["processId"] == pid and node["info"]["name"] == title
    )
    assert window["source"] == "winforms", window
    return window


def attach(rpc: Rpc, window: dict[str, Any]) -> dict[str, Any]:
    first = rpc.result("inspect.children", {"nodeId": window["nodeId"], "tree": "visual"})
    assert first.get("attachRequired") is True
    facts = rpc.result("inspect.managed.identify", {"nodeId": window["nodeId"]})
    assert facts["winformsLoaded"] is True and facts["wpfLoaded"] is False
    session = rpc.result(
        "inspect.managed.attach", {"process": facts["process"], "hostCapability": CAPABILITY}
    )
    assert session["state"] == "ready"
    return session


def children(rpc: Rpc, node: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = rpc.result("inspect.children", {"nodeId": node["nodeId"], "tree": "visual"})["nodes"]
    assert all(item["nodeId"].startswith("winforms:") for item in nodes), nodes
    assert all(item["source"] == "winforms" for item in nodes), nodes
    return nodes


def named(rpc: Rpc, parent: dict[str, Any], name: str) -> dict[str, Any]:
    nodes = children(rpc, parent)
    for item in nodes:
        if item.get("identity", {}).get("xName") == name:
            return item
    raise AssertionError((name, [item.get("identity") for item in nodes]))


def select(rpc: Rpc, session: dict[str, Any], node: dict[str, Any]) -> dict[str, str]:
    """The calls the extension host makes for a selected object, in order."""
    rpc.result("inspect.managed.spySelect", {"hostCapability": CAPABILITY})
    properties = rpc.result(
        "inspect.properties", {"nodeId": node["nodeId"], "includeAncestors": True}
    )
    assert properties["source"] == "winforms"
    mapping = rpc.result(
        "inspect.managed.resolve", {"sessionId": session["sessionId"], "nodeId": node["nodeId"]}
    )
    assert mapping["status"] == "exact" and mapping["source"] == "winforms"
    bound = rpc.result(
        "inspect.managed.spySelect",
        {"hostCapability": CAPABILITY, "sessionId": session["sessionId"], "nodeId": node["nodeId"]},
    )
    assert bound["canInvoke"] is True
    return mapping["object"]


def read(rpc: Rpc, session: dict[str, Any], ref: dict[str, Any], row: dict[str, Any]) -> Any:
    response = rpc.result(
        "inspect.managed.spyRead",
        {
            "sessionId": session["sessionId"],
            "objectId": ref["objectId"],
            "generation": ref["generation"],
            "paths": [[row["pathSegment"]]],
        },
    )
    return response["values"][0]["value"]


def members(rpc: Rpc, session: dict[str, Any], ref: dict[str, Any]) -> dict[tuple[str, str], Any]:
    rows = rpc.pages(
        "inspect.managed.members",
        {
            "sessionId": session["sessionId"],
            "objectId": ref["objectId"],
            "generation": ref["generation"],
        },
    )
    return {(row["category"], row["name"]): row for row in rows}


def test_tree_properties_fields_and_methods_of_a_button(fixture: Any) -> None:
    rpc, pid = fixture
    window = window_named(rpc, pid, "WinForms Fixture")
    session = attach(rpc, window)
    button = named(rpc, window, "button1")
    assert button["info"]["controlType"] == "Button" and button["info"]["name"] == "OK"
    assert button["identity"]["type"] == "System.Windows.Forms.Button"
    ref = select(rpc, session, button)
    properties = rpc.result(
        "inspect.properties", {"nodeId": button["nodeId"], "includeAncestors": True}
    )
    assert properties["properties"]["ControlName"] == "button1"
    assert properties["properties"]["WinFormsControlText"] == "OK"
    assert properties["properties"]["ClrFullClassName"] == "System.Windows.Forms.Button"
    assert properties["properties"]["Visible"] == "True"
    assert properties["uiaMapped"] is True and properties["ancestors"]
    assert properties["window"]["className"], "the Win32 Window group describes the control's HWND"
    rows = members(rpc, session, ref)
    assert read(rpc, session, ref, rows[("clrProperty", "Text")])["scalar"] == "OK"
    assert read(rpc, session, ref, rows[("clrProperty", "Enabled")])["scalar"] is True
    assert any(category == "clrField" for category, _ in rows), "the Fields tab has rows"
    methods = rpc.pages(
        "inspect.managed.spyMethods",
        {
            "sessionId": session["sessionId"],
            "objectId": ref["objectId"],
            "generation": ref["generation"],
        },
    )
    assert any(item["name"] == "PerformClick" for item in methods)
    assert rpc.result("inspect.managed.keepalive", {"sessionId": session["sessionId"]}) == {
        "alive": True
    }


def test_nested_controls_menus_and_tab_pages_follow_the_control_tree(fixture: Any) -> None:
    rpc, pid = fixture
    window = window_named(rpc, pid, "WinForms Fixture")
    attach(rpc, window)
    group = named(rpc, window, "groupBox1")
    assert group["hasChildren"] is True
    assert {item["identity"]["xName"] for item in children(rpc, group)} == {
        "nestedButton1",
        "nestedButton2",
    }
    tabs = named(rpc, window, "tabControl1")
    assert [item["identity"]["xName"] for item in children(rpc, tabs)] == ["tabPage1", "tabPage2"]
    file = named(rpc, named(rpc, window, "menuStrip1"), "fileToolStripMenuItem")
    assert file["hasChildren"] is True
    assert named(rpc, file, "openToolStripMenuItem")["info"]["controlType"] == "ToolStripMenuItem"


def test_custom_control_members_and_a_live_invoke(fixture: Any) -> None:
    rpc, pid = fixture
    window = window_named(rpc, pid, "WinForms Fixture")
    session = attach(rpc, window)
    custom = named(rpc, window, "fixtureUserControl1")
    ref = select(rpc, session, custom)
    rows = members(rpc, session, ref)
    assert (
        read(rpc, session, ref, rows[("clrProperty", "PublicProperty")])["scalar"] == "public value"
    )
    assert read(rpc, session, ref, rows[("clrField", "PublicField")])["scalar"] == 3
    assert read(rpc, session, ref, rows[("clrField", "privateField")])["scalar"] == "private field"
    assert read(rpc, session, ref, rows[("clrField", "internalField")])["scalar"] == 5
    assert (
        read(rpc, session, ref, rows[("clrProperty", "ThrowingProperty")])["status"] == "exception"
    )
    assert ("clrProperty", "DefaultedProperty") in rows and (
        "clrProperty",
        "PrivateProperty",
    ) in rows
    methods = rpc.pages(
        "inspect.managed.spyMethods",
        {
            "sessionId": session["sessionId"],
            "objectId": ref["objectId"],
            "generation": ref["generation"],
        },
    )
    record = next(item for item in methods if item["name"] == "RecordWrite")
    assert [item["type"] for item in record["parameters"]] == ["System.String", "System.Int32"]
    prepared = rpc.result(
        "inspect.managed.spyPrepareInvoke",
        {
            "hostCapability": CAPABILITY,
            "sessionId": session["sessionId"],
            "objectId": ref["objectId"],
            "generation": ref["generation"],
            "memberKey": record["key"],
            "arguments": [
                {"type": "System.String", "value": "live"},
                {"type": "System.Int32", "value": 7},
            ],
        },
    )
    performed = rpc.result(
        "inspect.managed.spyInvoke", {"hostCapability": CAPABILITY, "ticket": prepared["ticket"]}
    )
    assert performed["audit"]["outcome"] == "performed"
    assert read(rpc, session, ref, rows[("clrField", "LastValue")])["scalar"] == "live"
    assert read(rpc, session, ref, rows[("clrField", "LastNumber")])["scalar"] == 7
    output = named(rpc, custom, "writeOutput")
    shown = rpc.result("inspect.properties", {"nodeId": output["nodeId"]})
    assert shown["properties"]["WinFormsControlText"] == "RecordWrite(live, 7) #1"


def test_password_box_is_redacted_and_unnamed_in_the_tree(fixture: Any) -> None:
    rpc, pid = fixture
    window = window_named(rpc, pid, "WinForms Fixture")
    session = attach(rpc, window)
    box = next(
        item
        for item in children(rpc, window)
        if item["identity"]["type"].endswith("TextBox")
        and item["info"]["controlType"] == "TextBox"
        and "xName" not in item["identity"]
    )
    ref = select(rpc, session, box)
    rows = members(rpc, session, ref)
    assert read(rpc, session, ref, rows[("clrProperty", "Text")])["status"] == "redacted"
    assert (
        read(rpc, session, ref, rows[("clrProperty", "UseSystemPasswordChar")])["status"]
        == "redacted"
    )
    properties = rpc.result("inspect.properties", {"nodeId": box["nodeId"]})
    assert "hunter2" not in json.dumps(properties)
    assert "WinFormsControlText" not in properties["properties"]


def test_unnamed_siblings_are_told_apart_by_type_text_and_place(duplicates: Any) -> None:
    rpc, pid = duplicates
    window = window_named(rpc, pid, "Duplicate Buttons")
    attach(rpc, window)
    buttons = children(rpc, window)
    assert [item["info"]["name"] for item in buttons] == ["Same", "Same", "Other"]
    assert all("xName" not in item["identity"] for item in buttons)
