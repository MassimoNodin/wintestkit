"""JSON-RPC method mapping, validation, errors, transport and shutdown."""

import io
import json
import logging
import threading
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeApp
from rpc_support import RpcElement, make_server, request

from wintestkit.engine import actions, overlay
from wintestkit.errors import AppNotRunningError, EnvironmentNotReadyError, WtkError
from wintestkit.targets import TargetError
from wintestkit.uia.element import Rect


def test_app_status_survives_an_app_without_a_main_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, output, _ = make_server(tmp_path, monkeypatch)
    request(server, output, "initialize", {"root": str(tmp_path)})

    def no_window(timeout: float = 0.0) -> None:
        raise WtkError("No window matches Window for CalculatorApp.exe (open windows: none)")

    assert server.app is not None
    monkeypatch.setattr(server.app, "main_window", no_window, raising=False)
    assert request(server, output, "app.status")["result"] == {
        "running": True,
        "pids": [1],
        "owned": False,
    }


def test_app_status_only_claims_unchanged_server_owned_pids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, output, _ = make_server(tmp_path, monkeypatch)
    request(server, output, "initialize", {"root": str(tmp_path)})
    server._owned_app_pids = {1}
    assert request(server, output, "app.status")["result"]["owned"] is True

    monkeypatch.setattr(FakeApp, "pids", property(lambda self: [2]))
    result = request(server, output, "app.status")["result"]
    assert result == {
        "running": True,
        "pids": [2],
        "owned": False,
        "mainWindowTitle": "Demo",
    }
    assert server._owned_app_pids is None


