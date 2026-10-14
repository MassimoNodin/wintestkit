"""Persisted results validate against the shared schema and match emitted events."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from wintestkit import runtime


def test_pytest_results_match_events(
    pytester: pytest.Pytester, validate: Callable[[str, str, Any], None]
) -> None:
    runtime.reset()
    pytester.makepyprojecttoml('[tool.wintestkit]\nscreenshots = "off"\n')
    pytester.makepyfile("""
import sys
import pytest
from wintestkit import runtime
def test_ok():
    print("captured output")
    print("captured error", file=sys.stderr)
    with runtime.step("click", "Main.button", "Button[id=ok]", {}):
        pass
def test_failure():
    assert False, "failure details"
@pytest.fixture
def broken():
    raise RuntimeError("setup failed")
def test_error(broken): pass
@pytest.mark.skip(reason="skip")
def test_skip(): pass
""")
    result = pytester.runpytest("--wtk-events=events.ndjson")
    result.assert_outcomes(passed=1, failed=1, errors=1, skipped=1)
    results = json.loads((pytester.path / "wtk-report/results.json").read_text(encoding="utf-8"))
    validate("results.schema.json", "Results", results)
    events = [
        json.loads(line)
        for line in (pytester.path / "events.ndjson").read_text(encoding="utf-8").splitlines()
    ]
    assert results["summary"] == events[-1]["summary"]
    endings = {event["id"]: event for event in events if event["event"] == "test_end"}
    for test in results["tests"]:
        assert test["outcome"] == endings[test["id"]]["outcome"]
        assert test["duration"] == endings[test["id"]]["duration"]
    passed = next(test for test in results["tests"] if test["outcome"] == "passed")
    assert passed["stdout"] == "captured output\n"
    assert passed["stderr"] == "captured error\n"
    assert passed["steps"][0]["action"] == "click"
    failed = next(test for test in results["tests"] if test["outcome"] == "failed")
    assert "failure details" in failed["message"]
    assert failed["location"]["file"].startswith("../")
    runtime.reset()


def test_no_report_preserves_existing_outputs(pytester: pytest.Pytester) -> None:
    pytester.makepyprojecttoml('[tool.wintestkit]\nscreenshots = "off"\n')
    pytester.makepyfile("def test_ok(): pass")
    directory = pytester.path / "wtk-report"
    directory.mkdir()
    (directory / "index.html").write_text("previous", encoding="utf-8")
    pytester.runpytest("--wtk-no-report").assert_outcomes(passed=1)
    assert (directory / "index.html").read_text(encoding="utf-8") == "previous"
    assert not (directory / "results.json").exists()
    runtime.reset()


def test_session_end_reports_output_paths(pytester: pytest.Pytester) -> None:
    pytester.makepyprojecttoml('[tool.wintestkit]\nscreenshots = "off"\n')
    pytester.makepyfile("def test_ok(): pass")
    result = pytester.runpytest("--wtk-events=events.ndjson", "--junitxml=junit.xml")
    result.assert_outcomes(passed=1)
    events = [
        json.loads(line)
        for line in (pytester.path / "events.ndjson").read_text(encoding="utf-8").splitlines()
    ]
    end = events[-1]
    assert end["event"] == "session_end"
    assert end["reportPath"].endswith("/wtk-report/index.html")
    assert Path(end["reportPath"]).is_file()
    assert Path(end["junitPath"]) == (pytester.path / "junit.xml").resolve()
    result.stdout.fnmatch_lines(["Report: *index.html"])
    runtime.reset()
