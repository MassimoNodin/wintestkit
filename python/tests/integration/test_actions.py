"""Integration tests for engine actions against the demo app."""

import re
import time
from collections.abc import Callable

import pytest
from support import DemoProcess, window_props

from wintestkit.app import App
from wintestkit.engine import actions
from wintestkit.engine.locator import Locator, WindowLocator
from wintestkit.engine.resolve import Scope, resolve
from wintestkit.errors import ActionError, ElementNotFoundError
from wintestkit.uia import win32
from wintestkit.uia.element import UIAElement

pytestmark = pytest.mark.integration


class Demo:
    def __init__(self, demo: DemoProcess) -> None:
        self.demo = demo
        self.scope = Scope(App.attach(pid=demo.pid))

    def find(self, **kwargs: object) -> UIAElement:
        return resolve(self.scope, Locator(**kwargs))  # type: ignore[arg-type]

    def button(self, name: str, **kwargs: object) -> UIAElement:
        return self.find(control_type="Button", name=name, **kwargs)

    @property
    def username(self) -> UIAElement:
        return self.find(control_type="Edit", class_name="TextBox")

    @property
    def password(self) -> UIAElement:
        return self.find(control_type="Edit", class_name="PasswordBox")

    def status(self) -> str:
        return actions.get_text(self.find(automation_id="StatusText"))

    def expect_status(self, text: str, timeout: float = 5.0) -> None:
        wait_for(lambda: self.status() == text, timeout, f"status {text!r}, got {self.status()!r}")

    def panel_ok(self, panel: str) -> UIAElement:
        within = Locator(control_type="Group", name=panel)
        return resolve(self.scope, Locator(control_type="Button", name="OK", within=within))


def wait_for(predicate: Callable[[], object], timeout: float = 5.0, message: str = "") -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert predicate(), message


@pytest.fixture
def demo(demo_process: DemoProcess) -> Demo:
    return Demo(demo_process)


@pytest.mark.parametrize("mode", ["pattern", "mouse"])
def test_login_success_and_failure(demo: Demo, mode: str) -> None:
    assert actions.type_text(demo.username, "admin") == "value"
    actions.type_text(demo.password, "wrong")
    strategy = actions.click(demo.button("Sign in"), mode=mode)  # type: ignore[arg-type]
    assert strategy == ("invoke" if mode == "pattern" else "mouse")
    demo.expect_status("Invalid credentials")

    actions.type_text(demo.password, "secret")
    actions.click(demo.button("Sign in"), mode=mode)  # type: ignore[arg-type]
    demo.expect_status("Welcome, admin")


def test_type_text_with_keys(demo: Demo) -> None:
    box = demo.username
    assert actions.type_text(box, "héllo", keys=True) == "keys"
    wait_for(lambda: actions.get_value(box) == "héllo")
    assert actions.type_text(box, " world", clear=False) == "value"
    assert actions.get_value(box) == "héllo world"
    actions.clear(box)
    assert actions.get_value(box) == ""
    actions.type_text(box, "abc", keys=True)
    wait_for(lambda: actions.get_value(box) == "abc")
    actions.type_text(box, "xyz", keys=True)  # clears first
    wait_for(lambda: actions.get_value(box) == "xyz")


def test_password_box_append_falls_back_to_keys(demo: Demo) -> None:
    box = demo.password
    actions.type_text(box, "sec")
    assert actions.type_text(box, "ret", clear=False) == "keys"
    actions.type_text(demo.username, "admin")
    actions.click(demo.button("Sign in"))
    demo.expect_status("Welcome, admin")


def test_panels_a_and_b(demo: Demo) -> None:
    assert actions.click(demo.panel_ok("Panel A")) == "invoke"
    demo.expect_status("A OK")
    actions.click(demo.panel_ok("Panel B"))
    demo.expect_status("B OK")


def test_remember_me(demo: Demo) -> None:
    box = demo.find(control_type="CheckBox", name="Remember me")
    actions.set_checked(box, True)
    assert actions.is_checked(box)
    demo.expect_status("Remember: True")
    actions.set_checked(box, True)  # already on: no change
    actions.set_checked(box, False)
    assert not actions.is_checked(box)
    demo.expect_status("Remember: False")
    assert actions.click(box) == "toggle"
    assert actions.is_checked(box)


