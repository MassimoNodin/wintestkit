"""Unit tests for waits, using a fake clock."""

from typing import Any

import pytest
from fakes import FakeElement

from wintestkit.engine import waits
from wintestkit.engine.diagnose import Diagnostic
from wintestkit.engine.waits import element_state_ok, wait_for_state, wait_until
from wintestkit.errors import ElementNotFoundError, UIAError, WaitTimeoutError
from wintestkit.uia.element import Rect


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def fake_time(monkeypatch: pytest.MonkeyPatch) -> FakeTime:
    fake = FakeTime()
    monkeypatch.setattr(waits, "_clock", fake.clock)
    monkeypatch.setattr(waits, "_sleep", fake.sleep)
    return fake


def not_found() -> ElementNotFoundError:
    return ElementNotFoundError(
        Diagnostic(
            kind="not_found",
            message='No element matches Button[name="x"] in Window "W"',
            locator='Button[name="x"]',
            searched_in='Window "W"',
            match_count=0,
        )
    )


def test_immediate_success(fake_time: FakeTime) -> None:
    assert wait_until(lambda: "ok", 5, description="thing") == "ok"
    assert fake_time.sleeps == []


def test_success_after_n_polls(fake_time: FakeTime) -> None:
    calls = [0]

    def fn() -> str | None:
        calls[0] += 1
        return "done" if calls[0] == 4 else None

    assert wait_until(fn, 5, description="thing") == "done"
    assert calls[0] == 4
    assert fake_time.sleeps == [0.1, 0.1, 0.1]


def test_false_and_none_mean_not_yet_but_zero_is_a_value(fake_time: FakeTime) -> None:
    results: list[Any] = [False, None, 0]
    assert wait_until(lambda: results.pop(0), 5, description="x") == 0


def test_timeout_raises_wait_timeout_error(fake_time: FakeTime) -> None:
    with pytest.raises(WaitTimeoutError) as exc_info:
        wait_until(lambda: None, 1.0, description="the status to change")
    assert str(exc_info.value) == "Timed out after 1.0s waiting for the status to change"
    assert exc_info.value.waited == pytest.approx(1.0)
    assert exc_info.value.last_error is None
    assert fake_time.now == pytest.approx(1.0)


def test_timeout_reraises_locator_error_with_suffix(fake_time: FakeTime) -> None:
    def fn() -> None:
        raise not_found()

    with pytest.raises(ElementNotFoundError) as exc_info:
        wait_until(fn, 10.0, description="x")
    assert str(exc_info.value) == (
        'No element matches Button[name="x"] in Window "W" (waited 10.0s)'
    )
    assert exc_info.value.to_dict()["message"].endswith("(waited 10.0s)")


def test_locator_error_is_retried_until_it_resolves(fake_time: FakeTime) -> None:
    attempts = [0]

    def fn() -> str:
        attempts[0] += 1
        if attempts[0] < 3:
            raise not_found()
        return "found"

    assert wait_until(fn, 5, description="x") == "found"


def test_uia_error_timeout_becomes_wait_timeout_with_cause(fake_time: FakeTime) -> None:
    gone = UIAError("gone", element_gone=True)

    def fn() -> None:
        raise gone

    with pytest.raises(WaitTimeoutError) as exc_info:
        wait_until(fn, 0.5, description="x")
    assert exc_info.value.last_error is gone


def test_non_retry_exception_propagates(fake_time: FakeTime) -> None:
    def fn() -> None:
        raise KeyError("boom")

    with pytest.raises(KeyError):
        wait_until(fn, 5, description="x")
    assert fake_time.sleeps == []


def test_custom_retry_on(fake_time: FakeTime) -> None:
    calls = [0]

    def fn() -> int:
        calls[0] += 1
        if calls[0] < 2:
            raise ValueError("not yet")
        return 7

    assert wait_until(fn, 5, description="x", retry_on=(ValueError,)) == 7


def test_zero_timeout_is_a_single_attempt(fake_time: FakeTime) -> None:
    calls = [0]

    def fn() -> None:
        calls[0] += 1

    with pytest.raises(WaitTimeoutError):
        wait_until(fn, 0, description="x")
    assert calls[0] == 1
    assert fake_time.sleeps == []


