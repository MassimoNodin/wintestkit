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
        output.seek(0)
        output.truncate()
        server.handle(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "inspect.managed.attach",
                "params": {"process": identity},
            }
        )
        assert json.loads(output.getvalue())["error"]["data"]["code"] == "unsupportedTarget"
        assert not agent_active(target.pid)
        server.cfg = load_config(tmp_path)
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