def test_combo_select_by_name_and_index(demo: Demo) -> None:
    combo = demo.find(automation_id="ColorCombo")
    actions.select(combo, "Blue")
    demo.expect_status("Color: Blue")
    assert actions.selected_items(combo) == ["Blue"]
    actions.select(combo, 0)
    demo.expect_status("Color: Red")
    actions.select(combo, re.compile("^Gr"))
    demo.expect_status("Color: Green")
    with pytest.raises(ElementNotFoundError) as exc_info:
        actions.select(combo, "Purple")
    assert str(exc_info.value) == (
        'No item "Purple" in ComboBox #ColorCombo (available: "Red", "Green", "Blue")'
    )


def test_listbox_select_virtualized_item(demo: Demo) -> None:
    items = demo.find(control_type="List", class_name="ListBox")
    actions.select(items, "Item 450")
    demo.expect_status("Selected: Item 450")
    assert actions.selected_items(items) == ["Item 450"]
    actions.select(items, 3)
    demo.expect_status("Selected: Item 4")
    with pytest.raises(ElementNotFoundError, match='No item "Nope"'):
        actions.select(items, "Nope")


def test_datagrid_select_row_by_index(demo: Demo) -> None:
    grid = demo.find(control_type="DataGrid")
    actions.select(grid, 120)
    demo.expect_status("Row: Product 121")
    with pytest.raises(ElementNotFoundError):
        actions.select(grid, 500)


def test_select_unsupported_element(demo: Demo) -> None:
    with pytest.raises(ActionError, match="select\\(\\) is not supported on"):
        actions.select(demo.button("Sign in"), "x")


def test_file_reset_through_menu_clicks(demo: Demo) -> None:
    actions.type_text(demo.username, "admin")
    actions.type_text(demo.password, "secret")
    actions.click(demo.button("Sign in"))
    demo.expect_status("Welcome, admin")
    assert actions.click(demo.find(control_type="MenuItem", name="File")) == "expand_collapse"
    reset = demo.find(control_type="MenuItem", name="Reset")
    actions.click(reset)
    demo.expect_status("Ready")
    assert actions.get_value(demo.username) == ""


def test_alt_f4_closes_the_dialog(demo: Demo) -> None:
    actions.click(demo.button("Open dialog"))
    dialog = WindowLocator(title="WTK Demo - Dialog")
    wait_for(lambda: "WTK Demo - Dialog" in window_props(demo.scope.app, "name"))
    save = resolve(demo.scope, Locator(control_type="Button", name="Save", window=dialog))
    actions.press(save, "Alt+F4")
    wait_for(lambda: "WTK Demo - Dialog" not in window_props(demo.scope.app, "name"))
    demo.expect_status("Note cancelled")


def test_double_click_right_click_hover(demo: Demo) -> None:
    status = demo.find(automation_id="StatusText")
    assert win32.bring_to_foreground(demo.demo.hwnd)
    actions.hover(status)
    actions.double_click(status)
    actions.right_click(status)
    actions.press(demo.username, "Esc")
    assert actions.get_text(status) == "Ready"
    with pytest.raises(ActionError, match="cannot take keyboard focus"):
        actions.focus(status)


def test_focus_and_press_keys_in_edit(demo: Demo) -> None:
    box = demo.username
    actions.focus(box)
    assert box.has_keyboard_focus
    actions.press(box, "A B")
    wait_for(lambda: actions.get_value(box) == "ab")


def test_ensure_visible_after_selecting_a_far_item(demo: Demo) -> None:
    items = demo.find(control_type="List", class_name="ListBox")
    actions.select(items, "Item 300")
    item = demo.find(control_type="ListItem", name="Item 300")
    actions.ensure_visible(item)
    assert not item.is_offscreen


def test_get_text_variants(demo: Demo) -> None:
    assert actions.get_text(demo.find(automation_id="StatusText")) == "Ready"
    actions.type_text(demo.username, "abc")
    assert actions.get_text(demo.username) == "abc"
    actions.type_text(demo.password, "secret")
    assert actions.get_text(demo.password) != "secret"  # never reads password text
