"""The plugin's real event stream must validate against events.schema.json."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from wintestkit import runtime

Validate = Callable[[str, str, Any], None]

SCENARIOS = """
import pytest
from wintestkit import runtime
from wintestkit.engine.diagnose import Diagnostic
from wintestkit.errors import ElementNotFoundError


def test_pass():
    print("hello from the test")
    with runtime.step("click", "Screen.button", 'Button[name="OK"]', {"mode": "pattern"}):
        pass


def test_assertion_failure():
    assert 1 == 2, "numbers differ"


def test_locator_failure():
    raise ElementNotFoundError(
        Diagnostic(
            kind="not_found",
            message='No element matches Button[name="Sign In"] in Window "WTK Demo"',
            locator='Button[name="Sign In"]',
            searched_in='Window "WTK Demo"',
            match_count=0,
        )
    )


def test_other_exception():
    raise KeyError("missing")


@pytest.mark.skip(reason="not today")
def test_skipped():
    pass


@pytest.fixture
def broken():
    raise RuntimeError("fixture boom")


def test_error_in_fixture(broken):
    pass


@pytest.fixture
def broken_teardown():
    yield
    raise RuntimeError("teardown boom")


def test_error_in_teardown(broken_teardown):
    pass


@pytest.mark.parametrize("user,password", [("admin", "secret"), ("guest", "x")])
def test_parametrized(user, password):
    pass


@pytest.mark.xfail(reason="known bug")
def test_expected_failure():
    assert False


class TestGroup:
    def test_method(self):
        pass
