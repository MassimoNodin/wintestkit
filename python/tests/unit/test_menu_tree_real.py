"""Live tests for menu paths and tree paths in the fixture's Controls window."""

import os
from dataclasses import replace

import pytest
from test_wpf_query_gate_real import _fixture_scenario, config

from wintestkit import runtime
from wintestkit.controls import Button, ContextMenu, Menu, Text, TreeView
from wintestkit.engine.resolve import Scope
from wintestkit.expect import expect
from wintestkit.model import Page, Window

pytest_plugins = ["test_wpf_query_gate_real"]

pytestmark = pytest.mark.skipif(
    os.name != "nt" or os.environ.get("WTK_INSPECTOR_REAL") != "1",
    reason="requires explicitly enabled owned Windows fixture",
)

MenuTreePage = type(
    "MenuTreePage",
    (Page,),
    {
        "window": Window(automation_id="ControlsWindow"),
        "effect": Text(automation_id="ControlsEffect"),
        "menu": Menu(automation_id="ControlsMenu"),
        "target": Button(automation_id="ContextTarget"),
        "tree": TreeView(automation_id="ControlsTree"),
        "popup": ContextMenu(class_name="ContextMenu"),
    },
)


@pytest.fixture
def controls(owned):
    scope, path = owned
    assert isinstance(scope, Scope)
    _fixture_scenario(scope.app.pids[0], "openControls", 0)
    return MenuTreePage(scope.app), path


def settings(path, backend, mode):
    return replace(config(path, "agent"), backend=backend, input_mode=mode)


@pytest.mark.parametrize("mode", ["mouse", "pattern"])
@pytest.mark.parametrize("backend", ["auto", "uia"])
@pytest.mark.parametrize(
    "menu_path,effect",
    [
        ("File|Open", "Open clicked"),
        ("File|Recent|Report.txt", "Recent Report.txt"),
        ("Edit|Copy", "Copy clicked"),
    ],
)
def test_menu_click_path(controls, backend, mode, menu_path, effect):
    page, path = controls
    with runtime.config_scope(settings(path, backend, mode)):
        expect(page.menu, timeout=5).to_exist()
        page.menu.click_path(menu_path)
        expect(page.effect, timeout=5).to_have_text(effect)


@pytest.mark.parametrize("mode", ["mouse", "pattern"])
@pytest.mark.parametrize("backend", ["auto", "uia"])
def test_context_menu_click_path(controls, backend, mode):
    page, path = controls
    with runtime.config_scope(settings(path, backend, mode)):
        menu = page.target.open_context_menu()
        menu.click_path("More|Deep")
        expect(page.effect, timeout=5).to_have_text("Deep clicked")


@pytest.mark.parametrize("mode", ["mouse", "pattern"])
@pytest.mark.parametrize("backend", ["auto", "uia"])
def test_menu_failure_closes_the_menus(controls, backend, mode):
    page, path = controls
    with runtime.config_scope(settings(path, backend, mode)):
        with pytest.raises(Exception, match="Nope"):
            page.menu.click_path("File|Recent|Nope", timeout=2)
        page.menu.click_path("Edit|Copy")
        expect(page.effect, timeout=5).to_have_text("Copy clicked")


@pytest.mark.parametrize("mode", ["mouse", "pattern"])
@pytest.mark.parametrize("backend", ["auto", "uia"])
def test_tree_select_path(controls, backend, mode):
    page, path = controls
    with runtime.config_scope(settings(path, backend, mode)):
        page.tree.select("Root|Child A|Leaf 2")
        expect(page.effect, timeout=5).to_have_text("Selected Leaf 2")


@pytest.mark.parametrize("mode", ["mouse", "pattern"])
@pytest.mark.parametrize("backend", ["auto", "uia"])
def test_tree_expand_path_and_items(controls, backend, mode):
    page, path = controls
    with runtime.config_scope(settings(path, backend, mode)):
        assert page.tree.items() == ["Root", "Other"]
        page.tree.expand("Root|Child B")
        assert page.tree.items("Root|Child B") == ["Leaf 3"]
        assert page.tree.items("Root") == ["Child A", "Child B"]
        page.tree.collapse("Root|Child B")
