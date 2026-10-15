"""JSON-RPC method mapping, validation, errors, transport and shutdown."""

import io
import json
import logging
import threading
from pathlib import Path
from typing import Any

import pytest
from rpc_support import make_server, request

from wintestkit.engine import actions, overlay
from wintestkit.errors import AppNotRunningError, EnvironmentNotReadyError
from wintestkit.targets import TargetError
from wintestkit.uia.element import Rect


def test_methods_and_nodes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    server, output, button = make_server(tmp_path, monkeypatch)
    assert request(server, output, "discover")["error"]["message"] == "not initialized"
    assert (
        request(server, output, "initialize", {"root": str(tmp_path)})["result"]["protocolVersion"]
        == 1
    )
    assert request(server, output, "app.status")["result"]["running"]
    assert request(server, output, "app.launch")["result"]["pids"] == [1]
    assert request(server, output, "discover")["result"]["screens"]
    assert (
        request(
            server,
            output,
            "element.highlight",
            {"file": "screen.py", "qualname": "Main.ok", "durationMs": 0},
        )["result"]["status"]
        == "found"
    )
    assert (
        request(server, output, "screen.check", {"file": "screen.py", "screen": "Main"})["result"][
            "results"
        ][0]["status"]
        == "found"
    )
    root = request(server, output, "inspect.roots")["result"][0]
    assert root["hasChildren"]
    child = request(server, output, "inspect.children", {"nodeId": root["nodeId"]})["result"][0]
    assert child["nodeId"] == button.runtime_id
    params = {"nodeId": child["nodeId"]}
    properties = request(server, output, "inspect.properties", params)["result"]
    assert properties["properties"]["Name"] == "OK"
    assert properties["ancestors"][0]["info"]["name"] == "Demo"
    assert request(server, output, "inspect.highlight", params)["result"] is None
    assert request(server, output, "suggest.locator", params)["result"]["strategy"] == "name"
    assert (
        request(server, output, "inspect.children", {"nodeId": "stale"})["error"]["code"] == -32005
    )
    assert request(server, output, "initialize", {"root": str(tmp_path)})["error"]["code"] == -32600


@pytest.mark.parametrize("activated", [True, False])
def test_highlight_raises_window_before_reading_bounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, activated: bool
) -> None:
    server, output, button = make_server(tmp_path, monkeypatch)
    request(server, output, "initialize", {"root": str(tmp_path)})
    node = server._register(button)
    button.rect = None
    calls: list[str] = []
    restored_rect = Rect(20, 30, 100, 50)

    def foreground(element: Any) -> bool:
        assert element is button
        calls.append("foreground")
        button.rect = restored_rect
        return activated

    def flash(rect: Rect, duration: int, *, block: bool) -> None:
        assert rect == restored_rect
        assert duration == 800
        assert not block
        calls.append("highlight")

    monkeypatch.setattr(actions, "bring_to_front", foreground)
    monkeypatch.setattr(overlay, "flash", flash)
    assert (
        request(server, output, "inspect.highlight", {"nodeId": node["nodeId"], "durationMs": 800})[
            "result"
        ]
        is None
    )
    assert calls == ["foreground", "highlight"]


@pytest.mark.parametrize(
    "method,params",
    [
        ("unknown", {}),
        ("discover", {"overrides": []}),
        ("discover", {"overrides": {"file": 1}}),
        ("inspect.children", {}),
        ("inspect.highlight", {"nodeId": "x", "durationMs": -1}),
        ("inspect.highlight", {"nodeId": "x", "durationMs": True}),
        ("inspect.highlight", {"nodeId": "x", "durationMs": float("nan")}),
        ("app.status", {"extra": 1}),
        ("app.status", []),
    ],
)
def test_invalid_params(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, method: str, params: Any
) -> None:
    server, output, _ = make_server(tmp_path, monkeypatch)
    request(server, output, "initialize", {"root": str(tmp_path)})
    assert request(server, output, method, params)["error"]["code"] == (
        -32601 if method == "unknown" else -32602
    )


