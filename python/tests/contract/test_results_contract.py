"""Persisted results validate against the shared schema and match emitted events."""

import json
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from wintestkit import runtime
from wintestkit.engine import treedump
from wintestkit.replay import ReplayRecorder
from wintestkit.uia import screenshot
from wintestkit.uia.webp import encode_webp


def test_webp_screenshots_flow_through_results_and_events(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    validate: Callable[[str, str, Any], None],
) -> None:
    runtime.reset()
    pixels = b"\x11\x77\xee"
    captured = encode_webp(1, 1, pixels)
    monkeypatch.setattr(screenshot, "capture_window", lambda hwnd: captured)
    monkeypatch.setattr(screenshot, "capture_screen", lambda: captured)
    monkeypatch.setattr(treedump, "dump", lambda *args, **kwargs: "Window")
    pytester.makepyprojecttoml('[tool.wintestkit]\nscreenshots = "every-step"\n')
    pytester.makeconftest("""
import pytest
from unittest.mock import Mock
@pytest.fixture
def app():
    return Mock()
""")
    pytester.makepyfile("""
from wintestkit import runtime
def test_failure(app):
    with runtime.step("click", "Main", "Window", {}):
        assert False, "screenshot verification"
""")
    pytester.runpytest("--wtk-events=events.ndjson").assert_outcomes(failed=1)
    directory = pytester.path / "wtk-report"
    results = json.loads((directory / "results.json").read_text(encoding="utf-8"))
    validate("results.schema.json", "Results", results)
    events = [
        json.loads(line)
        for line in (pytester.path / "events.ndjson").read_text(encoding="utf-8").splitlines()
    ]
    for event in events:
        validate("events.schema.json", "RunEvent", event)
    test = results["tests"][0]
    assert {Path(path).name for path in test["screenshots"]} == {
        "window.webp",
        "desktop.webp",
        "1.webp",
    }
    assert test["steps"][0]["screenshot"].endswith("/steps/1.webp")
    ending = next(event for event in events if event["event"] == "test_end")
    assert {Path(path).name for path in ending["screenshots"]} == {
        "window.webp",
        "desktop.webp",
        "1.webp",
    }
    for path in test["screenshots"]:
        with Image.open(BytesIO((directory / path).read_bytes())) as image:
            assert image.format == "WEBP"
            assert image.tobytes() == pixels
    assert not list(directory.rglob("*.png"))
    runtime.reset()


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


@pytest.mark.parametrize("mode", ["on", "retain-on-failure"])
def test_replay_results_and_events_match_contract(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    validate: Callable[[str, str, Any], None],
    mode: str,
) -> None:
    monkeypatch.setattr(ReplayRecorder, "_capture_window", lambda self: (1, 1, b"\xff\x00\x00"))
    pytester.makepyprojecttoml(f'[tool.wintestkit]\nscreenshots = "off"\nreplay = "{mode}"\n')
    pytester.makepyfile("""
import time
import pytest
from wintestkit import runtime
def test_ok():
    with runtime.step("wait", "Main", "Window", {}):
        time.sleep(0.06)
def test_failure():
    time.sleep(0.06)
    assert False, "replay failure"
@pytest.fixture
def broken():
    time.sleep(0.06)
    raise RuntimeError("setup failed")
def test_setup_error(broken): pass
""")
    result = pytester.runpytest("--wtk-events=replay-events.ndjson")
    result.assert_outcomes(passed=1, failed=1, errors=1)
    results = json.loads((pytester.path / "wtk-report/results.json").read_text(encoding="utf-8"))
    validate("results.schema.json", "Results", results)
    events = [
        json.loads(line)
        for line in (pytester.path / "replay-events.ndjson")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    for event in events:
        validate("events.schema.json", "RunEvent", event)
    endings = {event["id"]: event for event in events if event["event"] == "test_end"}
    for test in results["tests"]:
        retained = mode == "on" or test["outcome"] in ("failed", "error")
        assert ("replay" in test) == retained
        if retained:
            replay = test["replay"]
            assert replay == endings[test["id"]]["replay"]
            assert len(replay["frames"]) == 1
            assert replay["duration"] >= 0.04
            assert (pytester.path / "wtk-report" / replay["frames"][0]["path"]).is_file()
    expected = 3 if mode == "on" else 2
    assert len(list((pytester.path / "wtk-report").rglob("*.webp"))) == expected
    runtime.reset()


def test_no_report_disables_replay_capture(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected_start(self: ReplayRecorder) -> None:
        raise AssertionError("replay must be disabled with --wtk-no-report")

    monkeypatch.setattr(ReplayRecorder, "start", unexpected_start)
    pytester.makepyprojecttoml('[tool.wintestkit]\nscreenshots = "off"\nreplay = "on"\n')
    pytester.makepyfile("def test_ok(): pass")
    pytester.runpytest("--wtk-no-report").assert_outcomes(passed=1)
    assert not (pytester.path / "wtk-report").exists()
    runtime.reset()


def test_no_html_writes_results_without_the_html_report(pytester: pytest.Pytester) -> None:
    pytester.makepyprojecttoml('[tool.wintestkit]\nscreenshots = "off"\n')
    pytester.makepyfile("def test_ok(): pass")
    directory = pytester.path / "wtk-report"
    directory.mkdir()
    (directory / "index.html").write_text("stale", encoding="utf-8")
    result = pytester.runpytest("--wtk-no-html")
    result.assert_outcomes(passed=1)
    assert (directory / "results.json").is_file()
    assert not (directory / "index.html").exists()
    result.stdout.fnmatch_lines(["Results: *results.json"])
    runtime.reset()
