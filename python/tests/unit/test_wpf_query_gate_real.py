"""Phase 1 live query gate, against the owned .NET 10 fixture."""

import os
import re
import statistics
import subprocess
import time
from dataclasses import replace

import pytest
from test_inspector_owned_integration import DOTNET, FIXTURE, PAYLOAD, _control

from wintestkit import runtime
from wintestkit.app import App
from wintestkit.config import load_config
from wintestkit.engine.actions import click
from wintestkit.engine.locator import Locator, WindowLocator
from wintestkit.engine.properties import resolve_where
from wintestkit.engine.query import query_all
from wintestkit.engine.resolve import Scope, resolve, resolve_all
from wintestkit.engine.wpf_query import translate
from wintestkit.errors import (
    AmbiguousElementError,
    InspectorError,
    InspectorLimitError,
    InspectorUnavailableError,
)
from wintestkit.inspector.models import Scope as WireScope
from wintestkit.inspector.probe import identify
from wintestkit.uia import win32

pytestmark = pytest.mark.skipif(
    os.name != "nt" or os.environ.get("WTK_INSPECTOR_REAL") != "1",
    reason="requires explicitly enabled owned Windows fixture",
)


@pytest.fixture
def owned(tmp_path, monkeypatch, request):
    runtime.reset()
    monkeypatch.syspath_prepend(str(PAYLOAD))
    env = os.environ.copy()
    env["DOTNET_ROOT_X64"] = DOTNET
    env["DOTNET_MULTILEVEL_LOOKUP"] = "0"
    target = subprocess.Popen(
        [str(FIXTURE / "WinTestKit.Fixture.exe")]
        + (
            ["--scenario", "openLarge"]
            if "large" in request.node.name
            else ["--scenario", "openVirtualItems"]
            if "virtual_items" in request.node.name
            else ["--scenario", "openPopup"]
            if "popup" in request.node.name
            else []
        ),
        cwd=FIXTURE,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        until = time.monotonic() + 30
        while True:
            assert target.poll() is None
            try:
                facts = identify(target.pid)
                if facts.wpf_loaded and len(win32.top_level_windows({target.pid})) >= (
                    2 if "large" in request.node.name else 1
                ):
                    _control(target.pid)
                    break
            except (OSError, InspectorUnavailableError):
                pass
            assert time.monotonic() < until
            time.sleep(0.1)
        yield Scope(App.attach(pid=target.pid)), tmp_path
    finally:
        runtime.reset()
        if target.poll() is None:
            target.terminate()
        target.wait(timeout=5)


def config(path, mode):
    return load_config(
        path, {"inspector.enabled": True, "inspector.attach": "on-demand", "inspector.query": mode}
    )


def test_virtual_items_realization(owned):
    from wintestkit.inspector.models import ItemMatch

    scope, path = owned
    with runtime.config_scope(config(path, "agent")):
        deadline = time.monotonic() + 10
        while True:
            windows = [
                window
                for window in scope.app.top_level_windows()
                if window.automation_id == "VirtualItemsWindow"
            ]
            if windows:
                break
            assert time.monotonic() < deadline
            time.sleep(0.1)
        root = windows[0]
        client = runtime.managed_client_for(
            root.process_id, deadline=deadline, target_hwnd=root.native_window_handle
        )
        rid, hwnd = runtime.managed_element_identity(root)
        mapping = client.resolve(rid, hwnd, deadline=deadline)
        assert mapping.object_ref is not None
        for automation_id in ("VirtualItemsList", "VirtualItemsGrid"):
            locator = Locator(automation_id=automation_id)
            constraints = resolve_where(locator.where, locator.describe_link(), locator.taken())
            wire = replace(
                translate(locator, constraints, mapping.object_ref),
                scope=WireScope("object", mapping.object_ref),
            )
            container = client.query_find(
                wire, timeout_ms=2000, deadline=time.monotonic() + 5
            ).match
            result = client.act_realize_item(
                container,
                ItemMatch("index", index=4999),
                max_items=5000,
                timeout_ms=2000,
                deadline=time.monotonic() + 5,
            )
            state = client.state_get(result.handle, timeout_ms=2000, deadline=time.monotonic() + 5)
            assert state.bounds is not None and state.bounds.width > 0 and state.bounds.height > 0
            assert not state.offscreen


@pytest.mark.parametrize("backend", ["uia", "auto"])
def test_phase2_backend_parity(owned, backend, monkeypatch):
    from wintestkit.expect import expect
    from wintestkit.model import Element, Elements, Page

    scope, path = owned

    class FixturePage(Page):
        button = Element(automation_id="FancyAutomationId")
        effect = Element(automation_id="ActionEffect")
        missing = Element(automation_id="NeverAppears")
        duplicates = Elements(automation_id="Duplicate")

    page = FixturePage(scope.app)
    with runtime.config_scope(replace(config(path, "agent"), backend=backend)):
        cases = [
            Locator(automation_id="FancyAutomationId"),
            Locator(name="Fancy action", control_type="Button"),
            Locator(class_name="Button", automation_id="FancyAutomationId"),
            Locator(control_type="Button", automation_id="FancyAutomationId"),
            Locator(automation_id=re.compile("^FancyAutomationId$")),
            Locator(automation_id="FancyAutomationId", where=(("clr:Tag", "fancy"),)),
            Locator(automation_id="NestedButton", within=Locator(automation_id="ParityGroup")),
        ]
        cases.extend(
            [
                Locator(automation_id=re.compile("Fancy(?=AutomationId)")),
                Locator(automation_id="FancyAutomationId", where=(("Name", "Fancy action"),)),
                Locator(automation_id="FancyAutomationId", where=(("IsEnabled", True),)),
                Locator(automation_id="FancyAutomationId", depth=20),
            ]
        )
        for locator in cases:
            assert len(resolve_all(scope, locator)) == 1
        assert len(resolve_all(scope, Locator(automation_id="Duplicate"))) == 2
        assert resolve(scope, Locator(automation_id="Duplicate", index=1)).name == "Duplicate"
        assert not resolve_all(scope, Locator(automation_id="NeverAppears"))
        with pytest.raises(AmbiguousElementError):
            resolve(scope, Locator(automation_id="Duplicate"))
        for state in ("attached", "visible", "enabled", "stable"):
            page.button.wait_for(state, timeout=5)
        for state in ("detached", "hidden"):
            page.missing.wait_for(state, timeout=5)
        expect(page.button, timeout=5).to_exist()
        expect(page.button, timeout=5).to_be_visible()
        expect(page.button, timeout=5).to_be_enabled()
        expect(page.button, timeout=5).not_.to_be_disabled()
        expect(page.missing, timeout=5).not_.to_exist()
        expect(page.duplicates, timeout=5).to_have_count(2)
        expect(page.button, timeout=5).to_have_text("Fancy action")
        expect(page.button, timeout=5).to_contain_text("Fancy")
        target = resolve(scope, Locator(automation_id="FancyAutomationId"))
        if backend == "auto":
            monkeypatch.setattr(
                target, "as_uia", lambda: pytest.fail("pattern action mapped to UIA")
            )
        assert click(target) == "invoke"
        expect(page.effect, timeout=5).to_have_text("Clicked 1")


def test_default_backend_and_mouse_input(owned):
    from wintestkit.controls import Button, Text
    from wintestkit.expect import expect
    from wintestkit.model import Page

    scope, path = owned

    class FixturePage(Page):
        button = Button(automation_id="FancyAutomationId")
        effect = Text(automation_id="ActionEffect")

    records = []
    remove = runtime.add_step_listener(records.append)
    try:
        with runtime.config_scope(load_config(path)):
            page = FixturePage(scope.app)
            page.button.click()
            expect(page.effect, timeout=5).to_have_text("Clicked 1")
        record = next(record for record in records if record.action == "click")
        assert record.backend == "wpf"
        assert record.args["mode"] == "mouse"
        assert record.args["strategy"] == "mouse"
    finally:
        remove()


@pytest.mark.parametrize("mode", ["pattern", "mouse"])
@pytest.mark.parametrize("backend", ["uia", "auto"])
def test_phase3_typed_button_click(owned, backend, mode, monkeypatch):
    from wintestkit.backends.element import WpfElement
    from wintestkit.controls import Button, Text
    from wintestkit.expect import expect
    from wintestkit.model import Page

    scope, path = owned

    class FixturePage(Page):
        button = Button(automation_id="FancyAutomationId")
        effect = Text(automation_id="ActionEffect")

    page = FixturePage(scope.app)
    with runtime.config_scope(replace(config(path, "agent"), backend=backend, input_mode=mode)):
        if backend == "auto":
            monkeypatch.setattr(
                WpfElement, "as_uia", lambda self: pytest.fail("unexpected UIA mapping")
            )
        assert page.button.click() is None
        expect(page.effect, timeout=5).to_have_text("Clicked 1")


def test_phase2_duplicate_order_matches(owned):
    from wintestkit.backends.element import uia_of

    scope, path = owned
    results = []
    for backend in ("uia", "auto"):
        with runtime.config_scope(replace(config(path, "agent"), backend=backend)):
            matches = resolve_all(scope, Locator(automation_id="Duplicate"))
            results.append([uia_of(element).runtime_id for element in matches])
    assert len(results[0]) == 2
    assert results[0] == results[1]


@pytest.mark.parametrize("mode", ["pattern", "mouse"])
@pytest.mark.parametrize("backend", ["uia", "auto"])
def test_phase2_existing_expectations_and_input(owned, backend, mode, monkeypatch):
    from wintestkit.controls import TextBox
    from wintestkit.expect import expect
    from wintestkit.model import Element, Elements, Page

    scope, path = owned

    class FixturePage(Page):
        button = Element(automation_id="FancyAutomationId")
        source = TextBox(automation_id="BindingSource")
        duplicates = Elements(automation_id="Duplicate")

    page = FixturePage(scope.app)
    with runtime.config_scope(replace(config(path, "agent"), backend=backend, input_mode=mode)):
        expect(page.button, timeout=5).not_.to_be_hidden()
        expect(page.button, timeout=5).not_.to_have_text("wrong")
        expect(page.button, timeout=5).not_.to_contain_text("wrong")
        expect(page.button, timeout=5).to_have_property("IsEnabled", True)
        expect(page.button, timeout=5).not_.to_have_property("Name", "wrong")
        expect(page.duplicates, timeout=5).not_.to_have_count(3)
        expect(page.source, timeout=5).to_have_value("source")
        expect(page.source, timeout=5).not_.to_have_value("wrong")
        from wintestkit.backends.element import WpfElement

        with monkeypatch.context() as guard:
            if backend == "auto":
                guard.setattr(
                    WpfElement, "as_uia", lambda self: pytest.fail("unexpected UIA mapping")
                )
            page.source.type("parity")
            expect(page.source, timeout=5).to_have_value("parity")
            page.source.clear()
        expect(page.source, timeout=5).to_have_value("")


@pytest.mark.parametrize("mode", ["pattern", "mouse"])
@pytest.mark.parametrize("backend", ["uia", "auto"])
def test_phase2_typed_selection_parity(owned, backend, mode, monkeypatch):
    from wintestkit.controls import CheckBox, ComboBox, ListBox, RadioButton
    from wintestkit.expect import expect
    from wintestkit.model import Element, Page

    scope, path = owned

    class FixturePage(Page):
        checkbox = CheckBox(automation_id="ParityCheck")
        radio = RadioButton(automation_id="ParityRadio")
        combo = ComboBox(automation_id="ParityCombo")
        listing = ListBox(automation_id="ParityList")
        expander = Element(automation_id="ParityExpander")
        expanded_content = Element(automation_id="ParityExpandedContent")

    page = FixturePage(scope.app)
    with runtime.config_scope(replace(config(path, "agent"), backend=backend, input_mode=mode)):
        from wintestkit.backends.element import WpfElement

        with monkeypatch.context() as guard:
            if backend == "auto":
                guard.setattr(
                    WpfElement, "as_uia", lambda self: pytest.fail("unexpected UIA mapping")
                )
            page.checkbox.check()
            expect(page.checkbox, timeout=5).to_be_checked()
            page.checkbox.uncheck()
            expect(page.checkbox, timeout=5).not_.to_be_checked()
            page.checkbox.toggle()
            expect(page.checkbox, timeout=5).to_be_checked()
            page.radio.select()
            expect(page.radio, timeout=5).to_be_selected()
        for selection, expected in (
            ("Alpha", "Alpha"),
            (re.compile("^Beta$"), "Beta"),
            (2, "Gamma"),
        ):
            page.combo.select(selection)
            assert page.combo.selected == expected
        for selection, expected in (("Beta", "Beta"), (0, "Alpha")):
            page.listing.select(selection)
            assert page.listing.selected_items() == [expected]
        with monkeypatch.context() as guard:
            if backend == "auto":
                guard.setattr(
                    WpfElement, "as_uia", lambda self: pytest.fail("unexpected UIA mapping")
                )
            page.expander.expand()
            expect(page.expanded_content, timeout=5).to_be_visible()
            page.expander.collapse()
            expect(page.expanded_content, timeout=5).not_.to_be_visible()


@pytest.mark.parametrize("mode", ["pattern", "mouse"])
@pytest.mark.parametrize("backend", ["uia", "auto"])
def test_phase3_typed_selection(owned, backend, mode, monkeypatch):
    from wintestkit.backends.element import WpfElement
    from wintestkit.controls import ComboBox, ListBox, ListItem, TabControl, Text, TreeView
    from wintestkit.model import Page

    scope, path = owned

    class FixturePage(Page):
        combo = ComboBox(automation_id="ParityCombo")
        listing = ListBox(automation_id="ParityList")
        item = ListItem(name="Beta", control_type="ListItem", within=listing)
        tree = TreeView(automation_id="ParityTree")
        tabs = TabControl(automation_id="ParityTabs")
        effect = Text(automation_id="ActionEffect")

    page = FixturePage(scope.app)
    with runtime.config_scope(replace(config(path, "agent"), backend=backend, input_mode=mode)):
        if backend == "auto":
            monkeypatch.setattr(
                WpfElement, "as_uia", lambda self: pytest.fail("unexpected UIA mapping")
            )
        assert page.combo.items() == ["Alpha", "Beta", "Gamma"]
        assert page.listing.items() == ["Alpha", "Beta", "Gamma"]
        assert page.effect.text == "Ready"
        for item, expected in (("Alpha", "Alpha"), (re.compile("^Beta$"), "Beta"), (2, "Gamma")):
            page.combo.select(item)
            assert page.combo.selected == expected
        for item, expected in (("Beta", "Beta"), (0, "Alpha")):
            page.listing.select(item)
            assert page.listing.selected_items() == [expected]
        assert page.item.select() is None
        assert page.item.is_selected()
        page.tree.select("Tree Alpha")
        assert page.tree.selected_items() == ["Tree Alpha"]
        page.tabs.select("Tab Beta")
        assert page.tabs.selected_items() == ["Tab Beta"]


@pytest.mark.parametrize("backend", ["uia", "auto"])
def test_column_only_grid_mouse_selection(owned, backend, monkeypatch):
    from wintestkit.backends.element import WpfElement
    from wintestkit.controls import DataGrid
    from wintestkit.model import Page

    scope, path = owned

    class FixturePage(Page):
        grid = DataGrid(automation_id="ParityColumnOnlyGrid")

    with runtime.config_scope(replace(config(path, "agent"), backend=backend, input_mode="mouse")):
        if backend == "auto":
            monkeypatch.setattr(
                WpfElement, "as_uia", lambda self: pytest.fail("unexpected UIA mapping")
            )
        page = FixturePage(scope.app)
        page.grid.select("Column Beta")
        assert page.grid.selected_items() == ["Column Beta"]


@pytest.mark.parametrize("mode", ["pattern", "mouse"])
def test_phase3_item_not_found_messages_match(owned, mode, monkeypatch):
    from wintestkit.backends.element import WpfElement
    from wintestkit.controls import ComboBox, DataGrid, ListBox, TabControl, TreeView
    from wintestkit.errors import ElementNotFoundError
    from wintestkit.model import Page

    scope, path = owned

    class FixturePage(Page):
        combo = ComboBox(automation_id="ParityCombo")
        listing = ListBox(automation_id="ParityList")
        grid = DataGrid(automation_id="ParityGrid")
        tree = TreeView(automation_id="ParityTree")
        tabs = TabControl(automation_id="ParityTabs")

    page = FixturePage(scope.app)
    messages = []
    for backend in ("uia", "auto"):
        with runtime.config_scope(replace(config(path, "agent"), backend=backend, input_mode=mode)):  # noqa: SIM117
            with monkeypatch.context() as guard:
                if backend == "auto":
                    guard.setattr(
                        WpfElement, "as_uia", lambda self: pytest.fail("unexpected UIA mapping")
                    )
                errors = []
                for control in (page.combo, page.listing, page.grid, page.tree, page.tabs):
                    with pytest.raises(ElementNotFoundError) as error:
                        control.select("Absent", timeout=5)
                    errors.append(re.sub(r"[0-9.]+s", "<time>", str(error.value)))
                messages.append(errors)
    assert messages[0] == messages[1]


@pytest.mark.parametrize("mode", ["pattern", "mouse"])
@pytest.mark.parametrize("backend", ["uia", "auto"])
@pytest.mark.parametrize("control_id", ["VirtualItemsList", "VirtualItemsGrid"])
def test_phase3_virtual_items_selection(owned, backend, mode, control_id, monkeypatch):
    from wintestkit.backends.element import WpfElement
    from wintestkit.controls import DataGrid, ListBox
    from wintestkit.model import Page, Window

    scope, path = owned
    scope = Scope(scope.app, WindowLocator(automation_id="VirtualItemsWindow"))

    class FixturePage(Page):
        window = Window(automation_id="VirtualItemsWindow")
        listing = ListBox(automation_id="VirtualItemsList")
        grid = DataGrid(automation_id="VirtualItemsGrid")

    page = FixturePage(scope.app)
    control = page.listing if control_id == "VirtualItemsList" else page.grid
    with runtime.config_scope(replace(config(path, "agent"), backend=backend, input_mode=mode)):  # noqa: SIM117
        with monkeypatch.context() as guard:
            if backend == "auto":
                guard.setattr(
                    WpfElement, "as_uia", lambda self: pytest.fail("unexpected UIA mapping")
                )
            times = []
            for _ in range(3):
                control.select(0, timeout=10)
                start = time.monotonic()
                control.select("Item 4999", timeout=10)
                times.append(time.monotonic() - start)
                from wintestkit.engine import waits

                assert waits.wait_until(
                    lambda: control.selected_items() or None, 2, description="item selection"
                ) == ["Item 4999"]
                items = resolve_all(
                    scope,
                    Locator(
                        name="Item 4999",
                        control_type="ListItem" if control_id == "VirtualItemsList" else "DataItem",
                        within=Locator(automation_id=control_id),
                    ),
                )
                assert any(item.rect is not None and not item.is_offscreen for item in items)
                from wintestkit.engine.actions import ensure_visible

                ensure_visible(items[0])
                assert not items[0].as_live().is_offscreen
            print(f"{backend} {mode} {control_id}: median {statistics.median(times):.3f}s")


@pytest.mark.parametrize("mode", ["pattern", "mouse"])
@pytest.mark.parametrize("backend", ["uia", "auto"])
def test_phase2_keyboard_menu_pointer_and_grid_parity(owned, backend, mode, monkeypatch):
    from wintestkit.controls import DataGrid, TextBox
    from wintestkit.expect import expect
    from wintestkit.model import Element, Page

    scope, path = owned

    class FixturePage(Page):
        source = TextBox(automation_id="BindingSource")
        menu = Element(automation_id="ParityMenu")
        menu_item = Element(automation_id="ParityMenuItem")
        context_item = Element(automation_id="ParityContextItem")
        pointer = Element(automation_id="ParityPointer")
        effect = Element(automation_id="ParityInteractionEffect")
        grid = DataGrid(automation_id="ParityGrid")

    page = FixturePage(scope.app)
    with runtime.config_scope(replace(config(path, "agent"), backend=backend, input_mode=mode)):
        page.source.focus()
        page.source.press("Ctrl+A Backspace h e l l o")
        expect(page.source, timeout=5).to_have_value("hello")
        page.menu.click()
        page.menu_item.click()
        expect(page.effect, timeout=5).to_have_text("Menu clicked")
        from wintestkit.backends import WpfElement

        with monkeypatch.context() as guard:
            if backend == "auto":
                guard.setattr(
                    WpfElement, "as_uia", lambda self: pytest.fail("unexpected UIA mapping")
                )
            page.menu.hover()  # Move away so MouseEnter fires on the pointer target.
            page.pointer.hover()
            expect(page.effect, timeout=5).to_have_text("Hovered")
            page.pointer.double_click()
            expect(page.effect, timeout=5).to_have_text("Double clicked")
            page.pointer.right_click()
        page.context_item.click()
        expect(page.effect, timeout=5).to_have_text("Context clicked")
        assert "First" in page.grid.row(0).text
        assert page.grid.cell(0, 0).text == "First"
        assert page.grid.cell(1, 1).text == "Two"


@pytest.mark.parametrize("mode", ["pattern", "mouse"])
def test_phase3_typed_failed_expectations_match(owned, mode, monkeypatch):
    from wintestkit.backends.element import WpfElement
    from wintestkit.controls import (
        Button,
        CheckBox,
        ComboBox,
        DataGrid,
        ListBox,
        ListItem,
        RadioButton,
        TabControl,
        Text,
        TextBox,
        TreeView,
    )
    from wintestkit.expect import expect
    from wintestkit.model import Page

    scope, path = owned

    class FixturePage(Page):
        button = Button(automation_id="FancyAutomationId")
        source = TextBox(automation_id="BindingSource")
        checkbox = CheckBox(automation_id="ParityCheck")
        radio = RadioButton(automation_id="ParityRadio")
        combo = ComboBox(automation_id="ParityCombo")
        listing = ListBox(automation_id="ParityList")
        item = ListItem(name="Beta", control_type="ListItem", within=listing)
        grid = DataGrid(automation_id="ParityGrid")
        tree = TreeView(automation_id="ParityTree")
        tabs = TabControl(automation_id="ParityTabs")
        text = Text(automation_id="ActionEffect")

    page = FixturePage(scope.app)
    messages = []
    for backend in ("uia", "auto"):
        with runtime.config_scope(replace(config(path, "agent"), backend=backend, input_mode=mode)):
            resolve(scope, Locator(automation_id="FixtureControl"))
            with monkeypatch.context() as guard:
                if backend == "auto":
                    guard.setattr(
                        WpfElement, "as_uia", lambda self: pytest.fail("unexpected UIA mapping")
                    )
                errors = []
                for name in (
                    "button",
                    "source",
                    "checkbox",
                    "radio",
                    "combo",
                    "listing",
                    "item",
                    "grid",
                    "tree",
                    "tabs",
                    "text",
                ):
                    with pytest.raises(AssertionError) as error:
                        expect(getattr(page, name), timeout=0.2).to_be_disabled()
                    errors.append(re.sub(r"after [0-9.]+s", "after <time>", str(error.value)))
                messages.append(errors)
    assert messages[0] == messages[1]


@pytest.mark.parametrize("mode", ["pattern", "mouse"])
def test_phase3_grid_access_parity(owned, mode):
    from wintestkit.controls import DataGrid
    from wintestkit.model import Page

    scope, path = owned

    class FixturePage(Page):
        grid = DataGrid(automation_id="ParityGrid")

    page = FixturePage(scope.app)
    results = []
    for backend in ("uia", "auto"):
        with runtime.config_scope(replace(config(path, "agent"), backend=backend, input_mode=mode)):
            results.append(
                (
                    page.grid.row_count(),
                    page.grid.column_count(),
                    page.grid.row(0).text,
                    page.grid.cell(0, 0).text,
                    page.grid.cell(1, 1).text,
                    page.grid.find_row("Name", "Second").text,
                )
            )
    assert results[0] == results[1]
    assert results[0][0:2] == (2, 2)
    assert "First" in results[0][2]
    assert results[0][3:5] == ("First", "Two")
    assert "Second" in results[0][5]


def test_phase2_error_diagnostics_match(owned):
    from wintestkit.errors import LocatorError

    scope, path = owned
    locators = [
        Locator(automation_id="NeverAppears"),
        Locator(name="Never appears"),
        Locator(automation_id="Duplicate"),
        Locator(name="Duplicate", control_type="Button"),
        Locator(automation_id="Duplicate", index=10),
        Locator(name="Duplicate", control_type="Button", index=10),
        Locator(automation_id="NestedButton", within=Locator(automation_id="NeverAppears")),
        Locator(automation_id="NestedButton", within=Locator(name="Never appears")),
    ]
    messages = []
    for backend in ("uia", "auto"):
        results = []
        with runtime.config_scope(replace(config(path, "agent"), backend=backend)):
            for locator in locators:
                with pytest.raises(LocatorError) as error:
                    resolve(scope, locator)
                results.append((type(error.value), str(error.value)))
        messages.append(results)
    assert messages[0] == messages[1]


@pytest.mark.parametrize("backend", ["uia", "auto"])
def test_phase2_predicates_backend_parity(owned, backend):
    scope, path = owned
    predicates = [
        ("type:FullName", "WinTestKit.Fixture.FixtureControl"),
        ("clr:DataContext.Customer.Address.City", "Sydney"),
        ("field:PublicField", "public field"),
        ("dp:WinTestKit.Fixture|WinTestKit.Fixture.FixtureControl::DefaultValue", "default"),
        ("clr:CoercedValue", 10),
        ("IsEnabled", True),
        ("Name", re.compile("fixture control", re.IGNORECASE)),
        ("Name", re.compile("^Fixture control$", re.MULTILINE)),
        ("Name", re.compile("Fixture.*control", re.DOTALL)),
        ("Name", re.compile("Fixture(?= control)")),
    ]
    with runtime.config_scope(replace(config(path, "agent"), backend=backend)):
        for key, value in predicates:
            locator = Locator(automation_id="FixtureControl", where=((key, value),))
            assert len(resolve_all(scope, locator)) == 1, key


@pytest.mark.parametrize("backend", ["uia", "auto"])
def test_phase2_popup_backend_parity(owned, backend):
    scope, path = owned
    with runtime.config_scope(replace(config(path, "agent"), backend=backend)):
        assert resolve(scope, Locator(automation_id="PopupContent")).name == "Popup content"


def test_auto_backend_smoke(owned):
    scope, path = owned
    with runtime.config_scope(replace(config(path, "agent"), backend="auto")):
        assert (
            resolve(scope, Locator(automation_id="FixtureControl")).automation_id
            == "FixtureControl"
        )
        assert (
            resolve(
                scope, Locator(automation_id="FancyAutomationId", where=(("clr:Tag", "fancy"),))
            ).automation_id
            == "FancyAutomationId"
        )
        assert (
            resolve(
                scope,
                Locator(automation_id="NestedButton", within=Locator(automation_id="ParityGroup")),
            ).automation_id
            == "NestedButton"
        )
        peerless = resolve(
            scope, Locator(where=(("type:Is", "WinTestKit.Fixture.PeerlessMarker"),))
        )
        assert peerless.runtime_id.startswith("wpf:")
        assert click(resolve(scope, Locator(automation_id="FancyAutomationId"))) == "invoke"


def test_parity_and_features(owned):
    scope, path = owned
    where = (("type:FullName", "WinTestKit.Fixture.FixtureControl"),)
    cases = [
        Locator(automation_id="FixtureControl", where=where),
        Locator(automation_id="FixtureControl", name="Fixture control", where=where),
        Locator(name="Fixture control", where=where),
        Locator(automation_id="FixtureControl", class_name="Button", where=where),
        Locator(automation_id="FixtureControl", control_type="Button", where=where),
        Locator(automation_id=re.compile("^Fixture"), where=where),
        Locator(automation_id="FixtureControl", where=(("clr:LocalValue", "local"),)),
        Locator(automation_id="FixtureControl", where=(("clr:DefaultValue", "default"),)),
        Locator(automation_id="FixtureControl", where=(("clr:Overridden", "fixture"),)),
        Locator(
            automation_id="FixtureControl",
            where=(("clr:DataContext.Customer.Address.City", "Sydney"),),
        ),
        Locator(
            automation_id="FixtureControl", where=(("clr:DataContext.Label", re.compile("^fix")),)
        ),
        Locator(automation_id="FixtureControl", where=(("field:PublicField", "public field"),)),
        Locator(
            automation_id="FixtureControl",
            where=(
                (
                    "dp:WinTestKit.Fixture|WinTestKit.Fixture.FixtureControl::DefaultValue",
                    "default",
                ),
            ),
        ),
        Locator(automation_id="FancyAutomationId", where=(("clr:Tag", "fancy"),)),
        Locator(
            automation_id="Duplicate", where=(("type:FullName", "System.Windows.Controls.Button"),)
        ),
        Locator(
            automation_id="Duplicate",
            index=1,
            where=(("type:FullName", "System.Windows.Controls.Button"),),
        ),
        Locator(
            automation_id="NestedButton",
            where=(("clr:Tag", "nested"),),
            within=Locator(automation_id="ParityGroup"),
        ),
    ]
    for locator in cases:
        results = []
        for mode in ("agent", "postfilter"):
            with runtime.config_scope(replace(config(path, mode), backend="uia")):
                if locator.index is not None:
                    found = [resolve(scope, locator)]
                else:
                    found = resolve_all(scope, locator)
                results.append([element.runtime_id for element in found])
        print("PARITY", locator.describe(), results)
        assert results[0] == results[1] and results[0]
    with runtime.config_scope(replace(config(path, "agent"), backend="uia")):
        fancy = resolve(
            scope,
            Locator(
                automation_id="FancyAutomationId",
                where=(("type:Is", "System.Windows.Controls.Button"),),
            ),
        )
        assert fancy.automation_id == "FancyAutomationId"
        assert not resolve_all(
            scope, Locator(automation_id="FancyXName", where=(("clr:Tag", "fancy"),))
        )
        assert not resolve_all(
            scope, Locator(where=(("type:Is", "WinTestKit.Fixture.PeerlessMarker"),))
        )
        assert click(fancy) == "invoke"
        assert resolve(scope, Locator(automation_id="ActionEffect")).name == "Clicked 1"
        assert click(fancy, mode="pattern") == "invoke"
        assert resolve(scope, Locator(automation_id="ActionEffect")).name == "Clicked 2"


def test_hit_test_button_real(owned):
    from wintestkit.backends import WpfElement

    scope, path = owned
    with runtime.config_scope(replace(config(path, "agent"), backend="auto")):
        target = resolve(
            scope,
            Locator(
                automation_id="FancyAutomationId",
                where=(("type:Is", "WinTestKit.Fixture.FancyButton"),),
            ),
        )
        assert isinstance(target, WpfElement)
        state = target.client.state_get(target.ref, timeout_ms=2000, deadline=time.monotonic() + 5)
        assert state.bounds is not None and state.window_handle is not None
        bounds = state.bounds
        hit = target.client.hit_test(
            state.window_handle,
            bounds.x + bounds.width / 2,
            bounds.y + bounds.height / 2,
            timeout_ms=2000,
            deadline=time.monotonic() + 5,
        )
        assert hit is not None
        assert (
            target.client.state_get(hit, timeout_ms=2000, deadline=time.monotonic() + 5).handle
            == hit
        )
        pending = [target.ref]
        found = False
        while pending:
            current = pending.pop()
            if current == hit:
                found = True
                break
            page = target.client.children(
                current.object_id, current.generation, "visual", deadline=time.monotonic() + 5
            )
            assert page.complete
            pending.extend(node.object_ref for node in page.items)
        assert found


def test_hit_test_peerless_real(owned):
    from wintestkit.backends import WpfElement

    scope, path = owned
    with runtime.config_scope(replace(config(path, "agent"), backend="auto")):
        target = resolve(
            scope, Locator(where=(("type:Is", "WinTestKit.Fixture.PeerlessClickTarget"),))
        )
        assert isinstance(target, WpfElement)
        state = target.client.state_get(target.ref, timeout_ms=2000, deadline=time.monotonic() + 5)
        assert state.bounds is not None and state.window_handle is not None
        bounds = state.bounds
        hit = target.client.hit_test(
            state.window_handle,
            bounds.x + bounds.width / 2,
            bounds.y + bounds.height / 2,
            timeout_ms=2000,
            deadline=time.monotonic() + 5,
        )
        assert hit == target.ref
        assert (
            target.client.state_get(hit, timeout_ms=2000, deadline=time.monotonic() + 5).handle
            == target.ref
        )


def test_popup_parity(owned):
    scope, path = owned
    locator = Locator(
        automation_id="PopupContent", where=(("type:FullName", "System.Windows.Controls.Button"),)
    )
    results = []
    for mode in ("agent", "postfilter"):
        with runtime.config_scope(config(path, mode)):
            results.append([element.runtime_id for element in resolve_all(scope, locator)])
    print("PARITY popup", results)
    assert results[0] == results[1] and results[0]


def test_large_latency(owned):
    scope, path = owned
    with runtime.config_scope(config(path, "agent")):
        root = next(w for w in scope.app.top_level_windows() if w.automation_id == "LargeWindow")
        client = runtime.managed_client_for(
            root.process_id, deadline=time.monotonic() + 10, target_hwnd=root.native_window_handle
        )
        rid, hwnd = runtime.managed_element_identity(root)
        mapping = client.resolve(rid, hwnd, deadline=time.monotonic() + 10)
        assert mapping.object_ref is not None
        checks = []
        for label, target in (("unique", "Large1499"), ("missing", "NotPresent")):
            locator = Locator(
                automation_id=target, where=(("type:FullName", "WinTestKit.Fixture.LargeButton"),)
            )
            constraints = resolve_where(locator.where, locator.describe_link(), locator.taken())
            wire = replace(
                translate(locator, constraints, mapping.object_ref),
                scope=WireScope("object", mapping.object_ref),
            )
            samples = []
            outcomes = []
            for _ in range(30):
                start = time.perf_counter()
                try:
                    result = client.query_find(wire, timeout_ms=2000, deadline=time.monotonic() + 5)
                    elapsed = (time.perf_counter() - start) * 1000
                    outcomes.append("match")
                    client.release([result.match.object_id], deadline=time.monotonic() + 2)
                except InspectorError as error:
                    elapsed = (time.perf_counter() - start) * 1000
                    outcomes.append(error.code)
                samples.append(elapsed)
            median = statistics.median(samples)
            p95 = sorted(samples)[28]
            print(
                f"QUERY_FIND {label} median={median:.2f}ms p95={p95:.2f}ms outcomes={outcomes}",
                flush=True,
            )
            checks.append((median, set(outcomes), label))
        client.release([mapping.object_ref.object_id], deadline=time.monotonic() + 2)
        for median, outcomes, label in checks:
            assert outcomes == ({"match"} if label == "unique" else {"notFound"})
            assert median <= 100


def test_large_end_to_end(owned):
    scope, path = owned
    large = WindowLocator(automation_id="LargeWindow")
    unique = Locator(
        control_type="Button",
        where=(("clr:Group", "shared"), ("clr:Key", "Large 1499")),
        window=large,
    )
    root = next(w for w in scope.app.top_level_windows() if w.automation_id == "LargeWindow")
    measurements = {}
    for mode in ("postfilter", "agent"):
        with runtime.config_scope(config(path, mode)):
            for label, locator in (
                ("unique", unique),
                ("missing", replace(unique, where=(("clr:Group", "absent"),))),
            ):
                samples = []
                outcomes = []
                for _ in range(10 if mode == "agent" else 3):
                    start = time.perf_counter()
                    try:
                        outcomes.append(str(len(query_all(root, locator))))
                    except InspectorError as error:
                        outcomes.append(error.code)
                    samples.append((time.perf_counter() - start) * 1000)
                measurements[(mode, label)] = outcomes
                print(
                    f"QUERY_ALL {mode} {label} median={statistics.median(samples):.2f}ms p95={max(samples):.2f}ms outcomes={outcomes}",
                    flush=True,
                )

    assert measurements[("agent", "unique")] == ["1"] * 10
    assert measurements[("agent", "missing")] == ["0"] * 10


def test_large_cap(owned):
    scope, path = owned
    large = WindowLocator(automation_id="LargeWindow")
    shared = Locator(
        control_type="Button",
        where=(("type:FullName", "WinTestKit.Fixture.LargeButton"),),
        window=large,
    )
    unique = replace(shared, where=(*shared.where, ("clr:Key", "Large 1499")))
    with runtime.config_scope(replace(config(path, "postfilter"), backend="uia")):
        with pytest.raises(InspectorLimitError) as exc:
            resolve_all(scope, shared)
        assert exc.value.code == "limitExceeded"
    with runtime.config_scope(replace(config(path, "agent"), backend="uia")):
        assert resolve(scope, unique).automation_id == "Large1499"
        with pytest.raises(AmbiguousElementError):
            resolve(scope, shared)


def test_large_mapping_latency(owned):
    scope, path = owned
    locator = Locator(automation_id="Large100", window=WindowLocator(automation_id="LargeWindow"))
    root = next(w for w in scope.app.top_level_windows() if w.automation_id == "LargeWindow")
    assert win32.raise_window(root.native_window_handle)
    samples = []
    with runtime.config_scope(replace(config(path, "agent"), backend="auto")):
        for _ in range(10):
            start = time.perf_counter()
            element = resolve(scope, locator)
            assert not element.is_offscreen
            assert element.as_uia().runtime_id == element.runtime_id
            samples.append((time.perf_counter() - start) * 1000)
    print(
        f"WPF_RESOLVE_AS_UIA median={statistics.median(samples):.2f}ms p95={sorted(samples)[-1]:.2f}ms samples={samples}",
        flush=True,
    )


def test_auto_backend_waits_for_delayed_appearance(owned, monkeypatch):
    import ctypes
    import json
    import threading

    from wintestkit.expect import expect
    from wintestkit.inspector.client import InspectorClient
    from wintestkit.inspector.pipe import WindowsPipe, _api
    from wintestkit.model import Element, Page

    scope, path = owned

    class FixturePage(Page):
        dynamic = Element(automation_id="Dynamic73")

    page = FixturePage(scope.app)
    calls = []
    original = InspectorClient.wait_until

    def recorded(self, condition, *, timeout_ms, deadline):
        calls.append(condition.kind)
        return original(self, condition, timeout_ms=timeout_ms, deadline=deadline)

    monkeypatch.setattr(InspectorClient, "wait_until", recorded)

    def appear():
        time.sleep(0.5)
        handle = _api().CreateFileW(
            rf"\\.\pipe\WinTestKit.Fixture.{scope.app.pids[0]}",
            0xC0000000,
            0,
            None,
            3,
            0x40000000,
            None,
        )
        assert handle != ctypes.c_void_p(-1).value
        pipe = WindowsPipe(handle)
        try:
            deadline = time.monotonic() + 2
            pipe.write(
                json.dumps({"cmd": "scenario", "name": "addDynamic", "value": 73}).encode() + b"\n",
                deadline,
            )
            while pipe.read_exact(1, deadline) != b"\n":
                pass
        finally:
            pipe.close()

    with runtime.config_scope(replace(config(path, "agent"), backend="auto")):
        resolve(scope, Locator(automation_id="FixtureControl"))
        thread = threading.Thread(target=appear)
        thread.start()
        page.dynamic.wait_for("attached", timeout=10)
        thread.join()
        expect(page.dynamic, timeout=5).to_exist()
        expect(page.dynamic, timeout=5).to_be_enabled()
        assert "exists" in calls and "enabled" in calls


def test_auto_expect_missing_message_matches_uia(owned):
    from wintestkit.expect import expect
    from wintestkit.model import Element, Page

    scope, path = owned

    class FixturePage(Page):
        missing = Element(automation_id="NeverAppears")

    page = FixturePage(scope.app)
    messages = []
    for backend in ("uia", "auto"):
        with runtime.config_scope(replace(config(path, "agent"), backend=backend)):
            resolve(scope, Locator(automation_id="FixtureControl"))
            with pytest.raises(AssertionError) as error:
                expect(page.missing, timeout=2).to_exist()
            messages.append(str(error.value))
    assert messages[0] == messages[1]

    from wintestkit.errors import LocatorError

    diagnostics = []
    for backend in ("uia", "auto"):
        with runtime.config_scope(replace(config(path, "agent"), backend=backend)):
            with pytest.raises(LocatorError) as error:
                page.missing.wait_for("attached", timeout=2)
            diagnostics.append(str(error.value))
    assert diagnostics[0] == diagnostics[1]


@pytest.mark.parametrize("method", ["to_exist", "to_be_visible"])
def test_negated_expect_present_message_matches_uia(owned, method):
    from wintestkit.expect import expect
    from wintestkit.model import Element, Page

    scope, path = owned

    class FixturePage(Page):
        present = Element(automation_id="FixtureControl")

    page = FixturePage(scope.app)
    messages = []
    for backend in ("uia", "auto"):
        with runtime.config_scope(replace(config(path, "agent"), backend=backend)):
            resolve(scope, Locator(automation_id="FixtureControl"))
            with pytest.raises(AssertionError) as error:
                getattr(expect(page.present, timeout=1).not_, method)()
            messages.append(str(error.value))
    assert messages[0] == messages[1]


@pytest.mark.parametrize(
    ("target", "method", "args", "truth"),
    [
        ("button", "to_exist", (), True),
        ("missing", "to_exist", (), False),
        ("button", "to_be_visible", (), True),
        ("missing", "to_be_visible", (), False),
        ("button", "to_be_hidden", (), False),
        ("missing", "to_be_hidden", (), True),
        ("button", "to_be_enabled", (), True),
        ("disabled", "to_be_enabled", (), False),
        ("button", "to_be_disabled", (), False),
        ("disabled", "to_be_disabled", (), True),
        ("checkbox", "to_be_checked", (), False),
        ("checkbox", "to_be_checked", (), True),
        ("radio", "to_be_selected", (), False),
        ("radio", "to_be_selected", (), True),
        ("button", "to_have_text", ("Fancy action",), True),
        ("button", "to_have_text", ("wrong",), False),
        ("button", "to_contain_text", ("Fancy",), True),
        ("button", "to_contain_text", ("wrong",), False),
        ("source", "to_have_value", ("source",), True),
        ("source", "to_have_value", ("wrong",), False),
        ("button", "to_have_property", ("IsEnabled", True), True),
        ("button", "to_have_property", ("IsEnabled", False), False),
        ("duplicates", "to_have_count", (2,), True),
        ("duplicates", "to_have_count", (3,), False),
    ],
)
def test_phase2_expect_matrix_messages_match(owned, target, method, args, truth):
    from wintestkit.expect import expect
    from wintestkit.model import Element, Elements, Page

    scope, path = owned

    class FixturePage(Page):
        button = Element(automation_id="FancyAutomationId")
        missing = Element(automation_id="NeverAppears")
        disabled = Element(automation_id="ParityDisabled")
        checkbox = Element(automation_id="ParityCheck")
        radio = Element(automation_id="ParityRadio")
        source = Element(automation_id="BindingSource")
        duplicates = Elements(automation_id="Duplicate")

    page = FixturePage(scope.app)
    if truth and target in ("checkbox", "radio"):
        with runtime.config_scope(replace(config(path, "agent"), backend="uia")):
            click(resolve(scope, getattr(page, target).locator))
    messages = []
    for backend in ("uia", "auto"):
        with runtime.config_scope(replace(config(path, "agent"), backend=backend)):
            resolve(scope, Locator(automation_id="FixtureControl"))
            for negate in (False, True):
                assertion = expect(getattr(page, target), timeout=0.5)
                if negate:
                    assertion = assertion.not_
                call = getattr(assertion, method)
                if truth != negate:
                    call(*args)
                else:
                    with pytest.raises(AssertionError) as error:
                        call(*args)
                    messages.append(re.sub(r"after [0-9.]+s", "after <time>", str(error.value)))
    assert messages[0] == messages[1]


@pytest.mark.parametrize("backend", ["uia", "auto"])
def test_phase2_predicate_edges(owned, backend):
    scope, path = owned
    matches = [
        ("clr:CoercedValue", 10),
        ("clr:IsEnabled", True),
        ("clr:Flags", 3),
        ("clr:Flags", "One, Two"),
        ("clr:DataContext.Customer.Address.City", "Sydney"),
        ("Name", re.compile("fixture CONTROL", re.IGNORECASE)),
        ("Name", re.compile("^fixture control$", re.IGNORECASE)),
    ]
    misses = [
        ("clr:NoSuchMember", "anything"),
        ("clr:DataContext.Customer.NoSuchMember", "anything"),
        ("Name", re.compile("^control", re.IGNORECASE)),
    ]
    with runtime.config_scope(replace(config(path, "agent"), backend=backend)):
        for key, value in matches:
            assert (
                len(
                    resolve_all(
                        scope, Locator(automation_id="FixtureControl", where=((key, value),))
                    )
                )
                == 1
            )
        for key, value in misses:
            assert not resolve_all(
                scope, Locator(automation_id="FixtureControl", where=((key, value),))
            )
        with pytest.raises(InspectorError) as error:
            resolve_all(
                scope, Locator(automation_id="FixtureControl", where=(("clr:Throwing", "x"),))
            )
        assert error.value.code == "exception"


def _fixture_scenario(pid, name, value):
    import ctypes
    import json

    from wintestkit.inspector.pipe import WindowsPipe, _api

    handle = _api().CreateFileW(
        rf"\\.\pipe\WinTestKit.Fixture.{pid}", 0xC0000000, 0, None, 3, 0x40000000, None
    )
    assert handle != ctypes.c_void_p(-1).value
    pipe = WindowsPipe(handle)
    try:
        deadline = time.monotonic() + 2
        pipe.write(
            json.dumps({"cmd": "scenario", "name": name, "value": value}).encode() + b"\n", deadline
        )
        line = bytearray()
        while not line.endswith(b"\n"):
            line.extend(pipe.read_exact(1, deadline))
        assert json.loads(line) == {"ok": True}
    finally:
        pipe.close()


@pytest.mark.parametrize("mode", ["pattern", "mouse"])
def test_phase3_disabled_action_messages_match(owned, mode, monkeypatch):
    from wintestkit.backends.element import WpfElement
    from wintestkit.controls import Button
    from wintestkit.errors import WaitTimeoutError
    from wintestkit.model import Page

    scope, path = owned

    class FixturePage(Page):
        disabled = Button(automation_id="ParityDisabled")

    page = FixturePage(scope.app)
    messages = []
    for backend in ("uia", "auto"):
        with runtime.config_scope(replace(config(path, "agent"), backend=backend, input_mode=mode)):  # noqa: SIM117
            with monkeypatch.context() as guard:
                if backend == "auto":
                    guard.setattr(
                        WpfElement, "as_uia", lambda self: pytest.fail("unexpected UIA mapping")
                    )
                with pytest.raises(WaitTimeoutError) as error:
                    page.disabled.click(timeout=2.0)
                messages.append(re.sub(r"[0-9.]+s", "<time>", str(error.value)))
    assert messages[0] == messages[1]


def test_phase2_disabled_waits_match(owned):
    from wintestkit.errors import WaitTimeoutError
    from wintestkit.model import Element, Page

    scope, path = owned

    class FixturePage(Page):
        disabled = Element(automation_id="ParityDisabled")

    page = FixturePage(scope.app)
    messages = []
    for backend in ("uia", "auto"):
        with runtime.config_scope(replace(config(path, "agent"), backend=backend)):
            resolve(scope, Locator(automation_id="FixtureControl"))
            with pytest.raises(WaitTimeoutError) as error:
                page.disabled.wait_for("enabled", timeout=0.5)
            messages.append(re.sub(r"[0-9.]+s", "<time>", str(error.value)))
            _fixture_scenario(scope.app.pids[0], "enableDelayed", 500)
            page.disabled.wait_for("enabled", timeout=5)
            _fixture_scenario(scope.app.pids[0], "enableDelayed", 60000)
            time.sleep(0.1)
    assert messages[0] == messages[1]


@pytest.mark.parametrize("mode", ["pattern", "mouse"])
def test_phase3_readonly_typing_parity(owned, mode, monkeypatch):
    from wintestkit.backends.element import WpfElement
    from wintestkit.model import Element, Page

    scope, path = owned

    class FixturePage(Page):
        field = Element(automation_id="ParityReadOnly")

    page = FixturePage(scope.app)
    outcomes = []
    for backend in ("uia", "auto"):
        with runtime.config_scope(replace(config(path, "agent"), backend=backend, input_mode=mode)):  # noqa: SIM117
            with monkeypatch.context() as guard:
                if backend == "auto":
                    guard.setattr(
                        WpfElement, "as_uia", lambda self: pytest.fail("unexpected UIA mapping")
                    )
                records = []
                remove = runtime.add_step_listener(records.append)
                try:
                    try:
                        page.field.type("changed", keys=mode == "mouse", timeout=5)
                        outcome = ("success", records[-1].args.get("strategy"))
                    except Exception as error:
                        outcome = (type(error).__name__, str(error))
                finally:
                    remove()
                outcomes.append((outcome, page.field.text))
    assert outcomes[0] == outcomes[1]
    assert outcomes[0][1] == "read only"


@pytest.mark.parametrize("mode", ["pattern", "mouse"])
def test_phase3_password_parity_and_redaction(owned, mode, monkeypatch, caplog):
    import logging

    from wintestkit.backends.element import WpfElement
    from wintestkit.model import Element, Page

    scope, path = owned
    secret = "ParitySecret987"

    class FixturePage(Page):
        password = Element(automation_id="PasswordBox")

    page = FixturePage(scope.app)
    outcomes = []
    caplog.set_level(logging.DEBUG)
    for backend in ("uia", "auto"):
        with runtime.config_scope(replace(config(path, "agent"), backend=backend, input_mode=mode)):  # noqa: SIM117
            with monkeypatch.context() as guard:
                if backend == "auto":
                    guard.setattr(
                        WpfElement, "as_uia", lambda self: pytest.fail("unexpected UIA mapping")
                    )
                records = []
                remove = runtime.add_step_listener(records.append)
                try:
                    page.password.type(secret, keys=mode == "mouse", timeout=5)
                    results = []
                    for getter in (lambda: page.password.text, lambda: page.password.value):
                        try:
                            results.append(("value", getter()))
                        except Exception as error:
                            assert secret not in str(error)
                            results.append((type(error).__name__, str(error)))
                    page.password.clear(timeout=5)
                finally:
                    remove()
                assert secret not in repr([record.args for record in records])
                assert secret not in repr(results)
                outcomes.append(results)
    assert secret not in caplog.text
    assert outcomes[0] == outcomes[1]


@pytest.mark.parametrize("mode", ["pattern", "mouse"])
def test_phase3_hidden_actions_parity(owned, mode, monkeypatch):
    from wintestkit.backends.element import WpfElement
    from wintestkit.errors import WtkError
    from wintestkit.model import Element, Page

    scope, path = owned

    class FixturePage(Page):
        hidden = Element(automation_id="ParityHiddenInput")

    page = FixturePage(scope.app)
    outcomes = []
    for backend in ("uia", "auto"):
        with runtime.config_scope(replace(config(path, "agent"), backend=backend, input_mode=mode)):  # noqa: SIM117
            with monkeypatch.context() as guard:
                if backend == "auto":
                    guard.setattr(
                        WpfElement, "as_uia", lambda self: pytest.fail("unexpected UIA mapping")
                    )
                errors = []
                for action in (
                    lambda: page.hidden.click(timeout=2),
                    lambda: page.hidden.type("hidden", timeout=2),
                ):
                    start = time.monotonic()
                    with pytest.raises(WtkError) as error:
                        action()
                    assert time.monotonic() - start < 5
                    errors.append(
                        (
                            type(error.value).__name__,
                            re.sub(r"[0-9.]+s", "<time>", str(error.value)),
                        )
                    )
                outcomes.append(errors)
    assert outcomes[0][0][0] == "ElementNotFoundError", "UIA omits collapsed descendants"
    assert outcomes[1][0][0] == "WaitTimeoutError"
    assert "to be visible" in outcomes[1][0][1]
    assert outcomes[0][1] == outcomes[1][1]


@pytest.mark.parametrize("mode", ["pattern", "mouse"])
def test_peerless_mouse_click(owned, monkeypatch, mode):
    from wintestkit.backends import WpfElement

    scope, path = owned
    locator = Locator(where=(("type:Is", "WinTestKit.Fixture.PeerlessClickTarget"),))
    with runtime.config_scope(replace(config(path, "agent"), backend="uia")):
        assert not resolve_all(scope, locator)
    with runtime.config_scope(replace(config(path, "agent"), backend="auto")):
        target = resolve(scope, locator)
        assert target.runtime_id.startswith("wpf:")
        monkeypatch.setattr(
            WpfElement, "as_uia", lambda self: pytest.fail("unexpected UIA mapping")
        )
        if mode == "pattern":
            from wintestkit.errors import UIAError

            with pytest.raises(UIAError, match="supported_patterns: unavailable"):
                click(target, mode=mode)
            return
        assert click(target, mode=mode) == "mouse"
        assert (
            resolve(scope, Locator(automation_id="ParityInteractionEffect")).name
            == "Peerless clicked"
        )


@pytest.mark.parametrize("mode", ["pattern", "mouse"])
@pytest.mark.parametrize("backend", ["uia", "auto"])
def test_partly_scrolled_mouse_parity(owned, backend, mode):
    from wintestkit.expect import expect
    from wintestkit.model import Element, Page

    scope, path = owned

    class FixturePage(Page):
        button = Element(automation_id="ParityClippedButton")
        effect = Element(automation_id="ActionEffect")

    page = FixturePage(scope.app)
    with runtime.config_scope(replace(config(path, "agent"), backend=backend)):
        page.button.click(mode=mode)
        expect(page.effect, timeout=5).to_have_text("Clipped clicked")


@pytest.mark.parametrize("backend", ["uia", "auto"])
def test_background_window_mouse_and_keyboard(owned, backend):
    from wintestkit.controls import TextBox
    from wintestkit.expect import expect
    from wintestkit.model import Element, Page

    scope, path = owned

    class FixturePage(Page):
        button = Element(automation_id="FancyAutomationId")
        effect = Element(automation_id="ActionEffect")
        source = TextBox(automation_id="BindingSource")

    page = FixturePage(scope.app)
    # A native top-level window avoids creating multiple Tcl interpreters in one run.
    hwnd = win32.CreateWindowExW(
        0,
        "STATIC",
        "WinTestKit foreground helper",
        0x10CF0000,
        100,
        100,
        200,
        100,
        None,
        None,
        None,
        None,
    )
    assert hwnd
    try:
        with runtime.config_scope(replace(config(path, "agent"), backend=backend)):
            assert win32.bring_to_foreground(hwnd)
            assert win32.GetForegroundWindow() == hwnd
            page.button.click(mode="mouse")
            expect(page.effect, timeout=5).to_have_text("Clicked 1")
            assert win32.bring_to_foreground(hwnd)
            assert win32.GetForegroundWindow() == hwnd
            page.source.focus()
            page.source.press("Ctrl+A Backspace h i")
            expect(page.source, timeout=5).to_have_value("hi")
    finally:
        win32.DestroyWindow(hwnd)


@pytest.mark.parametrize("backend", ["uia", "auto"])
def test_busy_dispatcher_state_and_wait(owned, backend):
    from wintestkit.engine.waits import wait_until

    scope, path = owned
    with runtime.config_scope(replace(config(path, "agent"), backend=backend)):
        target = resolve(scope, Locator(automation_id="FixtureControl"))
        pid = target.process_id
        for attempt in range(2):
            _fixture_scenario(pid, "sleepDispatcher", 0)
            deadline = time.monotonic() + 2
            while _control(pid).get("dispatcher.sleeping", 0) < attempt + 1:
                assert time.monotonic() < deadline
                time.sleep(0.01)
            if attempt == 0:
                assert target.is_enabled
            else:
                assert wait_until(lambda: target.is_enabled, 3, description="enabled")


@pytest.mark.parametrize("mode", ["pattern", "mouse"])
@pytest.mark.parametrize("backend", ["uia", "auto"])
def test_ensure_visible_scrolled(owned, backend, mode):
    from wintestkit.engine.actions import ensure_visible

    scope, path = owned
    with runtime.config_scope(replace(config(path, "agent"), backend=backend, input_mode=mode)):
        target = resolve(scope, Locator(automation_id="RichText"))
        # WPF's UIA provider reports this clipped descendant as on-screen.
        assert target.as_live().is_offscreen == (backend == "auto")
        ensure_visible(target)
        assert not target.as_live().is_offscreen


@pytest.mark.parametrize("mode", ["pattern", "mouse"])
@pytest.mark.parametrize("backend", ["uia", "auto"])
def test_ensure_visible_virtual_items_cached(owned, backend, mode):
    from wintestkit.engine import waits
    from wintestkit.engine.actions import ensure_visible

    scope, path = owned
    waits.wait_until(
        lambda: any(w.automation_id == "VirtualItemsWindow" for w in scope.app.top_level_windows()),
        10,
        description="virtual items window",
    )
    scope = Scope(scope.app, WindowLocator(automation_id="VirtualItemsWindow"))
    with runtime.config_scope(replace(config(path, "agent"), backend=backend, input_mode=mode)):
        items = resolve_all(
            scope,
            Locator(control_type="ListItem", within=Locator(automation_id="VirtualItemsList")),
        )
        offscreen = [item for item in items if item.as_live().is_offscreen]
        assert offscreen, f"No off-screen cached item among {len(items)} realized items"
        target = offscreen[0]
        ensure_visible(target)
        assert not target.as_live().is_offscreen
