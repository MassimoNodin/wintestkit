"""Tree paths and menu paths: parsing, walking order, popup search, errors, Escape cleanup, steps."""

import re
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeApp, FakeElement

from wintestkit import model, runtime
from wintestkit.config import load_config
from wintestkit.controls import (
    BoundContextMenu,
    BoundMenu,
    BoundTreeView,
    ContextMenu,
    Menu,
    TreeView,
)
from wintestkit.engine import actions, navigate, waits
from wintestkit.errors import ActionError, ElementNotFoundError
from wintestkit.model import Element, Page, Window
from wintestkit.uia import patterns
from wintestkit.uia.element import Rect


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture(autouse=True)
def runtime_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[runtime.StepRecord]:
    runtime.reset()
    runtime.set_config(load_config(tmp_path, {"timeout": 10.0, "input_mode": "pattern"}))
    fake = FakeTime()
    monkeypatch.setattr(waits, "_clock", fake.clock)
    monkeypatch.setattr(waits, "_sleep", fake.sleep)
    records: list[runtime.StepRecord] = []
    runtime.add_step_listener(records.append)
    yield records  # type: ignore[misc]
    runtime.reset()


def item(kind: str, name: str, *children: FakeElement) -> FakeElement:
    return FakeElement(kind, name, children=list(children))


