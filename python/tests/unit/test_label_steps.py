"""WPFObject and Window steps on a fake application: what they select, how they fail, how the
Name property and the label chains of the Spy resolve, and how navigation round-trips."""

from __future__ import annotations

import pytest
from fakes import FakeElement
from object_tree_fake import FakeApp, Node

from wintestkit import runtime
from wintestkit.app import App
from wintestkit.engine import query
from wintestkit.engine.locator import is_window_node
from wintestkit.errors import AmbiguousElementError, ElementNotFoundError
from wintestkit.finders import find_child, from_label, to_locator, window, wpf_object
from wintestkit.labels import LabelSyntaxError


def build() -> dict[str, Node]:
    """A main window and a popup; the main view has a list, a grid and two buttons."""
    items = [
        Node("ListBoxItem", "Alpha"),
        Node("ListBoxItem", "Beta"),
        Node("ListBoxItem", ""),
        Node("ListBoxItem", "Beta"),
    ]
    rows = [
        Node("DataGridRow", "", "", Node("DataGridCell", f"r{row}c1"), Node("DataGridCell", ""))
        for row in range(1, 4)
    ]
    grid = Node("DataGrid", "", "grid", *rows)
    listbox = Node("ListBox", "", "list", *items)
    ok, cancel = Node("Button", "OK", "ok"), Node("Button", "Cancel")
    panel = Node("Grid", "", "", ok, cancel, listbox, grid, Node("TextBlock", "Done"))
    main = Node("MainView", "Main title", "", panel)
    popup = Node("PopupRoot", "", "", Node("ComboBoxItem", "One"), Node("ComboBoxItem", "Two"))
    return {"main": main, "popup": popup, "list": listbox, "grid": grid, "ok": ok, "cancel": cancel}


@pytest.fixture
def fake(monkeypatch):
    tree = build()
    fake = FakeApp(monkeypatch, tree["main"], tree["popup"])
    fake.tree = tree  # type: ignore[attr-defined]
    yield fake
    runtime.reset()


def root_of(fake: FakeApp):
    """The main view, reached the way a ported chain does it."""
    return fake.app.wpf_object("HwndSource: MainView", "Main*").wpf_object("MainView", "Main*")


# -- window nodes -----------------------------------------------------------------------------


def test_window_nodes_come_from_the_application(fake):
    node = fake.app.wpf_object("HwndSource: MainView", "Main*")
    assert fake.resolve(node) is fake.tree["main"]
    assert is_window_node(node.locator)
    # The text is the title and may use wildcards; the type is exact.
    assert (
        fake.resolve(fake.app.WPFObject("HwndSource: MainView", "Main title")) is fake.tree["main"]
    )
    with pytest.raises(ElementNotFoundError):
        fake.app.wpf_object("HwndSource: MainView", "Other*").resolve_once()
    with pytest.raises(ElementNotFoundError):
        fake.app.wpf_object("HwndSource: Main*", "*").resolve_once()
    # A popup is a window node with an empty text.
    popup = fake.app.wpf_object("HwndSource: PopupRoot", "")
    assert fake.resolve(popup) is fake.tree["popup"]
    assert fake.resolve(fake.app.wpf_object("HwndSource: PopupRoot", "*")) is fake.tree["popup"]


def test_window_node_ordinals_count_nodes_of_the_same_type(monkeypatch):
    first, second = Node("Dialog", "A"), Node("Dialog", "B")
    other = Node("Shell", "S")
    fake = FakeApp(monkeypatch, first, other, second)
    for text, index, expected in (("*", 1, first), ("*", 2, second), ("B", 2, second)):
        assert fake.resolve(fake.app.wpf_object("HwndSource: Dialog", text, index)) is expected
    # The ordinal selects whatever the text is (""), and the text is checked when given.
    assert fake.resolve(fake.app.wpf_object("HwndSource: Dialog", "", 2)) is second
    assert fake.resolve(fake.app.wpf_object("HwndSource: Dialog", 2)) is second
    with pytest.raises(ElementNotFoundError):
        fake.app.wpf_object("HwndSource: Dialog", "A", 2).resolve_once()
    with pytest.raises(ElementNotFoundError):
        fake.app.wpf_object("HwndSource: Dialog", "*", 3).resolve_once()
    assert fake.resolve(fake.app.wpf_object("HwndSource: Shell", "*", 1)) is other
    # Without an index the first node of the type with a matching title wins.
    assert fake.resolve(fake.app.wpf_object("HwndSource: Dialog", "*")) is first
    assert fake.resolve(fake.app.wpf_object("HwndSource: Dialog", "B")) is second
    with pytest.raises(AmbiguousElementError):
        fake.app.wpf_object("HwndSource: Dialog", "*", strict=True).resolve_once()


