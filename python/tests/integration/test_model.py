"""Integration tests for the Page / Element model against the demo app."""

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from pages import MainPage, MessageBoxPage, NoteDialogPage
from support import DemoProcess

from wintestkit import Element, expect, runtime
from wintestkit.app import App
from wintestkit.config import load_config
from wintestkit.errors import AmbiguousElementError, ElementNotFoundError

pytestmark = pytest.mark.integration


@pytest.fixture
def app(demo_process: DemoProcess, tmp_path: Path) -> Iterator[App]:
    runtime.reset()
    runtime.set_config(load_config(tmp_path, {"timeout": 8.0}))
    yield App.attach(pid=demo_process.pid)
    runtime.reset()


@pytest.fixture
def main(app: App) -> MainPage:
    return MainPage(app)


@pytest.fixture
def steps() -> list[runtime.StepRecord]:
    records: list[runtime.StepRecord] = []
    runtime.add_step_listener(records.append)
    return records


def test_login_success_and_failure(main: MainPage, steps: list[runtime.StepRecord]) -> None:
    main.username.type("admin")
    main.password.type("wrong")
    main.sign_in.click()
    expect(main.status).to_have_text("Invalid credentials")
    main.password.type("secret")
    main.sign_in.click()
    expect(main.status).to_have_text("Welcome, admin")

    actions = [(s.action, s.target) for s in steps]
    assert ("type", "MainPage.username") in actions
    assert ("click", "MainPage.sign_in") in actions
    password_steps = [s for s in steps if s.target == "MainPage.password"]
    assert password_steps
    assert all(s.args["text"] == "***" for s in password_steps)
    assert "secret" not in str([s.to_dict() for s in steps])


def test_panel_ok_buttons_and_ambiguity(main: MainPage) -> None:
    main.ok_b.click()
    expect(main.status).to_have_text("B OK")
    main.ok_a.click()
    expect(main.status).to_have_text("A OK")

    class Ambiguous(MainPage):
        either_ok = Element(control_type="Button", name="OK", timeout=0.2)

    with pytest.raises(AmbiguousElementError) as exc_info:
        Ambiguous(main.app).either_ok.click()
    assert str(exc_info.value) == (
        '2 elements match Button[name="OK"] in Window "WTK Demo"; add within= or index= to pick one'
    )
    Ambiguous(main.app).either_ok.nth(1).click()  # index= picks Panel B
    expect(main.status).to_have_text("B OK")


def test_async_load_then_continue_auto_waits_for_enabled(main: MainPage) -> None:
    expect(main.data_loaded).not_.to_exist()
    main.load.click()
    expect(main.status).to_have_text("Loading...")
    main.continue_button.click()  # disabled for ~2s: click auto-waits
    expect(main.status).to_have_text("Continued")
    expect(main.data_loaded).to_exist()


def test_dialog_save_flow(main: MainPage) -> None:
    main.open_dialog.click()
    dialog = NoteDialogPage(main.app)
    dialog.window.wait_for("visible")
    dialog.note.type("hello note")
    dialog.save.click()
    expect(main.status).to_have_text("Note: hello note")
    expect(dialog.window).not_.to_exist()


def test_dialog_cancel_flow(main: MainPage) -> None:
    main.open_dialog.click()
    dialog = NoteDialogPage(main.app)
    dialog.cancel.click()
    expect(main.status).to_have_text("Note cancelled")


def test_message_box_ok(main: MainPage) -> None:
    main.show_message.click()
    box = MessageBoxPage(main.app)
    expect(box.window).to_exist()
    box.ok.click()
    expect(main.status).to_have_text("Message closed")


def test_remember_me_and_menu_reset(main: MainPage) -> None:
    main.remember.check()
    expect(main.status).to_have_text("Remember: True")
    assert main.remember.is_checked()
    main.remember.uncheck()
    expect(main.status).to_have_text("Remember: False")
    main.username.type("someone")
    main.menu_file.click()
    main.menu_reset.click()
    expect(main.status).to_have_text("Ready")
    expect(main.username).to_have_value("")


def test_select_in_combo_list_and_grid(main: MainPage) -> None:
    main.color.select("Green")
    expect(main.status).to_have_text("Color: Green")
    main.items.select("Item 450")
    expect(main.status).to_have_text("Selected: Item 450")
    main.products.select(120)
    expect(main.status).to_have_text("Row: Product 121")


def test_page_check_reports_missing_elements(main: MainPage) -> None:
    results = main.check()
    assert results["sign_in"] is None
    assert results["username"] is None
    assert results["all_oks"] is None
    assert isinstance(results["data_loaded"], ElementNotFoundError)  # collapsed until loaded
    assert isinstance(results["menu_reset"], ElementNotFoundError)  # menu closed


def test_failure_diagnostic_for_a_misspelled_locator(main: MainPage) -> None:
    class Typo(MainPage):
        sign_in = Element(control_type="Button", name="Sign In", timeout=0.3)

    with pytest.raises(ElementNotFoundError) as exc_info:
        Typo(main.app).sign_in.click()
    assert 'closest: Button "Sign in" — name differs' in str(exc_info.value)
    assert "(waited 0.3s)" in str(exc_info.value)


def test_expect_failure_message(main: MainPage) -> None:
    with pytest.raises(AssertionError) as exc_info:
        expect(main.status, timeout=0.3).to_have_text("Welcome, nobody")
    assert str(exc_info.value) == (
        'expect(MainPage.status).to_have_text("Welcome, nobody") failed after 0.3s\n'
        '  Expected: "Welcome, nobody"\n'
        '  Actual: "Ready"\n'
        '  Locator: *[id="StatusText"]'
    )


def test_text_value_info_and_waits(main: MainPage) -> None:
    assert main.status.text == "Ready"
    main.username.type("abc")
    assert main.username.value == "abc"
    assert main.sign_in.is_enabled()
    info = main.sign_in.info()
    assert info.control_type == "Button"
    assert info.patterns is not None
    assert "Invoke" in info.patterns
    assert main.sign_in.exists()
    assert main.sign_in.is_visible()
    assert not main.data_loaded.exists()
    assert main.sign_in.wait_for("enabled") is not None
    main.username.clear()
    assert main.username.value == ""
    assert re.fullmatch(r"<BoundElement MainPage\.sign_in .*>", repr(main.sign_in))


def test_window_operations(main: MainPage) -> None:
    assert main.window.title == "WTK Demo"
    main.window.minimize()
    main.window.restore()
    expect(main.window).to_be_visible()
    main.window.maximize()
    main.window.restore()
