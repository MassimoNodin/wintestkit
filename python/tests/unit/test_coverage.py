"""Which page definitions resolve to a UI Automation node: exactness, soundness and cost."""

from pathlib import Path
from typing import Any

import pytest
from fakes import FakeApp, FakeElement
from rpc_support import RpcElement, make_server, request

from wintestkit import coverage as coverage_module
from wintestkit.commands.init import _template
from wintestkit.engine import query

PAGES = """
import re
from wintestkit import Button, Element, Page, Window


class Base(Page):
    window = Window(title="Demo")
    ok = Element(control_type="Button", name="OK")
    shared = Button(automation_id="Shared", validate=False)


class Main(Base):
    save = Button(automation_id="Save", validate=False)
    duplicate = Element(name="Dup")
    missing = Element(name="Nope")
    pattern = Element(name=re.compile("^Pat"))
    where = Element(where={"HelpText": "tip"})


class Other(Base):
    pass
"""


class PropertyElement(RpcElement):
    """An element whose extra properties (``where=``) are readable, unlike ``RpcElement``'s."""

    def get_property(self, name: str) -> Any:
        return FakeElement.get_property(self, name)


def _project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any, dict[str, Any]]:
    server, output, _button = make_server(tmp_path, monkeypatch)
    (tmp_path / "page.py").write_text(PAGES, encoding="utf-8")
    request(server, output, "initialize", {"root": str(tmp_path)})
    assert isinstance(server.app, FakeApp)
    window = server.app.windows[0]
    window.children_list.clear()
    nodes: dict[str, FakeElement] = {
        "ok": RpcElement("Button", "OK"),
        "save": RpcElement("Button", "Other label", automation_id="Save"),
        "dup1": RpcElement("Text", "Dup"),
        "dup2": RpcElement("Text", "Dup"),
        "pattern": RpcElement("Text", "Pattern here"),
        "shared": RpcElement("Button", "Shared one", automation_id="Shared"),
        "tip": PropertyElement("Text", "Tip", properties={"HelpText": "tip"}),
        "unrelated": RpcElement("Text", "Nothing points here"),
    }
    for node in nodes.values():
        window.add(node)
    registered: dict[str, Any] = {"window": server._register(window)}
    for name, node in nodes.items():
        registered[name] = server._register(node)
    return server, output, registered


@pytest.mark.parametrize(
    "title",
    ["test - Visual Studio Code", "Different workspace - Visual Studio Code", "Visual Studio Code"],
)
def test_generated_mainpage_matches_the_second_direct_child_for_any_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, title: str
) -> None:
    server, output, _ = make_server(tmp_path, monkeypatch)
    (tmp_path / "page.py").write_text(_template("main.py.tmpl"), encoding="utf-8")
    first = RpcElement("Pane")
    second = RpcElement("Pane", title, children=[RpcElement("Pane", "nested")])
    window = RpcElement("Window", title, children=[first, second])
    other = RpcElement(
        "Window",
        "Other workspace - Visual Studio Code",
        children=[RpcElement("Pane"), RpcElement("Pane", "other")],
    )
    server.app = FakeApp([window, other], process_name="Code.exe")
    request(server, output, "initialize", {"root": str(tmp_path)})
    selected = server._register(second)
    definitions = _definitions(server, output, selected)
    assert [definition["qualname"] for definition in definitions] == ["MainPage.content"]
    assert _definitions(server, output, server._register(first)) == []
    assert _definitions(server, output, server._register(second.children_list[0])) == []
    assert _definitions(server, output, server._register(other.children_list[1])) == []


def _definitions(server: Any, output: Any, node: dict[str, Any]) -> list[dict[str, Any]]:
    response = request(server, output, "inspect.definitions", {"nodeId": node["nodeId"]})
    return response["result"]["definitions"]  # type: ignore[no-any-return]


def test_coverage_epoch_ignores_process_enumeration_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(coverage_module.win32, "top_level_windows", lambda pids: [])

    class App:
        def __init__(self) -> None:
            self.pids = [3, 1]

    app = App()
    original = coverage_module.Coverage._ui_epoch(app)
    app.pids = [1, 3]
    assert coverage_module.Coverage._ui_epoch(app) == original


