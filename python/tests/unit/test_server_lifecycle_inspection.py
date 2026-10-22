"""Picker epochs, EOF cleanup, and lazy external UIA inspection."""

import json
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from rpc_support import RpcElement, make_server, request

from wintestkit.engine import spy, suggest
from wintestkit.errors import UIAError
from wintestkit.uia import win32
from wintestkit.uia.constants import CONTROL_TYPES, TreeScope
from wintestkit.uia.element import (
    ElementEnumerationError,
    UIAElement,
    array_to_list,
    inspection_property,
)


class DescriptionRaw:
    def __init__(
        self,
        name: str,
        runtime_id: int,
        *,
        cached_only: bool = False,
        class_name: str = "",
        unavailable: bool = False,
    ) -> None:
        self.runtime_id = runtime_id
        self.cached_only = cached_only
        self.unavailable = unavailable
        self.description = {
            "AutomationId": "",
            "Name": name,
            "ControlType": CONTROL_TYPES["Window"],
            "ClassName": class_name,
            "FrameworkId": "WPF",
            "ProcessId": 2,
            "BoundingRectangle": SimpleNamespace(left=0, top=0, right=10, bottom=10),
            "IsEnabled": True,
            "IsOffscreen": False,
            "HasKeyboardFocus": False,
        }

    def __getattr__(self, attribute: str) -> Any:
        if attribute.startswith("Current"):
            assert not self.cached_only, "cached descriptions must not read Current properties"
            attribute = attribute.removeprefix("Current")
        elif attribute.startswith("Cached"):
            attribute = attribute.removeprefix("Cached")
        else:
            raise AttributeError(attribute)
        if attribute == "Name" and self.unavailable:
            raise RuntimeError("description unavailable")
        return self.description[attribute]

    def GetRuntimeId(self) -> list[int]:
        return [2, self.runtime_id]

    def FindFirst(self, scope: Any, condition: Any) -> None:
        return None


class CapturedSpy:
    def __init__(self, hover: Any, pick: Any, cancel: Any, process_filter: Any) -> None:
        self.hover, self.pick, self.cancel = hover, pick, cancel
        self.stopped = False

    def start(self) -> None:
        pass

    def stop(self) -> None:
        self.stopped = True


@pytest.mark.parametrize("session_id", [None, "picker-2"])
def test_picker_identity_and_epoch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, session_id: str | None
) -> None:
    server, output, button = make_server(tmp_path, monkeypatch)
    request(server, output, "initialize", {"root": str(tmp_path)})
    monkeypatch.setattr(spy, "SpySession", CapturedSpy)

    def no_suggestion(*args: Any) -> Any:
        pytest.fail("picking must not generate a locator")

    monkeypatch.setattr(suggest, "suggest_locator", no_suggestion)
    params = {} if session_id is None else {"sessionId": session_id}
    assert request(server, output, "spy.start", params)["result"] is None
    first = server.spy
    first.hover(button)
    first.pick(button)
    first.cancel()
    messages = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [message["method"] for message in messages] == [
        "spy.hover",
        "spy.picked",
        "spy.cancelled",
    ]
    for message in messages:
        assert ("sessionId" in message["params"]) == (session_id is not None)
        if session_id is not None:
            assert message["params"]["sessionId"] == session_id
        assert "suggestion" not in message["params"]
    output.seek(0)
    output.truncate()
    request(server, output, "spy.start", {"sessionId": "replacement"})
    replacement = server.spy
    first.hover(button)
    first.pick(button)
    first.cancel()
    assert output.getvalue() == b""
    assert server.spy is replacement
    assert not replacement.stopped
    server.stop_spy()


@pytest.mark.parametrize("value", ["", None, 1, False])
def test_session_id_must_be_nonempty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: Any
) -> None:
    server, output, _ = make_server(tmp_path, monkeypatch)
    request(server, output, "initialize", {"root": str(tmp_path)})
    assert request(server, output, "spy.start", {"sessionId": value})["error"]["code"] == -32602


