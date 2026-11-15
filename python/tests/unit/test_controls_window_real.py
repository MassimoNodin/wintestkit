"""Live smoke test for the fixture's Controls window (openControls scenario)."""

import os
from dataclasses import replace

import pytest
from test_wpf_query_gate_real import _fixture_scenario, config

from wintestkit import runtime
from wintestkit.engine.resolve import Scope
from wintestkit.expect import expect
from wintestkit.model import Element, Page, Window

pytest_plugins = ["test_wpf_query_gate_real"]

pytestmark = pytest.mark.skipif(
    os.name != "nt" or os.environ.get("WTK_INSPECTOR_REAL") != "1",
    reason="requires explicitly enabled owned Windows fixture",
)

ELEMENT_IDS = (
    "ControlsEffect",
    "ControlsMenu",
    "MenuFile",
    "MenuEdit",
    "ContextTarget",
    "ControlsTree",
    "MultiList",
    "RowsGrid",
    "VolumeSlider",
    "StartDate",
    "LoadProgress",
    "DetailsExpander",
    "BoldToggle",
    "HelpLink",
    "MainToolBar",
    "ToolNew",
    "ToolSave",
    "MainStatusBar",
    "StatusText",
    "HScroll",
    "DragSource",
    "DropTarget",
)


ControlsPage = type(
    "ControlsPage",
    (Page,),
    {
        "window": Window(automation_id="ControlsWindow"),
        "effect": Element(automation_id="ControlsEffect"),
        "drag_source": Element(automation_id="DragSource"),
        "drop_target": Element(automation_id="DropTarget"),
        **{automation_id: Element(automation_id=automation_id) for automation_id in ELEMENT_IDS},
    },
)


@pytest.fixture
def controls(owned):
    scope, path = owned
    assert isinstance(scope, Scope)
    _fixture_scenario(scope.app.pids[0], "openControls", 0)
    return ControlsPage(scope.app), path


def test_controls_window_elements_exist(controls):
    page, path = controls
    with runtime.config_scope(replace(config(path, "agent"), backend="auto")):
        expect(page.window, timeout=5).to_exist()
        for automation_id in ELEMENT_IDS:
            assert getattr(page, automation_id).exists(timeout=5), automation_id
        expect(page.effect, timeout=5).to_have_text("Ready")


def test_controls_window_drag_and_drop(controls):
    page, path = controls
    with runtime.config_scope(replace(config(path, "agent"), backend="auto")):
        page.drag_source.drag_to(page.drop_target)
        expect(page.effect, timeout=5).to_have_text("Dropped payload")