class Ui:
    """Fakes for the primitives the walkers use; children appear only once their parent opens."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.log: list[tuple[str, str]] = []
        self.escapes = 0
        self.hidden: dict[int, list[FakeElement]] = {}
        self.expanded: set[int] = set()
        self.popups: list[FakeElement] = []
        monkeypatch.setattr(navigate, "_query", self._query)
        monkeypatch.setattr(navigate, "_popup_items", lambda anchor: list(self.popups))
        monkeypatch.setattr(actions, "expand", self._expand)
        monkeypatch.setattr(
            actions, "collapse", lambda el, mode="pattern": self._note("collapse", el)
        )
        monkeypatch.setattr(actions, "is_expanded", lambda el: id(el) in self.expanded)
        monkeypatch.setattr(actions, "select_self", lambda el: self._note("select", el))
        monkeypatch.setattr(actions, "click", self._click)
        monkeypatch.setattr(actions, "right_click", lambda el: self._note("right_click", el))
        monkeypatch.setattr(actions, "press", lambda el, keys: self._note(f"press {keys}", el))
        monkeypatch.setattr(navigate.input, "press", self._escape)
        self.scrolled: list[str] = []
        self.click_selects = True
        monkeypatch.setattr(actions, "selected_items", lambda el: ["Child A"])
        self.heights: list[float | None] = []
        monkeypatch.setattr(actions, "click_header", self._click_header)
        self.selected: set[int] = set()
        monkeypatch.setattr(actions, "is_selected", lambda el: id(el) in self.selected)
        monkeypatch.setattr(actions, "ensure_visible", lambda el: self.scrolled.append(el.name))
        monkeypatch.setattr(patterns, "has_pattern", lambda el, name: True)
        monkeypatch.setattr(model, "resolve", lambda scope, locator: self.root)
        self.root: FakeElement

    def _note(self, verb: str, el: FakeElement) -> None:
        self.log.append((verb, el.name))

    def _query(self, root: FakeElement, locator: Any) -> list[FakeElement]:
        return [c for c in root.children_list if c.control_type == locator.control_type]

    def hide(self, parent: FakeElement) -> None:
        """Move the children of ``parent`` out of sight until it is expanded."""
        self.hidden[id(parent)] = parent.children_list[:]
        parent.children_list.clear()

    def _open(self, el: FakeElement) -> None:
        self.expanded.add(id(el))
        for child in self.hidden.pop(id(el), []):
            el.add(child)

    def _expand(self, el: FakeElement, mode: str = "pattern") -> None:
        self._note(f"expand {mode}", el)
        self._open(el)

    def _click(self, el: FakeElement, mode: str = "pattern", **kwargs: Any) -> str:
        self._note(f"click {mode}", el)
        if mode == "mouse":
            self._open(el)  # a mouse click opens a submenu
            if self.click_selects:
                self.selected.add(id(el))
        return "click"

    def _click_header(self, el: FakeElement, header_height: float | None = None) -> None:
        self._note("click_header", el)
        self.heights.append(header_height)
        if self.click_selects:
            self.selected.add(id(el))

    def _escape(self, keys: str) -> None:
        assert keys == "Escape"
        self.escapes += 1


@pytest.fixture
def ui(monkeypatch: pytest.MonkeyPatch) -> Ui:
    return Ui(monkeypatch)


def make_tree(ui: Ui) -> FakeElement:
    child_a = item("TreeItem", "Child A", item("TreeItem", "Leaf 1"), item("TreeItem", "Leaf 2"))
    child_b = item("TreeItem", "Child B", item("TreeItem", "Leaf 3"))
    root = item("TreeItem", "Root", child_a, child_b)
    tree = item("Tree", "tree", root, item("TreeItem", "Other"))
    for node in (root, child_a, child_b):
        ui.hide(node)
    ui.root = tree
    return tree


# -- parsing --------------------------------------------------------------------------------------


def test_split_path_forms() -> None:
    assert navigate.split_path("Root|Child A|Leaf 1") == ["Root", "Child A", "Leaf 1"]
    assert navigate.split_path("A/B", "/") == ["A", "B"]
    pattern = re.compile("Leaf \\d")
    assert navigate.split_path(["Root", pattern]) == ["Root", pattern]
    assert navigate.path_text(["Root", pattern]) == "Root|/Leaf \\d/"


@pytest.mark.parametrize("bad", ["", "A||B", "|A", [], ["A", ""], ["A", 3]])
def test_split_path_rejects_bad_paths(bad: Any) -> None:
    with pytest.raises(ActionError):
        navigate.split_path(bad)


def test_is_path() -> None:
    assert navigate.is_path("A|B")
    assert not navigate.is_path("A")
    assert not navigate.is_path("A|B", "/")
    assert navigate.is_path(["A"])
    assert not navigate.is_path(3)
    assert not navigate.is_path(re.compile("A|B"))


# -- trees ----------------------------------------------------------------------------------------


def test_select_expands_each_ancestor_in_order_then_selects(ui: Ui) -> None:
    tree = make_tree(ui)
    navigate.select_tree_path(tree, ["Root", "Child A", "Leaf 2"], mode="pattern")
    assert ui.log == [
        ("expand pattern", "Root"),
        ("expand pattern", "Child A"),
        ("select", "Leaf 2"),
    ]


def test_mouse_mode_clicks_the_leaf_but_still_expands_by_pattern(ui: Ui) -> None:
    tree = make_tree(ui)
    navigate.select_tree_path(tree, ["Root", "Child B", "Leaf 3"], mode="mouse")
    assert ui.log == [
        ("expand pattern", "Root"),
        ("expand pattern", "Child B"),
        ("click_header", "Leaf 3"),
    ]


def test_mouse_select_scrolls_and_waits_for_the_leaf_to_be_laid_out(ui: Ui) -> None:
    tree = make_tree(ui)
    leaf = tree.children_list[0].children_list  # hidden until expanded; fetch via the hidden map
    del leaf
    root = next(c for c in tree.children_list if c.name == "Root")
    child_a = ui.hidden[id(root)][0]
    leaf2 = ui.hidden[id(child_a)][1]
    leaf2.rect = None
    sleeps: list[float] = []

    def lay_out() -> None:
        sleeps.append(1)
        if len(sleeps) == 3:
            leaf2.rect = Rect(0, 0, 10, 10)

    original = waits._sleep
    waits._sleep = lambda seconds: (original(seconds), lay_out())[0]
    try:
        navigate.select_tree_path(tree, ["Root", "Child A", "Leaf 2"], mode="mouse")
    finally:
        waits._sleep = original
    assert len(sleeps) >= 3
    assert "Leaf 2" in ui.scrolled
    assert ui.log[-1] == ("click_header", "Leaf 2")


def test_mouse_select_fails_when_the_click_landed_elsewhere(ui: Ui) -> None:
    tree = make_tree(ui)
    ui.click_selects = False  # the click selected the parent instead
    with pytest.raises(ActionError, match='landed elsewhere; "Child A" is selected'):
        navigate.select_tree_path(tree, ["Root", "Child A", "Leaf 1"], mode="mouse")
    assert ("select", "Leaf 1") not in ui.log  # no silent pattern fallback


def test_mouse_click_targets_the_header_row_of_an_expanded_node(ui: Ui) -> None:
    child_a = item("TreeItem", "Child A", item("TreeItem", "Leaf 1"))
    child_a.rect = Rect(0, 100, 600, 48)
    child_a.children_list[0].rect = Rect(20, 116, 580, 16)
    root = item("TreeItem", "Root", child_a)
    tree = item("Tree", "tree", root)
    ui.hide(root)
    navigate.select_tree_path(tree, ["Root", "Child A"], mode="mouse")
    assert ui.heights == [None]  # collapsed when clicked: the whole row
    ui.expanded.add(id(child_a))
    ui.heights.clear()
    navigate.select_tree_path(tree, ["Root", "Child A"], mode="mouse")
    assert ui.heights == [16]


def test_mouse_select_gives_up_when_the_leaf_never_appears_on_screen(ui: Ui) -> None:
    tree = make_tree(ui)
    root = next(c for c in tree.children_list if c.name == "Root")
    ui.hidden[id(ui.hidden[id(root)][0])][0].rect = None
    with pytest.raises(ActionError, match="no on-screen rectangle"):
        navigate.select_tree_path(tree, ["Root", "Child A", "Leaf 1"], mode="mouse", timeout=0.5)
    assert ("click_header", "Leaf 1") not in ui.log


def test_regex_segment_matches_by_search(ui: Ui) -> None:
    tree = make_tree(ui)
    navigate.select_tree_path(
        tree, ["Root", re.compile("^Child B$"), re.compile(r"\d")], mode="pattern"
    )
    assert ui.log[-1] == ("select", "Leaf 3")


def test_expand_covers_the_whole_chain_and_collapse_only_the_last(ui: Ui) -> None:
    tree = make_tree(ui)
    navigate.expand_tree_path(tree, ["Root", "Child B"])
    assert ui.log == [("expand pattern", "Root"), ("expand pattern", "Child B")]
    ui.log.clear()
    navigate.collapse_tree_path(tree, ["Root", "Child B"])
    assert ui.log == [("expand pattern", "Root"), ("collapse", "Child B")]


def test_items_lists_top_level_or_the_children_of_a_path(ui: Ui) -> None:
    tree = make_tree(ui)
    assert navigate.tree_item_names(tree) == ["Root", "Other"]
    navigate.expand_tree_path(tree, ["Root", "Child B"])
    assert navigate.tree_item_names(tree, ["Root", "Child B"]) == ["Leaf 3"]
    assert navigate.tree_item_names(tree, ["Root"]) == ["Child A", "Child B"]


def test_missing_segment_names_it_and_its_siblings(ui: Ui) -> None:
    tree = make_tree(ui)
    with pytest.raises(ElementNotFoundError) as caught:
        navigate.select_tree_path(tree, ["Root", "Child A", "Leaf 9"], mode="pattern")
    message = str(caught.value)
    assert 'tree item "Leaf 9"' in message
    assert 'under "Root" > "Child A"' in message
    assert '"Leaf 1", "Leaf 2"' in message
    with pytest.raises(ElementNotFoundError, match=r'No tree item "Nope" in .*"Root", "Other"'):
        navigate.select_tree_path(tree, ["Nope"], mode="pattern")


class TreePage(Page):
    window = Window(title="Demo")
    tree = TreeView(automation_id="Tree")
    generic = Element(automation_id="Generic")
    menu = Menu(automation_id="Menu")
    popup = ContextMenu(automation_id="Popup")


@pytest.fixture
def page() -> TreePage:
    return TreePage(FakeApp([FakeElement("Window", "Demo")]))  # type: ignore[arg-type]


def test_bound_tree_select_path_records_one_step(
    ui: Ui, page: TreePage, runtime_setup: list[runtime.StepRecord]
) -> None:
    make_tree(ui)
    assert type(page.tree) is BoundTreeView
    page.tree.select("Root|Child A|Leaf 1")
    assert [verb for verb, _ in ui.log] == ["expand pattern", "expand pattern", "select"]
    (record,) = [r for r in runtime_setup if r.action == "select"]
    assert record.args == {"item": "Root|Child A|Leaf 1"}


def test_bound_tree_list_path_separator_and_single_names(
    ui: Ui, page: TreePage, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_tree(ui)
    page.tree.select(["Root", "Child B", "Leaf 3"])
    page.tree.select("Root/Child A/Leaf 2", separator="/")
    assert [name for verb, name in ui.log if verb == "select"] == ["Leaf 3", "Leaf 2"]
    seen: list[Any] = []
    monkeypatch.setattr(actions, "select", lambda el, item, **kw: seen.append(item))
    page.tree.select("Other")
    page.tree.select(2)
    assert seen == ["Other", 2]


def test_bound_tree_expand_collapse_items(ui: Ui, page: TreePage) -> None:
    make_tree(ui)
    page.tree.expand("Root|Child B")
    assert page.tree.items("Root|Child B") == ["Leaf 3"]
    assert page.tree.items() == ["Root", "Other"]
    page.tree.collapse("Root|Child B")
    assert ui.log[-1] == ("collapse", "Child B")


# -- menus ----------------------------------------------------------------------------------------


def make_menu(ui: Ui) -> FakeElement:
    """File > Open, Recent > Report.txt; Edit > Copy. Submenu items exist only in popups."""
    open_item = item("MenuItem", "Open")
    report = item("MenuItem", "Report.txt")
    recent = item("MenuItem", "Recent")
    file_item = item("MenuItem", "File", open_item, recent)
    copy = item("MenuItem", "Copy")
    edit = item("MenuItem", "Edit", copy)
    bar = item("Menu", "bar", file_item, edit)
    submenus = {id(file_item): [open_item, recent], id(recent): [report], id(edit): [copy]}
    for node in (file_item, edit):
        ui.hide(node)

    original = ui._open

    def open_level(el: FakeElement) -> None:
        original(el)
        ui.popups = list(submenus.get(id(el), []))

    ui._open = open_level  # type: ignore[method-assign]
    ui.root = bar
    return bar


def test_menu_walks_levels_through_popups(ui: Ui) -> None:
    bar = make_menu(ui)
    navigate.click_menu_path(bar, ["File", "Recent", "Report.txt"], mode="pattern")
    assert ui.log == [
        ("expand pattern", "File"),
        ("expand pattern", "Recent"),
        ("click pattern", "Report.txt"),
    ]
    assert ui.escapes == 0


def test_menu_mouse_mode_clicks_each_level(ui: Ui) -> None:
    bar = make_menu(ui)
    navigate.click_menu_path(bar, ["Edit", "Copy"], mode="mouse")
    assert ui.log == [("click mouse", "Edit"), ("click mouse", "Copy")]


def test_an_already_open_level_is_not_clicked_again(ui: Ui) -> None:
    bar = make_menu(ui)
    file_item = bar.children_list[0]
    ui._open(file_item)
    ui.popups = list(file_item.children_list)
    navigate.click_menu_path(bar, ["File", "Open"], mode="mouse")
    assert ui.log == [("click mouse", "Open")]


def test_missing_item_lists_the_level_and_closes_open_menus(ui: Ui) -> None:
    bar = make_menu(ui)
    with pytest.raises(ElementNotFoundError) as caught:
        navigate.click_menu_path(bar, ["File", "Recent", "Nope"], mode="pattern")
    message = str(caught.value)
    assert 'menu item "Nope"' in message
    assert 'under "File" > "Recent"' in message
    assert '"Report.txt"' in message
    assert ui.escapes == 2


def test_missing_top_item_presses_no_escape(ui: Ui) -> None:
    bar = make_menu(ui)
    with pytest.raises(ElementNotFoundError, match=r'menu item "View".*"File", "Edit"'):
        navigate.click_menu_path(bar, ["View", "X"], mode="pattern")
    assert ui.escapes == 0


def test_a_failing_click_closes_the_menus(ui: Ui, monkeypatch: pytest.MonkeyPatch) -> None:
    bar = make_menu(ui)

    def boom(el: FakeElement, mode: str = "pattern") -> str:
        raise ActionError("cannot click")

    monkeypatch.setattr(actions, "click", boom)
    with pytest.raises(ActionError, match="cannot click"):
        navigate.click_menu_path(bar, ["File", "Open"], mode="pattern")
    assert ui.escapes == 1


def test_escape_failure_does_not_mask_the_error(ui: Ui, monkeypatch: pytest.MonkeyPatch) -> None:
    bar = make_menu(ui)

    def broken(keys: str) -> None:
        raise RuntimeError("no input")

    monkeypatch.setattr(navigate.input, "press", broken)
    with pytest.raises(ElementNotFoundError):
        navigate.click_menu_path(bar, ["File", "Nope"], mode="pattern")


def test_bound_menu_click_path_records_one_step(
    ui: Ui, page: TreePage, runtime_setup: list[runtime.StepRecord]
) -> None:
    make_menu(ui)
    assert type(page.menu) is BoundMenu
    page.menu.click_path("File|Recent|Report.txt")
    steps = [r for r in runtime_setup if r.action == "click_path"]
    assert len(steps) == 1
    assert steps[0].args == {"path": "File|Recent|Report.txt"}
    assert steps[0].target == "TreePage.menu"
    page.menu.click_path(["Edit", re.compile("^Cop")])
    assert ui.log[-1] == ("click pattern", "Copy")


def test_context_menu_from_an_element_uses_the_popups(
    ui: Ui, page: TreePage, runtime_setup: list[runtime.StepRecord]
) -> None:
    deep = item("MenuItem", "Deep")
    more = item("MenuItem", "More")
    paste = item("MenuItem", "Paste")
    owner = item("Button", "ContextTarget")
    ui.root = owner
    ui.popups = [paste, more]
    original = ui._open

    def open_level(el: FakeElement) -> None:
        original(el)
        ui.popups = [deep] if el is more else []

    ui._open = open_level  # type: ignore[method-assign]
    menu = page.generic.open_context_menu(mode="pattern")
    assert type(menu) is BoundContextMenu
    assert ui.log == [("press Shift+F10", "ContextTarget")]
    menu.click_path("More|Deep")
    assert ui.log[1:] == [("expand pattern", "More"), ("click pattern", "Deep")]
    assert [r.action for r in runtime_setup] == ["open_context_menu", "click_path"]
    assert runtime_setup[0].args == {"mode": "pattern"}
    ui.popups = [paste, more]
    with pytest.raises(ElementNotFoundError, match='"Paste", "More"'):
        menu.click_path("Nope")
    assert ui.escapes == 1  # the context menu itself


def test_context_menu_opens_with_a_right_click_in_mouse_mode(ui: Ui, page: TreePage) -> None:
    ui.root = item("Button", "ContextTarget")
    page.generic.open_context_menu(mode="mouse")
    assert ui.log == [("right_click", "ContextTarget")]


def test_declared_context_menu_is_validated_as_a_menu(ui: Ui, page: TreePage) -> None:
    ui.root = item("Button", "NotAMenu")
    with pytest.raises(ActionError, match="control type"):
        page.popup.click_path("A")
    ui.root = item("Menu", "popup", item("MenuItem", "Paste"))
    page.popup.click_path("Paste")
    assert ui.log == [("click pattern", "Paste")]
