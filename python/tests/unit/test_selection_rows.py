"""Multi-selection actions and grid table checks, against in-memory fakes."""

import re
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeApp, FakeElement

from wintestkit import model, runtime
from wintestkit.config import load_config
from wintestkit.controls import DataGrid, ListBox
from wintestkit.engine import actions, table, waits
from wintestkit.errors import ActionError
from wintestkit.expect import expect
from wintestkit.model import Element, Page, Window
from wintestkit.uia import patterns

# -- fakes ----------------------------------------------------------------------------------------


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class Row:
    def __init__(self, name: str) -> None:
        self.name = name
        self.selected = False


class Demo(Page):
    window = Window(title="Demo")
    colors = ListBox(automation_id="Colors")
    grid = DataGrid(automation_id="Grid")
    loose = Element(automation_id="Loose")


@pytest.fixture(autouse=True)
def runtime_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[runtime.StepRecord]:
    runtime.reset()
    runtime.set_config(load_config(tmp_path, {"timeout": 2.0}))
    fake = FakeTime()
    monkeypatch.setattr(waits, "_clock", fake.clock)
    monkeypatch.setattr(waits, "_sleep", fake.sleep)
    records: list[runtime.StepRecord] = []
    runtime.add_step_listener(records.append)
    yield records  # type: ignore[misc]
    runtime.reset()


