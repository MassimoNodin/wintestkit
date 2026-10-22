"""Unit tests for expect() with patched element reads."""

import re
import sys
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeApp, FakeElement

from wintestkit import model, runtime
from wintestkit.config import load_config
from wintestkit.engine import actions, waits
from wintestkit.engine.diagnose import Diagnostic
from wintestkit.engine.locator import Locator
from wintestkit.errors import AmbiguousElementError, ElementNotFoundError
from wintestkit.expect import expect
from wintestkit.model import Element, Elements, Page, Window


class MainPage(Page):
    window = Window(title="WTK Demo")
    status = Element(automation_id="StatusText")
    password = Element(control_type="Edit", class_name="PasswordBox")
    oks = Elements(control_type="Button", name="OK")
    slow = Element(automation_id="Slow", timeout=1.0)


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def steps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[runtime.StepRecord]:
    runtime.reset()
    runtime.set_config(load_config(tmp_path, {"timeout": 2.0}))
    fake = FakeTime()
    monkeypatch.setattr(waits, "_clock", fake.clock)
    monkeypatch.setattr(waits, "_sleep", fake.sleep)
    records: list[runtime.StepRecord] = []
    runtime.add_step_listener(records.append)
    yield records  # type: ignore[misc]
    runtime.reset()


@pytest.fixture
def page() -> MainPage:
    return MainPage(FakeApp([FakeElement("Window", "WTK Demo")]))  # type: ignore[arg-type]


