"""WPFObject and Window label steps, navigation and the Name property on the owned WPF fixture.

Written against the fixture's main window; like the other ``*_real`` suites it needs the owned
fixture (``WTK_INSPECTOR_REAL=1``) and a desktop, so it is skipped by default.
"""

from __future__ import annotations

import os
from dataclasses import replace

import pytest
from test_wpf_query_gate_real import config

from wintestkit import runtime
from wintestkit.finders import find_child, from_label

pytest_plugins = ["test_wpf_query_gate_real"]

pytestmark = pytest.mark.skipif(
    os.name != "nt" or os.environ.get("WTK_INSPECTOR_REAL") != "1",
    reason="requires explicitly enabled owned Windows fixture",
)

TITLE = "WinTestKit WPF Fixture"


@pytest.fixture
def app(owned):
    scope, path = owned
    with runtime.config_scope(replace(config(path, "agent"), backend="auto")):
        yield scope.app


def main_view(app):
    """The fixture window's root visual, the way a migrated chain reaches it."""
    return app.WPFObject("HwndSource: MainWindow", TITLE).WPFObject("MainWindow", TITLE)


def test_window_node_and_root_visual(app):
    node = app.wpf_object("HwndSource: MainWindow", "WinTestKit*")
    root = node.wpf_object("MainWindow", "WinTestKit*")
    assert node.resolve().same_as(root.resolve())
    assert node.label == f'WPFObject("HwndSource: MainWindow", "{TITLE}")'
    assert node.parent is None and node.child_count == 1
    assert root.parent is not None and root.parent.label == node.label
    # The Name property finds the same node within two levels from the application.
    by_name = find_child(app, "Name", 'WPFObject("HwndSource: MainWindow", "WinTestKit*")', 2)
    assert by_name.resolve().same_as(node.resolve())


def test_list_items_by_text_and_ordinal(app):
    box = find_child(main_view(app), "WPFControlName", "ParityList", 20)
    items = box.children()
    assert [item.get("wpf:Text") for item in items] == ["Alpha", "Beta", "Gamma"]
    assert items[1].label == 'WPFObject("ListBoxItem", "Beta")'
    beta = box.wpf_object("ListBoxItem", "Beta")
    assert beta.resolve().same_as(items[1].resolve())
    for selected in (
        box.wpf_object("ListBoxItem", "", 2),  # the ordinal; the text is not checked
        box.wpf_object("ListBoxItem", "*", 2),
        box.wpf_object("ListBoxItem", 2),
        box.wpf_object("ListBoxItem", "Be*", 2),
        box.wpf_object("ListBoxItem", "*a", 2),
    ):
        assert selected.resolve().same_as(beta.resolve())
    assert not box.wpf_object("ListBoxItem", "Alpha", 2).exists()
    assert not box.wpf_object("ListBoxItem", "Delta").exists()
    assert box.child_count == 3


def test_grid_row_and_cell_chain(app):
    grid = find_child(main_view(app), "WPFControlName", "ParityGrid", 20)
    row = grid.wpf_object("DataGridRow", "", 2)
    cell = row.wpf_object("DataGridCell", "*", 2)
    assert cell.get("wpf:Text") == "Two"
    # The whole chain from the process parses back to the same cell.
    again = from_label(app, cell.full_name)
    assert again.resolve().same_as(cell.resolve())
    assert cell.parent is not None and cell.parent.resolve().same_as(row.resolve())


def test_combo_popup_is_a_window_node(app):
    combo = find_child(main_view(app), "WPFControlName", "ParityCombo", 20)
    combo.click()
    popup = app.wpf_object("HwndSource: PopupRoot", "")
    item = popup.wpf_object("PopupRoot", "").wpf_object("ComboBoxItem", "Beta")
    assert item.get("wpf:Text") == "Beta"
    assert from_label(app, item.full_name).resolve().same_as(item.resolve())


def test_every_element_below_the_root_round_trips(app):
    seen = 0
    pending = [main_view(app)]
    while pending and seen < 60:
        element = pending.pop()
        seen += 1
        assert from_label(app, element.full_name).resolve().same_as(element.resolve())
        for child in element.children():
            assert child.parent is not None and child.parent.resolve().same_as(element.resolve())
            pending.append(child)
    assert seen > 10