"""

PROJECT = '[tool.wintestkit]\nscreenshots = "off"\n'


def run(pytester: pytest.Pytester, *extra: str) -> list[dict[str, Any]]:
    events_file = pytester.path / "events.ndjson"
    pytester.runpytest("-p", "no:cacheprovider", f"--wtk-events={events_file}", *extra)
    return [json.loads(line) for line in events_file.read_text(encoding="utf-8").splitlines()]


@pytest.fixture(autouse=True)
def clean_runtime() -> Any:
    runtime.reset()
    yield
    runtime.reset()


@pytest.fixture
def stream(pytester: pytest.Pytester) -> list[dict[str, Any]]:
    pytester.makepyprojecttoml(PROJECT)
    pytester.makepyfile(test_scenarios=SCENARIOS)
    pytester.makepyfile(test_collect_error="def broken(:\n    pass\n")
    return run(pytester, "--continue-on-collection-errors")


def by_id(events: list[dict[str, Any]], kind: str) -> dict[str, dict[str, Any]]:
    return {e["id"]: e for e in events if e["event"] == kind}


def test_every_event_validates_against_the_schema(
    stream: list[dict[str, Any]], validate: Validate
) -> None:
    assert {e["event"] for e in stream} == {
        "session_start",
        "collected",
        "test_start",
        "step",
        "test_output",
        "test_end",
        "session_end",
    }
    for event in stream:
        validate("events.schema.json", "RunEvent", event)
        assert isinstance(event["time"], float)


def test_stream_framing(stream: list[dict[str, Any]]) -> None:
    assert stream[0]["event"] == "session_start"
    assert stream[1]["event"] == "collected"
    assert stream[-1]["event"] == "session_end"
    assert stream[0]["wintestkitVersion"] == "0.1.0"
    assert stream[0]["pid"] > 0
    assert "\\" not in stream[0]["root"]


def test_collected_tests_and_errors(stream: list[dict[str, Any]]) -> None:
    collected = stream[1]
    tests = {t["id"]: t for t in collected["tests"]}
    assert "test_scenarios.py::test_pass" in tests
    first = tests["test_scenarios.py::test_pass"]
    assert first["parent"] is None
    assert first["name"] == "test_pass"
    assert first["file"].endswith("/test_scenarios.py")
    assert "\\" not in first["file"]
    assert first["line"] >= 0
    param = tests["test_scenarios.py::test_parametrized[admin-secret]"]
    assert param["parent"] == "test_scenarios.py::test_parametrized"
    assert param["name"] == "test_parametrized[admin-secret]"
    method = tests["test_scenarios.py::TestGroup::test_method"]
    assert method["parent"] == "test_scenarios.py::TestGroup"
    assert len(collected["errors"]) == 1
    assert collected["errors"][0]["file"].endswith("test_collect_error.py")
    assert collected["errors"][0]["message"]


def test_outcomes(stream: list[dict[str, Any]]) -> None:
    ends = by_id(stream, "test_end")
    outcome = {key.split("::", 1)[1]: value["outcome"] for key, value in ends.items()}
    assert outcome == {
        "test_pass": "passed",
        "test_assertion_failure": "failed",
        "test_locator_failure": "failed",
        "test_other_exception": "failed",
        "test_skipped": "skipped",
        "test_error_in_fixture": "error",
        "test_error_in_teardown": "error",
        "test_parametrized[admin-secret]": "passed",
        "test_parametrized[guest-x]": "passed",
        "test_expected_failure": "skipped",
        "TestGroup::test_method": "passed",
    }


def test_one_test_end_per_test_after_teardown(stream: list[dict[str, Any]]) -> None:
    counts: dict[str, int] = {}
    for event in stream:
        if event["event"] == "test_end":
            counts[event["id"]] = counts.get(event["id"], 0) + 1
    assert set(counts.values()) == {1}
    starts = [e["id"] for e in stream if e["event"] == "test_start"]
    assert sorted(starts) == sorted(counts)
    for test_id in counts:
        start = next(
            i for i, e in enumerate(stream) if e["event"] == "test_start" and e["id"] == test_id
        )
        end = next(
            i for i, e in enumerate(stream) if e["event"] == "test_end" and e["id"] == test_id
        )
        assert start < end


def test_failure_details(stream: list[dict[str, Any]]) -> None:
    ends = by_id(stream, "test_end")
    assertion = ends["test_scenarios.py::test_assertion_failure"]
    assert assertion["message"].startswith("numbers differ")
    assert "error" not in assertion
    assert assertion["location"]["file"].endswith("/test_scenarios.py")
    assert isinstance(assertion["location"]["line"], int)

    locator = ends["test_scenarios.py::test_locator_failure"]
    assert locator["message"] == 'No element matches Button[name="Sign In"] in Window "WTK Demo"'
    assert locator["error"]["type"] == "ElementNotFoundError"
    assert locator["error"]["diagnostic"]["kind"] == "not_found"
    assert locator["location"]["file"].endswith("/test_scenarios.py")

    other = ends["test_scenarios.py::test_other_exception"]
    assert other["message"] == "KeyError('missing')"
    assert "error" not in other


def test_location_is_zero_based_and_points_at_the_raising_line(
    stream: list[dict[str, Any]],
) -> None:
    lines = SCENARIOS.strip().splitlines()  # pytester strips the leading newline
    ends = by_id(stream, "test_end")
    raised = ends["test_scenarios.py::test_other_exception"]["location"]["line"]
    assert lines[raised].strip() == 'raise KeyError("missing")'


def test_steps_and_output(stream: list[dict[str, Any]]) -> None:
    steps = [e for e in stream if e["event"] == "step"]
    assert len(steps) == 1
    assert steps[0]["id"] == "test_scenarios.py::test_pass"
    assert steps[0]["step"]["action"] == "click"
    assert steps[0]["step"]["seq"] == 1
    outputs = [e for e in stream if e["event"] == "test_output"]
    stdout = [o for o in outputs if o["stream"] == "stdout"]
    assert any("hello from the test" in o["text"] for o in stdout)
    assert all(o["text"] for o in outputs)


def test_session_end_summary(stream: list[dict[str, Any]]) -> None:
    end = stream[-1]
    assert end["summary"]["total"] == 11
    assert end["summary"]["passed"] == 4
    assert end["summary"]["failed"] == 3
    assert end["summary"]["skipped"] == 2
    assert end["summary"]["errors"] == 2
    assert end["summary"]["duration"] >= 0
    assert isinstance(end["exitCode"], int)


def test_durations_are_nonnegative(stream: list[dict[str, Any]]) -> None:
    for event in stream:
        if event["event"] == "test_end":
            assert event["duration"] >= 0
            assert event["screenshots"] == []


def test_events_url_can_be_a_file_url(pytester: pytest.Pytester, validate: Validate) -> None:
    pytester.makepyprojecttoml(PROJECT)
    pytester.makepyfile("def test_ok(): pass")
    target = pytester.path / "via-url.ndjson"
    pytester.runpytest("-p", "no:cacheprovider", f"--wtk-events=file:///{target.as_posix()}")
    events = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()]
    assert [e["event"] for e in events] == [
        "session_start",
        "collected",
        "test_start",
        "test_end",
        "session_end",
    ]
    for event in events:
        validate("events.schema.json", "RunEvent", event)


def test_unreachable_tcp_server_does_not_fail_the_run(pytester: pytest.Pytester) -> None:
    import socket

    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    pytester.makepyprojecttoml(PROJECT)
    pytester.makepyfile("def test_ok(): pass")
    result = pytester.runpytest("-p", "no:cacheprovider", f"--wtk-events=tcp://127.0.0.1:{port}")
    result.assert_outcomes(passed=1)


def test_bad_events_url_is_a_usage_error(pytester: pytest.Pytester) -> None:
    pytester.makepyprojecttoml(PROJECT)
    pytester.makepyfile("def test_ok(): pass")
    result = pytester.runpytest("-p", "no:cacheprovider", "--wtk-events=tcp://nohost")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*--wtk-events*"])


def test_stream_file_is_valid_ndjson_even_with_unicode(
    pytester: pytest.Pytester, tmp_path: Path
) -> None:
    pytester.makepyprojecttoml(PROJECT)
    pytester.makepyfile('def test_unicode():\n    print("héllo ✓ 日本")\n')
    events = run(pytester)
    output = next(e for e in events if e["event"] == "test_output")
    assert output["text"] == "héllo ✓ 日本\n"
