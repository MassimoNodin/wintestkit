"""Live managed Spy path regression."""

import io
import json
import os
import time
from typing import Any

import pytest
from test_wpf_query_gate_real import _fixture_scenario  # pyright: ignore[reportPrivateUsage]

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


def test_duplicate_path_real(owned: Any) -> None:
    scope, path = owned
    output = io.BytesIO()
    server = Server(output)

    def rpc(method: str, params: dict[str, Any]) -> Any:
        output.seek(0)
        output.truncate()
        server.handle({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        response = json.loads(output.getvalue().splitlines()[-1])
        assert "result" in response, response
        return response["result"]

    rpc("initialize", {"root": str(path)})
    server.cfg = load_config(path, {"inspector.enabled": True})
    server.app = scope.app
    pid = scope.app.main_window().process_id
    _fixture_scenario(pid, "openDuplicateItems", 0)
    try:
        window = next(
            node
            for node in rpc("inspect.roots", {})
            if node["info"]["processId"] == pid and node["info"]["name"] == "Duplicate items"
        )

        def children(node: dict[str, Any]) -> list[dict[str, Any]]:
            start = time.monotonic()
            result = rpc(
                "inspect.children", {"nodeId": node["nodeId"], "tree": "visual", "pageSize": 200}
            )
            if isinstance(result, dict) and "attachRequired" in result:
                rpc("inspect.managed.attach", {"process": result["process"]})
                result = rpc(
                    "inspect.children",
                    {"nodeId": node["nodeId"], "tree": "visual", "pageSize": 200},
                )
            assert (
                isinstance(result, dict) and "nodes" in result and not result.get("nextPageToken")
            ), result
            print("PAGE", node["info"]["controlType"], round(time.monotonic() - start, 3))
            return result["nodes"]

        queue = [(window, [window])]
        while queue:
            parent, chain = queue.pop(0)
            items = children(parent)
            matches = [item for item in items if item["info"]["controlType"] == "ListBoxItem"]
            if len(matches) == 4:
                item = matches[2]
                subqueue = [(item, [*chain, item])]
                while subqueue:
                    node, subchain = subqueue.pop(0)
                    if node["info"]["controlType"] == "TextBlock":
                        element = server.nodes[node["nodeId"]]
                        bounds = element.state().bounds
                        assert bounds is not None
                        hit = element.client.hit_test(
                            server.nodes[window["nodeId"]].native_window_handle,
                            int(bounds.x + bounds.width / 2),
                            int(bounds.y + bounds.height / 2),
                            include_path=True,
                            timeout_ms=2000,
                            deadline=time.monotonic() + 5,
                        )
                        assert hit is not None
                        assert [entry.object_ref.object_id for entry in hit.path[1:]] == [
                            server.nodes[part["nodeId"]].ref.object_id for part in subchain[1:]
                        ]
                        print(
                            "HIT",
                            [
                                (entry.object_ref.type.name, entry.object_ref.object_id)
                                for entry in hit.path
                            ]
                            if hit
                            else None,
                        )
                        before = children(parent)
                        print("BEFORE_PICK", [(n["info"]["name"], n["nodeId"]) for n in before])
                        result = rpc(
                            "inspect.properties",
                            {"nodeId": node["nodeId"], "includeAncestors": True},
                        )
                        after = children(parent)
                        print("AFTER_PICK", [(n["info"]["name"], n["nodeId"]) for n in after])
                        assert [n["nodeId"] for n in before] == [n["nodeId"] for n in after]
                        print(
                            "LOADED",
                            [
                                (n["info"]["controlType"], n["nodeId"], n.get("identity"))
                                for n in subchain
                            ],
                        )
                        print(
                            "ANCESTORS",
                            [
                                (n["info"]["controlType"], n["nodeId"], n.get("identity"))
                                for n in result["ancestors"]
                            ],
                        )
                        print(
                            "ITEMS",
                            [(n["info"]["name"], n["nodeId"], n.get("identity")) for n in matches],
                        )
                        assert [n["nodeId"] for n in result["ancestors"]] == [
                            n["nodeId"] for n in subchain[:-1]
                        ]
                        assert [n["info"]["name"] for n in matches] == [
                            "Alpha",
                            "Beta",
                            "Beta",
                            "Gamma",
                        ]
                        assert node["info"]["name"] == "Beta"
                        x = int(bounds.x + bounds.width / 2)
                        y = int(bounds.y + bounds.height / 2)
                        _fixture_scenario(pid, "closeWindow", 0)
                        _fixture_scenario(pid, "openDuplicateItems", 0)
                        fresh_window = next(
                            root
                            for root in rpc("inspect.roots", {})
                            if root["info"]["processId"] == pid
                            and root["info"]["name"] == "Duplicate items"
                        )
                        from wintestkit.uia import win32

                        fresh_element = server.nodes[fresh_window["nodeId"]]
                        old_rect = server.nodes[window["nodeId"]].rect
                        fresh_rect = fresh_element.rect
                        x += fresh_rect.left - old_rect.left
                        y += fresh_rect.top - old_rect.top
                        with pytest.MonkeyPatch.context() as patch:
                            patch.setattr(
                                win32,
                                "WindowFromPoint",
                                lambda point, hwnd=fresh_element.native_window_handle: hwnd,
                            )
                            picked = server._spy_resolve(  # pyright: ignore[reportPrivateUsage]
                                fresh_element, x, y, True, "visual"
                            )
                        assert picked.node is not None
                        picked_info = rpc(
                            "inspect.properties",
                            {"nodeId": picked.node["nodeId"], "includeAncestors": True},
                        )
                        panel = next(
                            ancestor
                            for ancestor in picked_info["ancestors"]
                            if ancestor["info"]["controlType"] == "VirtualizingStackPanel"
                        )
                        picked_item = next(
                            ancestor
                            for ancestor in picked_info["ancestors"]
                            if ancestor["info"]["controlType"] == "ListBoxItem"
                        )
                        pick_first = children(panel)
                        print("PICK_FIRST", [(n["info"]["name"], n["nodeId"]) for n in pick_first])
                        assert [n["info"]["name"] for n in pick_first] == [
                            "Alpha",
                            "Beta",
                            "Beta",
                            "Gamma",
                        ]
                        assert pick_first[2]["nodeId"] == picked_item["nodeId"]
                        main = next(
                            root
                            for root in rpc("inspect.roots", {})
                            if root["info"]["processId"] == pid
                            and root["info"]["name"] != "Duplicate items"
                        )
                        original_read = element.client.read
                        element.client.read = lambda *args, **kwargs: ((), "read")
                        try:
                            started = time.monotonic()
                            children(main)
                            baseline = time.monotonic() - started
                        finally:
                            element.client.read = original_read
                        started = time.monotonic()
                        main_children = children(main)
                        elapsed = time.monotonic() - started
                        print("MAIN_FIRST_PAGE_BASELINE", baseline, "WITH_TEXT", elapsed)
                        assert elapsed < baseline + 5.5
                        pending = list(main_children)
                        while pending:
                            current = pending.pop(0)
                            if current["info"]["controlType"] == "PasswordBox":
                                assert current["info"]["name"] == ""
                                break
                            if current["hasChildren"]:
                                pending.extend(children(current))
                        else:
                            pytest.fail("PasswordBox not found")
                        return
                    subqueue.extend((child, [*subchain, child]) for child in children(node))
                pytest.fail("TextBlock not found")
            queue.extend((child, [*chain, child]) for child in items if child["hasChildren"])
        pytest.fail("duplicate items not found")
    finally:
        _fixture_scenario(pid, "closeWindow", 0)