@pytest.mark.parametrize(
    "exception,code",
    [
        (AppNotRunningError("absent"), -32002),
        (TargetError("bad target"), -32003),
        (EnvironmentNotReadyError("locked"), -32004),
        (RuntimeError("oops"), -32603),
    ],
)
def test_error_mapping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exception: Exception, code: int
) -> None:
    server, output, _ = make_server(tmp_path, monkeypatch)
    request(server, output, "initialize", {"root": str(tmp_path)})

    def fail(*args: Any) -> None:
        raise exception

    monkeypatch.setattr(server, "dispatch", fail)
    assert request(server, output, "app.status")["error"]["code"] == code


def test_transport_eof_order_and_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    server, output, _ = make_server(tmp_path, monkeypatch)
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"root": str(tmp_path)}},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "element.highlight",
            "params": {"file": "screen.py", "qualname": "Main.ok"},
        },
        {"jsonrpc": "2.0", "method": "app.status"},
        None,
        {"jsonrpc": "2.0", "id": 3, "method": "app.status"},
    ]
    source = io.BytesIO(
        b"invalid\n" + b"".join((json.dumps(message) + "\n").encode() for message in messages)
    )
    assert server.serve(source) == 0
    responses = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [response["id"] for response in responses if response.get("id") is not None] == [1, 2, 3]
    assert sorted(response["error"]["code"] for response in responses if "error" in response) == [
        -32700,
        -32600,
    ]
    assert "user module print" in capsys.readouterr().err


def test_spy_notifications_and_shutdown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from wintestkit.engine import spy

    server, output, button = make_server(tmp_path, monkeypatch)
    request(server, output, "initialize", {"root": str(tmp_path)})
    stopped: list[bool] = []

    class FakeSpy:
        def __init__(self, hover: Any, pick: Any, cancel: Any, process_filter: Any) -> None:
            self.hover, self.pick, self.cancel = hover, pick, cancel

        def start(self) -> None:
            self.hover(button)
            self.pick(button)

        def stop(self) -> None:
            stopped.append(True)

    monkeypatch.setattr(spy, "SpySession", FakeSpy)
    server.handle({"jsonrpc": "2.0", "id": 1, "method": "spy.start"})
    messages = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [message["method"] for message in messages if "method" in message] == [
        "spy.hover",
        "spy.picked",
    ]
    output.seek(0)
    output.truncate()
    assert request(server, output, "spy.stop")["result"] is None
    assert stopped == [True]
    assert request(server, output, "shutdown")["result"] is None


def test_lru_and_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from wintestkit.server import _LogForwarder

    server, output, button = make_server(tmp_path, monkeypatch)
    for index in range(5001):
        button.runtime_id = str(index)
        server._register(button)
    assert len(server.nodes) == 5000
    assert "0" not in server.nodes
    record = logging.LogRecord("wintestkit", logging.WARNING, "", 0, "hello", (), None)
    _LogForwarder(server).emit(record)
    assert json.loads(output.getvalue())["params"] == {"level": "warning", "message": "hello"}


def test_stop_bypasses_busy_worker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    server, output, _ = make_server(tmp_path, monkeypatch)
    request(server, output, "initialize", {"root": str(tmp_path)})
    entered = threading.Event()
    release = threading.Event()
    original = server.dispatch

    def dispatch(method: str, params: Any, epoch: Any = None) -> Any:
        if method == "app.status":
            entered.set()
            assert release.wait(2)
        if method == "spy.stop":
            assert entered.is_set()
            release.set()
        return original(method, params, epoch)

    monkeypatch.setattr(server, "dispatch", dispatch)

    class Input:
        def __iter__(self) -> Any:
            yield b'{"jsonrpc":"2.0","id":1,"method":"app.status"}\n'
            assert entered.wait(2)
            yield b'{"jsonrpc":"2.0","id":2,"method":"spy.stop"}\n'

    assert server.serve(Input()) == 0
    assert release.is_set()
    assert {json.loads(line)["id"] for line in output.getvalue().splitlines()} == {1, 2}


def test_config_errors_and_notifications(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    server, output, _ = make_server(tmp_path, monkeypatch)
    (tmp_path / "pyproject.toml").write_text("[tool.wintestkit]\ntimeout = -1\n", encoding="utf-8")
    assert request(server, output, "initialize", {"root": str(tmp_path)})["error"]["code"] == -32001
    assert server.cfg is None
    server.handle({"jsonrpc": "2.0", "method": "unknown"})
    assert not output.getvalue()
