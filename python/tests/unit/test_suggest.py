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
