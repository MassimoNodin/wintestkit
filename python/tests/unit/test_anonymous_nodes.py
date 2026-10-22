"""Elements whose provider reports no runtime id (TeamViewer's content) can still be picked."""

import json
from pathlib import Path
from typing import Any

import pytest
from rpc_support import RpcElement, make_server, request

from wintestkit.engine import spy
from wintestkit.server import RpcError, Server


class CapturedSpy:
    def __init__(self, hover: Any, pick: Any, cancel: Any, process_filter: Any) -> None:
        self.hover, self.pick, self.cancel = hover, pick, cancel

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


def anonymous(control_type: str, name: str = "", *children: RpcElement) -> RpcElement:
    element = RpcElement(control_type, name, children=list(children))
    element.runtime_id = ""
    return element


@pytest.fixture
def started(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Server, Any, Any]:
    server, output, _button = make_server(tmp_path, monkeypatch)
    request(server, output, "initialize", {"root": str(tmp_path)})
    monkeypatch.setattr(spy, "SpySession", CapturedSpy)
    request(server, output, "spy.start")
    return server, output, server.spy


def notifications(output: Any, method: str) -> list[dict[str, Any]]:
    messages = [json.loads(line) for line in output.getvalue().splitlines()]
    return [message["params"] for message in messages if message.get("method") == method]


def build() -> tuple[RpcElement, RpcElement, RpcElement, RpcElement]:
    first, second, third = (anonymous("Text", name) for name in ("one", "two", "three"))
    panel = anonymous("Pane", "", first, second, third)
    window = RpcElement("Window", "App", children=[panel])
    return window, panel, second, third


def test_picked_element_without_an_id_gets_the_key_tree_expansion_uses(
    started: tuple[Server, Any, Any],
) -> None:
    server, output, session = started
    window, _panel, second, _third = build()
    session.pick(second)
    picked = notifications(output, "spy.picked")[0]["node"]
    assert picked["nodeId"] == f"{window.runtime_id}~0~1"
    assert picked["info"]["runtimeId"] == picked["nodeId"]
    assert server.nodes[picked["nodeId"]] is second
    # Expanding the same part of the tree writes the same keys.
    root = server._register(window)
    [panel_node] = request(server, output, "inspect.children", {"nodeId": root["nodeId"]})["result"]
    children = request(server, output, "inspect.children", {"nodeId": panel_node["nodeId"]})
    assert [node["nodeId"] for node in children["result"]][1] == picked["nodeId"]
    assert panel_node["nodeId"] == f"{window.runtime_id}~0"


def test_siblings_are_told_apart_by_properties_when_comparison_cannot(
    started: tuple[Server, Any, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    server, output, session = started
    window, panel, _second, third = build()
    # CompareElements calls every sibling equal, as it does for a hidden menu's items.
    for element in (*panel.children_list, panel):
        monkeypatch.setattr(element, "same_as", lambda other: True)
    session.pick(third)
    assert notifications(output, "spy.picked")[0]["node"]["nodeId"] == f"{window.runtime_id}~0~2"
    assert server.nodes[f"{window.runtime_id}~0~2"] is third


def test_ancestors_of_a_picked_element_use_keys_the_tree_holds(
    started: tuple[Server, Any, Any],
) -> None:
    server, output, session = started
    window, _panel, second, _third = build()
    session.pick(second)
    node_id = notifications(output, "spy.picked")[0]["node"]["nodeId"]
    result = request(
        server, output, "inspect.properties", {"nodeId": node_id, "includeAncestors": True}
    )["result"]
    assert [ancestor["nodeId"] for ancestor in result["ancestors"]] == [
        window.runtime_id,
        f"{window.runtime_id}~0",
    ]
    assert result["info"]["runtimeId"] == node_id


def test_hover_over_such_an_element_skips_the_slow_lookup(
    started: tuple[Server, Any, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    server, output, session = started

    def forbidden(self: Server, element: Any) -> str:
        raise AssertionError("hovering must not search for the element's place")

    monkeypatch.setattr(Server, "_positional_id", forbidden)
    _window, _panel, second, _third = build()
    before = dict(server.nodes)
    session.hover(second)
    hovered = notifications(output, "spy.hover")[0]["node"]
    assert hovered["nodeId"] == ""
    assert hovered["info"]["name"] == "two"
    assert server.nodes == before


def test_an_element_that_cannot_be_placed_is_still_reported(
    started: tuple[Server, Any, Any],
) -> None:
    _server, _output, session = started
    orphan = anonymous("Text", "alone")  # no parent: nothing to key it under
    with pytest.raises(RpcError, match="no runtime id"):
        session.pick(orphan)


def test_elements_with_ids_are_unaffected(started: tuple[Server, Any, Any]) -> None:
    _server, output, session = started
    button = RpcElement("Button", "OK")
    session.pick(button)
    assert notifications(output, "spy.picked")[0]["node"]["nodeId"] == button.runtime_id
