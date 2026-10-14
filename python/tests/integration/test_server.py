"""The stdio server resolves and inspects the live demo in a separate process."""

import json
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from support import DemoProcess

from wintestkit.app import App

pytestmark = pytest.mark.integration


def test_stdio_server(tmp_path: Path, demo_process: DemoProcess) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.wintestkit]\n[tool.wintestkit.app]\nprocess = 'DemoApp.exe'\n", encoding="utf-8"
    )
    (tmp_path / "rpc_screen.py").write_text(
        "from wintestkit import Screen, Element\nprint('stray print from user module')\n"
        "class Main(Screen):\n"
        "    sign_in = Element(control_type='Button', name='Sign in')\n"
        "    missing = Element(name='not present')\n",
        encoding="utf-8",
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "wintestkit", "serve", "--stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    messages: queue.Queue[dict[str, Any]] = queue.Queue()
    assert process.stdout is not None
    assert process.stdin is not None

    def read() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            messages.put(json.loads(line))

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    counter = 0

    def call(method: str, params: dict[str, Any] | None = None) -> Any:
        nonlocal counter
        counter += 1
        assert process.stdin is not None
        payload = {"jsonrpc": "2.0", "id": counter, "method": method, "params": params or {}}
        process.stdin.write((json.dumps(payload) + "\n").encode())
        process.stdin.flush()
        deadline = time.monotonic() + 15
        while True:
            response = messages.get(timeout=max(0.01, deadline - time.monotonic()))
            if response.get("id") == counter:
                assert "error" not in response, response
                return response["result"]

    try:
        assert call("initialize", {"root": str(tmp_path)})["protocolVersion"] == 1
        assert call("discover")["screens"]
        assert call("app.status")["running"]
        found = call(
            "element.highlight",
            {"file": "rpc_screen.py", "qualname": "Main.sign_in", "durationMs": 10},
        )
        assert found["status"] == "found"
        assert (
            call("element.highlight", {"file": "rpc_screen.py", "qualname": "Main.missing"})[
                "status"
            ]
            == "not_found"
        )
        assert call("screen.check", {"file": "rpc_screen.py", "screen": "Main"})["results"]
        roots = call("inspect.roots")
        root = next(node for node in roots if node["info"]["name"] == "WTK Demo")
        assert call("inspect.children", {"nodeId": root["nodeId"]})
        pending = [root]
        button = None
        for _ in range(200):
            if not pending:
                break
            node = pending.pop()
            if node["info"]["controlType"] == "Button" and node["info"]["name"] == "Sign in":
                button = node
                break
            if node["hasChildren"]:
                pending.extend(call("inspect.children", {"nodeId": node["nodeId"]}))
        assert button is not None
        params = {"nodeId": button["nodeId"]}
        assert "Invoke" in call("inspect.properties", params)["info"]["patterns"]
        assert call("suggest.locator", params)["strategy"] == "name"
        assert call("inspect.highlight", {**params, "durationMs": 10}) is None
        assert call("shutdown") is None
        assert process.wait(timeout=10) == 0
        assert App.attach(pid=demo_process.pid).is_running()
        assert process.stderr is not None
        assert b"stray print from user module" in process.stderr.read()
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()
