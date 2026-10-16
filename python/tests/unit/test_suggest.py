"""Locator suggestion strategies and executable code rendering."""

import re

import pytest
from fakes import FakeApp, FakeElement

from wintestkit.engine import query
from wintestkit.engine.locator import Locator, WindowLocator
from wintestkit.engine.resolve import Scope, resolve
from wintestkit.engine.suggest import (
    attribute_name_for,
    render_element_code,
    render_window_code,
    suggest_locator,
)


@pytest.fixture(autouse=True)
def fake_conditions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(query, "make_condition", lambda **props: props)


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Sign in", "sign_in"),
        ("StatusText", "status_text"),
        ("class", "class_"),
        ("12 cats", "_12_cats"),
        ("!!!", "button_1"),
    ],
)
def test_names(name: str, expected: str) -> None:
    assert attribute_name_for(FakeElement("Button", name).info()) == expected
    assert (
        attribute_name_for(FakeElement("Text", automation_id="StatusText").info()) == "status_text"
    )
    assert attribute_name_for(FakeElement("Edit").info()) == "edit_1"


def test_rendering() -> None:
    locator = Locator(
        automation_id='a"b\n',
        control_type="Button",
        name=re.compile("OK", re.I),
        within=Locator(name="Panel"),
    )
    code = render_element_code(locator, "panel")
    assert (
        code
        == 'Element(automation_id="a\\"b\\n", control_type="Button", name=re.compile("OK", re.IGNORECASE), within=panel)'
    )
    assert (
        render_window_code(WindowLocator(title="Demo", class_name="#32770"))
        == 'Window(title="Demo", class_name="#32770")'
    )
    evaluated = eval(code, {"Element": Locator, "panel": locator.within, "re": re})
    assert evaluated == locator


@pytest.mark.parametrize("name", ["123456", "Clock 12:30", "Day 12/30", "a" * 61, "   "])
def test_volatile_names_use_index(name: str) -> None:
    button = FakeElement("Button", name, automation_id="123")
    app = FakeApp([FakeElement("Window", "Demo", children=[button])])
    suggestion = suggest_locator(button, app)
    assert suggestion.strategy == "index"
    assert resolve(Scope(app), suggestion.locator).same_as(button)


def test_strategies_and_helpers() -> None:
    selected = FakeElement("Button", "OK", class_name="Button")
    other = FakeElement("Button", "OK", class_name="Button")
    group = FakeElement("Group", "Panel B", children=[selected])
    app = FakeApp([FakeElement("Window", "Demo", children=[other, group])])
    suggestion = suggest_locator(selected, app)
    assert suggestion.strategy == "within"
    assert suggestion.helpers[0][0] == "panel_b"
    assert "within=panel_b" in suggestion.code
    assert resolve(Scope(app), suggestion.locator).same_as(selected)
    selected.automation_id = "Submit"
    assert suggest_locator(selected, app).strategy == "automation_id"
    selected.automation_id = ""
    selected.name = "Unique"
    assert suggest_locator(selected, app).strategy == "name"
    selected.name = ""
    selected.class_name = "SpecialButton"
    assert suggest_locator(selected, app).strategy == "class_name"


def test_nested_helpers_and_fragile_index() -> None:
    button = FakeElement("Button", "OK")
    group = FakeElement("Group", "Panel", children=[button, FakeElement("Button", "Other")])
    section = FakeElement("Group", "Section", children=[group])
    duplicate = FakeElement("Group", "Panel", children=[FakeElement("Button", "OK")])
    app = FakeApp([FakeElement("Window", "Demo", children=[section, duplicate])])
    suggestion = suggest_locator(button, app)
    assert suggestion.strategy == "within"
    assert [helper[0] for helper in suggestion.helpers] == ["section", "panel"]
    assert resolve(Scope(app), suggestion.locator).same_as(button)
    group.add(FakeElement("Button", "OK"))
    suggestion = suggest_locator(button, app)
    assert suggestion.strategy == "index"
    assert suggestion.locator.index == 0
    assert resolve(Scope(app), suggestion.locator).same_as(button)