def test_the_child_of_a_window_node_is_its_root_visual(fake):
    root = fake.app.wpf_object("HwndSource: MainView", "Main*").wpf_object("MainView", "Main*")
    assert fake.resolve(root) is fake.tree["main"]
    assert (
        fake.resolve(fake.app.WPFObject("HwndSource: MainView", "*").WPFObject("MainView", "*"))
        is (fake.tree["main"])
    )
    button = root.wpf_object("Grid", "").wpf_object("Button", "OK")
    assert fake.resolve(button) is fake.tree["ok"]
    # Only the root visual is the node's child, not the root visual's children.
    with pytest.raises(ElementNotFoundError):
        fake.app.wpf_object("HwndSource: MainView", "*").wpf_object("Grid").resolve_once()
    # Window nodes exist only below an application; below one, only objects.
    with pytest.raises(ValueError, match="only be selected from an application"):
        root.wpf_object("HwndSource: MainView", "*")
    with pytest.raises(ValueError, match="selects a window node"):
        fake.app.wpf_object("MainView")
    with pytest.raises(ValueError, match="selects a window node"):
        fake.app.wpf_object("name")


# -- the selection rules ------------------------------------------------------------------------


@pytest.fixture
def list_box(fake):
    return root_of(fake).wpf_object("Grid", "").wpf_object("ListBox", "")


def item(fake, list_box, *args, **options):
    node = fake.resolve(list_box.wpf_object("ListBoxItem", *args, **options))
    return fake.tree["list"].children.index(node)  # position in the list


def test_an_index_picks_the_ordinal_and_checks_text_unless_empty_or_star(fake, list_box):
    # ListBoxItem ordinals: Alpha 1, Beta 2, "" 3, Beta 4.
    assert item(fake, list_box, "", 3) == 2
    assert item(fake, list_box, "*", 3) == 2
    assert item(fake, list_box, 3) == 2  # the Spy form for an empty text
    assert item(fake, list_box, None, 4) == 3
    assert item(fake, list_box, "Beta", 4) == 3
    assert item(fake, list_box, "Be*", 2) == 1
    with pytest.raises(ElementNotFoundError):
        list_box.wpf_object("ListBoxItem", "Beta", 1).resolve_once()  # item 1 is Alpha
    with pytest.raises(ElementNotFoundError):
        list_box.wpf_object("ListBoxItem", "", 5).resolve_once()


def test_without_an_index_the_first_child_with_matching_text_wins(fake, list_box):
    assert item(fake, list_box, "*") == 0  # any text: the first item
    assert item(fake, list_box, "") == 2  # empty text only
    assert item(fake, list_box, "Beta") == 1  # two match; the first wins, silently
    assert item(fake, list_box, "B?ta") == 1
    assert item(fake, list_box, "*a") == 0
    with pytest.raises(AmbiguousElementError):
        list_box.wpf_object("ListBoxItem", "Beta", strict=True).resolve_once()
    assert (
        fake.resolve(list_box.wpf_object("ListBoxItem", "Alpha", strict=True))
        is (fake.tree["list"].children[0])
    )


def test_one_argument_is_the_x_name_of_a_direct_child(fake):
    grid = root_of(fake).wpf_object("Grid", "")
    assert fake.resolve(grid.wpf_object("ok")) is fake.tree["ok"]
    assert fake.resolve(grid.wpf_object("li*")) is fake.tree["list"]
    # A type name is not an x:Name, and only direct children count.
    with pytest.raises(ElementNotFoundError):
        grid.wpf_object("Button").resolve_once()
    with pytest.raises(ElementNotFoundError):
        root_of(fake).wpf_object("ok").resolve_once()


