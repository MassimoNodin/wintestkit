"""A handle that goes stale is resolved again from its locator, once, for reads and lookups.

Actions are different: one that may already have changed something is never repeated.
"""

from __future__ import annotations

import contextlib
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fakes import FakeApp, FakeElement

from wintestkit import effects, model, runtime
from wintestkit.config import load_config
from wintestkit.engine import resolve as resolver
from wintestkit.errors import (
    ActionError,
    InspectorError,
    UIAError,
    is_stale,
)
from wintestkit.inspector.client import InspectorClient
from wintestkit.model import Element, Page, Window


class StalePage(Page):
    window = Window(title="WTK Demo")
    status = Element(automation_id="StatusText")


def stale() -> InspectorError:
    return InspectorError("Request failed.", code="objectStale")


@pytest.fixture(autouse=True)
def configured(tmp_path: Path) -> Any:
    runtime.reset()
    runtime.set_config(load_config(tmp_path, {"timeout": 0.5}))
    yield
    runtime.reset()


# -- what counts as stale ----------------------------------------------------------------------


def test_stale_means_an_object_stale_or_a_vanished_element_including_translated_ones() -> None:
    assert is_stale(stale())
    assert is_stale(UIAError("gone", element_gone=True))
    translated = UIAError("The UI element is no longer available")
    translated.__cause__ = stale()
    assert is_stale(translated)
    assert not is_stale(InspectorError("late", code="timeout"))
    assert not is_stale(ActionError("no"))
    assert not is_stale(UIAError("COM error"))


# -- lookups -----------------------------------------------------------------------------------


@pytest.mark.parametrize("which", ["resolve", "resolve_all", "wait_link"])
def test_a_lookup_that_meets_a_stale_handle_runs_again_from_its_locator(
    monkeypatch: pytest.MonkeyPatch, which: str
) -> None:
    attempts: list[int] = []

    def walk(scope: Any, locator: Any, final_all: bool) -> list[str]:
        attempts.append(1)
        if len(attempts) == 1:
            raise stale()
        return ["element"]

    def wait(scope: Any, locator: Any, state: str) -> tuple[bool, str]:
        attempts.append(1)
        if len(attempts) == 1:
            raise UIAError("The UI element is no longer available", element_gone=True)
        return True, "element"

    monkeypatch.setattr(resolver, "_walk", walk)
    monkeypatch.setattr(resolver, "_wait_link", wait)
    locator = SimpleNamespace()
    if which == "resolve":
        assert resolver.resolve(SimpleNamespace(), locator) == "element"  # type: ignore[arg-type]
    elif which == "resolve_all":
        assert resolver.resolve_all(SimpleNamespace(), locator) == ["element"]  # type: ignore[arg-type]
    else:
        assert resolver.wait_link(SimpleNamespace(), locator, "visible") == (True, "element")  # type: ignore[arg-type]
    assert len(attempts) == 2


def test_a_second_stale_handle_in_a_row_is_reported_not_retried_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[int] = []

    def walk(scope: Any, locator: Any, final_all: bool) -> Any:
        attempts.append(1)
        raise stale()

    monkeypatch.setattr(resolver, "_walk", walk)
    with pytest.raises(InspectorError) as error:
        resolver.resolve(SimpleNamespace(), SimpleNamespace())  # type: ignore[arg-type]
    assert error.value.code == "objectStale" and len(attempts) == 2


def test_other_failures_are_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[int] = []

    def walk(scope: Any, locator: Any, final_all: bool) -> Any:
        attempts.append(1)
        raise InspectorError("Request failed.", code="timeout")

    monkeypatch.setattr(resolver, "_walk", walk)
    with pytest.raises(InspectorError):
        resolver.resolve(SimpleNamespace(), SimpleNamespace())  # type: ignore[arg-type]
    assert len(attempts) == 1


# -- reads -------------------------------------------------------------------------------------


class Reader(model._BoundBase):  # pyright: ignore[reportPrivateUsage]
    def __init__(self) -> None:
        self.resolved = 0

    def resolve(self, timeout: float | None = None) -> Any:
        self.resolved += 1
        return SimpleNamespace(generation=self.resolved)


def test_a_read_that_finds_the_handle_gone_resolves_again_and_reads_once_more() -> None:
    reader = Reader()
    reads: list[int] = []

    def read(element: Any) -> str:
        reads.append(element.generation)
        if element.generation == 1:
            raise stale()
        return "value"

    assert reader._read(read) == "value"  # pyright: ignore[reportPrivateUsage]
    assert reads == [1, 2] and reader.resolved == 2


