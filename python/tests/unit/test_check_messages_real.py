"""Input-free check-result messages against the owned WPF fixture."""

import io
import os
from pathlib import Path
from typing import Any

import pytest
from test_managed_attach_real import _result
from test_managed_attach_real import target as fixture_target

from wintestkit.app import App
from wintestkit.config import load_config
from wintestkit.server import Server
from wintestkit.targets import ModuleLoader

target = fixture_target

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.name != "nt" or os.environ.get("WTK_INSPECTOR_REAL") != "1",
        reason="requires explicitly enabled owned Windows fixture",
    ),
]


@pytest.mark.parametrize("name,enabled", [("missing", True), ("content", False), ("content", True)])
def test_check_messages(tmp_path: Path, target: Any, name: str, enabled: bool) -> None:
    (tmp_path / "pages.py").write_text(
        "from wintestkit import Page, Window, Element\n"
        "class FixturePage(Page):\n"
        "    window = Window()\n"
        "    missing = Element(automation_id='NoSuchButton')\n"
        "    content = Element(where={'clr:Name': '_mainWindowDockPanel'})\n",
        encoding="utf-8",
    )
    output = io.BytesIO()
    server = Server(output)
    server.cfg = load_config(
        tmp_path, {"inspector.enabled": enabled, "inspector.attach": "on-demand"}
    )
    server.loader = ModuleLoader(server.cfg)
    server.app = App.attach(pid=target.pid)
    result = _result(
        server, output, "element.check", {"file": "pages.py", "qualname": f"FixturePage.{name}"}
    )
    print(f"LIVE {name} enabled={enabled}: {result}")
    if name == "missing":
        assert "no descendant has automation_id 'NoSuchButton'" in result["message"]
        assert "Nearest:" in result["message"]
    elif enabled:
        assert result["status"] == "found"
    else:
        assert "`clr:Name` needs the .NET inspector, which is disabled" in result["message"]