def test_grid_cells_chain_row_and_column(fake):
    grid = root_of(fake).wpf_object("Grid", "").wpf_object("grid")
    cell = grid.WPFObject("DataGridRow", "", 2).WPFObject("DataGridCell", "*", 1)
    assert fake.resolve(cell).text == "r2c1"
    assert fake.resolve(
        grid.WPFObject("DataGridRow", "", 3).WPFObject("DataGridCell", "r3c1")
    ).text == ("r3c1")
    assert (
        fake.resolve(grid.wpf_object("DataGridRow", 1).wpf_object("DataGridCell", "", 2)).text == ""
    )


def test_a_combo_popup_is_a_window_node_of_its_own(fake):
    item_two = (
        fake.app.WPFObject("HwndSource: PopupRoot", "")
        .WPFObject("PopupRoot", "")
        .WPFObject("ComboBoxItem", "Two")
    )
    assert fake.resolve(item_two).text == "Two"


def test_not_found_lists_the_children_of_that_type(fake, list_box):
    missing = list_box.wpf_object("ListBoxItem", "Gamma")
    with pytest.raises(ElementNotFoundError) as raised:
        missing.resolve_once()
    message = str(raised.value)
    assert 'children of type "ListBoxItem": #1 "Alpha", #2 "Beta", #3 "", #4 "Beta"' in message
    wrong_type = list_box.wpf_object("TreeViewItem", "x")
    with pytest.raises(ElementNotFoundError, match='no children of type "TreeViewItem"') as raised:
        wrong_type.resolve_once()
    assert '"ListBoxItem"' in str(raised.value)
    with pytest.raises(ElementNotFoundError, match="children with an x:Name"):
        root_of(fake).wpf_object("Grid", "").wpf_object("nothing").resolve_once()
    # An application lists its window nodes.
    with pytest.raises(
        ElementNotFoundError, match=r'children of type "HwndSource: MainView": #1 "Main title"'
    ):
        fake.app.wpf_object("HwndSource: MainView", "x").resolve_once()


def test_results_are_lazy_and_resolve_again(fake, list_box):
    step = list_box.wpf_object("ListBoxItem", "Gamma")
    assert not step.exists()
    fake.tree["list"].children.append(Node("ListBoxItem", "Gamma"))
    assert fake.resolve(step) is fake.tree["list"].children[-1]
    assert step.exists()


# -- the Name property --------------------------------------------------------------------------


def test_name_matches_any_object_within_depth_by_its_label_step(fake):
    found = find_child(fake.app, "Name", 'WPFObject("HwndSource: MainView", "Title*")', 2)
    assert not found.exists()
    found = find_child(fake.app, "Name", 'WPFObject("HwndSource: MainView", "Main*")', 2)
    assert fake.resolve(found) is fake.tree["main"]
    # Deeper objects, with the same rules as the step.
    assert (
        fake.resolve(find_child(fake.app, "Name", 'WPFObject("Button", "Cancel")', 4))
        is (fake.tree["cancel"])
    )
    assert not find_child(fake.app, "Name", 'WPFObject("Button", "Cancel")', 3).exists()
    assert fake.resolve(find_child(fake.app, "Name", 'WPFObject("ok")', 4)) is fake.tree["ok"]
    by_ordinal = find_child(fake.app, "Name", 'WPFObject("ListBoxItem", "Beta", 4)', None)
    assert fake.resolve(by_ordinal) is fake.tree["list"].children[3]
    empty = find_child(fake.app, "Name", "WPFObject('ListBoxItem', '')", None)
    assert fake.resolve(empty) is fake.tree["list"].children[2]
    # From an element, depth counts below it.
    list_node = root_of(fake)
    assert (
        fake.resolve(find_child(list_node, "Name", 'WPFObject("Button", "OK")', 2))
        is (fake.tree["ok"])
    )