def test_a_read_that_fails_twice_or_for_another_reason_is_not_retried_further() -> None:
    reader = Reader()

    def always(element: Any) -> str:
        raise UIAError("The UI element is no longer available", element_gone=True)

    with pytest.raises(UIAError):
        reader._read(always)  # pyright: ignore[reportPrivateUsage]
    assert reader.resolved == 2
    other = Reader()

    def broken(element: Any) -> str:
        raise ActionError("not readable")

    with pytest.raises(ActionError):
        other._read(broken)  # pyright: ignore[reportPrivateUsage]
    assert other.resolved == 1


def test_get_reads_through_a_fresh_resolution_after_a_stale_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = FakeElement("Window", "WTK Demo")
    page = StalePage(FakeApp([window]))  # type: ignore[arg-type]
    resolved: list[FakeElement] = []

    def lookup(scope: Any, locator: Any) -> FakeElement:
        element = FakeElement("Text", "ok", properties={"Name": "ok"})
        resolved.append(element)
        if len(resolved) == 1:

            def gone(name: str) -> Any:
                raise stale()

            element.get_property = gone  # type: ignore[method-assign]
        return element

    monkeypatch.setattr(model, "resolve", lookup)
    assert page.status.get("Name") == "ok"
    assert len(resolved) == 2


# -- actions are never repeated after they had an effect --------------------------------------


class Performer:
    """Just enough of a bound control for ``perform``."""

    def __init__(self) -> None:
        self.attempts = 0

    def _actionable(self, timeout: float | None) -> Any:
        self.attempts += 1
        return SimpleNamespace()

    def _maybe_highlight(self, element: Any) -> None:
        return None

    perform = model.BoundControl.perform


def test_an_action_that_failed_before_changing_anything_is_run_again() -> None:
    performer = Performer()
    calls: list[int] = []

    def act(element: Any) -> str:
        calls.append(1)
        if len(calls) == 1:
            raise UIAError("The UI element is no longer available", element_gone=True)
        return "done"

    assert performer.perform(None, act) == "done"  # type: ignore[arg-type]
    assert performer.attempts == 2


@pytest.mark.parametrize("cause", ["mark", "input"])
def test_an_action_that_had_an_effect_is_never_run_again(
    monkeypatch: pytest.MonkeyPatch, cause: str
) -> None:
    performer = Performer()

    def act(element: Any) -> str:
        if cause == "mark":
            effects.mark()
        else:
            from wintestkit.uia import input as uia_input

            monkeypatch.setattr(uia_input.win32, "SendInput", lambda count, array, size: count)
            uia_input.press("A")
        raise UIAError("The UI element is no longer available", element_gone=True)

    with pytest.raises(UIAError):
        performer.perform(None, act)  # type: ignore[arg-type]
    assert performer.attempts == 1


def test_a_pattern_action_that_ran_counts_as_an_effect_and_one_that_raised_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from wintestkit.uia import patterns

    class Pattern:
        def Invoke(self) -> None:
            return None

    monkeypatch.setattr(patterns, "_pattern", lambda el, name: Pattern())
    monkeypatch.setattr(patterns, "uia_of", lambda el: el)
    start = effects.count()
    patterns.invoke(SimpleNamespace())  # type: ignore[arg-type]
    assert effects.count() == start + 1

    def refuse(el: Any, name: str) -> Any:
        raise ActionError("no pattern")

    monkeypatch.setattr(patterns, "_pattern", refuse)
    with pytest.raises(ActionError):
        patterns.invoke(SimpleNamespace())  # type: ignore[arg-type]
    assert effects.count() == start + 1


# -- the client's marks ------------------------------------------------------------------------


def client_with(reply: dict[str, Any]) -> tuple[InspectorClient, Any]:
    from test_inspector_client import ScriptedTransport, session

    transport = ScriptedTransport(lambda request: {"id": request["id"], **reply})
    return InspectorClient(transport, session(), request_timeout=1.0), transport


@pytest.mark.parametrize(
    ("method", "reply", "delta"),
    [
        ("act.invoke", {"result": {}}, 1),  # ran
        ("act.invoke", {"error": {"code": "objectStale", "message": "x"}}, 0),  # refused outright
        ("act.invoke", {"error": {"code": "actionFailed", "message": "x"}}, 1),  # began, failed
        ("write.call", {"error": {"code": "objectStale", "message": "x"}}, 0),
        ("write.setProperty", {"error": {"code": "writeFailed", "message": "x"}}, 1),
        ("query.find", {"error": {"code": "objectStale", "message": "x"}}, 0),  # a read
        ("read", {"result": {}}, 0),
    ],
)
def test_the_client_marks_requests_that_may_have_acted(
    method: str, reply: dict[str, Any], delta: int
) -> None:
    client, _ = client_with(reply)
    try:
        start = effects.count()
        with contextlib.suppress(InspectorError):
            client._request(method, {}, time.monotonic() + 1)  # pyright: ignore[reportPrivateUsage]
        assert effects.count() - start == delta
    finally:
        client.close()


