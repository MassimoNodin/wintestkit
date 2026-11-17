"""Input-free live attachment failure checks through JSON-RPC."""

import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from live_dotnet import live_dotnet_root

from wintestkit import runtime
from wintestkit.config import load_config
from wintestkit.errors import InspectorUnavailableError
from wintestkit.inspector.hints import inspector_error_hint
from wintestkit.inspector.probe import identify
from wintestkit.inspector.sessions import SessionRegistry
from wintestkit.server import Server
from wintestkit.targets import ModuleLoader

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "wpf-inspector/tests/Fixtures/WpfFixture/bin/cells/net10.0-windows-x64"
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.name != "nt" or os.environ.get("WTK_INSPECTOR_REAL") != "1",
        reason="requires explicitly enabled owned Windows fixture",
    ),
]


@pytest.fixture
def target(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.syspath_prepend(str(ROOT / "inspector-payload/src"))
    env = os.environ.copy()
    env["DOTNET_ROOT_X64"] = live_dotnet_root()
    env["DOTNET_MULTILEVEL_LOOKUP"] = "0"
    process = subprocess.Popen(
        [str(FIXTURE / "WinTestKit.Fixture.exe")],
        cwd=FIXTURE,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 15
        while True:
            assert process.poll() is None
            try:
                facts = identify(process.pid)
                from wintestkit.uia import win32

                if (
                    facts.wpf_loaded
                    and facts.runtime == "net10"
                    and win32.top_level_windows({process.pid})
                ):
                    break
            except (OSError, InspectorUnavailableError):
                pass
            assert time.monotonic() < deadline
            time.sleep(0.1)
        yield facts.identity
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)
        runtime.reset()


def rpc_attach(tmp_path: Path, identity: Any, enabled: bool) -> dict[str, Any]:
    output = io.BytesIO()
    server = Server(output)
    server.cfg = load_config(tmp_path, {"inspector.enabled": enabled})
    server.loader = ModuleLoader(server.cfg)
    server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "inspect.managed.attach",
            "params": {"process": identity.to_json()},
        }
    )
    return json.loads(output.getvalue())["error"]


def test_disabled(tmp_path: Path, target: Any) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.wintestkit.inspector]\nenabled = false\n", encoding="utf-8"
    )
    output = io.BytesIO()
    server = Server(output)
    server.cfg = load_config(tmp_path)
    server.loader = ModuleLoader(server.cfg)
    server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "inspect.managed.attach",
            "params": {"process": target.to_json()},
        }
    )
    error = json.loads(output.getvalue())["error"]
    assert error["data"]["code"] == "inspectorDisabled"
    assert error["data"]["hint"] == inspector_error_hint("inspectorDisabled")


def test_second_session(tmp_path: Path, target: Any) -> None:
    registry = SessionRegistry()
    try:
        registry.attach(target, target_hwnd=None, deadline=time.monotonic() + 10)
        error = rpc_attach(tmp_path, target, True)
        assert error["data"]["code"] == "alreadyAttached"
        assert error["data"]["hint"] == inspector_error_hint("alreadyAttached")
    finally:
        registry.close_all()


def test_new_registry_after_close(target: Any) -> None:
    first = SessionRegistry()
    second = SessionRegistry()
    try:
        first.attach(target, target_hwnd=None, deadline=time.monotonic() + 10)
        first.close_all()
        client = second.attach(target, target_hwnd=None, deadline=time.monotonic() + 10)
        assert client.session.state == "ready"
    finally:
        first.close_all()
        second.close_all()


def test_same_registry_reuses_session(target: Any) -> None:
    registry = SessionRegistry()
    try:
        tree = registry.attach(target, target_hwnd=None, deadline=time.monotonic() + 10)
        properties = registry.attach(target, target_hwnd=None, deadline=time.monotonic() + 10)
        assert properties is tree
    finally:
        registry.close_all()


