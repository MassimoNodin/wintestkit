"""Unit tests for the runtime context and step recording."""

import dataclasses
import json
import logging
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

from wintestkit import runtime
from wintestkit.config import load_config
from wintestkit.errors import ActionError, ConfigError
from wintestkit.runtime import StepRecord, step


@pytest.fixture(autouse=True)
def fresh_runtime(tmp_path: Path) -> Iterator[None]:
    runtime.reset()
    runtime.set_config(load_config(tmp_path))
    yield
    runtime.reset()


def collect() -> tuple[list[StepRecord], object]:
    records: list[StepRecord] = []
    remove = runtime.add_step_listener(records.append)
    return records, remove


def test_seq_numbers_restart_per_test() -> None:
    records, _ = collect()
    runtime.begin_test("tests/test_a.py::test_one")
    assert runtime.current_test() == "tests/test_a.py::test_one"
    with step("click", "A.b", 'Button[name="b"]'):
        pass
    with step("click", "A.c", 'Button[name="c"]'):
        pass
    runtime.begin_test("tests/test_a.py::test_two")
    with step("click", "A.b", 'Button[name="b"]'):
        pass
    assert [r.seq for r in records] == [1, 2, 1]
    runtime.end_test()
    assert runtime.current_test() is None


def test_record_fields_and_to_dict() -> None:
    records, _ = collect()
    with step("type", "MainPage.username", 'Edit[class="TextBox"]', {"text": "admin"}):
        pass
    (record,) = records
    assert record.action == "type"
    assert record.target == "MainPage.username"
    assert record.locator == 'Edit[class="TextBox"]'
    assert record.status == "passed"
    assert record.error is None
    assert record.start > 1_700_000_000
    assert record.duration >= 0
    data = record.to_dict()
    assert set(data) == {
        "seq",
        "action",
        "target",
        "locator",
        "args",
        "start",
        "duration",
        "status",
    }
    assert data["args"] == {"text": "admin"}
    json.dumps(data)


def test_to_dict_includes_optional_fields() -> None:
    record = StepRecord(
        1, "click", "A.b", "x", {}, 1.0, 0.5, "failed", {"type": "E", "message": "m"}, "s.png"
    )
    data = record.to_dict()
    assert data["error"] == {"type": "E", "message": "m"}
    assert data["screenshot"] == "s.png"


def test_secret_argument_names_are_redacted() -> None:
    records, _ = collect()
    with step(
        "type",
        "X.y",
        "z",
        {"text": "visible", "password": "p", "MY_SECRET": "s", "api_token": "t", "clear": True},
    ):
        pass
    assert records[0].args == {
        "text": "visible",
        "password": "***",
        "MY_SECRET": "***",
        "api_token": "***",
        "clear": True,
    }


def test_secret_flag_redacts_everything() -> None:
    records, _ = collect()
    with step("type", "X.password", "z", {"text": "hunter2", "clear": True}, secret=True):
        pass
    assert records[0].args == {"text": "***", "clear": "***"}


def test_args_are_made_json_safe() -> None:
    records, _ = collect()

    class Odd:
        def __repr__(self) -> str:
            return "<Odd>"

    args = {
        "pattern": re.compile("^a.b$", re.IGNORECASE | re.DOTALL),
        "path": Path("a/b"),
        "items": (1, "two", re.compile("x")),
        "nested": {"k": Odd(), 3: None},
        "plain": 1.5,
        "odd": Odd(),
    }
    with step("select", "X.y", "z", args):
        pass
    safe = records[0].args
    assert safe["pattern"] == "/^a.b$/is"
    assert safe["path"] == str(Path("a/b"))
    assert safe["items"] == [1, "two", "/x/"]
    assert safe["nested"] == {"k": "<Odd>", "3": None}
    assert safe["plain"] == 1.5
    assert safe["odd"] == "<Odd>"
    json.dumps(safe)


def test_failed_step_records_error_and_reraises() -> None:
    records, _ = collect()
    with pytest.raises(ActionError), step("click", "X.y", "z"):
        raise ActionError("cannot click")
    (record,) = records
    assert record.status == "failed"
    assert record.error == {"type": "ActionError", "message": "cannot click"}
    assert record.duration >= 0


def test_non_wtk_exception_uses_type_and_message() -> None:
    records, _ = collect()
    with pytest.raises(KeyError), step("click", "X.y", "z"):
        raise KeyError("missing")
    assert records[0].error == {"type": "KeyError", "message": "'missing'"}


def test_failing_to_dict_falls_back() -> None:
    records, _ = collect()

    class Broken(Exception):
        def to_dict(self) -> dict[str, str]:
            raise RuntimeError("nope")

    with pytest.raises(Broken), step("click", "X.y", "z"):
        raise Broken("bad")
    assert records[0].error == {"type": "Broken", "message": "bad"}


def test_listener_errors_are_isolated(caplog: pytest.LogCaptureFixture) -> None:
    def broken(record: StepRecord) -> None:
        raise RuntimeError("listener crashed")

    runtime.add_step_listener(broken)
    records, _ = collect()
    with caplog.at_level(logging.ERROR, logger="wintestkit.runtime"), step("click", "X.y", "z"):
        pass
    assert len(records) == 1  # later listeners still run
    assert "listener crashed" in caplog.text


def test_listener_error_does_not_hide_a_step_failure() -> None:
    def broken(record: StepRecord) -> None:
        raise RuntimeError("listener crashed")

    runtime.add_step_listener(broken)
    with pytest.raises(ActionError), step("click", "X.y", "z"):
        raise ActionError("real failure")


def test_listener_can_be_removed() -> None:
    records: list[StepRecord] = []
    remove = runtime.add_step_listener(records.append)
    with step("a", "t", "l"):
        pass
    remove()
    remove()  # idempotent
    with step("b", "t", "l"):
        pass
    assert [r.action for r in records] == ["a"]


def test_listener_sees_final_state() -> None:
    seen: list[tuple[str, float]] = []
    runtime.add_step_listener(lambda r: seen.append((r.status, r.duration)))
    with step("a", "t", "l"):
        pass
    assert seen[0][0] == "passed"
    assert seen[0][1] >= 0


def test_slow_mo_sleeps_after_successful_steps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(runtime, "_sleep", sleeps.append)
    config = load_config(tmp_path, {"slow_mo_ms": 250})
    runtime.set_config(config)
    with step("a", "t", "l"):
        pass
    assert sleeps == [0.25]
    with pytest.raises(ActionError), step("b", "t", "l"):
        raise ActionError("x")
    assert sleeps == [0.25]  # no sleep after a failure


def test_no_sleep_without_slow_mo(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(runtime, "_sleep", sleeps.append)
    with step("a", "t", "l"):
        pass
    assert sleeps == []


def test_get_config_loads_lazily_and_set_config_replaces(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime.reset()
    (tmp_path / "pyproject.toml").write_text("[tool.wintestkit]\ntimeout = 3\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert runtime.get_config().timeout == 3.0
    replaced = dataclasses.replace(runtime.get_config(), timeout=9.0)
    runtime.set_config(replaced)
    assert runtime.get_config() is replaced


def test_bad_config_surfaces_config_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runtime.reset()
    (tmp_path / "pyproject.toml").write_text("[tool.wintestkit]\nbogus = 1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError):
        runtime.get_config()
