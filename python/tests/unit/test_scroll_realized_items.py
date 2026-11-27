"""Off-screen grid rows, cells and list items that are realized are scrolled into view."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fakes import FakeElement

from wintestkit.engine import actions
from wintestkit.errors import ActionError, InspectorError, UIAError


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(actions.time, "sleep", lambda seconds: None)


def _grid_cell() -> tuple[FakeElement, FakeElement]:
    cell = FakeElement("DataItem", "cell", class_name="DataGridCell")
    row = FakeElement("DataItem", "row", class_name="DataGridRow", children=[cell])
    cell.is_offscreen = row.is_offscreen = True
    return row, cell


def _patterns(monkeypatch: pytest.MonkeyPatch, *having: FakeElement) -> list[FakeElement]:
    scrolled: list[FakeElement] = []

    def scroll(element: FakeElement) -> None:
        scrolled.append(element)
        element.is_offscreen = False

    monkeypatch.setattr(
        actions.patterns,
        "has_pattern",
        lambda element, name: name == "ScrollItem" and any(element is item for item in having),
    )
    monkeypatch.setattr(actions.patterns, "scroll_into_view", scroll)
    return scrolled


def test_a_cell_without_the_pattern_scrolls_through_its_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row, cell = _grid_cell()
    scrolled = _patterns(monkeypatch, row)
    # Scrolling the row brings its cell on screen.
    monkeypatch.setattr(
        actions.patterns,
        "scroll_into_view",
        lambda element: (scrolled.append(element), setattr(cell, "is_offscreen", False)),
    )
    monkeypatch.setattr(actions, "wpf_capable", lambda element: False)
    actions.ensure_visible(cell)
    assert scrolled == [row]


def test_the_agent_scrolls_a_realized_item_whose_peer_has_no_scroll_pattern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, cell = _grid_cell()
    _patterns(monkeypatch)
    acted: list[tuple[Any, str]] = []
    managed = SimpleNamespace(name="managed cell")
    monkeypatch.setattr(actions, "wpf_capable", lambda element: True)
    monkeypatch.setattr(actions, "to_managed", lambda element: managed)
    monkeypatch.setattr(actions, "_wpf_patterns", lambda element: {"Invoke"})

    def act(element: Any, verb: str, *args: Any) -> None:
        acted.append((element, verb))
        cell.is_offscreen = False

    monkeypatch.setattr(actions, "_wpf_act", act)
    actions.ensure_visible(cell)
    assert acted == [(managed, "bring_into_view")]


def test_the_agent_uses_the_scroll_item_pattern_when_the_object_has_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = FakeElement("ListItem", "item", class_name="ListBoxItem")
    item.is_offscreen = True
    _patterns(monkeypatch)
    verbs: list[str] = []
    monkeypatch.setattr(actions, "wpf_capable", lambda element: True)
    monkeypatch.setattr(actions, "to_managed", lambda element: object())
    monkeypatch.setattr(actions, "_wpf_patterns", lambda element: {"ScrollItem"})
    monkeypatch.setattr(
        actions,
        "_wpf_act",
        lambda element, verb, *a: (verbs.append(verb), setattr(item, "is_offscreen", False)),
    )
    actions.ensure_visible(item)
    assert verbs == ["scroll_into_view"]


def test_an_item_that_cannot_be_scrolled_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    row, cell = _grid_cell()
    scrolled: list[FakeElement] = []
    monkeypatch.setattr(
        actions.patterns,
        "has_pattern",
        lambda element, name: name == "ScrollItem" and element is row,
    )

    def scroll(element: FakeElement) -> None:
        scrolled.append(element)
        raise UIAError("the pattern failed")

    monkeypatch.setattr(actions.patterns, "scroll_into_view", scroll)
    monkeypatch.setattr(actions, "wpf_capable", lambda element: True)

    def broken(element: Any) -> Any:
        raise InspectorError("mapping failed", code="mappingFailed")

    monkeypatch.setattr(actions, "to_managed", broken)
    with pytest.raises(ActionError, match="off-screen and cannot be scrolled into view"):
        actions.ensure_visible(cell)
    assert scrolled == [row]


def test_elements_that_are_not_wpf_items_are_not_mapped(monkeypatch: pytest.MonkeyPatch) -> None:
    _, cell = _grid_cell()
    _patterns(monkeypatch)
    monkeypatch.setattr(actions, "wpf_capable", lambda element: False)
    monkeypatch.setattr(actions, "to_managed", lambda element: pytest.fail("mapped"))
    with pytest.raises(ActionError, match="cannot be scrolled into view"):
        actions.ensure_visible(cell)


@pytest.mark.parametrize(
    ("control_type", "expected"),
    [("DataItem", True), ("ListItem", True), ("TreeItem", True), ("Button", False)],
)
def test_realized_item_types_scroll_through_the_agent(
    monkeypatch: pytest.MonkeyPatch, control_type: str, expected: bool
) -> None:
    monkeypatch.setattr(actions, "wpf_capable", lambda element: True)
    assert actions.scrolls_through_agent(FakeElement(control_type)) is expected
    monkeypatch.setattr(actions, "wpf_capable", lambda element: False)
    assert actions.scrolls_through_agent(FakeElement(control_type)) is False
