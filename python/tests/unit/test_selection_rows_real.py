"""Live tests for multi-select and the grid table check in the fixture's Controls window."""

import os
import re
from dataclasses import replace

import pytest
from test_wpf_query_gate_real import _fixture_scenario, config

from wintestkit import runtime
from wintestkit.controls import DataGrid, ListBox, Text
from wintestkit.engine.resolve import Scope
from wintestkit.expect import expect
from wintestkit.model import Page, Window

pytest_plugins = ["test_wpf_query_gate_real"]

pytestmark = pytest.mark.skipif(
    os.name != "nt" or os.environ.get("WTK_INSPECTOR_REAL") != "1",
    reason="requires explicitly enabled owned Windows fixture",
)

SelectionPage = type(
    "SelectionPage",
    (Page,),
    {
        "window": Window(automation_id="ControlsWindow"),
        "effect": Text(automation_id="ControlsEffect"),
        "multi": ListBox(automation_id="MultiList"),
        "grid": DataGrid(automation_id="RowsGrid"),
    },
)

ROWS = [["Apple", "3", "Paris"], ["Banana", "5", "Rome"], ["Cherry", "7", "Oslo"]]


@pytest.fixture
def controls(owned):
    scope, path = owned
    assert isinstance(scope, Scope)
    _fixture_scenario(scope.app.pids[0], "openControls", 0)
    return SelectionPage(scope.app), path


def settings(path, backend, mode):
    return replace(config(path, "agent"), backend=backend, input_mode=mode)


@pytest.mark.parametrize("mode", ["mouse", "pattern"])
@pytest.mark.parametrize("backend", ["auto", "uia"])
def test_list_multi_select(controls, backend, mode):
    page, path = controls
    with runtime.config_scope(settings(path, backend, mode)):
        page.multi.select(["Two", "Four"])
        expect(page.effect, timeout=5).to_have_text("Selected: Two, Four")
        assert page.multi.selected_items() == ["Two", "Four"]
        page.multi.select("Six", add=True)
        expect(page.effect, timeout=5).to_have_text("Selected: Two, Four, Six")
        page.multi.deselect("Two")
        expect(page.effect, timeout=5).to_have_text("Selected: Four, Six")
        page.multi.select([0, re.compile("^Thr")])
        expect(page.effect, timeout=5).to_have_text("Selected: One, Three")
        page.multi.clear_selection()
        assert page.multi.selected_items() == []


@pytest.mark.parametrize("mode", ["mouse", "pattern"])
@pytest.mark.parametrize("backend", ["auto", "uia"])
def test_grid_row_multi_select(controls, backend, mode):
    page, path = controls
    with runtime.config_scope(settings(path, backend, mode)):
        page.grid.select([0, 2])
        assert len(page.grid.selected_items()) == 2
        page.grid.select([1], add=True)
        assert len(page.grid.selected_items()) == 3
        page.grid.deselect([0])
        assert len(page.grid.selected_items()) == 2
        page.grid.clear_selection()
        assert page.grid.selected_items() == []


@pytest.mark.parametrize("backend", ["auto", "uia"])
def test_grid_rows_checks(controls, backend):
    page, path = controls
    with runtime.config_scope(settings(path, backend, "pattern")):
        expect(page.grid, timeout=5).to_have_rows(ROWS)
        expect(page.grid).to_have_rows(
            [{"Name": "Apple", "Qty": "3"}, {"Name": "Banana", "Qty": 5}, {"Name": "Cherry"}]
        )
        expect(page.grid).to_have_rows(
            [["Paris", "Apple"], ["Rome", "Banana"], ["Oslo", "Cherry"]], columns=["City", "Name"]
        )
        expect(page.grid).to_have_rows([ROWS[2], ROWS[0], ROWS[1]], ordered=False)
        expect(page.grid).to_have_rows(
            [["Apple", re.compile(r"^\d$"), "Paris"], [re.compile("^B"), "5", "Rome"], ROWS[2]]
        )
        expect(page.grid).not_.to_have_rows(ROWS[:2])


@pytest.mark.parametrize("backend", ["auto", "uia"])
def test_grid_rows_failure_names_the_cell(controls, backend):
    page, path = controls
    with runtime.config_scope(settings(path, backend, "pattern")):
        wrong = [ROWS[0], ["Banana", "6", "Rome"], ROWS[2]]
        with pytest.raises(AssertionError) as failure:
            expect(page.grid, timeout=1).to_have_rows(wrong)
        assert "row 2, column 'Qty': expected '6', got '5'" in str(failure.value)