class World:
    """Mutable state behind the patched resolver and text reads."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.element: FakeElement | None = FakeElement("Text", "Ready", automation_id="StatusText")
        self.text = "Ready"
        self.value = "v"
        self.count = 2
        self.error: BaseException | None = None
        self.resolves = 0
        monkeypatch.setattr(model, "resolve", self._resolve)
        monkeypatch.setattr(model, "resolve_all", self._resolve_all)
        monkeypatch.setattr(actions, "get_text", lambda el: self.text)
        monkeypatch.setattr(actions, "get_value", lambda el: self.value)

    def _resolve(self, scope: Any, locator: Locator) -> FakeElement:
        self.resolves += 1
        if self.error is not None:
            raise self.error
        assert self.element is not None
        return self.element

    def _resolve_all(self, scope: Any, locator: Locator) -> list[FakeElement]:
        return [FakeElement("Button", "OK") for _ in range(self.count)]


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> World:
    return World(monkeypatch)


def not_found(
    message: str = 'No element matches *[id="StatusText"] in Window "WTK Demo"',
) -> ElementNotFoundError:
    return ElementNotFoundError(
        Diagnostic(
            kind="not_found",
            message=message,
            locator='*[id="StatusText"]',
            searched_in='Window "WTK Demo"',
            match_count=0,
        )
    )


def test_passes_immediately(page: MainPage, world: World, steps: list[runtime.StepRecord]) -> None:
    expect(page.status).to_have_text("Ready")
    assert world.resolves == 1
    assert steps[0].action == "expect.to_have_text"
    assert steps[0].target == "MainPage.status"
    assert steps[0].locator == '*[id="StatusText"]'
    assert steps[0].args == {"expected": "Ready"}
    assert steps[0].status == "passed"


def test_passes_after_a_delay(
    page: MainPage,
    world: World,
    monkeypatch: pytest.MonkeyPatch,
    steps: list[runtime.StepRecord],
) -> None:
    polls = [0]

    def text(el: Any) -> str:
        polls[0] += 1
        return "Welcome, admin" if polls[0] >= 4 else "Invalid credentials"

    monkeypatch.setattr(actions, "get_text", text)
    expect(page.status).to_have_text("Welcome, admin")
    assert polls[0] == 4
    assert steps[0].status == "passed"


def test_failure_message_is_exact(
    page: MainPage, world: World, steps: list[runtime.StepRecord]
) -> None:
    world.text = "Invalid credentials"
    with pytest.raises(AssertionError) as exc_info:
        expect(page.status).to_have_text("Welcome, admin")
    assert str(exc_info.value) == (
        'expect(MainPage.status).to_have_text("Welcome, admin") failed after 2.0s\n'
        '  Expected: "Welcome, admin"\n'
        '  Actual: "Invalid credentials"\n'
        '  Locator: *[id="StatusText"]'
    )
    assert steps[0].status == "failed"
    assert steps[0].error is not None
    assert steps[0].error["type"] == "AssertionError"


def test_failure_after_custom_timeout(
    page: MainPage, world: World, steps: list[runtime.StepRecord]
) -> None:
    world.text = "no"
    with pytest.raises(AssertionError, match=r"failed after 0\.5s"):
        expect(page.status, timeout=0.5).to_have_text("yes")
    with pytest.raises(AssertionError, match=r"failed after 1\.0s"):
        expect(page.slow).to_have_text("yes")  # Element(timeout=1.0)


def test_never_found_appends_the_diagnostic(
    page: MainPage, world: World, steps: list[runtime.StepRecord]
) -> None:
    world.error = not_found()
    with pytest.raises(AssertionError) as exc_info:
        expect(page.status).to_have_text("x")
    message = str(exc_info.value)
    assert "  Actual: <element not found>" in message
    assert 'No element matches *[id="StatusText"] in Window "WTK Demo"' in message
    assert 'Searched in: Window "WTK Demo"' in message


def test_negation_waits_for_the_opposite(
    page: MainPage, world: World, steps: list[runtime.StepRecord]
) -> None:
    world.text = "Loading"
    with pytest.raises(AssertionError) as exc_info:
        expect(page.status).not_.to_have_text("Loading")
    assert str(exc_info.value).startswith(
        'expect(MainPage.status).not_.to_have_text("Loading") failed after 2.0s\n'
        '  Expected: not "Loading"'
    )
    world.text = "Ready"
    expect(page.status).not_.to_have_text("Loading")


def test_negation_does_not_pass_for_a_missing_element(
    page: MainPage, world: World, steps: list[runtime.StepRecord]
) -> None:
    world.error = not_found()
    with pytest.raises(AssertionError):
        expect(page.status).not_.to_have_text("x")


def test_not_to_exist(page: MainPage, world: World, steps: list[runtime.StepRecord]) -> None:
    world.error = not_found()
    expect(page.status).not_.to_exist()
    with pytest.raises(AssertionError, match="to_exist"):
        expect(page.status).to_exist()
    world.error = None
    expect(page.status).to_exist()
    with pytest.raises(AssertionError) as exc_info:
        expect(page.status).not_.to_exist()
    assert "Expected: not to exist" in str(exc_info.value)
    assert "Actual: exists" in str(exc_info.value)


def test_ambiguous_locator_fails_fast(
    page: MainPage, world: World, steps: list[runtime.StepRecord]
) -> None:
    world.error = AmbiguousElementError(
        Diagnostic(
            kind="ambiguous",
            message="2 elements match",
            locator="x",
            searched_in="Window",
            match_count=2,
        )
    )
    with pytest.raises(AmbiguousElementError):
        expect(page.status).to_have_text("x")
    assert world.resolves == 1  # no polling
    expect(page.status).to_exist()  # an ambiguous locator still exists


def test_visibility_and_hidden(
    page: MainPage, world: World, steps: list[runtime.StepRecord]
) -> None:
    expect(page.status).to_be_visible()
    expect(page.status).not_.to_be_hidden()
    assert world.element is not None
    world.element.is_offscreen = True
    expect(page.status).to_be_hidden()
    with pytest.raises(AssertionError, match="to be visible"):
        expect(page.status, timeout=0).to_be_visible()
    world.error = not_found()
    expect(page.status).to_be_hidden()
    expect(page.status).not_.to_be_visible()


def test_enabled_and_disabled(
    page: MainPage, world: World, steps: list[runtime.StepRecord]
) -> None:
    expect(page.status).to_be_enabled()
    assert world.element is not None
    world.element.is_enabled = False
    expect(page.status).to_be_disabled()
    with pytest.raises(AssertionError) as exc_info:
        expect(page.status, timeout=0).to_be_enabled()
    assert "  Actual: disabled" in str(exc_info.value)


def test_text_matching_variants(
    page: MainPage, world: World, steps: list[runtime.StepRecord]
) -> None:
    world.text = "  Welcome, admin \n"
    expect(page.status).to_have_text("Welcome, admin")  # strips
    expect(page.status).to_have_text(re.compile(r"^Welcome"))
    expect(page.status).to_contain_text("come, ad")
    with pytest.raises(AssertionError, match=r"Expected: /\^Bye/"):
        expect(page.status, timeout=0).to_have_text(re.compile("^Bye"))
    assert steps[1].args == {"expected": "/^Welcome/"}


def test_value_assertion(page: MainPage, world: World, steps: list[runtime.StepRecord]) -> None:
    world.value = "abc"
    expect(page.status).to_have_value("abc")
    expect(page.status).to_have_value(re.compile("b"))
    with pytest.raises(AssertionError, match='Actual: "abc"'):
        expect(page.status, timeout=0).to_have_value("nope")


def test_count_assertion(page: MainPage, world: World, steps: list[runtime.StepRecord]) -> None:
    expect(page.oks).to_have_count(2)
    with pytest.raises(AssertionError) as exc_info:
        expect(page.oks, timeout=0).to_have_count(3)
    assert str(exc_info.value) == (
        "expect(MainPage.oks).to_have_count(3) failed after 0.0s\n"
        "  Expected: 3\n"
        "  Actual: 2\n"
        '  Locator: Button[name="OK"]'
    )
    world.count = 0
    expect(page.oks).not_.to_have_count(2)


def test_count_needs_elements_and_other_assertions_need_one_element(
    page: MainPage, world: World, steps: list[runtime.StepRecord]
) -> None:
    with pytest.raises(TypeError, match="Elements"):
        expect(page.status).to_have_count(1)
    with pytest.raises(TypeError, match="single element"):
        expect(page.oks).to_have_text("x")


def test_checked_selected_and_property(
    page: MainPage,
    world: World,
    monkeypatch: pytest.MonkeyPatch,
    steps: list[runtime.StepRecord],
) -> None:
    from wintestkit.uia.constants import ToggleState

    state = {"toggle": ToggleState.On, "selected": True}
    monkeypatch.setattr(model.patterns, "toggle_state", lambda el: state["toggle"])
    monkeypatch.setattr(model.patterns, "is_selected", lambda el: state["selected"])
    expect_module = sys.modules["wintestkit.expect"]

    monkeypatch.setattr(expect_module.patterns, "toggle_state", lambda el: state["toggle"])
    monkeypatch.setattr(expect_module.patterns, "is_selected", lambda el: state["selected"])
    expect(page.status).to_be_checked()
    expect(page.status).to_be_selected()
    state["toggle"] = ToggleState.Off
    state["selected"] = False
    expect(page.status).not_.to_be_checked()
    expect(page.status).not_.to_be_selected()
    with pytest.raises(AssertionError, match="Actual: Off"):
        expect(page.status, timeout=0).to_be_checked()
    assert world.element is not None
    monkeypatch.setattr(
        type(world.element), "get_property", lambda self, name: "StatusText", raising=False
    )
    expect(page.status).to_have_property("AutomationId", "StatusText")
    with pytest.raises(AssertionError, match="Expected: AutomationId = "):
        expect(page.status, timeout=0).to_have_property("AutomationId", "Other")


def test_password_expectations_are_redacted(
    page: MainPage, world: World, steps: list[runtime.StepRecord]
) -> None:
    world.value = "hunter2"
    expect(page.password).to_have_value("hunter2")
    assert steps[-1].args == {"expected": "***"}


@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("negate", [False, True])
def test_password_failure_never_discloses_expected_or_actual(
    page: MainPage,
    world: World,
    steps: list[runtime.StepRecord],
    explicit: bool,
    negate: bool,
) -> None:
    assert world.element is not None
    world.element.properties["IsPassword"] = not explicit
    expected = "PRIVATE_EXPECTED_SENTINEL"
    actual = expected if negate else "PRIVATE_ACTUAL_SENTINEL"
    world.value = actual
    assertion = expect(page.status, timeout=0, secret=explicit)
    if negate:
        assertion = assertion.not_
    with pytest.raises(AssertionError) as failure:
        assertion.to_have_value(expected)
    for sentinel in (expected, actual):
        assert sentinel not in str(failure.value)
        assert sentinel not in str([record.to_dict() for record in steps])
    assert steps[-1].args == {"expected": "***"}


def test_password_property_failure_hides_wanted_text(
    page: MainPage,
    world: World,
    steps: list[runtime.StepRecord],
) -> None:
    assert world.element is not None
    world.element.properties.update(IsPassword=True, ValueValue="PRIVATE_ACTUAL_SENTINEL")
    with pytest.raises(AssertionError) as failure:
        expect(page.status, timeout=0).to_have_property("ValueValue", "PRIVATE_EXPECTED_SENTINEL")
    assert "PRIVATE_" not in str(failure.value)
    assert "PRIVATE_" not in str(steps[-1].to_dict())


def test_element_gone_during_evaluation_is_retried(
    page: MainPage,
    world: World,
    monkeypatch: pytest.MonkeyPatch,
    steps: list[runtime.StepRecord],
) -> None:
    from wintestkit.errors import UIAError

    calls = [0]

    def text(el: Any) -> str:
        calls[0] += 1
        if calls[0] < 3:
            raise UIAError("gone", element_gone=True)
        return "Ready"

    monkeypatch.setattr(actions, "get_text", text)
    expect(page.status).to_have_text("Ready")
    assert calls[0] == 3


def test_window_target(
    page: MainPage, monkeypatch: pytest.MonkeyPatch, steps: list[runtime.StepRecord]
) -> None:
    window = FakeElement("Window", "WTK Demo")
    monkeypatch.setattr(model, "resolve_window", lambda app, wl: window)
    monkeypatch.setattr(actions, "get_text", lambda el: el.name)
    expect(page.window).to_exist()
    expect(page.window).to_be_visible()
    expect(page.window).to_have_text("WTK Demo")
    assert steps[0].locator == 'Window[title="WTK Demo"]'
