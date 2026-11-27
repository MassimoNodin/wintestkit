"""Migration helpers against the owned .NET fixture (written for the live run, never part of
the unit suite: it needs ``WTK_INSPECTOR_REAL=1`` and a visible desktop)."""

import os

import pytest
from test_wpf_query_gate_real import config, owned  # noqa: F401  (the fixture and its config)

from wintestkit import finders, keyboard, runtime, soft
from wintestkit.controls import Button, ComboBox, ListBox, Text, TextBox
from wintestkit.expect import expect
from wintestkit.model import Element, Page

pytestmark = pytest.mark.skipif(
    os.name != "nt" or os.environ.get("WTK_INSPECTOR_REAL") != "1",
    reason="requires explicitly enabled owned Windows fixture",
)


class FixturePage(Page):
    fancy = Button(automation_id="FancyAutomationId")
    effect = Text(automation_id="ActionEffect")
    pointer = Element(automation_id="ParityPointer")
    pointer_effect = Element(automation_id="ParityInteractionEffect")
    rows = ListBox(automation_id="ParityList")
    combo = ComboBox(automation_id="ParityCombo")
    disabled = Button(automation_id="ParityDisabled")
    source = TextBox(automation_id="BindingSource")
    missing = Element(automation_id="NoSuchElement", timeout=0.5)


@pytest.fixture
def page(owned):  # noqa: F811
    scope, path = owned
    soft.clear()
    runtime.set_current_app(scope.app)
    with runtime.config_scope(config(path, "agent")):
        yield FixturePage(scope.app)
    soft.clear()


def test_centre_click_with_a_modifier_and_a_computed_offset(page):
    page.fancy.click(x=-1, y=-1, modifiers="Shift")
    expect(page.effect, timeout=5).to_have_text("Clicked 1")
    page.fancy.click(x=page.fancy.width - 5, y=-1)
    expect(page.effect, timeout=5).to_have_text("Clicked 2")
    assert page.fancy.width > 5 and page.fancy.height > 5


def test_double_click_drag_and_wheel_at_the_centre(page):
    page.pointer.double_click(x=-1, y=-1)
    expect(page.pointer_effect, timeout=5).to_have_text("Double clicked")
    page.pointer.drag(-1, -1, 4, 0, modifiers="Shift")
    page.rows.scroll(-1, x=-1, y=-1)
    page.rows.scroll(1)


def test_checks_use_the_old_property_and_condition_names(page):
    check = finders.check_property
    assert check(page.fancy, "WPFControlText", "equal", "Fancy action")
    assert check(page.fancy, "WPFControlText", "contains", "Fancy")
    assert check(page.fancy, "Exists", "equal", True)
    assert check(page.fancy, "VisibleOnScreen", "equal", "True")
    assert check(page.fancy, "IsEnabled", "equal", True)
    assert check(page.disabled, "Enabled", "equal", False)
    assert check(page.rows, "wItemCount", "equal", 3)
    assert check(page.rows, "wItemCount", "greaterOrEqual", 2)
    assert check(page.rows, "wItemCount", "lessOrEqual", 3)
    assert check(page.rows, "wItemList", "contains", "Beta")
    assert check(page.combo, "wItemCount", "notEqual", 0)
    assert check(page.rows, "Items.Count", "equal", "3")
    assert check(page.rows, "Items.Count.OleValue", "equal", 3)
    assert check(page.rows, "ChildCount", "greaterOrEqual", 1)
    assert check(page.missing, "Exists", "equal", False, timeout=0)


def test_a_failed_check_names_the_expected_actual_and_condition(page):
    with pytest.raises(AssertionError, match=r"Expected: wItemCount >= 4(.|\n)*Actual: 3"):
        finders.check_property(page.rows, "wItemCount", "greaterOrEqual", 4, timeout=0.5)


def test_soft_checks_let_the_test_continue(page):
    assert not finders.check_property(page.rows, "wItemCount", "equal", 9, timeout=0, soft=True)
    expect(page.fancy, timeout=0, soft=True).to_have_property("wpf:Text", "Other")
    assert finders.check_property(page.rows, "wItemCount", "equal", 3, soft=True)
    errors = soft.drain()
    assert len(errors) == 2 and "Actual: 3" in errors[0].message


def test_waits_return_booleans_and_never_raise(page):
    assert finders.wait_property(page.fancy, "Exists", True, 2000) is True
    assert finders.wait_property(page.fancy, "Enabled", True, 2000) is True
    assert finders.wait_property(page.fancy, "VisibleOnScreen", True, 2000) is True
    assert finders.wait_property(page.rows, "wItemCount", 3, 2000) is True
    assert finders.wait_property(page.missing, "Exists", False, 2000) is True
    assert finders.wait_property(page.missing, "Exists", True, 600) is False
    assert finders.wait_property(page.rows, "wItemCount", 99, 600) is False


def test_keys_of_a_migrated_suite_edit_a_text_box(page):
    finders.send_keys(page.source, "^a[Del]hello")
    expect(page.source, timeout=5).to_have_text("hello")
    page.source.activate()
    page.source.focus()
    keyboard.keys("^a[Del]")  # the desktop-level form goes to the focused control
    expect(page.source, timeout=5).to_have_text("")
    assert page.source.refresh() is not None