class ListWorld:
    """A list control with named items; records the pattern and mouse operations it receives."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, names: list[str]) -> None:
        self.container = FakeElement("List", "colors", automation_id="Colors")
        self.items = [Row(name) for name in names]
        self.multiple = True
        self.log: list[tuple[Any, ...]] = []
        self.clicks_work = True
        monkeypatch.setattr(actions, "uia_of", lambda el: el)
        monkeypatch.setattr(patterns, "has_pattern", lambda el, name: name == "Selection")
        monkeypatch.setattr(patterns, "can_select_multiple", lambda el: self.multiple)
        monkeypatch.setattr(patterns, "selection", lambda el: [i for i in self.items if i.selected])
        monkeypatch.setattr(patterns, "add_to_selection", self.add)
        monkeypatch.setattr(patterns, "remove_from_selection", self.remove)
        monkeypatch.setattr(actions, "selected_items", self.selected)
        monkeypatch.setattr(actions, "is_selected", lambda item: item.selected)
        monkeypatch.setattr(actions, "_resolve_item", self.resolve)
        monkeypatch.setattr(
            actions, "_scroll_item", lambda item: self.log.append(("scroll", item.name))
        )
        monkeypatch.setattr(actions, "select_self", self.select_only)
        monkeypatch.setattr(actions, "_click_item", self.click)

    def selected(self, el: Any) -> list[str]:
        return [i.name for i in self.items if i.selected]

    def resolve(self, el: Any, item: Any, mode: Any) -> Row:
        if isinstance(item, int):
            return self.items[item]
        for row in self.items:
            if (row.name == item) if isinstance(item, str) else item.search(row.name):
                return row
        raise ActionError(f"no item {item!r}")

    def select_only(self, item: Row) -> None:
        self.log.append(("select", item.name))
        for row in self.items:
            row.selected = row is item

    def add(self, item: Row) -> None:
        self.log.append(("add", item.name))
        item.selected = True

    def remove(self, item: Row) -> None:
        self.log.append(("remove", item.name))
        item.selected = False

    def click(self, container: Any, item: Row, modifiers: tuple[int, ...]) -> None:
        self.log.append(("click", item.name, modifiers))
        if not self.clicks_work:
            return
        if modifiers:
            item.selected = not item.selected
        else:
            self.select_only(item)
            self.log.pop()


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> ListWorld:
    return ListWorld(monkeypatch, ["One", "Two", "Three", "Four", "Five", "Six"])


# -- pattern mode ---------------------------------------------------------------------------------


def test_pattern_select_replaces_then_adds(world: ListWorld) -> None:
    world.items[5].selected = True
    actions.select_items(world.container, ["Two", "Four"])
    assert world.selected(None) == ["Two", "Four"]
    assert [e for e in world.log if e[0] != "scroll"] == [("select", "Two"), ("add", "Four")]


def test_pattern_add_keeps_the_selection(world: ListWorld) -> None:
    actions.select_items(world.container, ["Two", "Four"])
    world.log.clear()
    actions.select_items(world.container, ["Six"], add=True)
    assert world.selected(None) == ["Two", "Four", "Six"]
    assert [e[0] for e in world.log if e[0] != "scroll"] == ["add"]


def test_pattern_add_skips_items_that_are_already_selected(world: ListWorld) -> None:
    actions.select_items(world.container, ["Two"])
    world.log.clear()
    actions.select_items(world.container, ["Two", "Three"], add=True)
    assert [e for e in world.log if e[0] != "scroll"] == [("add", "Three")]


def test_items_may_be_indices_and_regexes(world: ListWorld) -> None:
    actions.select_items(world.container, [0, re.compile("^Th"), "Six"])
    assert world.selected(None) == ["One", "Three", "Six"]


def test_duplicate_items_are_selected_once(world: ListWorld) -> None:
    actions.select_items(world.container, ["Two", "Two", "Four"])
    assert world.selected(None) == ["Two", "Four"]


def test_pattern_deselect_uses_remove_from_selection(world: ListWorld) -> None:
    actions.select_items(world.container, ["Two", "Four", "Six"])
    world.log.clear()
    actions.deselect_items(world.container, ["Two", "One"])
    assert world.selected(None) == ["Four", "Six"]
    assert [e for e in world.log if e[0] != "scroll"] == [("remove", "Two")]


def test_pattern_clear_selection(world: ListWorld) -> None:
    actions.select_items(world.container, ["Two", "Four"])
    actions.clear_selection(world.container)
    assert world.selected(None) == []


def test_pattern_refuses_several_items_on_a_single_select_control(world: ListWorld) -> None:
    world.multiple = False
    with pytest.raises(ActionError, match="CanSelectMultiple"):
        actions.select_items(world.container, ["Two", "Four"])
    assert world.log == []
    actions.select_items(world.container, ["Two"])
    assert world.selected(None) == ["Two"]


def test_empty_item_lists_are_refused(world: ListWorld) -> None:
    with pytest.raises(ActionError, match="at least one item"):
        actions.select_items(world.container, [])
    with pytest.raises(ActionError, match="at least one item"):
        actions.deselect_items(world.container, [])


def test_missing_item_is_reported(world: ListWorld) -> None:
    with pytest.raises(ActionError, match="Nope"):
        actions.select_items(world.container, ["Two", "Nope"])


def test_a_control_without_selection_is_refused(
    world: ListWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(patterns, "has_pattern", lambda el, name: False)
    with pytest.raises(ActionError, match="not supported"):
        actions.select_items(world.container, ["Two"])


def test_a_combo_box_is_refused(world: ListWorld) -> None:
    world.container.control_type = "ComboBox"
    with pytest.raises(ActionError, match="not supported"):
        actions.clear_selection(world.container)


# -- mouse mode -----------------------------------------------------------------------------------


def test_mouse_clicks_the_first_item_and_ctrl_clicks_the_others(world: ListWorld) -> None:
    actions.select_items(world.container, ["Two", "Four"], mode="mouse")
    assert world.selected(None) == ["Two", "Four"]
    ctrl = actions.parse_modifiers("Ctrl")
    assert world.log == [("click", "Two", ()), ("click", "Four", ctrl)]


def test_mouse_add_ctrl_clicks_every_new_item(world: ListWorld) -> None:
    actions.select_items(world.container, ["Two"], mode="mouse")
    world.log.clear()
    actions.select_items(world.container, ["Two", "Six"], add=True, mode="mouse")
    assert world.selected(None) == ["Two", "Six"]
    assert world.log == [("click", "Six", actions.parse_modifiers("Ctrl"))]


def test_mouse_deselect_ctrl_clicks_selected_items_only(world: ListWorld) -> None:
    actions.select_items(world.container, ["Two", "Four"], mode="mouse")
    world.log.clear()
    actions.deselect_items(world.container, ["Two", "Six"], mode="mouse")
    assert world.selected(None) == ["Four"]
    assert world.log == [("click", "Two", actions.parse_modifiers("Ctrl"))]


def test_mouse_clear_selection_ctrl_clicks_each_selected_item(world: ListWorld) -> None:
    actions.select_items(world.container, ["Two", "Four"], mode="mouse")
    world.log.clear()
    actions.clear_selection(world.container, mode="mouse")
    assert world.selected(None) == []
    assert [e[1] for e in world.log] == ["Two", "Four"]


def test_mouse_mode_never_uses_selection_patterns(world: ListWorld) -> None:
    actions.select_items(world.container, ["Two", "Four"], mode="mouse")
    actions.deselect_items(world.container, ["Two"], mode="mouse")
    assert {entry[0] for entry in world.log} == {"click"}


def test_mouse_that_does_not_change_the_selection_is_an_error(world: ListWorld) -> None:
    world.clicks_work = False
    with pytest.raises(ActionError) as failure:
        actions.select_items(world.container, ["Two", "Four"], mode="mouse")
    message = str(failure.value)
    assert "['Two', 'Four']" in message
    assert "is []" in message


def test_selection_is_verified_with_a_bounded_wait(
    world: ListWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    reads = [0]
    real = world.selected

    def lagging(el: Any) -> list[str]:
        reads[0] += 1
        return real(el) if reads[0] > 3 else []

    monkeypatch.setattr(actions, "selected_items", lagging)
    actions.select_items(world.container, ["Two"], timeout=5)
    assert reads[0] > 3


def test_click_item_passes_modifiers_to_the_mouse(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Any] = []
    monkeypatch.setattr(actions, "uia_of", lambda el: el)
    monkeypatch.setattr(actions, "_mouse_click", lambda el, **kwargs: seen.append(kwargs))
    item = FakeElement("ListItem", "One")
    actions._click_item(FakeElement("List"), item, actions._CTRL)
    assert seen == [{"modifiers": actions._CTRL}]


# -- model layer ----------------------------------------------------------------------------------


class Recorded:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.log: list[tuple[str, Any, dict[str, Any]]] = []
        self.element = FakeElement("List", "colors", automation_id="Colors")
        monkeypatch.setattr(model, "resolve", lambda scope, locator: self.element)
        monkeypatch.setattr(patterns, "has_pattern", lambda el, name: True)
        for name in ("select_items", "deselect_items", "clear_selection", "select"):
            monkeypatch.setattr(actions, name, self._record(name))

    def _record(self, name: str) -> Any:
        def call(el: Any, *args: Any, **kwargs: Any) -> None:
            self.log.append((name, args, kwargs))

        return call


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> Recorded:
    return Recorded(monkeypatch)


@pytest.fixture
def page() -> Demo:
    return Demo(FakeApp([FakeElement("Window", "Demo")]))  # type: ignore[arg-type]


def test_select_a_list_records_one_step(
    page: Demo, recorded: Recorded, runtime_setup: list[runtime.StepRecord]
) -> None:
    page.colors.select(["Two", "Four"])
    name, args, kwargs = recorded.log[-1]
    assert name == "select_items" and args == (["Two", "Four"],)
    assert kwargs["add"] is False and kwargs["mode"] == runtime.get_config().input_mode
    step = runtime_setup[-1]
    assert step.action == "select"
    assert step.args == {"items": ["Two", "Four"], "add": False}


def test_select_add_and_single_item_forms(page: Demo, recorded: Recorded) -> None:
    page.colors.select("Six", add=True)
    assert recorded.log[-1][:2] == ("select_items", (["Six"],))
    assert recorded.log[-1][2]["add"] is True
    page.colors.select("Six")
    assert recorded.log[-1][0] == "select"


def test_deselect_and_clear_record_steps(
    page: Demo, recorded: Recorded, runtime_setup: list[runtime.StepRecord]
) -> None:
    page.colors.deselect("Two")
    assert recorded.log[-1][:2] == ("deselect_items", (["Two"],))
    assert runtime_setup[-1].action == "deselect"
    assert runtime_setup[-1].args == {"items": ["Two"]}
    page.colors.deselect(("Two", "Four"))
    assert recorded.log[-1][1] == (["Two", "Four"],)
    page.colors.clear_selection()
    assert recorded.log[-1][0] == "clear_selection"
    assert runtime_setup[-1].action == "clear_selection"


def test_mode_comes_from_the_config(page: Demo, recorded: Recorded, tmp_path: Path) -> None:
    runtime.set_config(load_config(tmp_path, {"timeout": 2.0, "input_mode": "mouse"}))
    page.colors.select(["Two", "Four"])
    assert recorded.log[-1][2]["mode"] == "mouse"


def test_the_grid_and_the_generic_element_take_lists_too(page: Demo, recorded: Recorded) -> None:
    page.grid.select([0, 2])
    assert recorded.log[-1][:2] == ("select_items", ([0, 2],))
    page.loose.select([0, 2], add=True)
    page.grid.clear_selection()
    page.loose.deselect([1])
    assert [name for name, _, _ in recorded.log[-4:]] == [
        "select_items",
        "select_items",
        "clear_selection",
        "deselect_items",
    ]


# -- table comparison -----------------------------------------------------------------------------

HEADERS = ["Name", "Qty", "City"]
ROWS = [["Apple", "3", "Paris"], ["Banana", "5", "Rome"], ["Cherry", "7", "Oslo"]]


@pytest.fixture
def grid_world(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    rows = [list(row) for row in ROWS]
    element = FakeElement("DataGrid", "grid", automation_id="Grid")
    monkeypatch.setattr(model, "resolve", lambda scope, locator: element)
    monkeypatch.setattr(patterns, "has_pattern", lambda el, name: True)
    monkeypatch.setattr(patterns, "grid_size", lambda el: (len(rows), len(HEADERS)))
    monkeypatch.setattr(actions, "grid_headers", lambda el: HEADERS)
    fake_rows = [FakeElement("DataItem") for _ in rows]
    for index, row in enumerate(fake_rows):
        for column in range(len(HEADERS)):
            row.add(FakeElement("Custom", properties={"position": (index, column)}))
    monkeypatch.setattr(actions, "uia_of", lambda el: el)
    monkeypatch.setattr(patterns, "grid_item", lambda el, r, c: fake_rows[r].children()[c])
    monkeypatch.setattr(
        actions,
        "get_text",
        lambda cell: rows[cell.properties["position"][0]][cell.properties["position"][1]],
    )
    return rows


def test_rows_exact_match(page: Demo, grid_world: list[list[str]]) -> None:
    expect(page.grid).to_have_rows(ROWS)
    expect(page.grid).to_have_rows([tuple(row) for row in ROWS])
    expect(page.loose).to_have_rows(ROWS)


def test_rows_as_dicts_compare_only_named_columns(page: Demo, grid_world: list[list[str]]) -> None:
    expect(page.grid).to_have_rows(
        [
            {"Name": "Apple", "Qty": "3"},
            {"Name": "Banana", "Qty": "5"},
            {"Name": "Cherry", "Qty": 7},
        ]
    )
    expect(page.grid).to_have_rows([{"City": "Paris"}, {"City": "Rome"}, {"City": "Oslo"}])
    expect(page.grid).to_have_rows([{0: "Apple"}, {0: "Banana"}, {0: "Cherry"}])


def test_rows_columns_limit_and_order(page: Demo, grid_world: list[list[str]]) -> None:
    expect(page.grid).to_have_rows(
        [["Paris", "Apple"], ["Rome", "Banana"], ["Oslo", "Cherry"]], columns=["City", "Name"]
    )
    expect(page.grid).to_have_rows([["3"], ["5"], ["7"]], columns=[1])
    expect(page.grid).to_have_rows(
        [{"Qty": "3"}, {"Qty": "5"}, {"Qty": "7"}], columns=["Qty", "Name"]
    )


def test_rows_unordered_is_a_multiset(page: Demo, grid_world: list[list[str]]) -> None:
    shuffled = [ROWS[2], ROWS[0], ROWS[1]]
    expect(page.grid).to_have_rows(shuffled, ordered=False)
    with pytest.raises(AssertionError, match="row 1"):
        expect(page.grid, timeout=0).to_have_rows(shuffled)
    with pytest.raises(AssertionError, match="no unused row matches expected row 2"):
        expect(page.grid, timeout=0).to_have_rows([ROWS[0], ROWS[0], ROWS[1]], ordered=False)


def test_rows_regex_cells(page: Demo, grid_world: list[list[str]]) -> None:
    expect(page.grid).to_have_rows(
        [
            ["Apple", re.compile(r"^\d$"), "Paris"],
            [re.compile("^B"), "5", re.compile("om")],
            ["Cherry", re.compile("7"), "Oslo"],
        ]
    )
    expect(page.grid).to_have_rows(
        [[re.compile("^C")], [re.compile("^A")], [re.compile("^B")]], columns=[0], ordered=False
    )


def test_rows_failure_names_the_first_difference(page: Demo, grid_world: list[list[str]]) -> None:
    wrong = [ROWS[0], ["Banana", "6", "Rome"], ROWS[2]]
    with pytest.raises(AssertionError) as failure:
        expect(page.grid, timeout=0.2).to_have_rows(wrong)
    message = str(failure.value)
    assert "row 2, column 'Qty': expected '6', got '5'" in message
    assert "Expected table:" in message and "Actual table:" in message
    assert "Banana | 5" in message and "Banana | 6" in message


def test_rows_count_mismatch(page: Demo, grid_world: list[list[str]]) -> None:
    with pytest.raises(AssertionError, match="expected 2 rows, got 3"):
        expect(page.grid, timeout=0).to_have_rows(ROWS[:2])


def test_rows_retry_until_the_table_changes(
    page: Demo, grid_world: list[list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    grid_world[1][1] = "6"
    sleeps = [0]
    real_sleep = waits._sleep

    def sleep(seconds: float) -> None:
        sleeps[0] += 1
        grid_world[1][1] = "5"
        real_sleep(seconds)

    monkeypatch.setattr(waits, "_sleep", sleep)
    expect(page.grid).to_have_rows(ROWS)
    assert sleeps[0] >= 1


def test_rows_negated(page: Demo, grid_world: list[list[str]]) -> None:
    expect(page.grid).not_.to_have_rows([ROWS[0]])
    with pytest.raises(AssertionError, match="not"):
        expect(page.grid, timeout=0).not_.to_have_rows(ROWS)


def test_rows_secret_hides_cells(
    page: Demo, grid_world: list[list[str]], runtime_setup: list[runtime.StepRecord]
) -> None:
    grid_world[1][1] = "PRIVATE_ACTUAL"
    with pytest.raises(AssertionError) as failure:
        expect(page.grid, timeout=0, secret=True).to_have_rows(
            [ROWS[0], ["Banana", "PRIVATE_EXPECTED", "Rome"], ROWS[2]]
        )
    assert "PRIVATE_" not in str(failure.value)
    assert "PRIVATE_" not in str([record.to_dict() for record in runtime_setup])


def test_rows_validation_errors(page: Demo, grid_world: list[list[str]]) -> None:
    with pytest.raises(ActionError, match="no column 'Nope'"):
        expect(page.grid, timeout=0).to_have_rows([{"Nope": "x"}])
    with pytest.raises(ActionError, match="out of range"):
        expect(page.grid, timeout=0).to_have_rows([["x"]], columns=[7])
    with pytest.raises(ActionError, match="has 2 cells but 3 columns"):
        expect(page.grid, timeout=0).to_have_rows([["a", "b"]])
    with pytest.raises(ActionError, match="not among the compared columns"):
        expect(page.grid, timeout=0).to_have_rows([{"City": "x"}], columns=["Name"])


def test_read_grid_refuses_big_grids(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(patterns, "grid_size", lambda el: (501, 3))
    element = FakeElement("DataGrid", "grid")
    with pytest.raises(ActionError, match="limited to 500 rows"):
        actions.read_grid(element)


def test_read_grid_reads_the_requested_columns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(actions, "grid_headers", lambda el: [])
    monkeypatch.setattr(patterns, "grid_size", lambda el: (2, 3))
    rows = [FakeElement("DataItem") for _ in range(2)]
    for r, row in enumerate(rows):
        for c in range(3):
            row.add(FakeElement("Custom", f"{r}:{c}"))
    monkeypatch.setattr(patterns, "grid_item", lambda el, r, c: rows[r].children()[c])
    monkeypatch.setattr(actions, "get_text", lambda cell: f" {cell.name} ")
    element = FakeElement("DataGrid", "grid")
    assert actions.read_grid(element) == [["0:0", "0:1", "0:2"], ["1:0", "1:1", "1:2"]]
    assert actions.read_grid(element, [2, 0]) == [["0:2", "0:0"], ["1:2", "1:0"]]


def test_format_table_truncates_long_tables() -> None:
    text = table.format_table(["A"], [("x",)] * 30)
    assert "... 10 more rows" in text


def test_click_item_clicks_the_row_header_of_a_grid_row(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Any] = []
    monkeypatch.setattr(actions, "uia_of", lambda el: el)
    monkeypatch.setattr(actions, "_mouse_click", lambda el, **kwargs: seen.append((el, kwargs)))
    row = FakeElement("DataItem", "row")
    cell = row.add(FakeElement("Custom", "Apple"))
    header = FakeElement("HeaderItem", "")
    row.children_list.insert(0, header)
    actions._click_item(FakeElement("DataGrid"), row, actions._CTRL)
    assert seen == [(header, {"modifiers": actions._CTRL})]
    row.children_list.remove(header)
    seen.clear()
    actions._click_item(FakeElement("DataGrid"), row, ())
    assert seen == [(cell, {"modifiers": ()})]


class GroupedGrid:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.grid = FakeElement("DataGrid", "grid", automation_id="Grid")
        self.rows: list[FakeElement] = []
        for kind, name in [
            ("Group", "Standards"),
            ("DataItem", "Order 1"),
            ("DataItem", "Order 2"),
            ("Group", "Other"),
            ("DataItem", "Order 3"),
            ("DataItem", "Order 4"),
            ("DataItem", "{NewItemPlaceholder}"),
        ]:
            row = self.grid.add(
                FakeElement(
                    kind, name, class_name="GroupItem" if kind == "Group" else "DataGridRow"
                )
            )
            row.add(
                FakeElement(
                    "Custom", f"Item: {name}, Column Display Index: 0", properties={"text": name}
                )
            )
            row.add(FakeElement("Custom", "value", properties={"text": "value"}))
            self.rows.append(row)
        self.selected: list[FakeElement] = []
        monkeypatch.setattr(actions, "uia_of", lambda el: el)
        monkeypatch.setattr(model, "resolve", lambda scope, locator: self.grid)
        monkeypatch.setattr(patterns, "grid_size", lambda el: (len(self.rows), 2))
        monkeypatch.setattr(patterns, "grid_item", lambda el, r, c: self.rows[r].children()[c])
        monkeypatch.setattr(
            patterns,
            "column_headers",
            lambda el: [FakeElement("HeaderItem", "Name"), FakeElement("HeaderItem", "Value")],
        )
        monkeypatch.setattr(actions, "get_text", lambda cell: cell.properties["text"])
        monkeypatch.setattr(patterns, "has_pattern", lambda el, name: name in ("Selection", "Grid"))
        monkeypatch.setattr(patterns, "can_select_multiple", lambda el: True)
        monkeypatch.setattr(
            patterns, "selection", lambda el: [row.children()[0] for row in self.selected]
        )
        monkeypatch.setattr(actions, "is_selected", lambda row: row in self.selected)
        monkeypatch.setattr(actions, "_scroll_item", lambda row: None)
        monkeypatch.setattr(
            actions, "select_self", lambda row: self.selected.__setitem__(slice(None), [row])
        )
        monkeypatch.setattr(patterns, "add_to_selection", lambda row: self.selected.append(row))
        monkeypatch.setattr(
            patterns,
            "remove_from_selection",
            lambda row: self.selected.remove(row if row in self.selected else row.parent()),
        )


@pytest.fixture
def grouped(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> GroupedGrid:
    runtime.set_config(load_config(tmp_path, {"timeout": 2.0, "input_mode": "pattern"}))
    return GroupedGrid(monkeypatch)


def test_grouped_grid_rows_and_selection(page: Demo, grouped: GroupedGrid) -> None:
    import importlib

    resolver = importlib.import_module("wintestkit.engine.resolve")
    grid = page.grid
    assert grid.row_count() == 4
    assert grid.find_row("Name", "Order 3").locator.item.row == 2
    assert (
        resolver._apply_item(grouped.grid, grid.cell(0, "Name").locator, "window", grid.locator)
        is grouped.rows[1].children()[0]
    )
    assert (
        resolver._apply_item(grouped.grid, grid.row(2).locator, "window", grid.locator)
        is grouped.rows[4]
    )
    expect(grid).to_have_rows([[f"Order {i}", "value"] for i in range(1, 5)])
    with pytest.raises(AssertionError) as failure:
        expect(grid, timeout=0).to_have_rows([["wrong", "value"]])
    assert "Order 1" in str(failure.value)
    assert "<element not found>" not in str(failure.value)
    grid.select([1, 3])
    assert grid.selected_items() == ["Order 2 value", "Order 4 value"]
    grid.clear_selection()
    assert grid.selected_items() == []
    grid.select("Order 1 value")
    assert grid.selected_items() == ["Order 1 value"]


def test_grouped_grid_missing_selection_is_short_and_immediate(grouped: GroupedGrid) -> None:
    for i in range(20):
        row = grouped.grid.add(FakeElement("DataItem", f"Extra {i}", class_name="DataGridRow"))
        row.add(FakeElement("Custom", properties={"text": f"Extra {i}"}))
        row.add(FakeElement("Custom", properties={"text": "value"}))
        grouped.rows.append(row)
    for item in (99, "missing"):
        with pytest.raises(ActionError) as failure:
            actions.select_items(grouped.grid, [item], timeout=100)
        assert "more" in str(failure.value)
        assert len(str(failure.value)) < 400


def test_grid_skips_rows_that_vanish(grouped: GroupedGrid, monkeypatch: pytest.MonkeyPatch) -> None:
    from wintestkit.errors import UIAError

    calls = 0

    def get_item(el: Any, r: int, c: int) -> FakeElement:
        nonlocal calls
        if r == 2:
            calls += 1
            raise UIAError("The UI element is no longer available", element_gone=True)
        return grouped.rows[r].children()[c]

    monkeypatch.setattr(patterns, "grid_item", get_item)
    assert [row.text for row in actions.grid_data_rows(grouped.grid)] == [
        "Order 1 value",
        "Order 3 value",
        "Order 4 value",
    ]
    assert calls == 2


def test_indexed_cell_reads_only_first_row(monkeypatch: pytest.MonkeyPatch, page: Demo) -> None:
    import importlib

    resolver = importlib.import_module("wintestkit.engine.resolve")
    grid = FakeElement("DataGrid", "grid")
    monkeypatch.setattr(actions, "grid_headers", lambda el: [])
    rows = []
    for _index in range(500):
        row = grid.add(FakeElement("DataItem", "", class_name="DataGridRow"))
        row.add(FakeElement("Custom", "first"))
        row.add(FakeElement("Custom", "second"))
        rows.append(row)
    fetched: list[int] = []
    texts: list[Any] = []
    monkeypatch.setattr(actions, "uia_of", lambda el: el)
    monkeypatch.setattr(resolver, "uia_of", lambda el: el)
    monkeypatch.setattr(patterns, "grid_size", lambda el: (500, 2))

    def item(el: Any, row: int, col: int) -> Any:
        fetched.append(row)
        return rows[row].children()[col]

    monkeypatch.setattr(patterns, "grid_item", item)
    monkeypatch.setattr(actions, "get_text", lambda cell: texts.append(cell) or cell.name)
    locator = page.grid.cell(0, 1).locator
    assert resolver._apply_item(grid, locator, "window", locator) is rows[0].children()[1]
    assert set(fetched) == {0}
    assert texts == []  # no cell text is read for index access


class BigGrid:
    """A 500-row grid that counts the reads the engine makes."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.grid = FakeElement("DataGrid", "grid", automation_id="Grid")
        self.rows: list[FakeElement] = []
        for index in range(500):
            row = self.grid.add(FakeElement("DataItem", "", class_name="DataGridRow"))
            row.add(FakeElement("Custom", properties={"text": f"name {index}"}))
            row.add(FakeElement("Custom", properties={"text": f"value {index}"}))
            self.rows.append(row)
        self.items: list[int] = []
        self.texts: list[str] = []
        monkeypatch.setattr(actions, "uia_of", lambda el: el)
        monkeypatch.setattr(model, "resolve", lambda scope, locator: self.grid)
        monkeypatch.setattr(patterns, "grid_size", lambda el: (500, 2))
        monkeypatch.setattr(patterns, "grid_item", self.item)
        monkeypatch.setattr(patterns, "has_pattern", lambda el, name: name in ("Selection", "Grid"))
        monkeypatch.setattr(
            patterns,
            "column_headers",
            lambda el: [FakeElement("HeaderItem", "Name"), FakeElement("HeaderItem", "Value")],
        )
        monkeypatch.setattr(actions, "get_text", self.text)

    def item(self, grid: Any, row: int, column: int) -> FakeElement:
        self.items.append(row)
        return self.rows[row].children()[column]

    def text(self, cell: FakeElement) -> str:
        self.texts.append(cell.properties["text"])
        return cell.properties["text"]


