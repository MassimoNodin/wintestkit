"""Typed elements: method availability, binding, type validation and user-defined types."""

import re
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeApp, FakeElement

from wintestkit import controls, model, runtime
from wintestkit.config import load_config
from wintestkit.controls import (
    BoundButton,
    BoundCheckBox,
    BoundComboBox,
    BoundDataGrid,
    BoundListBox,
    BoundListItem,
    BoundRadioButton,
    BoundTabControl,
    BoundText,
    BoundTextBox,
    BoundTreeView,
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
from wintestkit.engine import actions, waits
from wintestkit.engine.locator import ItemSelector, Locator
from wintestkit.errors import ActionError, ElementTypeError
from wintestkit.model import BoundControl, BoundElement, Element, Elements, Page, Window
from wintestkit.uia import patterns


class Typed(Page):
    window = Window(title="Demo")

    save = Button(automation_id="Save")
    name = TextBox(automation_id="Name")
    agree = CheckBox(automation_id="Agree")
    male = RadioButton(automation_id="Male")
    country = ComboBox(automation_id="Country")
    colors = ListBox(automation_id="Colors")
    nav = ListItem(automation_id="Nav")
    grid = DataGrid(automation_id="Grid")
    tree = TreeView(automation_id="Tree")
    tabs = TabControl(automation_id="Tabs")
    caption = Text(automation_id="Caption")
    loose = ComboBox(automation_id="Loose", validate=False)
    generic = Element(automation_id="Generic")


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.on_sleep: Any = None

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds
        if self.on_sleep is not None:
            self.on_sleep()


@pytest.fixture(autouse=True)
def runtime_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[runtime.StepRecord]:
    runtime.reset()
    runtime.set_config(load_config(tmp_path, {"timeout": 10.0}))
    fake = FakeTime()
    monkeypatch.setattr(waits, "_clock", fake.clock)
    monkeypatch.setattr(waits, "_sleep", fake.sleep)
    records: list[runtime.StepRecord] = []
    runtime.add_step_listener(records.append)
    yield records  # type: ignore[misc]
    runtime.reset()


class World:
    """One fake matched element whose UIA patterns the test chooses."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.element = FakeElement("Custom", "thing", class_name="Thing")
        self.supported: set[str] = set()
        self.asked: list[str] = []
        monkeypatch.setattr(model, "resolve", lambda scope, locator: self.element)
        monkeypatch.setattr(patterns, "has_pattern", self._has_pattern)

    def _has_pattern(self, element: Any, name: str) -> bool:
        self.asked.append(name)
        return name in self.supported


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> World:
    return World(monkeypatch)


@pytest.fixture
def page() -> Typed:
    return Typed(FakeApp([FakeElement("Window", "Demo")]))  # type: ignore[arg-type]


def public(cls: type) -> set[str]:
    return {name for name in dir(cls) if not name.startswith("_")}


COMMON = public(BoundControl)

EXPECTED = {
    BoundButton: {"click", "double_click", "right_click"},
    BoundTextBox: {"type", "clear", "press", "value"},
    BoundCheckBox: {"click", "double_click", "right_click", "check", "uncheck", "toggle"}
    | {"is_checked"},
    BoundRadioButton: {"click", "double_click", "right_click", "select", "is_selected"},
    BoundComboBox: {"select", "selected", "selected_items", "items", "expand", "collapse"}
    | {"value"},
    BoundListBox: {"select", "selected", "selected_items", "items"},
    BoundListItem: {"click", "double_click", "right_click", "select", "is_selected"},
    BoundDataGrid: {"row", "cell", "row_count", "column_count", "find_row", "select"}
    | {"selected_items"},
    BoundTreeView: {"select", "selected", "selected_items", "items"},
    BoundTabControl: {"select", "selected", "selected_items", "items"},
    BoundText: set(),
}


@pytest.mark.parametrize("cls", list(EXPECTED))
def test_each_type_offers_exactly_its_actions(cls: type[BoundControl]) -> None:
    assert public(cls) == COMMON | EXPECTED[cls]


def test_common_base_has_the_shared_surface() -> None:
    assert {
        "resolve",
        "exists",
        "is_visible",
        "info",
        "wait_for",
        "highlight",
        "text",
        "is_enabled",
        "focus",
        "scroll_into_view",
        "hover",
        "nth",
        "locator",
        "qualname",
        "perform",
        "step",
    } <= COMMON
    assert not COMMON & {"click", "type", "select", "check", "expand", "row", "cell"}


@pytest.mark.parametrize(
    "attribute,cls",
    [
        ("save", BoundButton),
        ("name", BoundTextBox),
        ("agree", BoundCheckBox),
        ("male", BoundRadioButton),
        ("country", BoundComboBox),
        ("colors", BoundListBox),
        ("nav", BoundListItem),
        ("grid", BoundDataGrid),
        ("tree", BoundTreeView),
        ("tabs", BoundTabControl),
        ("caption", BoundText),
    ],
)
def test_instance_access_binds_the_declared_type(page: Typed, attribute: str, cls: type) -> None:
    bound = getattr(page, attribute)
    assert type(bound) is cls
    assert bound.page is page
    assert bound.definition is getattr(Typed, attribute)
    assert isinstance(getattr(Typed, attribute), Element)


def test_class_access_returns_the_definition() -> None:
    assert type(Typed.save) is Button
    assert type(Typed.country) is ComboBox
    assert Typed.save.qualname == "Typed.save"


def test_plain_element_still_offers_every_action(page: Typed) -> None:
    assert type(page.generic) is BoundElement
    for method in (
        "click",
        "double_click",
        "right_click",
        "hover",
        "type",
        "clear",
        "press",
        "select",
        "check",
        "uncheck",
        "expand",
        "collapse",
        "focus",
        "scroll_into_view",
        "text",
        "value",
        "is_enabled",
        "is_checked",
        "selected_items",
        "nth",
        "row",
        "cell",
        "row_count",
        "column_count",
        "find_row",
    ):
        assert hasattr(BoundElement, method), method
    assert issubclass(BoundElement, BoundControl)


def test_typed_locator_has_no_control_type_filter() -> None:
    assert Typed.save.locator() == Locator(automation_id="Save")
    assert Typed.country.locator().control_type is None


def test_typed_elements_work_as_within_and_root() -> None:
    class Inner(Page):
        panel = Element(automation_id="Panel")
        ok = Button(name="OK", within=panel)
        box = ComboBox(automation_id="B", within=ok)

    assert Inner.ok.within is Inner.panel
    assert Inner.box.locator().within is not None


# -- validation -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "attribute,patterns_needed",
    [
        ("save", {"Invoke"}),
        ("name", {"Value"}),
        ("agree", {"Toggle"}),
        ("male", {"SelectionItem"}),
        ("country", {"ExpandCollapse", "Selection"}),
        ("colors", {"Selection"}),
        ("grid", {"Grid"}),
        ("tabs", {"Selection"}),
    ],
)
def test_a_matching_element_passes_and_a_mismatch_names_everything(
    page: Typed, world: World, attribute: str, patterns_needed: set[str]
) -> None:
    world.supported = set(patterns_needed)
    assert getattr(page, attribute).resolve() is world.element
    world.supported = set()
    with pytest.raises(ElementTypeError) as caught:
        getattr(page, attribute).resolve()
    message = str(caught.value)
    declared = type(getattr(Typed, attribute)).__name__
    assert f"Typed.{attribute} is declared as {declared}" in message
    assert "control type 'Custom'" in message
    assert "class 'Thing'" in message
    assert "name 'thing'" in message
    assert "validate=False" in message
    assert isinstance(caught.value, ActionError)


def test_either_of_alternative_patterns_is_enough(page: Typed, world: World) -> None:
    world.supported = {"Toggle"}
    assert page.save.resolve() is world.element  # a toggle button is a button
    world.supported = {"Text"}
    assert page.name.resolve() is world.element


def test_missing_patterns_are_listed(page: Typed, world: World) -> None:
    world.supported = {"ExpandCollapse"}
    with pytest.raises(ElementTypeError, match="does not support the Selection pattern"):
        page.country.resolve()
    world.supported = set()
    with pytest.raises(
        ElementTypeError, match="does not support the ExpandCollapse and Selection pattern"
    ):
        page.country.resolve()


def test_control_type_is_the_fallback_without_patterns(page: Typed, world: World) -> None:
    world.element = FakeElement("Tree", "t")
    assert page.tree.resolve() is world.element
    world.element = FakeElement("Custom", "t", class_name="MyTree")
    with pytest.raises(ElementTypeError, match="not one of the control types Tree"):
        page.tree.resolve()
    for control_type in ("Text", "Edit", "Document"):
        world.element = FakeElement(control_type, "label")
        assert page.caption.resolve() is world.element
    world.element = FakeElement("Button", "b")
    with pytest.raises(ElementTypeError, match=r"Typed.caption is declared as Text"):
        page.caption.resolve()


def test_opt_out_skips_validation(page: Typed, world: World) -> None:
    world.supported = set()
    assert page.loose.resolve() is world.element
    assert page.loose.exists()
    assert world.asked == []


def test_plain_element_is_never_validated(page: Typed, world: World) -> None:
    assert page.generic.resolve() is world.element
    assert world.asked == []


def test_a_mismatch_fails_fast_and_is_not_swallowed(page: Typed, world: World) -> None:
    started = waits._clock()
    with pytest.raises(ElementTypeError):
        page.country.expand()
    assert waits._clock() == started  # no retrying until the timeout
    with pytest.raises(ElementTypeError):
        page.country.wait_for("visible")
    with pytest.raises(ElementTypeError):
        page.country.exists()
    with pytest.raises(ElementTypeError):
        _ = page.country.text


def test_check_reports_the_mismatch(page: Typed, world: World) -> None:
    world.supported = {"Invoke"}
    results = page.check()
    assert results["save"] is None
    failure = results["country"]
    assert isinstance(failure, ElementTypeError)
    assert "Typed.country is declared as ComboBox" in str(failure)
    assert results["loose"] is None
    assert results["generic"] is None


def test_nth_keeps_the_type_and_validation(page: Typed, world: World) -> None:
    second = page.country.nth(1)
    assert type(second) is BoundComboBox
    assert second.locator.index == 1
    with pytest.raises(ElementTypeError):
        second.resolve()


# -- behaviour ------------------------------------------------------------------------------------


class Calls:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.log: list[tuple[str, Any]] = []
        for name in (
            "click",
            "type_text",
            "toggle",
            "set_checked",
            "select_self",
            "select_in_combo",
            "select",
            "expand",
            "collapse",
        ):
            monkeypatch.setattr(actions, name, self._record(name))
        monkeypatch.setattr(actions, "combo_item_names", lambda el: ["Red", "Green"])
        monkeypatch.setattr(actions, "listed_item_names", lambda el: ["A", "B"])
        monkeypatch.setattr(actions, "selected_items", lambda el: self.selected)
        monkeypatch.setattr(actions, "is_selected", lambda el: True)
        self.selected: list[str] = []

    def _record(self, name: str) -> Any:
        def call(el: Any, *args: Any, **kwargs: Any) -> str:
            self.log.append((name, (args, kwargs)))
            return name

        return call


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch, world: World) -> Calls:
    world.supported = {
        "Invoke",
        "Value",
        "Toggle",
        "SelectionItem",
        "ExpandCollapse",
        "Selection",
        "Grid",
    }
    return Calls(monkeypatch)


def test_button_click_reports_a_step(
    page: Typed, calls: Calls, runtime_setup: list[runtime.StepRecord]
) -> None:
    page.save.click()
    assert [name for name, _ in calls.log] == ["click"]
    assert runtime_setup[-1].action == "click"
    assert runtime_setup[-1].target == "Typed.save"


def test_textbox_types(page: Typed, calls: Calls) -> None:
    page.name.type("Ada", clear=False)
    assert calls.log == [("type_text", (("Ada",), {"clear": False, "keys": False}))]


def test_checkbox_toggle_check_uncheck(page: Typed, calls: Calls) -> None:
    page.agree.toggle()
    page.agree.check()
    page.agree.uncheck()
    assert [name for name, _ in calls.log] == ["toggle", "set_checked", "set_checked"]
    assert [args[0][0] for _, args in calls.log[1:]] == [True, False]


def test_radio_button_select(page: Typed, calls: Calls) -> None:
    page.male.select()
    assert calls.log[-1][0] == "select_self"
    assert page.male.is_selected() is True


def test_combo_select_uses_the_combo_path_and_reads(page: Typed, calls: Calls) -> None:
    page.country.select("Green")
    assert calls.log == [("select_in_combo", (("Green",), {}))]
    assert page.country.items() == ["Red", "Green"]
    assert page.country.selected is None
    calls.selected = ["Green"]
    assert page.country.selected == "Green"
    assert page.country.selected_items() == ["Green"]
    page.country.expand()
    page.country.collapse()
    assert [name for name, _ in calls.log[-2:]] == ["expand", "collapse"]


def test_list_tree_tab_select_generic_path(page: Typed, calls: Calls, world: World) -> None:
    world.element = FakeElement("Tree", "t")
    for bound in (page.colors, page.tree, page.tabs):
        bound.select(re.compile("A"))
        assert bound.items() == ["A", "B"]
    assert [name for name, _ in calls.log] == ["select"] * 3


def test_grid_rows_and_cells_are_plain_elements(page: Typed, calls: Calls) -> None:
    row = page.grid.row(2)
    assert type(row) is BoundElement
    assert row.locator.item == ItemSelector("row", 2)
    cell = page.grid.cell(1, "Name")
    assert type(cell) is BoundElement
    assert cell.locator.item == ItemSelector("cell", 1, "Name")
    # a row is not a grid: the grid's type is not enforced on it
    assert cell.definition is Typed.grid


def test_typed_actions_auto_wait(
    page: Typed, calls: Calls, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.element.is_enabled = False
    fake = FakeTime()
    fake.on_sleep = lambda: setattr(world.element, "is_enabled", True)
    monkeypatch.setattr(waits, "_clock", fake.clock)
    monkeypatch.setattr(waits, "_sleep", fake.sleep)
    page.save.click()
    assert fake.now > 0
    assert calls.log[-1][0] == "click"


# -- user-defined types ---------------------------------------------------------------------------


class BoundDatePicker(BoundControl):
    required_patterns = ("Value",)

    def pick(self, day: str, *, timeout: float | None = None) -> None:
        with self.step("pick", {"day": day}):
            self.perform(timeout, lambda el: actions.type_text(el, day))


class DatePicker(Element[BoundDatePicker]):
    pass


class Calendar(Page):
    window = Window(title="Demo")
    start = DatePicker(automation_id="Start")
    end = DatePicker(automation_id="End", validate=False)


@pytest.fixture
def calendar() -> Calendar:
    return Calendar(FakeApp([FakeElement("Window", "Demo")]))  # type: ignore[arg-type]


def test_a_custom_type_binds_through_its_generic_argument(calendar: Calendar) -> None:
    assert type(calendar.start) is BoundDatePicker
    assert type(Calendar.start) is DatePicker
    assert "pick" in public(BoundDatePicker)
    assert not hasattr(calendar.start, "click")
    assert Calendar.start in Calendar.elements().values()


def test_a_custom_action_auto_waits_and_reports(
    calendar: Calendar,
    world: World,
    monkeypatch: pytest.MonkeyPatch,
    runtime_setup: list[runtime.StepRecord],
) -> None:
    world.supported = {"Value"}
    typed: list[str] = []
    monkeypatch.setattr(actions, "type_text", lambda el, text: typed.append(text))
    world.element.is_enabled = False
    fake = FakeTime()
    fake.on_sleep = lambda: setattr(world.element, "is_enabled", True)
    monkeypatch.setattr(waits, "_clock", fake.clock)
    monkeypatch.setattr(waits, "_sleep", fake.sleep)
    calendar.start.pick("2026-01-02")
    assert typed == ["2026-01-02"]
    assert fake.now > 0  # waited for the control to become enabled
    assert runtime_setup[-1].action == "pick"
    assert runtime_setup[-1].target == "Calendar.start"
    assert runtime_setup[-1].args == {"day": "2026-01-02"}


def test_a_custom_type_is_validated_and_can_opt_out(calendar: Calendar, world: World) -> None:
    with pytest.raises(ElementTypeError, match=r"Calendar.start is declared as DatePicker"):
        calendar.start.resolve()
    assert calendar.end.resolve() is world.element
    world.supported = {"Value"}
    assert calendar.start.resolve() is world.element


def test_a_custom_check_type_hook_replaces_the_rule(world: World) -> None:
    class BoundStrict(BoundControl):
        def check_type(self, element: Any) -> None:
            if element.class_name != "Strict":
                raise self.type_mismatch(element, "is not a Strict control")

    class Strict(Element[BoundStrict]):
        pass

    class P(Page):
        window = Window(title="Demo")
        one = Strict(automation_id="One")

    one = P(FakeApp([FakeElement("Window", "Demo")])).one  # type: ignore[arg-type]
    with pytest.raises(ElementTypeError, match="is not a Strict control"):
        one.resolve()
    world.element = FakeElement("Custom", "x", class_name="Strict")
    assert one.resolve() is world.element


def test_subclassing_a_builtin_type_keeps_its_binding(world: World) -> None:
    class FancyCombo(ComboBox):
        pass

    class P(Page):
        window = Window(title="Demo")
        box = FancyCombo(automation_id="Box")

    assert type(P(FakeApp([FakeElement("Window", "Demo")])).box) is BoundComboBox  # type: ignore[arg-type]


def test_unparameterized_subclass_of_element_is_generic(world: World) -> None:
    class Legacy(Element):  # type: ignore[type-arg]
        pass

    class P(Page):
        window = Window(title="Demo")
        thing = Legacy(automation_id="T")

    assert type(P(FakeApp([FakeElement("Window", "Demo")])).thing) is BoundElement  # type: ignore[arg-type]


def test_elements_collections_are_unchanged() -> None:
    class P(Page):
        window = Window(title="Demo")
        items = Elements(control_type="ListItem")

    assert type(P(FakeApp([FakeElement("Window", "Demo")])).items) is model.BoundElements  # type: ignore[arg-type]


def test_every_builtin_is_exported_and_listed() -> None:
    assert set(controls.__all__) >= {
        "Button",
        "TextBox",
        "CheckBox",
        "RadioButton",
        "ComboBox",
        "ListBox",
        "ListItem",
        "DataGrid",
        "TreeView",
        "TabControl",
        "Text",
    }
    assert not hasattr(controls, "Menu")