def test_eof_stops_picker_before_waiting_without_cancelling_other_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, output, _ = make_server(tmp_path, monkeypatch)
    request(server, output, "initialize", {"root": str(tmp_path)})
    entered = threading.Event()
    released = threading.Event()
    original = server.dispatch

    class ReleasingSpy:
        def stop(self) -> None:
            released.set()

    server.spy = ReleasingSpy()

    def dispatch(method: str, params: Any, epoch: Any = None) -> Any:
        if method == "app.status":
            entered.set()
            assert released.wait(2), "EOF must clean up before waiting for the worker"
        return original(method, params, epoch)

    monkeypatch.setattr(server, "dispatch", dispatch)

    class Input:
        def __iter__(self) -> Any:
            yield b'{"jsonrpc":"2.0","id":1,"method":"app.status"}\n'
            assert entered.wait(2)
            yield b'{"jsonrpc":"2.0","id":2,"method":"discover"}\n'

    assert server.serve(Input()) == 0
    responses = [json.loads(line) for line in output.getvalue().splitlines()]
    assert {response["id"] for response in responses if "result" in response} == {1, 2}


def test_callback_blocked_in_registration_cannot_publish_after_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, output, button = make_server(tmp_path, monkeypatch)
    request(server, output, "initialize", {"root": str(tmp_path)})
    monkeypatch.setattr(spy, "SpySession", CapturedSpy)
    request(server, output, "spy.start")
    first = server.spy
    entered = threading.Event()
    released = threading.Event()
    original = server._register

    def register(element: Any, *args: Any, **kwargs: Any) -> Any:
        entered.set()
        assert released.wait(2)
        return original(element, *args, **kwargs)

    monkeypatch.setattr(server, "_register", register)
    worker = threading.Thread(target=first.pick, args=(button,))
    worker.start()
    try:
        assert entered.wait(2)
        server.stop_spy()
    finally:
        released.set()
        worker.join(2)
    assert not worker.is_alive()
    assert output.getvalue() == b""


def test_refresh_shares_one_window_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, output, _ = make_server(tmp_path, monkeypatch)
    request(server, output, "initialize", {"root": str(tmp_path)})
    app = server.app
    windows = app.top_level_windows()
    calls: list[bool] = []

    def top_level_windows() -> Any:
        calls.append(True)
        assert len(calls) == 1
        return windows

    def no_main_window(*args: Any) -> Any:
        pytest.fail("refresh must not independently re-enumerate the main window")

    monkeypatch.setattr(app, "top_level_windows", top_level_windows)
    monkeypatch.setattr(app, "main_window", no_main_window)
    monkeypatch.setattr(win32, "window_owner", lambda hwnd: 0)
    result = request(server, output, "inspect.refresh")["result"]
    assert result["status"] == {
        "running": True,
        "pids": [1],
        "owned": False,
        "mainWindowTitle": "Demo",
    }
    assert result["nodes"][0]["info"]["name"] == "Demo"
    assert calls == [True]


@pytest.mark.parametrize("method", ["inspect.roots", "inspect.refresh", "inspect.children"])
def test_stale_sibling_preserves_partial_nodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    server, output, button = make_server(tmp_path, monkeypatch)
    request(server, output, "initialize", {"root": str(tmp_path)})
    selected = server._register(button)
    stale = RpcElement("Button", "stale")
    last = RpcElement("Button", "last")

    def unavailable(*args: Any) -> Any:
        raise RuntimeError("stale sibling")

    monkeypatch.setattr(stale, "info", unavailable)
    siblings = [button, stale, last]

    def children(scope: Any, condition: Any = None, cached: bool = False) -> Any:
        assert scope == TreeScope.Children
        return siblings if cached else []

    monkeypatch.setattr(button, "find_all", children)
    monkeypatch.setattr(server.app, "top_level_windows", lambda: siblings)
    response = request(
        server,
        output,
        method,
        {"nodeId": selected["nodeId"]} if method == "inspect.children" else {},
    )
    error = response["error"]
    assert error["code"] == -32005
    assert error["data"]["complete"] is False
    assert [node["info"]["name"] for node in error["data"]["nodes"]] == ["OK", "last"]
    assert error["data"]["errors"] == [{"index": 1, "message": "stale sibling"}]


