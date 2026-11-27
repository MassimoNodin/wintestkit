"""parent, children, child_count, label and full_name: they walk the tree and round-trip."""

from __future__ import annotations

import pytest
from fakes import FakeElement
from object_tree_fake import FakeApp, Node
from test_label_steps import build, uia_app

from wintestkit import runtime
from wintestkit.engine import query
from wintestkit.engine.locator import is_window_node
from wintestkit.errors import InspectorLimitError
from wintestkit.finders import from_label, window
from wintestkit.labels import parse_label

PROCESS = 'Process("Demo.exe")'
MAIN = 'WPFObject("HwndSource: MainView", "Main title").WPFObject("MainView", "Main title")'


@pytest.fixture
def fake(monkeypatch):
    tree = build()
    fake = FakeApp(monkeypatch, tree["main"], tree["popup"])
    fake.tree = tree  # type: ignore[attr-defined]
    yield fake
    runtime.reset()


def main_view(fake: FakeApp):
    return from_label(fake.app, MAIN)


def test_labels_and_full_names_of_objects(fake):
    root = main_view(fake)
    grid = root.wpf_object("Grid", "")
    assert grid.label == 'WPFObject("Grid", "")'
    assert grid.full_name == f'{PROCESS}.{MAIN}.WPFObject("Grid", "")'
    assert grid.wpf_object("ok").label == 'WPFObject("ok")'  # an x:Name no sibling shares
    assert grid.wpf_object("Button", "Cancel").label == 'WPFObject("Button", "Cancel")'
    box = grid.wpf_object("ListBox", "")
    labels = [item.label for item in box.children()]
    assert labels == [
        'WPFObject("ListBoxItem", "Alpha")',
        'WPFObject("ListBoxItem", "Beta", 2)',  # the ordinal counts every ListBoxItem
        'WPFObject("ListBoxItem", "")',  # the only item with an empty text
        'WPFObject("ListBoxItem", "Beta", 4)',
    ]
    assert box.child_count == 4
    assert box.children()[1].full_name.endswith(
        '.WPFObject("list").WPFObject("ListBoxItem", "Beta", 2)'
    )


def test_every_element_round_trips_through_its_full_name(fake):
    root = main_view(fake)
    seen = 0

    def visit(bound, node: Node, parent: Node | None) -> None:
        nonlocal seen
        seen += 1
        assert fake.resolve(bound) is node
        # full_name parses back to the same element, with the application or by process name.
        name = bound.full_name
        assert parse_label(name).process == "Demo.exe"
        assert fake.resolve(from_label(fake.app, name)) is node
        assert bound.label == str(parse_label(name).steps[-1])
        # parent: the element above, and the window node above a root visual.
        up = bound.parent
        assert up is not None
        if parent is not None:
            assert fake.resolve(up) is parent
        else:
            assert is_window_node(up.locator)
        # children: bound elements that re-resolve by their own step, in order.
        kids = bound.children()
        assert bound.child_count == len(kids) == len(node.children)
        for child_bound, child in zip(kids, node.children, strict=True):
            visit(child_bound, child, node)

    visit(root, fake.tree["main"], None)
    assert seen == len(fake.tree["main"].preorder())


def test_a_window_node_has_the_root_visual_as_its_only_child(fake):
    node = fake.app.wpf_object("HwndSource: MainView", "*")
    assert node.label == 'WPFObject("HwndSource: MainView", "Main title")'
    assert node.full_name == f'{PROCESS}.WPFObject("HwndSource: MainView", "Main title")'
    assert node.parent is None
    assert node.child_count == 1
    (only,) = node.children()
    assert fake.resolve(only) is fake.tree["main"]
    assert only.label == 'WPFObject("MainView", "Main title")'
    parent = only.parent
    assert parent is not None and is_window_node(parent.locator)
    assert fake.resolve(from_label(fake.app, node.full_name)) is fake.tree["main"]
    popup = fake.app.wpf_object("HwndSource: PopupRoot", "")
    assert popup.label == 'WPFObject("HwndSource: PopupRoot", "")'
    assert popup.children()[0].children()[1].label == 'WPFObject("ComboBoxItem", "Two")'


def test_window_nodes_of_the_same_type_are_told_apart_by_ordinal(monkeypatch):
    one, two, three = Node("Dialog", "Same"), Node("Dialog", "Same"), Node("Dialog", "Other")
    fake = FakeApp(monkeypatch, one, two, three)
    labels = [fake.app.wpf_object("HwndSource: Dialog", "*", index).label for index in (1, 2, 3)]
    assert labels == [
        'WPFObject("HwndSource: Dialog", "Same", 1)',
        'WPFObject("HwndSource: Dialog", "Same", 2)',
        'WPFObject("HwndSource: Dialog", "Other")',
    ]
    for index, node in enumerate((one, two, three), start=1):
        bound = fake.app.wpf_object("HwndSource: Dialog", "*", index)
        assert fake.resolve(from_label(fake.app, bound.full_name)) is node
    runtime.reset()


