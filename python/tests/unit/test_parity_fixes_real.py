"""Migration lookups against the owned WPF fixture: parents, unreadable candidates, nested types.

These need the interactive fixture application (``WTK_INSPECTOR_REAL=1``) and are not run in the
unit suite.
"""

import os
from dataclasses import replace

import pytest
from test_wpf_query_gate_real import config

from wintestkit import runtime
from wintestkit.errors import ElementNotFoundError
from wintestkit.finders import find_all_children, find_child
from wintestkit.model import Element, Page

pytest_plugins = ["test_wpf_query_gate_real"]

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.name != "nt" or os.environ.get("WTK_INSPECTOR_REAL") != "1",
        reason="requires explicitly enabled owned Windows fixture",
    ),
]


class FixturePage(Page):
    panel = Element(automation_id="MainPanel")
    grid = Element(automation_id="ParityGrid")


def auto(path):
    return runtime.config_scope(replace(config(path, "agent"), backend="auto"))


def test_app_level_result_is_a_parent_in_its_own_window(owned):
    """A window found from the application resolves its children there, not in the main window."""
    scope, path = owned
    with auto(path):
        main = scope.app.main_window()
        window = find_child(scope.app, "WndCaption", main.name, 1)
        assert window.resolve_once().same_as(main)
        # The panel is a descendant of the found window: found through it, then through the panel.
        panel = find_child(window, "WPFControlName", "MainPanel", 20)
        button = find_child(panel, "WPFControlName", "FancyAutomationId", 20)
        assert button.resolve_once().same_as(
            find_child(scope.app, "WPFControlName", "FancyAutomationId", 20).resolve_once()
        )
        assert [
            item.resolve_once()
            for item in find_all_children(window, "WPFControlName", "Duplicate", 20)
        ]


def test_whole_window_query_survives_objects_met_twice(owned):
    """``DataContext.Cycle`` is the view model itself: a path that returns to an earlier object."""
    scope, path = owned
    with auto(path):
        matches = find_all_children(scope.app, "DataContext.Cycle.Label", "fixture", None)
        assert len(matches) > 1
        assert all(item.resolve_once() for item in matches[:5])
        # The same query with a type condition finds the same elements the view model reaches.
        typed = find_all_children(
            scope.app, ["ClrClassName", "DataContext.Cycle.Label"], ["Button", "fixture"], None
        )
        assert 0 < len(typed) <= len(matches)


def test_unreadable_candidates_are_non_matches_and_counted(owned):
    scope, path = owned
    with auto(path):
        # DataContext.Customer is an object, not a value: every candidate that has one is unreadable.
        missing = find_child(scope.app, "DataContext.Customer", "x", None)
        with pytest.raises(
            ElementNotFoundError, match=r"candidates? could not be read \(unsupported"
        ):
            missing.resolve_once()
        # A search for a readable value is not aborted by those candidates.
        found = find_child(scope.app, "DataContext.Label", "fixture", None)
        assert found.resolve_once()


def test_nested_type_reads_on_elements_rows_and_cells(owned):
    scope, path = owned
    page = FixturePage(scope.app)
    with auto(path):
        assert page.panel.get("type:Name@DataContext") == "ViewModel"
        assert page.panel.get("type:FullName@DataContext").endswith("ViewModel")
        row, cell = page.grid.row(0), page.grid.cell(0, 0)
        # Rows and cells come from UI Automation: managed reads go through their WPF object.
        assert row.get("clr:DataContext.Name") == "First"
        assert cell.get("type:FullName@DataContext") == row.get("type:FullName@DataContext")
        assert cell.get("clr:IsEnabled") is True
        assert cell.get("type:Name") == "DataGridCell"


def test_offscreen_realized_list_item_scrolls_into_view(owned):
    scope, path = owned
    with auto(path):
        item = find_child(
            scope.app, ["ClrClassName", "WPFControlText"], ["ListBoxItem", "Six"], None
        )
        item.scroll_into_view()
        assert not item.resolve().is_offscreen