def test_children_without_a_runtime_id_are_keyed_by_their_place_under_the_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, output, button = make_server(tmp_path, monkeypatch)
    request(server, output, "initialize", {"root": str(tmp_path)})
    parent = server._register(button)
    anonymous = RpcElement("Pane", "custom content")
    anonymous.runtime_id = ""  # TeamViewer's custom-drawn content reports an empty runtime id
    named = RpcElement("Button", "named")
    siblings = [named, anonymous]
    monkeypatch.setattr(button, "find_all", lambda *args, **kwargs: siblings)
    first = request(server, output, "inspect.children", {"nodeId": parent["nodeId"]})["result"]
    second = request(server, output, "inspect.children", {"nodeId": parent["nodeId"]})["result"]
    anonymous_id = f"{parent['nodeId']}~1"
    assert [node["nodeId"] for node in first] == [named.runtime_id, anonymous_id]
    assert [node["nodeId"] for node in second] == [named.runtime_id, anonymous_id]
    assert first[1]["info"]["runtimeId"] == anonymous_id
    assert server.nodes[anonymous_id] is anonymous
    # The key reaches the element again, so the node can be expanded and inspected.
    properties = request(server, output, "inspect.properties", {"nodeId": anonymous_id})
    assert properties["result"]["info"]["name"] == "custom content"


def test_a_root_without_a_runtime_id_is_still_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, output, _button = make_server(tmp_path, monkeypatch)
    request(server, output, "initialize", {"root": str(tmp_path)})
    assert server.app is not None
    server.app.windows[0].runtime_id = ""  # type: ignore[attr-defined]
    error = request(server, output, "inspect.roots")["error"]
    assert error["data"]["errors"] == [{"index": 0, "message": "element has no runtime id"}]


def test_com_array_retains_successful_sibling_slots() -> None:
    class Array:
        Length = 3

        def GetElement(self, index: int) -> Any:
            if index == 1:
                raise RuntimeError("closed during enumeration")
            return object()

    with pytest.raises(ElementEnumerationError) as caught:
        array_to_list(Array(), cached=True)
    assert len(caught.value.elements) == 3
    assert caught.value.elements[1] is None
    assert caught.value.errors == [{"index": 1, "message": "closed during enumeration"}]


@pytest.mark.parametrize("method", ["inspect.roots", "inspect.refresh"])
@pytest.mark.parametrize("attached", [False, True])
def test_desktop_roots_report_unavailable_windows_by_source_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, method: str, attached: bool
) -> None:
    server, output, _ = make_server(tmp_path, monkeypatch)
    request(server, output, "initialize", {"root": str(tmp_path)})
    if not attached:
        monkeypatch.setattr(server, "_app", lambda required=True: None)
    windows = {
        100: DescriptionRaw("popup", 0, class_name="Xaml_WindowedPopupClass"),
        101: None,  # closed while the desktop was listed
        102: DescriptionRaw("survivor", 2),
        103: DescriptionRaw("stale", 3, unavailable=True),
        104: DescriptionRaw("last", 5),
    }

    def from_handle(hwnd: int) -> UIAElement:
        raw = windows[hwnd]
        if raw is None:
            raise UIAError("The UI element is no longer available", element_gone=True)
        return UIAElement(raw)

    monkeypatch.setattr("wintestkit.uia.win32.desktop_windows", lambda: list(windows))
    monkeypatch.setattr("wintestkit.uia.element.from_handle", from_handle)
    params = {"includeOtherApps": True} if attached else {}
    error = request(server, output, method, params)["error"]
    assert error["code"] == -32005
    data = error["data"]
    assert data["complete"] is False
    assert [node["info"]["name"] for node in data["nodes"]] == (
        (["Demo"] if attached else []) + ["survivor", "last"]
    )
    # The closed window is skipped quietly; the index counts only the windows that were listed.
    assert data["errors"] == [{"index": 2, "message": "description unavailable"}]
    assert all(node["nodeId"] in server.nodes for node in data["nodes"])