def test_window_disambiguation() -> None:
    button = FakeElement("Button", "OK")
    window = FakeElement("Window", "Dialog", class_name="#32770", children=[button])
    app = FakeApp([FakeElement("Window", "Dialog", class_name="Other"), window])
    suggestion = suggest_locator(button, app)
    assert suggestion.window is not None
    assert suggestion.window[1].class_name == "#32770"
    assert suggestion.to_dict()["window"]["locator"]["title"] == "Dialog"


def test_candidate_must_match_selected(monkeypatch: pytest.MonkeyPatch) -> None:
    button = FakeElement("Button", "OK")
    other = FakeElement("Button", "Other")
    app = FakeApp([FakeElement("Window", "Demo", children=[button, other])])
    from wintestkit.engine import suggest

    original = suggest.query_all
    monkeypatch.setattr(
        suggest,
        "query_all",
        lambda root, locator: [other] if locator.name else original(root, locator),
    )
    assert suggest_locator(button, app).strategy == "index"


def test_typed_declaration_for_a_known_control_type() -> None:
    combo = FakeElement("ComboBox", "Country", automation_id="Country")
    edit = FakeElement("Edit", "", automation_id="Street")
    app = FakeApp([FakeElement("Window", "Demo", children=[combo, edit])])
    suggestion = suggest_locator(combo, app)
    assert suggestion.code == 'ComboBox(automation_id="Country")'
    assert suggestion.locator == Locator(automation_id="Country")
    assert resolve(Scope(app), suggestion.locator).same_as(combo)
    assert suggest_locator(edit, app).code == 'TextBox(automation_id="Street")'


@pytest.mark.parametrize(
    "control_type,typed",
    [
        ("Button", "Button"),
        ("CheckBox", "CheckBox"),
        ("RadioButton", "RadioButton"),
        ("List", "ListBox"),
        ("ListItem", "ListItem"),
        ("DataGrid", "DataGrid"),
        ("Tree", "TreeView"),
        ("Tab", "TabControl"),
        ("Text", "Text"),
    ],
)
def test_every_built_in_type_maps_from_its_control_type(control_type: str, typed: str) -> None:
    target = FakeElement(control_type, "x", automation_id="Target")
    app = FakeApp([FakeElement("Window", "Demo", children=[target])])
    assert suggest_locator(target, app).code == f'{typed}(automation_id="Target")'


def test_the_control_type_stays_when_it_is_needed_for_uniqueness() -> None:
    button = FakeElement("Button", "OK")
    label = FakeElement("Text", "OK")
    app = FakeApp([FakeElement("Window", "Demo", children=[button, label])])
    suggestion = suggest_locator(button, app)
    assert suggestion.code == 'Button(control_type="Button", name="OK")'
    assert resolve(Scope(app), suggestion.locator).same_as(button)


def test_other_control_types_stay_plain_elements() -> None:
    group = FakeElement("Group", "Panel", automation_id="Panel")
    app = FakeApp([FakeElement("Window", "Demo", children=[group])])
    assert (
        suggest_locator(group, app).code == 'Element(automation_id="Panel", control_type="Group")'
    )


def test_the_typed_name_is_used_with_within_and_index() -> None:
    first = FakeElement("Edit", "", class_name="TextBox")
    second = FakeElement("Edit", "", class_name="TextBox")
    app = FakeApp([FakeElement("Window", "Demo", children=[first, second])])
    suggestion = suggest_locator(second, app)
    assert suggestion.strategy == "index"
    assert suggestion.code.startswith("TextBox(")
    assert 'control_type="Edit"' in suggestion.code
    button = FakeElement("Button", "OK")
    group = FakeElement("Group", "Panel B", children=[button])
    app = FakeApp([FakeElement("Window", "Demo", children=[FakeElement("Button", "OK"), group])])
    within = suggest_locator(button, app)
    assert within.strategy == "within"
    assert within.code.startswith("Button(") and "within=panel_b" in within.code
    assert within.helpers[0][1].startswith("Element(")
