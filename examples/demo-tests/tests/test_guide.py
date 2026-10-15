"""Patterns quoted by the user guide (docs/guide). Keep the two in sync."""

import re

import pytest
from screens import MainScreen

from wintestkit import Element, Screen, Window, expect


class AnyDemoWindow(Screen):
    # Regular expressions match with re.search; plain strings must match exactly.
    window = Window(title=re.compile(r"^WTK Demo$"))

    sign_in = Element(control_type="Button", name=re.compile(r"^Sign\s+in$"))


class SignedInScreen(MainScreen):
    """Inherits every element of MainScreen and adds its own."""

    welcome = Element(automation_id="StatusText", name=re.compile("^Welcome"))


def test_regular_expression_locators(main: MainScreen) -> None:
    screen = AnyDemoWindow(main.app)
    expect(screen.window).to_be_visible()
    expect(screen.sign_in).to_be_enabled()


def test_inherited_screens(main: MainScreen) -> None:
    screen = SignedInScreen(main.app)
    screen.username.type("admin")
    screen.password.type("secret")
    screen.sign_in.click()
    expect(screen.welcome).to_exist()


def test_typing_and_keys(main: MainScreen) -> None:
    main.username.type("adm")
    main.username.type("in", clear=False)  # append instead of replacing
    expect(main.username).to_have_value("admin")
    main.username.press("Ctrl+A Delete")  # key combos separated by spaces
    expect(main.username).to_have_value("")


def test_timeouts(main: MainScreen) -> None:
    main.load.click()
    main.continue_button.click(timeout=5)  # per-call: wait up to 5 s for this action
    expect(main.status, timeout=5).to_contain_text("Continued")


@pytest.mark.wtk(timeout=20)  # default auto-wait for this test only
def test_a_slow_test(main: MainScreen) -> None:
    main.load.click()
    expect(main.data_loaded).to_be_visible()


def test_mouse_mode_and_nth(main: MainScreen) -> None:
    main.sign_in.click(mode="mouse")  # a real mouse click instead of the Invoke pattern
    expect(main.status).to_have_text("Invalid credentials")
    main.all_ok_buttons.nth(1).click()  # 0-based
    expect(main.status).to_have_text("B OK")


def test_reading_state(main: MainScreen) -> None:
    assert main.sign_in.exists()
    assert not main.data_loaded.exists()
    assert main.sign_in.is_enabled()
    main.username.type("admin")
    assert main.username.value == "admin"