def test_children_reenumerate_fresh_build_cache_descriptions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, output, button = make_server(tmp_path, monkeypatch)
    request(server, output, "initialize", {"root": str(tmp_path)})
    selected = server._register(button)
    cache_request = object()
    snapshots: list[DescriptionRaw] = []

    class Array:
        Length = 1

        def __init__(self, child: DescriptionRaw) -> None:
            self.child = child

        def GetElement(self, index: int) -> DescriptionRaw:
            assert index == 0
            return self.child

    class Parent:
        def FindAllBuildCache(self, scope: int, condition: Any, cache: Any) -> Any:
            assert scope == int(TreeScope.Children)
            assert cache is cache_request
            child = DescriptionRaw(
                f"snapshot {len(snapshots)}", len(snapshots) + 10, cached_only=True
            )
            snapshots.append(child)
            return Array(child)

        def FindAll(self, scope: Any, condition: Any) -> Any:
            pytest.fail("fresh children must use FindAllBuildCache")

    parent = UIAElement(Parent())
    monkeypatch.setattr(button, "as_live", lambda: parent)
    monkeypatch.setattr("wintestkit.uia.element._get_cache_request", lambda: cache_request)
    monkeypatch.setattr("wintestkit.uia.element._control_view_condition", lambda condition: None)
    params = {"nodeId": selected["nodeId"]}
    first = request(server, output, "inspect.children", params)["result"]
    second = request(server, output, "inspect.children", params)["result"]
    assert len(snapshots) == 2
    assert [node["info"]["name"] for node in first] == ["snapshot 0"]
    assert [node["info"]["name"] for node in second] == ["snapshot 1"]
    assert first[0]["nodeId"] != second[0]["nodeId"]
    assert server.nodes[first[0]["nodeId"]].raw is snapshots[0]
    assert server.nodes[second[0]["nodeId"]].raw is snapshots[1]


def test_inspection_is_bounded_and_does_not_reflect_objects() -> None:
    class Opaque:
        def __str__(self) -> str:
            pytest.fail("opaque UIA objects must not be stringified")

        @property
        def dangerous(self) -> Any:
            pytest.fail("arbitrary object members must not be read")

    result = inspection_property("UIA", [Opaque(), list(range(100)), "x" * 5000])
    opaque, array, string = result["children"]
    assert opaque["kind"] == "object"
    assert "children" not in opaque
    assert len(array["children"]) == 32
    assert len(string["value"]) == 4096
    assert inspection_property("bad", float("nan"))["kind"] == "unavailable"
    nested = inspection_property("nested", [[[1]]])
    assert "children" not in nested["children"][0]["children"][0]


def test_full_properties_report_unavailable_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, output, button = make_server(tmp_path, monkeypatch)
    request(server, output, "initialize", {"root": str(tmp_path)})
    node = server._register(button)
    original = button.get_property

    def get_property(name: str) -> Any:
        if name == "Name":
            raise RuntimeError("provider refused property")
        return original(name)

    monkeypatch.setattr(button, "get_property", get_property)
    result = request(
        server, output, "inspect.properties", {"nodeId": node["nodeId"], "full": True}
    )["result"]
    name = next(prop for prop in result["inspection"] if prop["name"] == "Name")
    assert name["kind"] == "unavailable"
    assert name["status"] == "provider refused property"
    assert "Name" not in result["properties"]


def test_stopped_spy_worker_drops_callbacks() -> None:
    calls: list[bool] = []
    session = spy.SpySession(lambda element: None, lambda element: None, lambda: None)
    session._stop.set()
    session._callback(lambda: calls.append(True))
    assert calls == []