def test_a_definition_is_listed_only_for_the_node_it_resolves_to(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, output, nodes = _project(tmp_path, monkeypatch)
    ok = _definitions(server, output, nodes["ok"])
    assert [d["qualname"] for d in ok] == ["Base.ok"]
    assert ok[0]["file"].endswith("page.py")
    assert ok[0]["line"] == 8
    assert ok[0]["kind"] == "element"
    assert ok[0]["range"]["start"]["line"] == 7
    assert [d["qualname"] for d in _definitions(server, output, nodes["save"])] == ["Main.save"]
    assert [d["qualname"] for d in _definitions(server, output, nodes["pattern"])] == [
        "Main.pattern"
    ]
    assert [d["qualname"] for d in _definitions(server, output, nodes["tip"])] == ["Main.where"]
    # Ambiguous (two matches) and missing definitions are not exact matches of anything.
    assert _definitions(server, output, nodes["dup1"]) == []
    assert _definitions(server, output, nodes["dup2"]) == []
    assert _definitions(server, output, nodes["unrelated"]) == []


def test_a_window_definition_matches_its_window_and_inherited_ones_group_their_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, output, nodes = _project(tmp_path, monkeypatch)
    (window_match,) = _definitions(server, output, nodes["window"])
    assert window_match["qualname"] == "Base.window"
    assert window_match["kind"] == "window"
    (shared,) = _definitions(server, output, nodes["shared"])
    assert shared["qualname"] == "Base.shared"
    assert sorted(shared["pages"]) == ["Base.shared", "Main.shared", "Other.shared"]
    assert shared["pageCount"] == 3


def test_coverage_equals_resolving_every_definition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, output, nodes = _project(tmp_path, monkeypatch)
    ids = [node["nodeId"] for node in nodes.values()]
    result = request(server, output, "inspect.coverage", {"nodeIds": ids})["result"]
    assert result["pending"] == []
    engine = server._coverage()
    truth: dict[str, set[str]] = {}
    snapshot = coverage_module._SnapshotApp(server.app)
    assert engine.catalogue is not None
    for entry in engine.catalogue.entries:
        for node_id in engine._resolve(snapshot, entry):
            truth.setdefault(node_id, set()).add(entry.definition_id)
    expected = {node_id: len(defined) for node_id, defined in truth.items()}
    assert {n: c["count"] for n, c in result["covered"].items()} == expected
    assert nodes["unrelated"]["nodeId"] not in result["covered"]
    assert nodes["dup1"]["nodeId"] not in result["covered"]


def test_each_distinct_locator_is_resolved_once_and_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, output, nodes = _project(tmp_path, monkeypatch)
    engine = server._coverage()
    calls: list[str] = []
    original = engine._resolve

    def counting(app: Any, entry: Any) -> Any:
        calls.append(entry.page_path)
        return original(app, entry)

    monkeypatch.setattr(engine, "_resolve", counting)
    ids = [node["nodeId"] for node in nodes.values()]
    request(server, output, "inspect.coverage", {"nodeIds": ids})
    first = len(calls)
    assert engine.catalogue is not None
    distinct = {entry.resolution_key for entry in engine.catalogue.entries}
    assert 0 < first < len(engine.catalogue.entries)  # inherited elements share one resolution
    assert first <= len(distinct)
    request(server, output, "inspect.coverage", {"nodeIds": ids})
    assert len(calls) == first  # warm: nothing is resolved again
    request(server, output, "inspect.roots")  # a refresh forgets the resolutions
    request(server, output, "inspect.coverage", {"nodeIds": ids})
    assert len(calls) == 2 * first


@pytest.mark.parametrize("partial", [False, True])
def test_fresh_children_invalidate_replaced_descendants_without_rebuilding_catalogue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, partial: bool
) -> None:
    server, output, nodes = _project(tmp_path, monkeypatch)
    original_id = nodes["ok"]["nodeId"]
    initial = request(server, output, "inspect.coverage", {"nodeIds": [original_id]})["result"]
    assert original_id in initial["covered"]
    engine = server._coverage()
    catalogue = engine.catalogue
    epoch = engine._ui_epoch(server.app)
    window = server.app.windows[0]
    replacement = RpcElement("Button", "OK")
    window.children_list.clear()
    window.add(replacement)
    if partial:
        stale = window.add(RpcElement("Button", "stale"))

        def unavailable(*args: Any) -> Any:
            raise RuntimeError("stale child")

        monkeypatch.setattr(stale, "info", unavailable)
    assert engine._ui_epoch(server.app) == epoch
    response = request(server, output, "inspect.children", {"nodeId": nodes["window"]["nodeId"]})
    if partial:
        assert response["error"]["code"] == -32005
        children = response["error"]["data"]["nodes"]
    else:
        children = response["result"]
    assert [node["nodeId"] for node in children] == [replacement.runtime_id]
    assert engine._resolved == {}
    assert engine.catalogue is catalogue
    infos = {replacement.runtime_id: server.node_infos[replacement.runtime_id]}
    pending = engine.covered_nodes(server.app, infos, budget=0)
    assert pending == {"covered": {}, "pending": [replacement.runtime_id]}
    calls: list[str] = []
    original_resolve = engine._resolve

    def counting(app: Any, entry: Any) -> Any:
        calls.append(entry.page_path)
        return original_resolve(app, entry)

    monkeypatch.setattr(engine, "_resolve", counting)
    params = {"nodeIds": [original_id, replacement.runtime_id]}
    updated = request(server, output, "inspect.coverage", params)["result"]
    assert updated["pending"] == []
    assert replacement.runtime_id in updated["covered"]
    assert original_id not in updated["covered"]
    assert engine.catalogue is catalogue
    first = len(calls)
    assert first > 0
    assert request(server, output, "inspect.coverage", params)["result"] == updated
    assert len(calls) == first