def test_controller_exit_allows_new_registry(target: Any) -> None:
    code = (
        "import sys,time; "
        "from wintestkit.inspector.probe import current_identity; "
        "from wintestkit.inspector.sessions import SessionRegistry; "
        "r=SessionRegistry(); "
        "r.attach(current_identity(int(sys.argv[1])), target_hwnd=None, "
        "deadline=time.monotonic()+10); "
        "print('ready', flush=True); time.sleep(60)"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "inspector-payload/src")
    controller = subprocess.Popen(
        [sys.executable, "-c", code, str(target.pid)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    registry = SessionRegistry()
    try:
        assert controller.stdout is not None
        assert controller.stdout.readline().strip() == "ready"
        controller.terminate()
        controller.wait(timeout=5)
        client = registry.attach(target, target_hwnd=None, deadline=time.monotonic() + 10)
        assert client.session.state == "ready"
    finally:
        if controller.poll() is None:
            controller.terminate()
        controller.wait(timeout=5)
        registry.close_all()


def _rpc(server: Server, output: io.BytesIO, method: str, params: dict[str, Any]) -> dict[str, Any]:
    output.seek(0)
    output.truncate()
    server.handle({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    return json.loads(output.getvalue())


def _live_server(target: Any) -> tuple[Server, io.BytesIO]:
    from wintestkit.app import App

    output = io.BytesIO()
    server = Server(output)
    root = ROOT / "examples/wpf-fixture-tests"
    server.cfg = load_config(root, {"inspector.enabled": True, "inspector.attach": "on-demand"})
    server.loader = ModuleLoader(server.cfg)
    server.app = App.attach(pid=target.pid)
    return server, output


def _result(server: Server, output: io.BytesIO, method: str, params: dict[str, Any]) -> Any:
    response = _rpc(server, output, method, params)
    assert "result" in response, response
    return response["result"]


def _check(server: Server, output: io.BytesIO) -> dict[str, Any]:
    return _result(
        server, output, "element.check", {"file": "pages.py", "qualname": "FixturePage.content"}
    )


@pytest.mark.parametrize("tree_first", [True, False])
def test_tree_properties_and_check_reuse(target: Any, tree_first: bool) -> None:
    from wintestkit.uia import com
    from wintestkit.uia.constants import TreeScope

    server, output = _live_server(target)
    assert server.app is not None
    window = server.app.main_window()
    root = server._register(window)
    server._mark_roots([root])
    window_id = root["nodeId"]
    identity = _result(server, output, "inspect.managed.identify", {"nodeId": window_id})["process"]
    fixture = window.find_first(
        TreeScope.Descendants, com.create_condition(automation_id="FixtureControl")
    )
    assert fixture is not None
    fixture_id = server._register(fixture)["nodeId"]
    if not tree_first:
        _result(server, output, "inspect.managed.identify", {"nodeId": fixture_id})
    session = _result(server, output, "inspect.managed.attach", {"process": identity})
    assert session["state"] == "ready"
    session_id = session["sessionId"]

    def members_for(node_id: str) -> None:
        mapping = _result(
            server, output, "inspect.managed.resolve", {"sessionId": session_id, "nodeId": node_id}
        )
        assert mapping["status"] == "exact"
        ref = mapping["object"]
        members = _result(
            server,
            output,
            "inspect.managed.members",
            {**{k: ref[k] for k in ("sessionId", "objectId", "generation")}, "pageSize": 200},
        )
        assert members["items"]

    if not tree_first:
        members_for(fixture_id)
    children = _result(
        server, output, "inspect.children", {"nodeId": window_id, "tree": "visual", "pageSize": 200}
    )
    assert children["nodes"]
    content_id = children["nodes"][0]["nodeId"]
    facts = _result(server, output, "inspect.managed.identify", {"nodeId": content_id})
    assert facts["process"] == identity
    status = _result(server, output, "inspect.managed.status", {"process": identity})
    assert status["sessionId"] == session_id
    members_for(content_id)
    assert (
        _result(server, output, "inspect.managed.attach", {"process": identity})["sessionId"]
        == session_id
    )
    assert _check(server, output)["status"] == "found"


def test_fresh_check_attaches(target: Any) -> None:
    server, output = _live_server(target)
    assert _check(server, output)["status"] == "found"


def test_check_reports_other_owner(target: Any) -> None:
    registry = SessionRegistry()
    try:
        registry.attach(target, target_hwnd=None, deadline=time.monotonic() + 10)
        server, output = _live_server(target)
        result = _check(server, output)
        assert result["status"] == "error", result
        assert result["code"] == "alreadyAttached", result
        assert result["hint"] == inspector_error_hint("alreadyAttached")
    finally:
        registry.close_all()


def test_different_loaded_build_reports_restart(
    tmp_path: Path, target: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    from wintestkit import doctor

    external_python = os.environ.get("WTK_PYPI_PYTHON")
    if not external_python:
        pytest.skip("requires a separately installed release payload")
    code = (
        "import sys,time; from wintestkit.inspector.probe import identify; "
        "from wintestkit.inspector.sessions import SessionRegistry; "
        "r=SessionRegistry(); c=r.attach(identify(int(sys.argv[1])).identity, "
        "target_hwnd=None, deadline=time.monotonic()+10); c.close()"
    )
    subprocess.run([external_python, "-c", code, str(target.pid)], check=True, timeout=20)
    registry = SessionRegistry()
    try:
        with pytest.raises(InspectorUnavailableError) as error:
            registry.attach(target, target_hwnd=None, deadline=time.monotonic() + 10)
        assert error.value.code == "agentVersionMismatch"
    finally:
        registry.close_all()
    cfg = load_config(tmp_path, {"backend": "auto", "inspector.enabled": True})
    cfg = replace(cfg, inspector=replace(cfg.inspector, attach_timeout=10))
    monkeypatch.setattr(doctor, "_app_pids", lambda cfg: ("fixture", [target.pid]))
    check = doctor._check_wpf_agent(cfg)
    assert check.status == "fail"
    assert "agentVersionMismatch" in check.detail
