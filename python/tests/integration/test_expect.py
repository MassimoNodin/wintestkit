"""Integration tests for expect() against the demo app."""

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from pages import MainPage
from support import DemoProcess

from wintestkit import expect, runtime
from wintestkit.app import App
from wintestkit.config import load_config

pytestmark = pytest.mark.integration


@pytest.fixture
def main(demo_process: DemoProcess, tmp_path: Path) -> Iterator[MainPage]:
    runtime.reset()
    runtime.set_config(load_config(tmp_path, {"timeout": 8.0}))
    yield MainPage(App.attach(pid=demo_process.pid))
    runtime.reset()


def test_to_have_text_waits_through_the_async_load(main: MainPage) -> None:
    main.load.click()
    expect(main.status).to_have_text("Loading...")
    expect(main.status).to_have_text("Loaded")  # arrives ~2s later
    expect(main.continue_button).to_be_enabled()
    expect(main.load).to_be_disabled()  # the demo keeps Load disabled after it ran


def test_data_loaded_appears_after_load(main: MainPage) -> None:
    expect(main.data_loaded).not_.to_exist()
    main.load.click()
    expect(main.data_loaded).to_exist()
    expect(main.data_loaded).to_be_visible()
    expect(main.data_loaded).to_have_text("Data loaded")


def test_continue_is_disabled_until_loaded(main: MainPage) -> None:
    expect(main.continue_button).to_be_disabled()
    main.load.click()
    expect(main.continue_button).to_be_enabled()
    expect(main.continue_button).not_.to_be_disabled()


def test_checked_selected_text_variants(main: MainPage) -> None:
    expect(main.remember).not_.to_be_checked()
    main.remember.check()
    expect(main.remember).to_be_checked()
    expect(main.status).to_contain_text("Remember")
    expect(main.status).to_have_text(re.compile(r"^Remember: (True|False)$"))
    main.color.select("Blue")
    expect(main.status).to_have_text("Color: Blue")
    main.username.type("alice")
    expect(main.username).to_have_value("alice")
    expect(main.username).to_have_value(re.compile("^ali"))
    expect(main.status).to_have_property("AutomationId", "StatusText")


def test_failure_is_an_assertion_error_with_actual_value(main: MainPage) -> None:
    main.username.type("admin")
    main.password.type("nope")
    main.sign_in.click()
    with pytest.raises(AssertionError) as exc_info:
        expect(main.status, timeout=1).to_have_text("Welcome, admin")
    message = str(exc_info.value)
    assert message.startswith(
        'expect(MainPage.status).to_have_text("Welcome, admin") failed after 1.0s\n'
        '  Expected: "Welcome, admin"\n'
        '  Actual: "Invalid credentials"'
    )


def test_failure_for_a_missing_element_includes_the_diagnostic(main: MainPage) -> None:
    with pytest.raises(AssertionError) as exc_info:
        expect(main.data_loaded, timeout=0.5).to_be_visible()
    message = str(exc_info.value)
    assert message.startswith("expect(MainPage.data_loaded).to_be_visible() failed after 0.5s")
    assert "  Actual: does not exist" in message
    assert 'No element matches Text[name="Data loaded"] in Window "WTK Demo"' in message


def test_window_assertions(main: MainPage) -> None:
    expect(main.window).to_exist()
    expect(main.window).to_be_visible()
    expect(main.window).to_have_text("WTK Demo")