def test_app_launch_owns_only_the_process_it_started(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from wintestkit.app import App

    server, output, _ = make_server(tmp_path, monkeypatch)
    request(server, output, "initialize", {"root": str(tmp_path)})
    app = server.app
    server.app = None

    def not_running(*, process: str | None = None) -> Any:
        raise AppNotRunningError("not running")

    with monkeypatch.context() as patch:
        patch.setattr(App, "attach", not_running)
        patch.setattr(
            "wintestkit.pytest_plugin.launch_app",
            lambda config, progress=None: app,
        )
        request(server, output, "app.launch")
        status = request(server, output, "app.status")["result"]
    assert status == {
        "running": True,
        "pids": [1],
        "owned": True,
        "mainWindowTitle": "Demo",
    }


def test_server_auto_attach_is_always_unowned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from wintestkit.app import App

    server, output, _ = make_server(tmp_path, monkeypatch)
    request(server, output, "initialize", {"root": str(tmp_path)})
    app = server.app
    server.app = None
    with monkeypatch.context() as patch:
        patch.setattr(App, "attach", lambda *, process=None: app)
        status = request(server, output, "app.status")["result"]
    assert status == {
        "running": True,
        "pids": [1],
        "owned": False,
        "mainWindowTitle": "Demo",
    }


def test_methods_and_nodes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    server, output, button = make_server(tmp_path, monkeypatch)
    assert request(server, output, "discover")["error"]["message"] == "not initialized"
    assert (
        request(server, output, "initialize", {"root": str(tmp_path)})["result"]["protocolVersion"]
        == 1
    )
    assert request(server, output, "app.status")["result"]["running"]
    assert request(server, output, "app.launch")["result"]["pids"] == [1]
    assert request(server, output, "discover")["result"]["pages"]
    assert (
        request(
            server,
            output,
            "element.highlight",
            {"file": "page.py", "qualname": "Main.ok", "durationMs": 0},
        )["result"]["status"]
        == "found"
    )
    assert (
        request(server, output, "page.check", {"file": "page.py", "page": "Main"})["result"][
            "results"
        ][0]["status"]
        == "found"
    )
    root = request(server, output, "inspect.roots")["result"][0]
    assert root["hasChildren"]
    child = request(server, output, "inspect.children", {"nodeId": root["nodeId"]})["result"][0]
    assert child["nodeId"] == button.runtime_id
    params = {"nodeId": child["nodeId"]}
    properties = request(
        server, output, "inspect.properties", {**params, "full": True, "includeAncestors": True}
    )["result"]
    assert properties["properties"]["Name"] == "OK"
    assert properties["ancestors"][0]["info"]["name"] == "Demo"
    assert request(server, output, "inspect.highlight", params)["result"] is None
    assert request(server, output, "suggest.locator", params)["result"]["strategy"] == "name"
    window_error = request(server, output, "suggest.locator", {"nodeId": root["nodeId"]})["error"]
    assert window_error["code"] == -32006
    assert "window descendant" in window_error["message"]
    assert (
        request(server, output, "inspect.children", {"nodeId": "stale"})["error"]["code"] == -32005
    )
    assert request(server, output, "initialize", {"root": str(tmp_path)})["error"]["code"] == -32600


def test_app_launch_reports_its_stages_while_starting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, output, _button = make_server(tmp_path, monkeypatch)
    request(server, output, "initialize", {"root": str(tmp_path)})
    server.app = None  # nothing is running yet, so app.launch has to start the app
    started = FakeApp([])

    def launch(config: Any, progress: Any = None) -> FakeApp:
        progress("process")
        progress("window")
        return started

    monkeypatch.setattr("wintestkit.pytest_plugin.launch_app", launch)

    def not_running(**kwargs: Any) -> None:
        raise AppNotRunningError("not running")

    monkeypatch.setattr("wintestkit.app.App.attach", staticmethod(not_running))
    server.handle({"jsonrpc": "2.0", "id": 1, "method": "app.launch", "params": {}})
    messages = [json.loads(line) for line in output.getvalue().splitlines()]
    stages = [m["params"]["stage"] for m in messages if m.get("method") == "app.starting"]
    assert stages == ["process", "window"]
    assert server.app is started


def test_app_processes_lists_the_running_apps_with_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, output, _button = make_server(tmp_path, monkeypatch)
    request(server, output, "initialize", {"root": str(tmp_path)})
    monkeypatch.setattr(
        "wintestkit.uia.win32.windowed_processes",
        lambda: [("CalculatorApp.exe", [38000], "Calculator"), ("code.exe", [7, 9], "Code")],
    )
    assert request(server, output, "app.processes")["result"] == {
        "processes": [
            {"name": "CalculatorApp.exe", "pids": [38000], "windowTitle": "Calculator"},
            {"name": "code.exe", "pids": [7, 9], "windowTitle": "Code"},
        ]
    }


def test_tutorial_roots_use_only_the_verified_host_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, output, _ = make_server(tmp_path, monkeypatch)
    request(server, output, "initialize", {"root": str(tmp_path)})
    host = RpcElement("Window", "Any workspace - Visual Studio Code")
    monkeypatch.setattr(
        "wintestkit.uia.win32.foreground_window_for_process",
        lambda pid: 123 if pid == 456 else None,
    )
    monkeypatch.setattr("wintestkit.uia.element.from_handle", lambda hwnd: host)
    roots = request(server, output, "inspect.roots", {"foregroundForProcessId": 456})["result"]
    assert [node["info"]["name"] for node in roots] == [host.name]
    error = request(server, output, "inspect.roots", {"foregroundForProcessId": 789})["error"]
    assert "Focus the VS Code window" in error["message"]


@pytest.mark.parametrize("pid", [True, False, 0, -1, "123", 1.5, None])
def test_tutorial_roots_validate_host_process_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pid: object
) -> None:
    server, output, _ = make_server(tmp_path, monkeypatch)
    request(server, output, "initialize", {"root": str(tmp_path)})
    result = request(server, output, "inspect.roots", {"foregroundForProcessId": pid})
    assert result["error"]["code"] == -32602