def test_cell_access_reads_the_text_of_no_row(monkeypatch: pytest.MonkeyPatch, page: Demo) -> None:
    import importlib

    resolver = importlib.import_module("wintestkit.engine.resolve")
    big = BigGrid(monkeypatch)
    monkeypatch.setattr(resolver, "uia_of", lambda el: el)
    locator = page.grid.cell(0, 1).locator
    assert resolver._apply_item(big.grid, locator, "window", locator) is big.rows[0].children()[1]
    assert big.texts == []
    assert set(big.items) == {0}  # one row classified, one cell fetched


def test_deep_index_access_stops_at_the_wanted_row(
    monkeypatch: pytest.MonkeyPatch, page: Demo
) -> None:
    import importlib

    resolver = importlib.import_module("wintestkit.engine.resolve")
    big = BigGrid(monkeypatch)
    monkeypatch.setattr(resolver, "uia_of", lambda el: el)
    locator = page.grid.cell(10, 1).locator
    assert resolver._apply_item(big.grid, locator, "window", locator) is big.rows[10].children()[1]
    assert big.texts == []
    assert max(big.items) == 10
    big.items.clear()
    assert actions._item_by_index(big.grid, 3) is big.rows[3]
    assert big.texts == [] and max(big.items) == 3


def test_find_row_reads_one_column_until_the_match(
    monkeypatch: pytest.MonkeyPatch, page: Demo
) -> None:
    big = BigGrid(monkeypatch)
    assert page.grid.find_row("Name", "name 4").locator.item.row == 4
    assert big.texts == [f"name {i}" for i in range(5)]


