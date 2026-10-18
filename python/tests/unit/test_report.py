"""Report safety, portability, cleanup and regeneration."""

import json
from pathlib import Path

from wintestkit.cli import main
from wintestkit.report.html import TREE_TEXT_LIMIT, render, write_report
from wintestkit.report.results import RunRecorder, prepare_directory


def test_owned_cleanup_preserves_other_files(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("keep", encoding="utf-8")
    (tmp_path / "index.html").write_text("old", encoding="utf-8")
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "artifacts/old.png").write_bytes(b"old")
    prepare_directory(tmp_path)
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "keep"
    assert not (tmp_path / "artifacts").exists()
    assert not (tmp_path / "index.html").exists()


def test_embedded_json_cannot_end_script() -> None:
    payload = {"message": '</script><script>alert("bad")</script>', "unicode": "日本 ✓"}
    html = render(payload)
    data = html.split('<script type="application/json" id="wtk-data">')[1].split("</script>")[0]
    assert json.loads(data) == payload
    assert "<script>alert" not in html
    assert 'src="http' not in html and 'href="http' not in html
    assert "innerHTML" not in html


def test_recorder_paths_are_portable_and_omit_unrun_tests(tmp_path: Path) -> None:
    recorder = RunRecorder(tmp_path)
    recorder.record({"event": "session_start", "time": 1})
    recorder.record(
        {
            "event": "collected",
            "tests": [
                {"id": name, "name": name, "file": str(tmp_path / "test.py"), "line": 0}
                for name in ("run", "unrun")
            ],
        }
    )
    recorder.record({"event": "step", "id": "run", "step": {"screenshot": "artifacts/steps/1.png"}})
    tree_diff = tmp_path / "artifacts" / "tree-diff.txt"
    tree_diff.parent.mkdir(parents=True)
    tree_diff.write_text("- old\n+ new\n", encoding="utf-8")
    recorder.record(
        {
            "event": "test_end",
            "id": "run",
            "outcome": "passed",
            "duration": 1,
            "screenshots": [str(tmp_path / "artifacts/window.png")],
            "treeDiff": str(tree_diff),
        }
    )
    recorder.record({"event": "session_end", "time": 2, "summary": {}})
    results = recorder.results()
    assert len(results["tests"]) == 1
    assert results["tests"][0]["screenshots"] == ["artifacts/window.png"]
    assert results["tests"][0]["steps"][0]["screenshot"] == "artifacts/steps/1.png"
    assert results["tests"][0]["treeDiff"] == "artifacts/tree-diff.txt"


def test_report_command_regenerates_html(tmp_path: Path) -> None:
    write_report(tmp_path, {"version": 1, "message": "saved results"})
    (tmp_path / "index.html").unlink()
    assert main(["report", str(tmp_path)]) == 0
    assert "saved results" in (tmp_path / "index.html").read_text(encoding="utf-8")


def test_report_command_handles_missing_results(tmp_path: Path) -> None:
    assert main(["report", str(tmp_path)]) == 2


def test_trace_paths_are_portable_and_payload_is_not_mutated(tmp_path: Path) -> None:
    recorder = RunRecorder(tmp_path)
    recorder.record(
        {
            "event": "collected",
            "tests": [{"id": "test", "name": "test", "file": str(tmp_path / "test.py"), "line": 0}],
        }
    )
    trace = {
        "startedAt": 1,
        "duration": 1,
        "truncated": False,
        "frames": [{"time": 0, "path": str(tmp_path / "artifacts/frame.png")}],
    }
    recorder.record(
        {
            "event": "test_end",
            "id": "test",
            "outcome": "passed",
            "duration": 1,
            "screenshots": [],
            "trace": trace,
        }
    )
    recorded = recorder.results()["tests"][0]["trace"]
    assert recorded["frames"][0]["path"] == "artifacts/frame.png"
    assert trace["frames"][0]["path"] == str(tmp_path / "artifacts/frame.png")


def embedded_results(html: str) -> dict:
    return json.loads(
        html.split('<script type="application/json" id="wtk-data">')[1].split("</script>")[0]
    )


def test_tree_is_embedded_without_mutating_saved_results(tmp_path: Path) -> None:
    tree = tmp_path / "artifacts" / "tree.txt"
    tree.parent.mkdir()
    content = 'Window "App"\n  Button "</script><script>bad()</script>" id=save disabled'
    tree.write_bytes(content.encode("utf-8"))
    results = {"tests": [{"id": "test", "treeDump": "artifacts/tree.txt"}]}
    report = write_report(tmp_path, results)
    embedded = embedded_results(report.read_text(encoding="utf-8"))
    assert embedded["tests"][0]["treeText"] == content
    assert embedded["tests"][0]["treeTextTruncated"] is False
    assert "treeText" not in results["tests"][0]
    assert json.loads((tmp_path / "results.json").read_text(encoding="utf-8")) == results
    assert "<script>bad()" not in report.read_text(encoding="utf-8")


def test_tree_embedding_is_bounded_and_rejects_outside_files(tmp_path: Path) -> None:
    report_dir = tmp_path / "report"
    report_dir.mkdir()
    (report_dir / "large.txt").write_bytes(b"x" * (TREE_TEXT_LIMIT + 10))
    (tmp_path / "private.txt").write_text("secret", encoding="utf-8")
    results = {
        "tests": [{"treeDump": name} for name in ("large.txt", "../private.txt", "missing.txt")]
    }
    embedded = embedded_results(render(results, report_dir))["tests"]
    assert len(embedded[0]["treeText"]) == TREE_TEXT_LIMIT
    assert embedded[0]["treeTextTruncated"] is True
    assert "treeText" not in embedded[1]
    assert "treeText" not in embedded[2]


def test_recorder_retains_editor_and_run_metadata(tmp_path: Path) -> None:
    recorder = RunRecorder(tmp_path)
    recorder.record(
        {"event": "session_start", "time": 1, "root": str(tmp_path), "command": "pytest -q"}
    )
    recorder.record(
        {
            "event": "collected",
            "tests": [
                {
                    "id": "test.py::test",
                    "name": "test",
                    "file": str(tmp_path / "test.py"),
                    "line": 9,
                    "markers": ["smoke"],
                }
            ],
        }
    )
    recorder.record(
        {
            "event": "test_end",
            "id": "test.py::test",
            "outcome": "error",
            "duration": 0.1,
            "screenshots": [],
            "message": "setup failed",
        }
    )
    result = recorder.results()
    assert result["root"] == str(tmp_path)
    assert result["command"] == "pytest -q"
    test = result["tests"][0]
    assert test["absoluteFile"] == str(tmp_path / "test.py")
    assert test["line"] == 9
    assert test["markers"] == ["smoke"]
    assert test["outcome"] == "error"
