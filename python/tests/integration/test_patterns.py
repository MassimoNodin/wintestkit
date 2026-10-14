"""Integration tests for the pattern wrappers against the demo app."""

import time
from collections.abc import Callable

import pytest
from support import DemoProcess

from wintestkit.errors import ActionError
from wintestkit.uia import com, element, patterns, win32
from wintestkit.uia.constants import TreeScope
from wintestkit.uia.element import UIAElement

pytestmark = pytest.mark.integration

BUTTON, EDIT, CHECKBOX, COMBOBOX, LISTITEM, LIST, GROUP, DATAGRID, TEXT = (
    50000,
    50004,
    50002,
    50003,
    50007,
    50008,
    50026,
    50028,
    50020,
)


def find(root: UIAElement, **props: object) -> UIAElement:
    found = root.find_first(TreeScope.Descendants, com.create_condition(**props))
    assert found is not None, f"element {props} not found"
    return found


def wait_for(predicate: Callable[[], object], timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert predicate()


class Demo:
    def __init__(self, demo: DemoProcess) -> None:
        self.demo = demo
        self.window = element.from_handle(demo.hwnd)
        self.status = find(self.window, automation_id="StatusText")

    def expect_status(self, text: str) -> None:
        wait_for(lambda: self.status.name == text)
        assert self.status.name == text


@pytest.fixture
def demo(demo_process: DemoProcess) -> Demo:
    return Demo(demo_process)


def test_invoke_panel_a_ok(demo: Demo) -> None:
    panel = find(demo.window, control_type=GROUP, name="Panel A")
    ok = find(panel, control_type=BUTTON, name="OK")
    assert patterns.has_pattern(ok, "Invoke")
    patterns.invoke(ok)
    demo.expect_status("A OK")


def test_value_pattern(demo: Demo) -> None:
    box = find(demo.window, control_type=EDIT, class_name="TextBox")
    patterns.set_value(box, "admin")
    assert patterns.get_value(box) == "admin"
    assert patterns.is_read_only(box) is False


def test_toggle_remember_me(demo: Demo) -> None:
    box = find(demo.window, control_type=CHECKBOX, name="Remember me")
    assert patterns.toggle_state(box).name == "Off"
    patterns.toggle(box)
    demo.expect_status("Remember: True")
    assert patterns.toggle_state(box).name == "On"


def test_combo_expand_select_collapse(demo: Demo) -> None:
    combo = find(demo.window, automation_id="ColorCombo")
    patterns.expand(combo)
    wait_for(lambda: patterns.expand_state(combo).name == "Expanded")
    green = find(combo, control_type=LISTITEM, name="Green")
    patterns.select_item(green)
    assert patterns.is_selected(green)
    patterns.collapse(combo)
    wait_for(lambda: patterns.expand_state(combo).name == "Collapsed")
    demo.expect_status("Color: Green")
    assert [e.name for e in patterns.selection(combo)] == ["Green"]


def test_virtualized_list_item(demo: Demo) -> None:
    items = find(demo.window, control_type=LIST, class_name="ListBox")
    assert patterns.has_pattern(items, "ItemContainer")
    item = patterns.find_item_by_property(items, None, "Name", "Item 400")
    assert item is not None
    patterns.realize(item)
    patterns.scroll_into_view(item)
    patterns.select_item(item)
    demo.expect_status("Selected: Item 400")
    assert patterns.find_item_by_property(items, None, "Name", "No such item") is None
    first = patterns.find_item_by_property(items, None, None, None)
    assert first is not None
    print(f"first container item: {first.info().short()}")


def test_scroll_pattern(demo: Demo) -> None:
    items = find(demo.window, control_type=LIST, class_name="ListBox")
    _, before = patterns.scroll_percent(items)
    patterns.scroll(items, vertical="large_inc")
    wait_for(lambda: patterns.scroll_percent(items)[1] > before)
    patterns.set_scroll_percent(items, -1, 0)
    wait_for(lambda: patterns.scroll_percent(items)[1] == 0)


def test_grid_and_table(demo: Demo) -> None:
    grid = find(demo.window, control_type=DATAGRID)
    assert patterns.grid_size(grid) == (200, 3)
    cell = patterns.grid_item(grid, 150, 1)
    # Record whether GetItem realizes/scrolls the row: the cell is returned either way.
    print(f"grid_item(150, 1) -> {cell.info().short()} offscreen={cell.is_offscreen}")
    assert cell.name == "Product 151"
    headers = patterns.column_headers(grid)
    assert [h.name for h in headers] == ["Id", "Name", "Qty"]


def test_window_close_note_dialog(demo: Demo) -> None:
    assert win32.bring_to_foreground(demo.demo.hwnd)
    patterns.invoke(find(demo.window, control_type=BUTTON, name="Open dialog"))
    dialog_hwnd = 0
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not dialog_hwnd:
        for hwnd in win32.top_level_windows({demo.demo.pid}):
            if win32.window_text(hwnd) == "WTK Demo - Dialog":
                dialog_hwnd = hwnd
        time.sleep(0.05)
    assert dialog_hwnd
    dialog = element.from_handle(dialog_hwnd)
    assert patterns.window_is_modal(dialog)
    assert win32.window_owner(dialog_hwnd) == demo.demo.hwnd
    patterns.window_close(dialog)
    wait_for(lambda: dialog_hwnd not in win32.top_level_windows({demo.demo.pid}))
    demo.expect_status("Note cancelled")


def test_window_set_state(demo: Demo) -> None:
    patterns.window_set_state(demo.window, "minimized")
    wait_for(lambda: win32.IsIconic(demo.demo.hwnd))
    patterns.window_set_state(demo.window, "normal")
    wait_for(lambda: not win32.IsIconic(demo.demo.hwnd))
    with pytest.raises(ValueError, match="state"):
        patterns.window_set_state(demo.window, "huge")


def test_unsupported_pattern_raises_action_error(demo: Demo) -> None:
    status = demo.status
    assert not patterns.has_pattern(status, "Invoke")
    with pytest.raises(
        ActionError, match=r"Text #StatusText .* does not support the Invoke pattern"
    ):
        patterns.invoke(status)
    with pytest.raises(ValueError, match="unknown UIA pattern"):
        patterns.has_pattern(status, "Nope")


def test_legacy_default_action_on_button(demo: Demo) -> None:
    ok = find(find(demo.window, control_type=GROUP, name="Panel B"), control_type=BUTTON, name="OK")
    if patterns.has_pattern(ok, "LegacyIAccessible"):
        patterns.legacy_default_action(ok)
        demo.expect_status("B OK")
