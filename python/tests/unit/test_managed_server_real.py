"""Opt-in S7 RPC and CLI validation against an unchanged fixture started by this test."""

import io
import json
import os
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from test_inspector_owned_integration import DOTNET, FIXTURE, PAYLOAD, ROOT, _control, _hashes  # pyright: ignore[reportPrivateUsage]

from wintestkit import runtime
from wintestkit.cli import main
from wintestkit.commands import common
from wintestkit.config import load_config
from wintestkit.errors import InspectorUnavailableError
from wintestkit.inspector.probe import agent_active, identify
from wintestkit.server import Server
from wintestkit.targets import ModuleLoader
from wintestkit.uia import com, element, win32
from wintestkit.uia.constants import TreeScope

pytestmark = pytest.mark.skipif(
    os.name != "nt" or os.environ.get("WTK_INSPECTOR_REAL") != "1",
    reason="requires explicitly enabled owned Windows fixture",
)


def _fixture_counters(pid: int) -> dict[str, object]:
    deadline = time.monotonic() + 2
    while True:
        try:
            return _control(pid)
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)


def _call(server: Server, output: io.BytesIO, name: str, params: dict[str, Any]) -> Any:
    output.seek(0)
    output.truncate()
    server.handle(
        {"jsonrpc": "2.0", "id": 1, "method": f"inspect.managed.{name}", "params": params}
    )
    response = json.loads(output.getvalue())
    assert "result" in response, response
    documents = [
        json.loads(path.read_text(encoding="utf-8-sig"))
        for path in [
            *sorted((ROOT / "schemas").glob("*.schema.json")),
            ROOT / "wpf-inspector/protocol/inspector.schema.json",
        ]
    ]
    registry = Registry[Any]().with_resources(
        (doc["$id"], Resource.from_contents(doc)) for doc in documents
    )
    schema = (
        f"https://wintestkit.dev/schemas/rpc.schema.json#/$defs/InspectManaged{name.title()}Result"
    )
    validator = Draft202012Validator({"$ref": schema}, registry=registry)
    assert validator.is_valid(response["result"]), list(validator.iter_errors(response["result"]))  # pyright: ignore[reportUnknownMemberType]
    return response["result"]