@pytest.mark.parametrize("method", ["inspect.roots", "inspect.refresh"])
def test_roots_include_other_apps_only_when_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    server, output, _button = make_server(tmp_path, monkeypatch)
    request(server, output, "initialize", {"root": str(tmp_path)})
    assert server.app is not None
    window = server.app.windows[0]  # type: ignore[attr-defined]
    other = RpcElement("Window", "Notepad")
    other.process_id = 2
    owned = RpcElement("Window", "Owned dialog")
    owned.process_id = 1
    desktop_reads = 0
    handles = {10: window, 11: owned, 12: other}

    def desktop_windows() -> list[int]:
        nonlocal desktop_reads
        desktop_reads += 1
        return list(handles)

    monkeypatch.setattr("wintestkit.uia.win32.desktop_windows", desktop_windows)
    monkeypatch.setattr("wintestkit.uia.element.from_handle", lambda hwnd: handles[hwnd])

    def roots(params: Any = None) -> Any:
        result = request(server, output, method, params)["result"]
        if method == "inspect.refresh":
            assert set(result) == {"nodes", "status"}
            assert result["status"]["running"] is True
            return result["nodes"]
        assert isinstance(result, list)
        return result

    scoped = roots()
    assert [node["info"]["name"] for node in scoped] == ["Demo"]
    assert desktop_reads == 0
    widened = roots({"includeOtherApps": True})
    assert [node["info"]["name"] for node in widened] == ["Demo", "Notepad"]
    assert desktop_reads == 1
    restored = roots({"includeOtherApps": False})
    assert [node["info"]["name"] for node in restored] == ["Demo"]
    assert desktop_reads == 1


def test_roots_skip_a_window_that_closes_while_listing_the_desktop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from wintestkit.errors import UIAError

    server, output, _button = make_server(tmp_path, monkeypatch)
    request(server, output, "initialize", {"root": str(tmp_path)})
    other = RpcElement("Window", "Notepad")
    other.process_id = 2

    def from_handle(hwnd: int) -> Any:
        if hwnd == 11:
            raise UIAError("The UI element is no longer available", element_gone=True)
        return other

    monkeypatch.setattr("wintestkit.uia.win32.desktop_windows", lambda: [11, 12])
    monkeypatch.setattr("wintestkit.uia.element.from_handle", from_handle)
    response = request(server, output, "inspect.roots", {"includeOtherApps": True})
    assert "error" not in response
    assert "Notepad" in [node["info"]["name"] for node in response["result"]]


def test_roots_leave_out_transient_popup_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, output, _button = make_server(tmp_path, monkeypatch)
    request(server, output, "initialize", {"root": str(tmp_path)})
    assert server.app is not None
    window = server.app.windows[0]  # type: ignore[attr-defined]
    for popup_class in ("Xaml_WindowedPopupClass", "Microsoft.UI.Content.PopupWindowSiteBridge"):
        server.app.windows.append(  # type: ignore[attr-defined]
            RpcElement("Window", "PopupHost", class_name=popup_class)
        )
    roots = request(server, output, "inspect.roots")["result"]
    assert [node["info"]["name"] for node in roots] == [window.name]


@pytest.mark.parametrize("full", [False, True])
@pytest.mark.parametrize("ancestors", [False, True])
def test_inspection_expensive_reads_are_opt_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, full: bool, ancestors: bool
) -> None:
    from wintestkit.uia.constants import PROPERTY_IDS

    server, output, button = make_server(tmp_path, monkeypatch)
    request(server, output, "initialize", {"root": str(tmp_path)})
    node = server._register(button)
    property_reads: list[str] = []
    pattern_reads: list[bool] = []
    parent_reads: list[bool] = []
    original_info = button.info
    original_parent = button.parent

    def info(with_patterns: bool = False) -> Any:
        pattern_reads.append(with_patterns)
        return original_info(with_patterns)

    def parent() -> Any:
        parent_reads.append(True)
        return original_parent()

    monkeypatch.setattr(button, "get_property", lambda name: property_reads.append(name) or "value")
    monkeypatch.setattr(button, "info", info)
    monkeypatch.setattr(button, "parent", parent)
    params = {"nodeId": node["nodeId"]}
    if full:
        params["full"] = True
    if ancestors:
        params["includeAncestors"] = True
    result = request(server, output, "inspect.properties", params)["result"]
    assert property_reads == (list(PROPERTY_IDS) if full else [])
    assert pattern_reads == [full]
    assert bool(parent_reads) is ancestors
    assert bool(result["ancestors"]) is ancestors
    assert result["info"]["name"] == "OK"