def test_only_candidates_that_can_match_are_resolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, output, nodes = _project(tmp_path, monkeypatch)
    engine = server._coverage()
    resolved: list[str] = []
    original = engine._resolve

    def counting(app: Any, entry: Any) -> Any:
        resolved.append(entry.page_path)
        return original(app, entry)

    monkeypatch.setattr(engine, "_resolve", counting)
    request(server, output, "inspect.coverage", {"nodeIds": [nodes["unrelated"]["nodeId"]]})
    # Only the definition made of a ``where=`` alone cannot be ruled out from the node's cheap
    # properties; every other definition names a different name, id, class or type.
    assert resolved == ["Main.where"]


def test_misses_do_not_scan_for_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, output, nodes = _project(tmp_path, monkeypatch)

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("a miss must not scan the window for the closest candidates")

    monkeypatch.setattr(query, "relaxed_descendants", forbidden)
    monkeypatch.setattr("wintestkit.engine.diagnose.relaxed_descendants", forbidden)
    ids = [node["nodeId"] for node in nodes.values()]
    request(server, output, "inspect.coverage", {"nodeIds": ids})
    request(server, output, "inspect.definitions", {"nodeId": nodes["ok"]["nodeId"]})


def test_an_exhausted_budget_reports_the_unfinished_nodes_as_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, _output, nodes = _project(tmp_path, monkeypatch)
    engine = server._coverage()
    app = server._app()
    infos = {node["nodeId"]: server.node_infos[node["nodeId"]] for node in nodes.values()}
    result = engine.covered_nodes(app, infos, budget=0)
    assert result["covered"] == {}
    assert nodes["ok"]["nodeId"] in result["pending"]
    done = engine.covered_nodes(app, infos, budget=60)
    assert done["pending"] == []
    assert nodes["ok"]["nodeId"] in done["covered"]


def test_editing_a_page_file_rebuilds_the_catalogue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, output, nodes = _project(tmp_path, monkeypatch)
    assert _definitions(server, output, nodes["unrelated"]) == []
    source = PAGES.replace(
        'missing = Element(name="Nope")', 'extra = Element(name="Nothing points here")'
    )
    (tmp_path / "page.py").write_text(source, encoding="utf-8")
    assert server.loader is not None
    server.loader._last_scan = 0.0  # let the next scan see the edit now
    found = _definitions(server, output, nodes["unrelated"])
    assert [d["qualname"] for d in found] == ["Main.extra"]


def test_an_unimportable_page_is_reported_and_the_rest_still_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, output, nodes = _project(tmp_path, monkeypatch)
    (tmp_path / "broken.py").write_text(
        "from wintestkit import Page\nraise RuntimeError('boom')\nclass Broken(Page): pass\n",
        encoding="utf-8",
    )
    response = request(server, output, "inspect.definitions", {"nodeId": nodes["ok"]["nodeId"]})
    assert [d["qualname"] for d in response["result"]["definitions"]] == ["Base.ok"]


def test_stopped_app_preserves_catalogue_without_resolving(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, output, nodes = _project(tmp_path, monkeypatch)
    running = request(server, output, "inspect.definitions", {"nodeId": nodes["ok"]["nodeId"]})[
        "result"
    ]
    assert running["appRunning"] is True
    app = server.app
    monkeypatch.setattr(server, "_app", lambda required=True: None)
    resolve = server._coverage()._resolve

    def unexpected_resolution(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Stopped-app inspection must not resolve locators")

    monkeypatch.setattr(server._coverage(), "_resolve", unexpected_resolution)
    stopped = request(server, output, "inspect.definitions", {"nodeId": nodes["ok"]["nodeId"]})[
        "result"
    ]
    assert stopped == {
        "definitions": [],
        "errors": [],
        "pageCount": running["pageCount"],
        "appRunning": False,
    }
    assert stopped["pageCount"] > 0
    monkeypatch.setattr(server._coverage(), "_resolve", resolve)
    monkeypatch.setattr(server, "_app", lambda required=True: app)
    assert _definitions(server, output, nodes["ok"])


def test_stopped_app_loads_catalogue_before_any_live_inspection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, output, nodes = _project(tmp_path, monkeypatch)
    monkeypatch.setattr(server, "_app", lambda required=True: None)
    result = request(server, output, "inspect.definitions", {"nodeId": nodes["ok"]["nodeId"]})[
        "result"
    ]
    assert result["pageCount"] > 0
    assert result["appRunning"] is False
    assert result["definitions"] == []


def test_coverage_params_are_validated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    server, output, _nodes = _project(tmp_path, monkeypatch)
    for bad in ("x", [""], [1], ["a"] * 501):
        error = request(server, output, "inspect.coverage", {"nodeIds": bad})["error"]
        assert error["code"] == -32602
    assert request(server, output, "inspect.coverage", {"nodeIds": []})["result"] == {
        "covered": {},
        "pending": [],
    }
