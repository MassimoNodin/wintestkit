"""Running a flow from the editor: the flow is called with the running app."""

from pathlib import Path
from textwrap import dedent
from typing import Any

import pytest
from rpc_support import make_server, request

from wintestkit.config import load_config
from wintestkit.targets import ModuleLoader, TargetError, run_flow


def write_flows(root: Path, source: str) -> Path:
    (root / "pyproject.toml").write_text("[tool.wintestkit]\n", encoding="utf-8")
    file = root / "flows" / "tour.py"
    file.parent.mkdir(exist_ok=True)
    file.write_text(dedent(source).lstrip(), encoding="utf-8")
    return file


def run(root: Path, file: Path, name: str, app: Any = "the app") -> dict[str, Any]:
    return run_flow(app, ModuleLoader(load_config(root)), file, name).to_dict()


def test_calls_the_flow_with_the_app(tmp_path: Path) -> None:
    file = write_flows(
        tmp_path,
        """
        seen = []
        def tour(app):
            seen.append(app)
            return "ignored"
    """,
    )
    result = run(tmp_path, file, "tour", app="fake-app")
    assert result["status"] == "passed"
    assert "message" not in result
    assert result["durationMs"] >= 0


def test_passes_validated_scalar_arguments_with_future_annotations(tmp_path: Path) -> None:
    file = write_flows(
        tmp_path,
        """
        from __future__ import annotations
        def tour(app, count: int, label: str = "safe"):
            assert type(count) is int
            assert label == "safe"
    """,
    )
    result = run_flow(
        "fake-app", ModuleLoader(load_config(tmp_path)), file, "tour", {"count": 3}
    )
    assert result.status == "passed"
    rejected = run_flow(
        "fake-app", ModuleLoader(load_config(tmp_path)), file, "tour", {"count": "3"}
    )
    assert rejected.status == "failed"
    assert "must be a supported typed scalar" in (rejected.message or "")


def test_awaits_async_flows(tmp_path: Path) -> None:
    file = write_flows(
        tmp_path,
        """
        async def tour(app):
            raise ValueError("late")
    """,
    )
    result = run(tmp_path, file, "tour")
    assert result["status"] == "failed"
    assert result["message"].startswith("ValueError: late")


def test_a_raising_flow_fails_with_the_innermost_user_frame(tmp_path: Path) -> None:
    file = write_flows(
        tmp_path,
        """
        def tour(app):
            assert app == "other", "wrong app"
    """,
    )
    result = run(tmp_path, file, "tour")
    assert result["status"] == "failed"
    assert result["message"].startswith("AssertionError: wrong app (")
    assert "tour.py:2)" in result["message"]


@pytest.mark.parametrize(
    ("source", "name", "message"),
    [
        ("def tour(): pass", "tour", "needs (no parameters)"),
        ("def tour(*, app): pass", "tour", "needs (app)"),
        ("def _private(app): pass", "_private", "has no flow '_private'"),
        ("def tour(app): pass", "missing", "has no flow 'missing'"),
        ("class Tour: pass", "Tour", "has no flow 'Tour'"),
    ],
)
def test_refuses_flows_that_cannot_be_called_with_only_the_app(
    tmp_path: Path, source: str, name: str, message: str
) -> None:
    file = write_flows(tmp_path, source)
    with pytest.raises(TargetError, match=message.replace("(", r"\(").replace(")", r"\)")):
        run(tmp_path, file, name)


def test_reports_missing_typed_flow_arguments(tmp_path: Path) -> None:
    file = write_flows(tmp_path, "def open_page(app, page_type: str): pass")
    result = run_flow("app", ModuleLoader(load_config(tmp_path)), file, "open_page")
    assert result.status == "failed"
    assert "missing required parameters: page_type" in (result.message or "")


def test_flow_run_over_rpc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    server, output, _ = make_server(tmp_path, monkeypatch)
    write_flows(tmp_path, "def tour(app):\n    assert app is not None\n")
    request(server, output, "initialize", {"root": str(tmp_path)})
    params = {"file": "flows/tour.py", "name": "tour"}
    assert request(server, output, "flow.run", params)["result"]["status"] == "passed"
    missing = request(server, output, "flow.run", {**params, "name": "nope"})
    assert missing["error"]["code"] == -32003
    server.app = None
    stopped = request(server, output, "flow.run", params)
    assert stopped["error"]["code"] == -32002