def test_name_combines_with_other_properties_and_reports_conflicts():
    locator = to_locator(
        ["Name", "WPFControlName", "Visible"], ['WPFObject("Button", "OK", 2)', "ident", True]
    )
    where = dict(locator.where)
    assert where["type:Name"] == "Button" and where["wpf:Ordinal"] == 2
    assert where["wpf:Text"] == "OK" and where["clr:IsVisible"] is True
    assert locator.automation_id == "ident"
    # The UIA form: the type, and the text and zero-based index as UIA fields.
    uia = locator.uia_form
    assert uia is not None and uia.index == 1 and uia.name == "OK"
    assert dict(uia.where)["type:Name"] == "Button"
    with pytest.raises(ValueError, match="Name and WPFControlText both set wpf:Text"):
        to_locator(["Name", "WPFControlText"], ['WPFObject("Button", "OK")', "x"])
    named = to_locator(["Name", "WPFControlName"], ['WPFObject("A", "t")', "ident"])
    assert named.automation_id == "ident" and dict(named.where)["wpf:Text"] == "t"
    assert dict(to_locator("Name", 'WPFObject("save")').where) == {"clr:Name": "save"}
    for bad in ("WPFObject(", "Button", 'Window("Edit")', 7, 'WPFObject("A").WPFObject("B")'):
        with pytest.raises(ValueError):
            to_locator("Name", bad)
    with pytest.raises(ValueError, match="both set"):
        to_locator(["Name", "ClrClassName"], ['WPFObject("A", "t")', "B"])
    with pytest.raises(ValueError, match="duplicate property"):
        to_locator(["Name", "name"], ['WPFObject("A")', 'WPFObject("B")'])


# -- window steps -------------------------------------------------------------------------------


def uia_app(monkeypatch, windows):
    app = object.__new__(App)
    app.process_name = "DemoApp.exe"
    monkeypatch.setattr(app, "top_level_windows", lambda: windows)
    return app


@pytest.fixture
def dialogs(monkeypatch):
    """A Win32 dialog with its child windows, and a second dialog of the same class."""
    monkeypatch.setenv("WTK_BACKEND", "uia")
    runtime.reset()
    monkeypatch.setattr(query, "make_condition", lambda **props: props)
    ok = FakeElement("Button", "OK", class_name="Button")
    cancel = FakeElement("Button", "Cancel", class_name="Button")
    first_edit = FakeElement("Edit", "", class_name="Edit")
    second_edit = FakeElement("Edit", "hello", class_name="Edit")
    third_edit = FakeElement("Edit", "hello", class_name="Edit")
    save = FakeElement(
        "Window",
        "Save As",
        class_name="#32770",
        children=[ok, first_edit, cancel, second_edit, third_edit],
    )
    other = FakeElement("Window", "Open", class_name="#32770")
    yield SimpleNamespace_(
        app=uia_app(monkeypatch, [save, other]),
        save=save,
        other=other,
        ok=ok,
        cancel=cancel,
        edits=[first_edit, second_edit, third_edit],
    )
    runtime.reset()


class SimpleNamespace_:
    def __init__(self, **values):
        self.__dict__.update(values)


def test_window_from_an_application_matches_class_caption_and_index(dialogs):
    app = dialogs.app
    assert window(app, "#32770", "Save As").resolve_once() is dialogs.save
    assert window(app, "#32770", "Op*").resolve_once() is dialogs.other
    assert window(app, "#32770").resolve_once() is dialogs.save  # the first of the class
    assert window(app, "#32770", "", 2).resolve_once() is dialogs.other
    assert window(app, "#32770", 2).resolve_once() is dialogs.other
    assert window(app, "#32770", "Open", 2).resolve_once() is dialogs.other
    with pytest.raises(ElementNotFoundError, match="name does not match"):
        window(app, "#32770", "Save As", 2).resolve_once()  # the second dialog is Open
    with pytest.raises(ElementNotFoundError):
        window(app, "#32770", "*", 3).resolve_once()
    with pytest.raises(AmbiguousElementError):
        window(app, "#32770", strict=True).resolve_once()
    assert App.Window is App.window  # the ported spelling is on the application too