def test_owned_fixture_server_and_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runtime.reset()
    monkeypatch.syspath_prepend(str(PAYLOAD))  # pyright: ignore[reportUnknownMemberType]
    (tmp_path / "wintestkit.yaml").write_text(
        "inspector:\n  enabled: true\n  attach: manual\n", encoding="utf-8"
    )
    before = _hashes()
    env = os.environ.copy()
    env["DOTNET_ROOT"] = DOTNET
    env["DOTNET_ROOT_X64"] = DOTNET
    env["DOTNET_MULTILEVEL_LOOKUP"] = "0"
    target = subprocess.Popen(
        [str(FIXTURE / "WinTestKit.Fixture.exe")],
        cwd=FIXTURE,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        until = time.monotonic() + 15
        while True:
            assert target.poll() is None
            try:
                facts = identify(target.pid)
                handles = win32.top_level_windows({target.pid})
                if facts.wpf_loaded and facts.runtime == "net10" and handles:
                    _fixture_counters(target.pid)
                    break
            except (OSError, InspectorUnavailableError):
                pass
            assert time.monotonic() < until, "Owned fixture did not become ready"
            time.sleep(0.1)
        window = element.from_handle(handles[0])
        output = io.BytesIO()
        server = Server(output)
        server.cfg = load_config(tmp_path)
        server.loader = ModuleLoader(server.cfg)
        server.nodes[window.runtime_id] = window
        node = {"nodeId": window.runtime_id}
        identity = _call(server, output, "identify", node)["process"]
        assert identity == facts.identity.to_json()
        server.cfg = load_config(tmp_path, {"inspector.redact_names": ["account"]})
        session = _call(server, output, "attach", {"process": identity})
        session_id = session["sessionId"]
        assert _call(server, output, "status", {"process": identity})["state"] == "ready"
        mapping = _call(server, output, "resolve", {"sessionId": session_id, **node})
        assert mapping["status"] == "exact"
        ref = mapping["object"]
        object_params = {key: ref[key] for key in ("sessionId", "objectId", "generation")}
        assert _call(server, output, "roots", {"sessionId": session_id})["items"]
        members = _call(server, output, "members", {**object_params, "pageSize": 200})
        assert members["items"]
        dependency = next(
            (
                item
                for item in members["items"]
                if item["category"] in {"dependencyProperty", "attachedProperty"}
            ),
            None,
        )
        while dependency is None and "nextToken" in members:
            members = _call(
                server,
                output,
                "members",
                {
                    **object_params,
                    "pageSize": 200,
                    "pageToken": members["nextToken"],
                },
            )
            dependency = next(
                (
                    item
                    for item in members["items"]
                    if item["category"] in {"dependencyProperty", "attachedProperty"}
                ),
                None,
            )
        assert dependency is not None
        bindings = _call(
            server,
            output,
            "bindings",
            {
                **object_params,
                "memberKeys": [dependency["memberKey"]],
            },
        )
        assert bindings["bindings"][0]["memberKey"] == dependency["memberKey"]
        _call(server, output, "children", {**object_params, "tree": "visual"})
        fixture_element = window.find_first(
            TreeScope.Descendants, com.create_condition(automation_id="FixtureControl")
        )
        assert fixture_element is not None
        server.nodes[fixture_element.runtime_id] = fixture_element
        fixture_mapping = _call(
            server,
            output,
            "resolve",
            {
                "sessionId": session_id,
                "nodeId": fixture_element.runtime_id,
            },
        )
        assert fixture_mapping["status"] == "exact"
        fixture_ref = fixture_mapping["object"]
        assert fixture_ref["type"]["name"] == "FixtureControl"
        fixture_params = {key: fixture_ref[key] for key in ("sessionId", "objectId", "generation")}
        before_password = _fixture_counters(target.pid).get("Password", 0)
        redacted = _call(
            server,
            output,
            "read",
            {
                **fixture_params,
                "paths": [[{"kind": "property", "name": "Password"}]],
            },
        )["values"][0]["value"]
        assert redacted["status"] == "redacted" and "scalar" not in redacted
        assert _fixture_counters(target.pid).get("Password", 0) == before_password
        before_guarded = _fixture_counters(target.pid).get("Guarded.VisibleValue", 0)
        guarded = _call(
            server,
            output,
            "read",
            {
                **fixture_params,
                "paths": [
                    [
                        {"kind": "property", "name": "Guarded"},
                        {"kind": "property", "name": "VisibleValue"},
                    ]
                ],
            },
        )["values"][0]["value"]
        assert guarded["status"] == "redacted" and guarded["redactionRule"] == "identity"
        assert _fixture_counters(target.pid).get("Guarded.VisibleValue", 0) == before_guarded
        before_account = _fixture_counters(target.pid).get("AccountNumber", 0)
        account = _call(
            server,
            output,
            "read",
            {
                **fixture_params,
                "paths": [[{"kind": "property", "name": "AccountNumber"}]],
            },
        )["values"][0]["value"]
        assert account["status"] == "redacted" and account["redactionRule"] == "account"
        assert "scalar" not in account
        assert _fixture_counters(target.pid).get("AccountNumber", 0) == before_account
        read = _call(
            server,
            output,
            "read",
            {
                **object_params,
                "paths": [[{"kind": "type", "name": "FullName"}]],
            },
        )
        assert read["values"][0]["value"]["status"] == "ok"
        _call(server, output, "release", {"sessionId": session_id, "objectIds": [ref["objectId"]]})
        _call(server, output, "detach", {"sessionId": session_id})
        _fixture_counters(target.pid)
        until = time.monotonic() + 3
        while agent_active(target.pid) and time.monotonic() < until:
            time.sleep(0.05)
        assert not agent_active(target.pid)

        def app(cfg: Any) -> Any:
            return SimpleNamespace(main_window=lambda: window)

        monkeypatch.setattr(common, "attach_app", app)
        assert (
            main(
                [
                    "--root",
                    str(tmp_path),
                    "inspect",
                    "--managed",
                    "--read-managed",
                    "type:FullName",
                    "--depth",
                    "0",
                    "--json",
                ]
            )
            == 0
        )
        cli = json.loads(capsys.readouterr().out)["managed"]
        assert cli["mapping"]["status"] == "exact"
        assert cli["read"]["values"][0]["value"]["status"] == "ok"
        _fixture_counters(target.pid)
        assert target.poll() is None and _hashes() == before
    finally:
        runtime.reset()
        if target.poll() is None:
            target.terminate()
        target.wait(timeout=5)


def test_spy_tree_peerless_and_large_page(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime.reset()
    monkeypatch.syspath_prepend(str(PAYLOAD))
    (tmp_path / "wintestkit.yaml").write_text(
        "inspector:\n  enabled: true\n  attach: manual\n", encoding="utf-8"
    )
    env = os.environ.copy()
    env["DOTNET_ROOT"] = DOTNET
    env["DOTNET_ROOT_X64"] = DOTNET
    env["DOTNET_MULTILEVEL_LOOKUP"] = "0"
    target = subprocess.Popen(
        [str(FIXTURE / "WinTestKit.Fixture.exe"), "--scenario", "openLarge"],
        cwd=FIXTURE,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        until = time.monotonic() + 15
        windows: list[Any] = []
        while time.monotonic() < until:
            assert target.poll() is None
            try:
                windows = [
                    element.from_handle(hwnd) for hwnd in win32.top_level_windows({target.pid})
                ]
                if len(windows) >= 2 and any(
                    window.automation_id == "LargeWindow" for window in windows
                ):
                    break
            except Exception:
                pass
            time.sleep(0.1)
        large = next(window for window in windows if window.automation_id == "LargeWindow")
        main_window = next(window for window in windows if window.automation_id != "LargeWindow")
        output = io.BytesIO()
        server = Server(output)
        server.cfg = load_config(tmp_path)
        server.loader = ModuleLoader(server.cfg)
        for window in (main_window, large):
            server.nodes[window.runtime_id] = window
            server.node_infos[window.runtime_id] = window.info()
            server._wpf_windows.add(window.runtime_id)
        _call(server, output, "attach", {"process": identify(target.pid).identity.to_json()})

        def children(node_id: str, tree: str, page_token: str | None = None) -> dict[str, Any]:
            output.seek(0)
            output.truncate()
            server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "inspect.children",
                    "params": {
                        "nodeId": node_id,
                        "tree": tree,
                        **({"pageToken": page_token} if page_token else {}),
                    },
                }
            )
            result = json.loads(output.getvalue())
            assert "result" in result, result
            assert isinstance(result["result"], dict), result
            return result["result"]

        found_nodes: dict[str, str] = {}
        for tree in ("visual", "logical"):
            queue = [main_window.runtime_id]
            found = False
            for _ in range(250):
                if not queue:
                    break
                for child in children(queue.pop(0), tree)["nodes"]:
                    if child["identity"]["type"].endswith(".PeerlessMarker"):
                        found_nodes["peerless"] = child["nodeId"]
                        found = True
                    if child["identity"]["type"].endswith(".PeerlessClickTarget"):
                        found_nodes["click_target"] = child["nodeId"]
                    if child["identity"].get("automationId") == "ParityPointer":
                        found_nodes["button"] = child["nodeId"]
                    if found and "button" in found_nodes and "click_target" in found_nodes:
                        break
                    if child["hasChildren"]:
                        queue.append(child["nodeId"])
                if found and "button" in found_nodes and "click_target" in found_nodes:
                    break
            assert found, f"peerless element missing from {tree} tree"
        assert "button" in found_nodes
        # These RPC suggestions must also survive the public declaration syntax and resolver.
        from wintestkit.app import App
        from wintestkit.engine.resolve import Scope, resolve
        from wintestkit.model import Element

        app = App.attach(pid=target.pid)
        server.app = app
        for node_id in found_nodes.values():
            output.seek(0)
            output.truncate()
            server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "suggest.locator",
                    "params": {"nodeId": node_id},
                }
            )
            response = json.loads(output.getvalue())
            assert "result" in response, response
            suggestion = response["result"]
            assert suggestion["unique"], suggestion
            namespace: dict[str, Any] = {"Element": Element}
            for helper in suggestion["helpers"]:
                namespace[helper["attributeName"]] = eval(helper["code"], namespace)
            declaration = eval(suggestion["code"], namespace)
            from wintestkit.engine.locator import WindowLocator

            window = WindowLocator.from_dict(suggestion["window"]["locator"])
            with runtime.config_scope(server.cfg):
                resolved = resolve(Scope(app, window), declaration.locator())
            assert resolved.same_as(server.nodes[node_id])
        for kind, node_id in found_nodes.items():
            output.seek(0)
            output.truncate()
            server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "inspect.properties",
                    "params": {"nodeId": node_id, "includeAncestors": True},
                }
            )
            response = json.loads(output.getvalue())
            assert response["result"]["source"] == "wpf", response
            ancestors = response["result"]["ancestors"]
            assert ancestors and ancestors[0]["nodeId"] == main_window.runtime_id
            assert ancestors[-1]["nodeId"] == server._wpf_parents[node_id]
            assert response["result"]["uiaMapped"] is (kind == "button")
            node = server.nodes[node_id]
            mapping = _call(
                server, output, "resolve", {"sessionId": node.ref.session_id, "nodeId": node_id}
            )
            obj = mapping["object"]
            members = _call(
                server,
                output,
                "members",
                {
                    "sessionId": obj["sessionId"],
                    "objectId": obj["objectId"],
                    "generation": obj["generation"],
                },
            )
            assert members["items"]
        # Exercise the picker's worker resolution directly, without installing global hooks.
        from wintestkit.engine import actions
        from wintestkit.engine.spy import SpySession

        monkeypatch.setattr(SpySession, "start", lambda self: None)
        output.seek(0)
        output.truncate()
        server.handle(
            {"jsonrpc": "2.0", "id": 2, "method": "spy.start", "params": {"tree": "visual"}}
        )
        assert json.loads(output.getvalue())["result"] is None
        picker = server.spy
        assert picker is not None

        def check_point(point: tuple[int, int], expected: str) -> None:
            for pick in (False, True):
                target = picker._element_at(*point, pick=pick)
                assert target is not None and target.node["source"] == "wpf"
                if pick:
                    output.seek(0)
                    output.truncate()
                    picker._on_pick(target)
                    notification = json.loads(output.getvalue())
                    assert notification["method"] == "spy.picked"
                    node_id = notification["params"]["node"]["nodeId"]
                    response = server._wpf_properties(
                        server.nodes[node_id], {"nodeId": node_id, "includeAncestors": True}
                    )
                    assert response["ancestors"]
                    assert expected in str([*response["ancestors"], target.node])
                else:
                    output.seek(0)
                    output.truncate()
                    picker._on_hover(target)
                    assert json.loads(output.getvalue())["params"]["node"]["source"] == "wpf"

        win32.raise_window(main_window.native_window_handle)
        for key, expected in (("button", "ParityPointer"), ("click_target", "PeerlessClickTarget")):
            rect = server.nodes[found_nodes[key]].rect
            assert rect is not None
            check_point(rect.center, expected)
        actions.right_click(server.nodes[found_nodes["button"]])
        deadline = time.monotonic() + 5
        menu_item = None
        while time.monotonic() < deadline and menu_item is None:
            for hwnd in win32.top_level_windows({target.pid}):
                root = element.from_handle(hwnd)
                candidates = [root, *root.children()]
                while candidates:
                    candidate = candidates.pop()
                    if candidate.automation_id == "ParityContextItem":
                        menu_item = candidate
                        break
                    candidates.extend(candidate.children())
            if menu_item is None:
                time.sleep(0.1)
        assert menu_item is not None and menu_item.rect is not None
        check_point(menu_item.rect.center, "ParityContextItem")
        server.stop_spy()
        queue = [large.runtime_id]
        for _ in range(40):
            node_id = queue.pop(0)
            started = time.monotonic()
            page = children(node_id, "logical")
            items = page["nodes"]
            elapsed = time.monotonic() - started
            if len(items) == 200 and "nextPageToken" in page:
                print(f"LARGE_PAGE_FIRST: {len(items)} children in {elapsed:.3f}s")
                seen_ids: set[str] = set()
                for page_index in range(4):
                    if page_index:
                        started = time.monotonic()
                        page = children(node_id, "logical", page["nextPageToken"])
                        items = page["nodes"]
                        print(
                            f"LARGE_PAGE_LATER_{page_index}: {len(items)} children in {time.monotonic() - started:.3f}s"
                        )
                    assert len(items) == 200
                    for item in items:
                        identity = item["identity"]
                        assert identity["type"].endswith(".LargeButton"), identity
                        assert identity.get("automationId", "").startswith("Large"), identity
                        seen_ids.add(identity["automationId"])
                assert len(seen_ids) == 800
                break
            queue.extend(item["nodeId"] for item in items if item["hasChildren"])
        else:
            pytest.fail("Large fixture child page not found")
        server._release_managed_objects()
    finally:
        runtime.reset()
        if target.poll() is None:
            target.terminate()
        target.wait(timeout=5)
