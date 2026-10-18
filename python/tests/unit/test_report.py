"""Report safety, portability, cleanup and regeneration."""

import json
from pathlib import Path

from wintestkit.cli import main
from wintestkit.report.html import render, write_report
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
    assert "http://" not in html and "https://" not in html
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