def test_window_children_count_siblings_of_the_class_in_child_order(dialogs):
    dialog = window(dialogs.app, "#32770", "Save*")
    assert dialog.window("Button", "OK").resolve_once() is dialogs.ok
    assert dialog.Window("Button", "&Cancel").resolve_once() is dialogs.cancel  # mnemonic
    assert dialog.window("Button", "", 2).resolve_once() is dialogs.cancel
    assert dialog.window("Edit").resolve_once() is dialogs.edits[0]
    assert dialog.window("Edit", "hello", 2).resolve_once() is dialogs.edits[1]
    assert dialog.window("Edit", "hello", 3).resolve_once() is dialogs.edits[2]
    assert dialog.window("Edit", "hel*").resolve_once() is dialogs.edits[1]
    assert dialog.window("Edit", "").resolve_once() is dialogs.edits[0]
    with pytest.raises(ElementNotFoundError) as raised:
        dialog.window("Edit", "hello", 1).resolve_once()  # the first Edit has no caption
    assert "name does not match" in str(raised.value)
    with pytest.raises(ElementNotFoundError, match='windows of class "Edit": #1 "", #2 "hello"'):
        dialog.window("Edit", "nope").resolve_once()
    with pytest.raises(ElementNotFoundError, match="no windows of class"):
        dialog.window("Static").resolve_once()
    # Windows below an index and caption are resolved through the checked parent.
    parent = window(dialogs.app, "#32770", "Save As", 2)
    with pytest.raises(ElementNotFoundError):
        parent.window("Button", "OK").resolve_once()
    assert window(dialogs.app, "#32770", "Save As", 1).resolve_once() is dialogs.save


def test_labels_parse_into_the_same_elements(dialogs, monkeypatch):
    label = 'Process("DemoApp.exe").Window("#32770", "Save As").Window("Edit", "hello", 3)'
    assert from_label(dialogs.app, label).resolve_once() is dialogs.edits[2]
    chain = "Sys.Process('DemoApp.exe').Window('#32770', 'Save*'). Window('Button', 2)"
    assert from_label(dialogs.app, chain).resolve_once() is dialogs.cancel
    # Without a process the label starts at the parent; with one, the application is attached.
    assert from_label(dialogs.app, 'Window("#32770", "Open")').resolve_once() is dialogs.other
    monkeypatch.setattr(App, "attach", staticmethod(lambda process=None, pid=None: dialogs.app))
    assert from_label(None, 'Process("DemoApp.exe").Window("#32770", 2)').resolve_once() is (
        dialogs.other
    )
    with pytest.raises(ValueError, match="needs a parent"):
        from_label(None, 'Window("#32770")')
    with pytest.raises(LabelSyntaxError, match="position 11"):
        from_label(dialogs.app, 'Window("a" "b")')


def test_steps_below_a_bound_window_or_a_page(fake, monkeypatch):
    from wintestkit import Page, Window, finders
    from wintestkit.engine import resolve as resolver

    first = fake.windows[0]
    monkeypatch.setattr(resolver, "resolve_window", lambda app, wl: first)
    monkeypatch.setattr(finders, "resolve_window", lambda app, wl: first)
    monkeypatch.setattr(finders, "route", fake.route)

    class MainPage(Page):
        window = Window(title="Main*")

    page = MainPage(fake.app)
    # Below a window, the root visual is the first object-tree level.
    root = page.window.wpf_object("MainView", "Main*")
    assert fake.resolve(root) is fake.tree["main"]
    assert (
        fake.resolve(page.window.WPFObject("MainView", "Main*").WPFObject("Grid", ""))
        is (fake.tree["main"].children[0])
    )
    assert (
        fake.resolve(from_label(page, 'WPFObject("MainView", "*").WPFObject("Grid", "")'))
        is (fake.tree["main"].children[0])
    )
    assert fake.resolve(wpf_object(page, "MainView", "Main title")) is fake.tree["main"]
    with pytest.raises(ElementNotFoundError) as raised:
        page.window.wpf_object("Nope", "*").resolve_once()
    assert 'no children of type "Nope"; its children have the types "MainView"' in str(raised.value)
    assert root.parent is not None and is_window_node(root.parent.locator)
    assert [child.label for child in root.children()] == ['WPFObject("Grid", "")']
