"""Shared deterministic server harness for unit and contract tests."""

import io
import json
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeApp, FakeElement

from wintestkit.engine import actions, overlay, query
from wintestkit.server import Server
from wintestkit.uia.constants import TreeScope


class RpcElement(FakeElement):
    def find_first(self, scope: TreeScope, condition: Any = None) -> FakeElement | None:
        matches = self.find_all(scope, condition)
        return matches[0] if matches else None

    def get_property(self, name: str) -> Any:
        return self.name if name == "Name" else [1, 2]


def make_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Server, io.BytesIO, RpcElement]:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.wintestkit]\n[tool.wintestkit.app]\nprocess = 'Demo.exe'\n", encoding="utf-8"
    )
    (tmp_path / "page.py").write_text(
        "from wintestkit import Page, Element\nprint('user module print')\n"
        "class Main(Page):\n    ok = Element(control_type='Button', name='OK')\n",
        encoding="utf-8",
    )
    button = RpcElement("Button", "OK")
    window = RpcElement("Window", "Demo", children=[button])
    output = io.BytesIO()
    server = Server(output)
    server.app = FakeApp([window])
    monkeypatch.setattr(query, "make_condition", lambda **props: props)
    monkeypatch.setattr(overlay, "flash", lambda *args, **kwargs: None)
    monkeypatch.setattr(actions, "bring_to_front", lambda element: True)
    return server, output, button


def request(server: Server, output: io.BytesIO, method: str, params: Any = None) -> dict[str, Any]:
    server.handle(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": {} if params is None else params}
    )
    messages = [json.loads(line) for line in output.getvalue().splitlines()]
    output.seek(0)
    output.truncate()
    return next(message for message in reversed(messages) if "id" in message)