def test_an_element_found_elsewhere_still_names_itself_from_the_process(fake):
    from wintestkit.finders import find_child

    found = find_child(fake.app, "Name", 'WPFObject("Button", 2)', 4)
    assert found.full_name.endswith('.WPFObject("Grid", "").WPFObject("Button", "Cancel")')
    assert found.parent is not None and fake.resolve(found.parent) is fake.tree["cancel"].parent
    # An unreadable text still has a label: the ordinal.
    fake.tree["cancel"].text = None
    assert found.label == 'WPFObject("Button", 2)'


def test_children_beyond_one_query_say_so(fake, monkeypatch):
    from wintestkit.engine import objects

    def incomplete(root, locator, **kwargs):
        result = fake.query(root, locator, **kwargs)
        result.complete = False
        return result

    monkeypatch.setattr(objects, "query", incomplete)
    with pytest.raises(InspectorLimitError, match="more object-tree children"):
        main_view(fake).child_count  # noqa: B018


# -- child windows --------------------------------------------------------------------------


@pytest.fixture
def dialog(monkeypatch):
    monkeypatch.setenv("WTK_BACKEND", "uia")
    runtime.reset()
    monkeypatch.setattr(query, "make_condition", lambda **props: props)
    children = [
        FakeElement("Button", "OK", class_name="Button"),
        FakeElement("Edit", "", class_name="Edit"),
        FakeElement("Edit", "hello", class_name="Edit"),
        FakeElement("Edit", "hello", class_name="Edit"),
        FakeElement("Pane", "no handle"),  # no class: not a window
    ]
    children[-1].native_window_handle = 0
    save = FakeElement("Window", "Save As", class_name="#32770", children=children)
    other = FakeElement("Window", "Open", class_name="#32770")
    yield uia_app(monkeypatch, [save, other]), save, children
    runtime.reset()


def test_child_windows_are_labelled_by_class_caption_and_index(dialog):
    app, save, children = dialog
    top = window(app, "#32770", "Save*")
    assert top.label == 'Window("#32770", "Save As")'
    assert top.full_name == 'Process("DemoApp.exe").Window("#32770", "Save As")'
    assert top.parent is None
    assert top.child_count == 4  # the pane has no window handle
    kids = top.children()
    assert [kid.label for kid in kids] == [
        'Window("Button")',
        'Window("Edit", "", 1)',
        'Window("Edit", "hello", 2)',
        'Window("Edit", "hello", 3)',
    ]
    for kid, element in zip(kids, children, strict=False):
        assert kid.resolve_once() is element
        again = from_label(app, kid.full_name)
        assert again.resolve_once() is element
        parent = kid.parent
        assert parent is not None and parent.resolve_once() is save
    assert kids[3].full_name == (
        'Process("DemoApp.exe").Window("#32770", "Save As").Window("Edit", "hello", 3)'
    )
    assert window(app, "#32770", "Open").label == 'Window("#32770", "Open")'


def test_a_window_node_is_labelled_by_the_x_name_of_its_root_visual(monkeypatch):
    named = Node("SettingsView", "Options", "SettingsViewWindow", Node("Grid", ""))
    plain = Node("SettingsView", "Other")
    fake = FakeApp(monkeypatch, named, plain)
    generated = 'WPFObject("HwndSource: SettingsViewWindow", "Options")'
    node = fake.app.wpf_object("HwndSource: SettingsViewWindow", "*")
    assert node.label == generated
    assert node.full_name == f"{PROCESS}.{generated}"
    # The type spelling of the same node keeps resolving it; the label is the generated one.
    legacy = fake.app.wpf_object("HwndSource: SettingsView", "Options")
    assert fake.resolve(legacy) is named
    assert legacy.label == generated
    assert fake.resolve(from_label(fake.app, f"{PROCESS}.{generated}")) is named
    # The window without an x:Name is labelled by its type, with its own ordinal.
    other = fake.app.wpf_object("HwndSource: SettingsView", "Other")
    assert other.label == 'WPFObject("HwndSource: SettingsView", "Other")'
    assert fake.resolve(other) is plain
    # The root visual below the node is still addressed by its x:Name.
    (root,) = node.children()
    assert root.label == 'WPFObject("SettingsViewWindow")'
    assert fake.resolve(from_label(fake.app, root.full_name)) is named
    runtime.reset()