def test_a_timed_out_action_counts_as_an_effect() -> None:
    from test_inspector_client import ScriptedTransport, session

    transport = ScriptedTransport(lambda request: None)
    client = InspectorClient(transport, session(), request_timeout=0.2)
    try:
        start = effects.count()
        with pytest.raises(InspectorError):
            client._request("act.invoke", {}, time.monotonic() + 1)  # pyright: ignore[reportPrivateUsage]
        assert effects.count() - start == 1  # the agent may have begun: never repeated
    finally:
        client.close()


# -- redacted failures still say what failed ---------------------------------------------------


SENTINEL = "PRIVATE_INPUT_SENTINEL"


def fail_sensitive(error: BaseException) -> tuple[BaseException, runtime.StepRecord]:
    records: list[runtime.StepRecord] = []
    runtime.add_step_listener(records.append)
    with (
        pytest.raises(BaseException) as raised,
        runtime.step("type", "Page.field", "*", {"text": SENTINEL}, secret=True),
    ):
        raise error
    return raised.value, records[-1]


@pytest.mark.parametrize(
    ("error", "label"),
    [
        (InspectorError(f"stale {SENTINEL}", code="objectStale"), "objectStale"),
        (InspectorError(f"late {SENTINEL}", code="timeout"), "timeout"),
        (ActionError(f"provider rejected {SENTINEL}"), "ActionError"),
        (UIAError(f"COM {SENTINEL}"), "UIAError"),
    ],
)
def test_a_redacted_action_failure_keeps_the_code_or_class_but_not_the_values(
    error: BaseException, label: str
) -> None:
    raised, record = fail_sensitive(error)
    assert isinstance(raised, ActionError)
    assert str(raised) == f"Sensitive action failed: {label} (details redacted)"
    assert SENTINEL not in str(raised) and SENTINEL not in str(record.to_dict())
    assert record.error is not None and label in record.error["message"]


def test_the_code_is_found_through_the_exceptions_a_failure_was_raised_from() -> None:
    translated = UIAError(f"The UI element is no longer available {SENTINEL}", element_gone=True)
    translated.__cause__ = stale()
    raised, _ = fail_sensitive(translated)
    assert str(raised) == "Sensitive action failed: objectStale (details redacted)"


def test_a_redacted_assertion_failure_keeps_a_code_when_there_is_one() -> None:
    records: list[runtime.StepRecord] = []
    runtime.add_step_listener(records.append)
    plain = AssertionError(f"expected {SENTINEL}")
    with (
        pytest.raises(AssertionError) as raised,
        runtime.step("expect.to_have_text", "Page.field", "*", {"expected": SENTINEL}, secret=True),
    ):
        raise plain
    assert str(raised.value) == "Sensitive assertion failed (details redacted)"
    coded = AssertionError(f"expected {SENTINEL}")
    coded.__cause__ = stale()
    with (
        pytest.raises(AssertionError) as raised,
        runtime.step("expect.to_have_text", "Page.field", "*", {"expected": SENTINEL}, secret=True),
    ):
        raise coded
    assert str(raised.value) == "Sensitive assertion failed: objectStale (details redacted)"
    assert SENTINEL not in str([record.to_dict() for record in records])


def test_a_failure_that_is_not_sensitive_is_reported_in_full() -> None:
    with (
        pytest.raises(InspectorError, match=r"Request failed\."),
        runtime.step("click", "Page.field", "*", {"text": "ordinary"}),
    ):
        raise stale()


def test_typing_into_an_ordinary_edit_whose_handle_went_stale_names_the_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The text is only hidden until the target is known not to be a password; the cause is not."""
    from wintestkit.engine import actions

    window = FakeElement("Window", "WTK Demo")
    page = StalePage(FakeApp([window]))  # type: ignore[arg-type]
    element = FakeElement("Edit", "Name", automation_id="StatusText")
    monkeypatch.setattr(model, "resolve", lambda scope, locator: element)

    def gone(self: Any, target: Any) -> bool:
        error = UIAError("The UI element is no longer available", element_gone=True)
        error.__cause__ = stale()
        raise error

    monkeypatch.setattr(actions.PasswordClassifier, "is_password", gone)
    with pytest.raises(ActionError) as raised:
        page.status.type(SENTINEL)  # type: ignore[attr-defined]
    assert "objectStale" in str(raised.value)
    assert SENTINEL not in str(raised.value)
