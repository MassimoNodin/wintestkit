"""Patterns quoted by the user guide (docs/guide). Keep the two in sync."""

import re

import pytest
from pages import MainPage

from wintestkit import Element, Page, Window, expect


class AnyDemoWindow(Page):
    # Regular expressions match with re.search; plain strings must match exactly.
    window = Window(title=re.compile(r"^WTK Demo$"))

    sign_in = Element(control_type="Button", name=re.compile(r"^Sign\s+in$"))


class SignedInPage(MainPage):
    """Inherits every element of MainPage and adds its own."""

    welcome = Element(automation_id="StatusText", name=re.compile("^Welcome"))


def test_regular_expression_locators(main: MainPage) -> None:
    page = AnyDemoWindow(main.app)
    expect(page.window).to_be_visible()
    expect(page.sign_in).to_be_enabled()


def test_inherited_pages(main: MainPage) -> None:
    page = SignedInPage(main.app)
    page.username.type("admin")
    page.password.type("secret")
    page.sign_in.click()
    expect(page.welcome).to_exist()


def test_typing_and_keys(main: MainPage) -> None:
    main.username.type("adm")
    main.username.type("in", clear=False)  # append instead of replacing
    expect(main.username).to_have_value("admin")
    main.username.press("Ctrl+A Delete")  # key combos separated by spaces
    expect(main.username).to_have_value("")


def test_timeouts(main: MainPage) -> None:
    main.load.click()
    main.continue_button.click(timeout=5)  # per-call: wait up to 5 s for this action
    expect(main.status, timeout=5).to_contain_text("Continued")


@pytest.mark.wtk(timeout=20)  # default auto-wait for this test only
def test_a_slow_test(main: MainPage) -> None:
    main.load.click()
    expect(main.data_loaded).to_be_visible()


def test_mouse_mode_and_nth(main: MainPage) -> None:
    main.sign_in.click(mode="mouse")  # a real mouse click instead of the Invoke pattern
    expect(main.status).to_have_text("Invalid credentials")
    main.all_ok_buttons.nth(1).click()  # 0-based
    expect(main.status).to_have_text("B OK")


def test_reading_state(main: MainPage) -> None:
    assert main.sign_in.exists()
    assert not main.data_loaded.exists()
    assert main.sign_in.is_enabled()
    main.username.type("admin")
    assert main.username.value == "admin"
