from __future__ import annotations

from types import SimpleNamespace

import pytest
from fakes import FakeElement

from wintestkit.artifacts import (
    TREE_TEXT_MAX_BYTES,
    baseline_path,
    capture_tree_text,
    write_tree_diff,
)
from wintestkit.engine import treedump


def test_baseline_is_partitioned_by_target_and_test(tmp_path):
    a = baseline_path(tmp_path, "app-one", "test_a")
    assert a != baseline_path(tmp_path, "app-two", "test_a")
    assert a != baseline_path(tmp_path, "app-one", "test_b")


def test_diff_is_bounded_and_omitted_when_no_change(tmp_path):
    previous, current, diff = (tmp_path / name for name in ("previous", "current", "diff"))
    previous.write_text("Window\n  Button Save\n", encoding="utf-8")
    current.write_text("Window\n  Button Cancel\n", encoding="utf-8")
    assert write_tree_diff(previous, current, diff)
    assert "Button Save" in diff.read_text(encoding="utf-8")
    current.write_text("Window\n  Button Save\n", encoding="utf-8")
    assert not write_tree_diff(previous, current, diff)
    previous.write_text("x" * (512 * 1024 + 1), encoding="utf-8")
    assert not write_tree_diff(previous, current, diff)


@pytest.mark.parametrize("corrupt", ["previous", "current"])
def test_corrupt_tree_text_is_unavailable_evidence(tmp_path, corrupt):
    previous, current, diff = (tmp_path / name for name in ("previous", "current", "diff"))
    previous.write_text("old", encoding="utf-8")
    current.write_text("new", encoding="utf-8")
    (tmp_path / corrupt).write_bytes(b"\xff")
    assert not write_tree_diff(previous, current, diff)
    assert not diff.exists()


def test_capture_bounds_multibyte_names_without_expanding_tree():
    class HugeNode(FakeElement):
        def iter_children(self):
            pytest.fail("text budget must stop traversal before requesting children")

    root = HugeNode("Window", name="\u2603" * TREE_TEXT_MAX_BYTES)
    text = capture_tree_text(SimpleNamespace(main_window=lambda: root))
    assert text is not None
    assert 0 < len(text.encode("utf-8")) <= TREE_TEXT_MAX_BYTES


def test_node_budget_does_not_expand_final_node():
    class FinalNode(FakeElement):
        def iter_children(self):
            pytest.fail("final node must not be expanded")

    root = FinalNode("Window")
    assert len(list(treedump.walk(root, max_nodes=1))) == 1


def test_wide_tree_is_enumerated_lazily():
    visited = []

    class WideNode(FakeElement):
        def iter_children(self):
            for index in range(10000):
                visited.append(index)
                yield FakeElement("Button", name=str(index))

    root = WideNode("Window")
    assert len(list(treedump.walk(root, max_nodes=3))) == 3
    assert visited == [0, 1]


def test_diff_byte_limit_includes_multibyte_text(tmp_path):
    previous, current, diff = (tmp_path / name for name in ("previous", "current", "diff"))
    previous.write_text("\u2603" * 100000, encoding="utf-8")
    current.write_text("\u2604" * 100000, encoding="utf-8")
    assert write_tree_diff(previous, current, diff)
    assert diff.stat().st_size <= TREE_TEXT_MAX_BYTES
    diff.read_text(encoding="utf-8")


def test_native_child_iterator_fetches_only_requested_siblings(monkeypatch):
    from wintestkit.uia import com
    from wintestkit.uia.element import UIAElement

    calls = []
    raw_child = object()

    class Walker:
        def GetFirstChildElementBuildCache(self, parent, request):
            calls.append("first")
            return raw_child

        def GetNextSiblingElementBuildCache(self, child, request):
            calls.append("next")
            return None

    monkeypatch.setattr(com, "get_uia", lambda: SimpleNamespace(ControlViewWalker=Walker()))
    monkeypatch.setattr("wintestkit.uia.element._get_cache_request", lambda: object())
    children = UIAElement(object()).iter_children()
    assert calls == []
    assert next(children).raw is raw_child
    assert calls == ["first"]
    assert list(children) == []
    assert calls == ["first", "next"]


def test_corrupt_baseline_does_not_abort_pytest(pytester, monkeypatch):
    from wintestkit import artifacts

    report_dir = pytester.path / "report"
    pytester.makepyprojecttoml('[tool.wintestkit]\ntimeout = 1\nreport_dir = "report"\n')
    pytester.makepyfile(
        test_ui='from pathlib import Path\ndef test_ui(): assert not Path("fail").exists()'
    )
    monkeypatch.setattr(artifacts, "capture_tree_text", lambda app: "Window\n")

    def capture_failure(app, directory):
        directory.mkdir(parents=True, exist_ok=True)
        current = directory / "tree.txt"
        current.write_text("Changed window\n", encoding="utf-8")
        return artifacts.ArtifactSet(directory, tree_dump=current)

    monkeypatch.setattr(artifacts, "capture_failure", capture_failure)

    class BaselineObserver:
        def pytest_sessionfinish(self, session):
            from wintestkit.pytest_plugin import CONTROLLER_KEY

            controller = session.config.stash[CONTROLLER_KEY]
            assert controller.runs
            assert all(run.tree_baseline is None for run in controller.runs.values())

    observer = BaselineObserver()
    options = ("-p", "wintestkit", "--wtk-ui-tree-diff", "-p", "no:cacheprovider")
    pytester.runpytest(*options, plugins=[observer]).assert_outcomes(passed=1)
    baselines = list((report_dir / "ui-tree-baselines").glob("*.txt"))
    assert len(baselines) == 1
    baselines[0].write_bytes(b"\xff")
    (pytester.path / "fail").touch()
    result = pytester.runpytest(*options, plugins=[observer])
    result.assert_outcomes(failed=1)
    assert result.ret == 1