def test_zero_timeout_locator_error(fake_time: FakeTime) -> None:
    def fn() -> None:
        raise not_found()

    with pytest.raises(ElementNotFoundError, match=r"\(waited 0\.0s\)"):
        wait_until(fn, 0, description="x")


def test_sleep_never_overshoots_the_deadline(fake_time: FakeTime) -> None:
    with pytest.raises(WaitTimeoutError):
        wait_until(lambda: None, 0.25, description="x")
    assert sum(fake_time.sleeps) == pytest.approx(0.25)


# -- element states -------------------------------------------------------------------------------


def test_attached_and_detached() -> None:
    element = FakeElement("Button", "x")
    assert element_state_ok(element, "attached")  # type: ignore[arg-type]
    assert not element_state_ok(element, "detached")  # type: ignore[arg-type]
    assert element_state_ok(None, "detached")
    assert not element_state_ok(None, "attached")


def test_dead_element_counts_as_detached() -> None:
    element = FakeElement("Button", "x")
    element.is_alive = lambda: False  # type: ignore[method-assign]
    assert element_state_ok(element, "detached")  # type: ignore[arg-type]


def test_visible_and_hidden() -> None:
    element = FakeElement("Button", "x")
    assert element_state_ok(element, "visible")  # type: ignore[arg-type]
    element.is_offscreen = True
    assert element_state_ok(element, "hidden")  # type: ignore[arg-type]
    assert not element_state_ok(element, "visible")  # type: ignore[arg-type]
    element.is_offscreen = False
    element.rect = None
    assert not element_state_ok(element, "visible")  # type: ignore[arg-type]
    element.rect = Rect(0, 0, 0, 5)
    assert element_state_ok(element, "hidden")  # type: ignore[arg-type]
    assert element_state_ok(None, "hidden")


def test_enabled_and_disabled() -> None:
    element = FakeElement("Button", "x")
    assert element_state_ok(element, "enabled")  # type: ignore[arg-type]
    element.is_enabled = False
    assert element_state_ok(element, "disabled")  # type: ignore[arg-type]
    assert not element_state_ok(element, "enabled")  # type: ignore[arg-type]
    assert not element_state_ok(None, "enabled")


def test_stable_compares_two_reads(fake_time: FakeTime) -> None:
    element = FakeElement("Button", "x")
    assert element_state_ok(element, "stable")  # type: ignore[arg-type]
    assert fake_time.sleeps == [waits.STABLE_INTERVAL]

    class Moving(FakeElement):
        reads = 0

        @property  # type: ignore[override]
        def rect(self) -> Rect:
            Moving.reads += 1
            return Rect(Moving.reads, 0, 5, 5)

        @rect.setter
        def rect(self, value: Any) -> None:
            pass

    assert not element_state_ok(Moving("Button", "m"), "stable")  # type: ignore[arg-type]


def test_wait_for_state_returns_the_element(fake_time: FakeTime) -> None:
    element = FakeElement("Button", "x")
    element.is_enabled = False
    polls = [0]

    def get() -> FakeElement:
        polls[0] += 1
        if polls[0] == 3:
            element.is_enabled = True
        return element

    result = wait_for_state(get, "enabled", 5, "x to be enabled")  # type: ignore[arg-type]
    assert result is element
    assert polls[0] == 3


def test_wait_for_state_detached_treats_missing_as_success(fake_time: FakeTime) -> None:
    def get() -> None:
        raise not_found()

    assert wait_for_state(get, "detached", 1, "x to disappear") is None
    assert wait_for_state(get, "hidden", 1, "x to hide") is None


def test_wait_for_state_visible_reraises_diagnostic(fake_time: FakeTime) -> None:
    def get() -> None:
        raise not_found()

    with pytest.raises(ElementNotFoundError, match=r"\(waited 1\.0s\)"):
        wait_for_state(get, "visible", 1, "x to appear")


def test_wait_for_state_timeout_message(fake_time: FakeTime) -> None:
    element = FakeElement("Button", "x")
    with pytest.raises(
        WaitTimeoutError, match=r"Timed out after 0\.5s waiting for x to be disabled"
    ):
        wait_for_state(lambda: element, "disabled", 0.5, "x to be disabled")  # type: ignore[arg-type,return-value]