@pytest.mark.parametrize("activated", [True, False])
@pytest.mark.parametrize("method", ["inspect.highlight", "element.highlight"])
def test_highlight_raises_window_before_reading_bounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, activated: bool, method: str
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

    monkeypatch.setattr(actions, "raise_without_activating", foreground)
    monkeypatch.setattr(actions, "window_is_minimized", lambda element: True)
    monkeypatch.setattr(overlay, "flash", flash)
    if method == "inspect.highlight":
        response = request(
            server,
            output,
            method,
            {"nodeId": node["nodeId"], "durationMs": 800, "bringToFront": True},
        )
        assert response["result"] is None
    else:
        response = request(
            server,
            output,
            method,
            {"file": "page.py", "qualname": "Main.ok", "durationMs": 800},
        )
        assert response["result"]["status"] == "found"
    assert calls == ["foreground", "highlight"]


@pytest.mark.parametrize("method", ["inspect.highlight", "element.highlight"])
def test_highlight_does_not_raise_a_window_for_an_element_without_bounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    server, output, button = make_server(tmp_path, monkeypatch)
    request(server, output, "initialize", {"root": str(tmp_path)})
    node = server._register(button)
    button.rect = None

    def unexpected(*args: Any, **kwargs: Any) -> None:
        pytest.fail("must not raise the window or outline an element that has no bounds")

    monkeypatch.setattr(actions, "raise_without_activating", unexpected)
    monkeypatch.setattr(actions, "window_is_minimized", lambda element: False)
    monkeypatch.setattr(overlay, "flash", unexpected)
    if method == "inspect.highlight":
        response = request(server, output, method, {"nodeId": node["nodeId"], "bringToFront": True})
        assert response["result"] is None
    else:
        response = request(server, output, method, {"file": "page.py", "qualname": "Main.ok"})
        assert response["result"]["status"] == "found"


def test_inspect_highlight_outlines_without_raising_the_window_unless_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, output, button = make_server(tmp_path, monkeypatch)
    request(server, output, "initialize", {"root": str(tmp_path)})
    node = server._register(button)
    raised: list[str] = []
    outlined: list[Rect] = []
    monkeypatch.setattr(
        actions, "raise_without_activating", lambda element: raised.append("raised") or True
    )
    monkeypatch.setattr(overlay, "flash", lambda rect, duration, *, block: outlined.append(rect))
    request(server, output, "inspect.highlight", {"nodeId": node["nodeId"]})
    assert raised == []  # off by default: the outline alone marks the element
    assert outlined == [button.rect]
    request(server, output, "inspect.highlight", {"nodeId": node["nodeId"], "bringToFront": False})
    assert raised == []
    request(server, output, "inspect.highlight", {"nodeId": node["nodeId"], "bringToFront": True})
    assert raised == ["raised"]
    assert (
        request(
            server, output, "inspect.highlight", {"nodeId": node["nodeId"], "bringToFront": "yes"}
        )["error"]["code"]
        == -32602
    )


def test_element_highlight_does_not_activate_a_missing_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, output, _ = make_server(tmp_path, monkeypatch)
    request(server, output, "initialize", {"root": str(tmp_path)})

    def unexpected(*args: Any, **kwargs: Any) -> None:
        pytest.fail("must not activate or outline a target that does not resolve")

    monkeypatch.setattr(actions, "raise_without_activating", unexpected)
    monkeypatch.setattr(overlay, "flash", unexpected)
    response = request(
        server, output, "element.highlight", {"file": "page.py", "qualname": "Main.missing"}
    )
    assert response["error"]["code"] == -32003


@pytest.mark.parametrize(
    "method,params",
    [
        ("unknown", {}),
        ("discover", {"overrides": []}),
        ("discover", {"overrides": {"file": 1}}),
        ("inspect.children", {}),
        ("inspect.properties", {"nodeId": "x", "full": "true"}),
        ("inspect.properties", {"nodeId": "x", "includeAncestors": 1}),
        ("inspect.roots", {"includeOtherApps": "yes"}),
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
            "params": {"file": "page.py", "qualname": "Main.ok"},
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