def test_selecting_a_row_by_index_reads_no_text(monkeypatch: pytest.MonkeyPatch) -> None:
    big = BigGrid(monkeypatch)
    chosen: list[Any] = []
    monkeypatch.setattr(actions, "_scroll_item", lambda row: None)
    monkeypatch.setattr(actions, "select_self", chosen.append)
    actions.select(big.grid, 2)
    assert chosen == [big.rows[2]]
    assert big.texts == [] and max(big.items) == 2


def test_indexed_access_is_not_limited_to_500_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    big = BigGrid(monkeypatch)
    monkeypatch.setattr(patterns, "grid_size", lambda el: (50_000, 2))
    assert actions.grid_data_rows(big.grid, 2)[1].element is big.rows[1]
    with pytest.raises(ActionError, match="limited to"):
        actions.grid_data_rows(big.grid)


def test_unavailable_columns_and_dataitem_groups(
    monkeypatch: pytest.MonkeyPatch, page: Demo, tmp_path: Path
) -> None:
    import importlib
    import time

    from wintestkit.errors import UIAError

    resolver = importlib.import_module("wintestkit.engine.resolve")
    runtime.set_config(load_config(tmp_path, {"timeout": 2.0, "input_mode": "pattern"}))
    hidden = {0, *range(4, 8), *range(11, 22)}

    class Unavailable(FakeElement):
        def get_property(self, name: str) -> Any:
            raise UIAError("gone", element_gone=True)

    grid = FakeElement("DataGrid", "grid")
    rows = []
    for name in ["Pending orders", "Order 1", "Order 2", "Other", "Order 3", "Order 4"]:
        row = grid.add(FakeElement("DataItem", name, class_name="DataGridRow"))
        group = name in {"Pending orders", "Other"}
        for col in range(22):
            row.add(
                Unavailable("Custom")
                if col in hidden
                else FakeElement("Custom", "" if group else (name if col == 1 else f"v{col}"))
            )
        rows.append(row)
    selected: list[Any] = []
    monkeypatch.setattr(actions, "uia_of", lambda el: el)
    monkeypatch.setattr(resolver, "uia_of", lambda el: el)
    monkeypatch.setattr(model, "resolve", lambda scope, locator: grid)
    monkeypatch.setattr(patterns, "grid_size", lambda el: (len(rows), 22))
    monkeypatch.setattr(patterns, "grid_item", lambda el, r, c: rows[r].children()[c])
    headers = ["" if i in hidden else ("Order Name" if i == 1 else f"C{i}") for i in range(22)]
    monkeypatch.setattr(
        patterns, "column_headers", lambda el: [FakeElement("HeaderItem", h) for h in headers]
    )
    monkeypatch.setattr(patterns, "has_pattern", lambda el, name: name in ("Selection", "Grid"))
    monkeypatch.setattr(patterns, "can_select_multiple", lambda el: True)
    monkeypatch.setattr(patterns, "selection", lambda el: [row.children()[1] for row in selected])
    monkeypatch.setattr(actions, "is_selected", lambda row: row in selected)
    monkeypatch.setattr(actions, "_scroll_item", lambda row: None)
    monkeypatch.setattr(
        actions, "select_self", lambda row: selected.__setitem__(slice(None), [row])
    )
    monkeypatch.setattr(patterns, "add_to_selection", selected.append)
    monkeypatch.setattr(patterns, "remove_from_selection", selected.remove)
    assert actions.get_text(rows[1].children()[0]) == ""
    monkeypatch.setattr(actions, "get_text", lambda cell: cell.name)
    bound = page.grid
    assert bound.row_count() == 4
    assert resolver._apply_item(grid, bound.row(0).locator, "window", bound.locator) is rows[1]
    assert (
        resolver._apply_item(grid, bound.cell(0, "Order Name").locator, "window", bound.locator)
        is rows[1].children()[1]
    )
    assert (
        resolver._apply_item(grid, bound.cell(0, 1).locator, "window", bound.locator)
        is rows[1].children()[1]
    )
    assert bound.find_row("Order Name", "Order 3").locator.item.row == 2
    with pytest.raises(Exception, match="missing"):
        bound.find_row("Order Name", "missing")
    expected = [[f"Order {i}", "v2", "v3", "v8", "v9", "v10"] for i in range(1, 5)]
    expect(bound).to_have_rows(expected)
    assert actions.read_grid(grid) == expected
    with pytest.raises(AssertionError, match="Order 1"):
        expect(bound, timeout=0).to_have_rows([["wrong", *expected[0][1:]]])
    bound.select([1, 3])
    assert bound.selected_items() == [" ".join(expected[i]) for i in (1, 3)]
    start = time.monotonic()
    bound.clear_selection()
    assert time.monotonic() - start < 1
    assert bound.selected_items() == []
    bound.select("Order 1")
    assert bound.selected_items() == [" ".join(expected[0])]


@pytest.mark.parametrize("mode", ["pattern", "mouse"])
@pytest.mark.parametrize("clear", [True, False])
def test_grid_cell_only_selection_is_removed(
    grouped: GroupedGrid, monkeypatch: pytest.MonkeyPatch, mode: str, clear: bool
) -> None:
    row = grouped.rows[2]
    cells = row.children()[:2]
    selected = list(cells)
    monkeypatch.setattr(patterns, "selection", lambda el: list(selected))
    monkeypatch.setattr(actions, "is_selected", lambda el: False)
    removed = []

    def remove(container: Any, target: Any, actual_mode: str) -> None:
        removed.append((target, actual_mode))
        selected.remove(target)

    monkeypatch.setattr(actions, "_toggle_off", remove)
    if clear:
        actions.clear_selection(grouped.grid, mode=mode)
    else:
        actions.deselect_items(grouped.grid, [1], mode=mode)
    assert removed == [(cell, mode) for cell in cells]
    assert not selected
