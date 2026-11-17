"""Input-free root enumeration against an owned fixture process."""

import io
import os
import time
from typing import Any

import pytest
from test_wpf_query_gate_real import _fixture_scenario  # pyright: ignore[reportPrivateUsage]

from wintestkit.server import Server

pytest_plugins = ("test_wpf_query_gate_real",)
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.name != "nt" or os.environ.get("WTK_INSPECTOR_REAL") != "1",
        reason="requires owned Windows fixture",
    ),
]


def test_roots_track_second_window(owned: Any) -> None:
    scope, path = owned
    server = Server(io.BytesIO())
    server.dispatch("initialize", {"root": str(path)})
    server.app = scope.app
    pid = scope.app.main_window().process_id

    def roots() -> list[dict[str, Any]]:
        return server.dispatch("inspect.roots", {})

    first = roots()
    first_ids = {node["nodeId"] for node in first if node["info"]["processId"] == pid}
    assert first_ids
    window = next(node for node in first if node["nodeId"] in first_ids)
    children = server.dispatch("inspect.children", {"nodeId": window["nodeId"]})
    if isinstance(children, list) and children:
        server.dispatch("inspect.children", {"nodeId": children[0]["nodeId"]})
    assert any(
        node["info"]["processId"] == pid
        and node["info"]["processName"].lower() == "wintestkit.fixture.exe"
        for node in first
    )
    try:
        _fixture_scenario(pid, "openSecondWindow", 0)
        deadline = time.monotonic() + 10
        while True:
            current = roots()
            second = next(
                (node for node in current if node["info"]["automationId"] == "SecondWindow"), None
            )
            if second:
                break
            assert time.monotonic() < deadline
            time.sleep(0.1)
        assert first_ids <= {node["nodeId"] for node in current}
        second_id = second["nodeId"]
        assert second["info"]["processId"] == pid
        assert len([node for node in current if node["info"]["processId"] == pid]) >= 2
    finally:
        _fixture_scenario(pid, "closeWindow", 0)
    deadline = time.monotonic() + 10
    while any(node["info"]["automationId"] == "SecondWindow" for node in roots()):
        assert time.monotonic() < deadline
        time.sleep(0.1)

    final_ids = {node["nodeId"] for node in roots()}
    assert first_ids <= final_ids
    assert second_id not in final_ids


def test_managed_tree_survives_second_window(owned: Any) -> None:
    scope, path = owned
    server = Server(io.BytesIO())
    server.dispatch("initialize", {"root": str(path), "config": {"inspector.enabled": True}})
    server.app = scope.app
    pid = scope.app.main_window().process_id

    def fetch() -> list[list[tuple[str, Any]]]:
        roots = server.dispatch("inspect.roots", {})
        window = next(
            node
            for node in roots
            if node["info"]["processId"] == pid and node["info"]["automationId"] != "SecondWindow"
        )
        levels = []
        parent = window
        for expected in ("Border", "AdornerDecorator", None):
            result = server.dispatch(
                "inspect.children", {"nodeId": parent["nodeId"], "tree": "visual"}
            )
            if isinstance(result, dict) and "attachRequired" in result:
                server.dispatch("inspect.managed.attach", {"process": result["process"]})
                result = server.dispatch(
                    "inspect.children", {"nodeId": parent["nodeId"], "tree": "visual"}
                )
            assert (
                isinstance(result, dict) and "nodes" in result and not result.get("nextPageToken")
            ), result
            children = result["nodes"]
            levels.append([(child["nodeId"], child.get("identity")) for child in children])
            if expected:
                parent = next(
                    child for child in children if child["info"]["controlType"] == expected
                )
        return levels

    first = fetch()
    try:
        _fixture_scenario(pid, "openSecondWindow", 0)
        deadline = time.monotonic() + 10
        while not any(
            node["info"]["automationId"] == "SecondWindow"
            for node in server.dispatch("inspect.roots", {})
        ):
            assert time.monotonic() < deadline
            time.sleep(0.1)
        server.dispatch("inspect.refresh", {})
        second = fetch()
        assert first == second, f"managed child lists differ: before={first!r}; after={second!r}"
    finally:
        _fixture_scenario(pid, "closeWindow", 0)
