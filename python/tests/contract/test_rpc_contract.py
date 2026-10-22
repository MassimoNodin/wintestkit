"""Real server results satisfy each method contract."""

import json
from pathlib import Path
from typing import Any

import pytest
from rpc_support import make_server, request


def test_stopped_app_definitions_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, validate: Any
) -> None:
    server, output, button = make_server(tmp_path, monkeypatch)
    request(server, output, "initialize", {"root": str(tmp_path)})
    node = server._register(button)
    monkeypatch.setattr(server, "_app", lambda required=True: None)
    result = request(server, output, "inspect.definitions", {"nodeId": node["nodeId"]})["result"]
    validate("rpc.schema.json", "InspectDefinitionsResult", result)
    assert result["appRunning"] is False
    assert result["pageCount"] == 1


def test_rpc_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, validate: Any) -> None:
    from wintestkit.engine import spy

    server, output, button = make_server(tmp_path, monkeypatch)

    class FakeSpy:
        def __init__(self, hover: Any, pick: Any, cancel: Any, process_filter: Any) -> None:
            self.hover, self.pick, self.cancel = hover, pick, cancel

        def start(self) -> None:
            self.hover(button)
            self.pick(button)

        def stop(self) -> None:
            pass

    monkeypatch.setattr(spy, "SpySession", FakeSpy)
    initialization = request(server, output, "initialize", {"root": str(tmp_path)})["result"]
    validate("rpc.schema.json", "InitializeResult", initialization)
    node = server._register(button)
    validate("rpc.schema.json", "NodeInfo", node)
    server.handle({"jsonrpc": "2.0", "id": 1, "method": "spy.start"})
    definitions = {"spy.hover": "SpyHoverNotification", "spy.picked": "SpyPickedNotification"}
    for response in map(json.loads, output.getvalue().splitlines()):
        validate(
            "rpc.schema.json",
            definitions[response["method"]] if "method" in response else "SpyStartResult",
            response.get("params", response.get("result")),
        )
    output.seek(0)
    output.truncate()
    server.notify("spy.cancelled", {})
    validate("rpc.schema.json", "SpyCancelledNotification", json.loads(output.getvalue())["params"])
    output.seek(0)
    output.truncate()
    methods = [
        ("discover", {}, "DiscoverResult"),
        ("app.status", {}, "AppStatusResult"),
        ("app.launch", {}, "AppLaunchResult"),
        ("app.processes", {}, "AppProcessesResult"),
        (
            "element.highlight",
            {"file": "page.py", "qualname": "Main.ok"},
            "ElementHighlightResult",
        ),
        ("page.check", {"file": "page.py", "page": "Main"}, "PageCheckResult"),
        ("inspect.roots", {}, "InspectRootsResult"),
        ("inspect.refresh", {}, "InspectRefreshResult"),
        ("inspect.children", {"nodeId": node["nodeId"]}, "InspectChildrenResult"),
        ("inspect.properties", {"nodeId": node["nodeId"]}, "InspectPropertiesResult"),
        (
            "inspect.properties",
            {"nodeId": node["nodeId"], "full": True, "includeAncestors": True},
            "InspectPropertiesResult",
        ),
        (
            "inspect.properties",
            {"nodeId": node["nodeId"], "include": ["Name", "RuntimeId"]},
            "InspectPropertiesResult",
        ),
        ("inspect.highlight", {"nodeId": node["nodeId"]}, "InspectHighlightResult"),
        ("inspect.preview", {"nodeId": node["nodeId"]}, "InspectPreviewResult"),
        ("suggest.locator", {"nodeId": node["nodeId"]}, "SuggestLocatorResult"),
        ("inspect.definitions", {"nodeId": node["nodeId"]}, "InspectDefinitionsResult"),
        ("inspect.coverage", {"nodeIds": [node["nodeId"]]}, "InspectCoverageResult"),
        ("spy.stop", {}, "SpyStopResult"),
    ]
    for method, params, definition in methods:
        response = request(server, output, method, params)
        assert "result" in response, response
        validate("rpc.schema.json", definition, response["result"])
    monkeypatch.setattr(server.app, "close", lambda **kwargs: None, raising=False)
    validate("rpc.schema.json", "AppCloseResult", request(server, output, "app.close")["result"])
    validate("rpc.schema.json", "ShutdownResult", request(server, output, "shutdown")["result"])
