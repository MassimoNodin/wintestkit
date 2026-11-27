import re

import pytest

from wintestkit.engine.properties import AsText, resolve_where
from wintestkit.engine.wpf_query import translate
from wintestkit.finders import to_locator


def test_mapped_properties():
    locator = to_locator(
        [
            "WPFControlName",
            "ClrFullClassName",
            "ClrClassName",
            "WPFControlText",
            "WPFControlOrdinalNo",
            "Visible",
            "Enabled",
        ],
        ["save", "Example.Button", "Button", "Save", 2, "True", False],
        depth=1,
    )
    # The object tree of a WPF window: text and ordinal are the managed keys.
    assert (
        locator.automation_id,
        locator.class_name,
        locator.name,
        locator.index,
        locator.depth,
        locator.tree,
    ) == ("save", None, None, None, 1, "objects")
    assert dict(locator.where) == {
        "type:FullName": "Example.Button",
        "type:Name": "Button",
        "wpf:Text": "Save",
        "wpf:Ordinal": 2,
        "clr:IsVisible": True,
        "clr:IsEnabled": False,
    }
    # Any other window keeps the UIA tree: the peer name and a zero-based global index.
    uia = locator.uia_form
    assert uia is not None
    assert (uia.automation_id, uia.name, uia.index, uia.tree) == ("save", "Save", 1, None)
    assert "wpf:Text" not in dict(uia.where)
    assert dict(uia.where)["type:Name"] == "Button"


def test_names_and_paths():
    locator = to_locator(["wPfCoNtRoLnAmE", "DataContext.Status", "Custom"], ["x", "Ready", 3])
    assert locator.automation_id == "x"
    assert dict(locator.where) == {"clr:DataContext.Status": AsText("Ready"), "clr:Custom": 3}
    assert dict(to_locator("CLrClAsSnAmE", "Button").where) == {"type:Name": "Button"}


@pytest.mark.parametrize("name", ["", "1abc", "a..b", "a-b", "DataContext[x]", "[0]", "a b"])
def test_invalid_names(name):
    with pytest.raises(ValueError, match="invalid property name"):
        to_locator(name, "x")


def test_name_rejected_and_list_shape():
    # Name is a label step (see test_labels.py); anything else is a syntax error.
    with pytest.raises(ValueError, match=r"expected '\('"):
        to_locator("nAmE", "WPFObject")
    assert to_locator("WPFControlName", "x") == to_locator(["WPFControlName"], ["x"])
    with pytest.raises(ValueError, match="equal length"):
        to_locator(["a", "b"], [1])
    with pytest.raises(ValueError, match="parallel sequences"):
        to_locator(["a"], "x")


@pytest.mark.parametrize(
    "value,expected", [(True, True), (False, False), ("True", True), ("false", False)]
)
def test_booleans(value, expected):
    assert dict(to_locator("Visible", value).where)["clr:IsVisible"] is expected
    assert dict(to_locator("Enabled", value).where)["clr:IsEnabled"] is expected


def test_invalid_boolean_and_ordinal():
    with pytest.raises(ValueError, match="True or False"):
        to_locator("Visible", 1)
    for value in (0, -1, True, "x"):
        with pytest.raises(ValueError, match="positive integer"):
            to_locator("WPFControlOrdinalNo", value)
    ordinal = to_locator("WPFControlOrdinalNo", 1)
    assert dict(ordinal.where) == {"wpf:Ordinal": 1}
    assert ordinal.index is None
    assert ordinal.uia_form is not None and ordinal.uia_form.index == 0


def test_wildcards_and_wpf_translation():
    locator = to_locator("WPFControlText", r"a.[x]+(b)\?*z")
    pattern = dict(locator.where)["wpf:Text"]
    assert isinstance(pattern, re.Pattern)
    assert pattern.search("a.[x]+(b)\\Qanythingz")
    assert not pattern.search("prefixa.[x]+(b)\\Qanythingz")
    assert not pattern.search("aX[x]+(b)\\Qanythingz")
    assert not pattern.search("a.[x]+(b)\\z")
    assert not pattern.search("a.[x]+(b)\\Qanythingzsuffix")
    assert translate(locator, resolve_where(locator.where, "test"), None).predicates
    assert dict(to_locator("WPFControlText", "a.b").where)["wpf:Text"] == "a.b"
    assert to_locator("WPFControlText", "a.b").uia_form.name == "a.b"


def test_depth_and_managed_wildcard_translation():
    locator = to_locator("DataContext.Status", "Ready*", depth=2)
    assert locator.depth == 2
    assert translate(locator, resolve_where(locator.where, "test"), None).depth == 2
    assert to_locator("WPFControlName", "x").depth is None
    with pytest.raises(ValueError, match="depth"):
        to_locator("WPFControlName", "x", depth=0)


def test_unicode_wildcard_strict_end():
    locator = to_locator("WPFControlText", "café?")
    pattern = dict(locator.where)["wpf:Text"]
    assert isinstance(pattern, re.Pattern)
    assert pattern.search("café!")
    assert not pattern.search("café!\n")
    translated = translate(locator, resolve_where(locator.where, "test"), None)
    assert translated.predicates[0].pattern == r"^café.\z"


@pytest.fixture
def helper_tree(monkeypatch):
    from fakes import FakeApp, FakeElement

    from wintestkit import runtime
    from wintestkit.engine import query
    from wintestkit.model import Element, Page

    monkeypatch.setenv("WTK_BACKEND", "uia")
    runtime.reset()
    monkeypatch.setattr(query, "make_condition", lambda **props: props)
    first = FakeElement("Button", "First", automation_id="Match1", class_name="Button")
    second = FakeElement("Button", "Second", automation_id="Match2", class_name="Button")
    group = FakeElement("Group", "Group", automation_id="Group", children=[first, second])
    app = FakeApp([FakeElement("Window", "Demo", children=[group])])

    class TestPage(Page):
        container = Element(automation_id="Group")

    yield TestPage(app), group, first, second
    runtime.reset()


def test_find_helpers_lazy_depth_and_order(helper_tree):
    from wintestkit.errors import AmbiguousElementError, ElementNotFoundError
    from wintestkit.finders import find, find_all_children, find_child

    page, group, first, second = helper_tree
    assert find_child(page.container, "WPFControlName", "Match*", 1).resolve_once() is first
    assert [
        item.resolve_once() for item in find_all_children(page.container, "ClassName", "Button")
    ] == [first, second]
    missing = find_child(page, "WPFControlName", "Match1", 1)
    assert not missing.exists()
    with pytest.raises(ElementNotFoundError, match="out of range"):
        missing.resolve_once()
    assert find_child(page, "WPFControlName", "Match1", 2).resolve_once() is first
    with pytest.raises(AmbiguousElementError):
        find_child(page.container, "ClassName", "Button", strict=True).resolve_once()
    assert find(page.container, "WPFControlName", "Group").resolve_once() is group
    assert find(page.container, "WPFControlName", "Match2").resolve_once() is second


def test_first_match_warning_channels_and_once(helper_tree, monkeypatch):
    from wintestkit import log
    from wintestkit.errors import AmbiguousMatchWarning
    from wintestkit.finders import find_child

    page, _, first, _ = helper_tree
    reports = []
    monkeypatch.setattr(log, "warning", lambda message: reports.append(message))
    lookup = find_child(page.container, "ClassName", "Button")
    with pytest.warns(AmbiguousMatchWarning, match="matched 2"):
        assert lookup.resolve_once() is first
    lookup.resolve_once()
    assert len(reports) == 1
    find_child(page.container, "WPFControlName", "Match1").resolve_once()
    find_child(page.container, ["ClassName", "WPFControlOrdinalNo"], ["Button", 1]).resolve_once()
    assert len(reports) == 1


def test_key_parser_and_conversion():
    from wintestkit.finders import parse_keys, to_keys

    segments = parse_keys("^a[Del]Hello~1[Enter]^^!!~~[[")
    assert [segment.kind for segment in segments] == ["key", "key", "text", "key", "key", "text"]
    assert segments[-1].text == "^!~["
    assert to_keys("^a[Del]") == "Ctrl+A Delete"
    assert to_keys("hello") is None
    assert [part.kind for part in parse_keys("^[Hold]a[Release]")] == ["hold", "key", "release"]
    with pytest.raises(ValueError, match="dangling"):
        parse_keys("^")
    with pytest.raises(ValueError, match="unknown"):
        parse_keys("[Bogus]")


@pytest.mark.parametrize(
    "name",
    [
        "Enter",
        "Tab",
        "BS",
        "Del",
        "Ins",
        "Esc",
        "Home",
        "End",
        "PageUp",
        "PageDown",
        "Up",
        "Down",
        "Left",
        "Right",
        "Win",
        "Apps",
        "Pause",
        "CapsLock",
        "NumLock",
        "ScrollLock",
        "PrtSc",
        "Space",
    ]
    + [f"F{number}" for number in range(1, 25)],
)
def test_named_key_conversion(name):
    from wintestkit.finders import parse_keys, to_keys
    from wintestkit.uia.input import parse_keys as parse_press_keys

    assert parse_keys(f"[{name}]")[0].kind == "key"
    assert parse_press_keys(to_keys(f"[{name}]"))


@pytest.mark.parametrize("secret, password", [(True, False), (False, True)])
def test_send_keys_sequence_and_redaction(helper_tree, monkeypatch, secret, password):
    from contextlib import contextmanager

    from wintestkit import finders

    page, _, element, _ = helper_tree
    target = finders.find_child(page.container, "WPFControlName", "Match1")
    events = []
    arguments = []

    class Record:
        sensitive = False

        def set_arguments(self, args, *, secret):
            arguments.append((args, secret))

    @contextmanager
    def step(*args, **kwargs):
        assert args[0] == "send_keys"
        assert kwargs["secret"]
        yield Record()

    monkeypatch.setattr(finders.runtime, "step", step)
    monkeypatch.setattr(target, "perform", lambda timeout, action: action(element))
    monkeypatch.setattr(finders.actions.PasswordClassifier, "is_password", lambda *args: password)
    monkeypatch.setattr(finders, "uia_of", lambda el: el)
    monkeypatch.setattr(finders.actions, "focus", lambda el: events.append("focus"))
    monkeypatch.setattr(finders.actions, "_keyboard_target", lambda el: events.append("safe"))
    monkeypatch.setattr(finders.keyboard, "_key_event", lambda key, up: (key, up))
    monkeypatch.setattr(finders.keyboard, "_send", lambda keys: events.extend(keys))
    monkeypatch.setattr(finders.keyboard, "type_text", lambda text: events.append(text))
    finders.send_keys(target, "^[Hold]a[Release]hello[Enter]", secret=secret)
    assert events == [
        "focus",
        "safe",
        (17, False),
        (65, False),
        (65, True),
        (17, True),
        "hello",
        (13, False),
        (13, True),
    ]
    assert arguments == [({"keys": "^[Hold]a[Release]hello[Enter]"}, True)]


@pytest.mark.parametrize(
    "prop,field,value,expected",
    [
        ("WndClass", "class_name", "Dialog", "Dialog"),
        ("ClassName", "class_name", "Button", "Button"),
        ("WinFormsControlName", "automation_id", "Save", "Save"),
        ("ControlId", "automation_id", 42, "42"),
        ("ControlId", "automation_id", "0042", "42"),
        ("WndCaption", "name", "&Yes && No", "Yes & No"),
    ],
)
def test_native_mappings(prop, field, value, expected):
    assert getattr(to_locator(prop, value), field) == expected


def test_migration_edges():
    assert dict(to_locator("FrameworkId", "Win32").where) == {"FrameworkId": "Win32"}
    assert dict(to_locator("LocalizedControlType", "button").where) == {
        "LocalizedControlType": "button"
    }
    assert dict(to_locator("VisibleOnScreen", "false").where) == {"VisibleOnScreen": False}
    assert dict(to_locator("DataContext.Caption.OleValue", "Pending").where) == {
        "clr:DataContext.Caption": AsText("Pending")
    }
    assert dict(to_locator("IsChecked.olevalue", True).where) == {"clr:IsChecked": True}
    assert dict(to_locator("WPFControlOrdinalNo", "6").where) == {"wpf:Ordinal": 6}
    assert to_locator("WPFControlOrdinalNo", "6").uia_form.index == 5
    assert not to_locator("Exists", True).where
    for prop, value in [
        ("Exists", False),
        ("OleValue", 1),
        ("ControlId", "abc"),
        ("VisibleOnScreen", 2),
    ]:
        with pytest.raises(ValueError):
            to_locator(prop, value)
    assert to_locator("WndCaption", "&Save*").name.fullmatch("Save As")
    assert dict(to_locator("ClrClassName", "Order*").where)["type:Name"].fullmatch("OrderWindow")


def test_app_search_and_visibility(monkeypatch):
    from fakes import FakeElement

    from wintestkit import runtime
    from wintestkit.app import App
    from wintestkit.engine import query
    from wintestkit.errors import AmbiguousElementError
    from wintestkit.finders import find, find_all_children, find_child

    monkeypatch.setenv("WTK_BACKEND", "uia")
    runtime.reset()
    monkeypatch.setattr(query, "make_condition", lambda **props: props)
    button = FakeElement("Button", "Save")
    hidden = FakeElement("Button", "Save", rect=None)
    main = FakeElement("Window", "Orders", children=[button, hidden])
    dialog = FakeElement("Window", "Save As")
    app = object.__new__(App)
    monkeypatch.setattr(app, "top_level_windows", lambda: [main, dialog])
    assert find_child(app, "WndCaption", "Save*", 1).resolve_once() is dialog
    assert find(app, "WndCaption", "Orders", 1).resolve_once() is main
    assert find_child(app, "WndCaption", "Save", 2).resolve_once() is button
    assert [e.resolve_once() for e in find_all_children(app, "WndCaption", "Save", 2)] == [
        button,
        hidden,
    ]
    assert (
        find_child(app, ["WndCaption", "VisibleOnScreen"], ["Save", False], 2).resolve_once()
        is hidden
    )
    with pytest.raises(AmbiguousElementError):
        find_child(app, "WndCaption", "Save", 2, strict=True).resolve_once()
    runtime.reset()


def test_plain_strings_on_managed_keys_compare_as_text():
    where = dict(
        to_locator(
            ["PersistId", "DataContext.Count", "Visible", "DataContext.Label", "WPFControlName"],
            ["15", "True", "false", "Order*", "Save"],
        ).where
    )
    assert where["clr:PersistId"] == AsText("15")
    assert where["clr:DataContext.Count"] == AsText("True")
    assert where["clr:IsVisible"] is False
    # Wildcards stay patterns; identity properties and type facets stay exact.
    assert where["clr:DataContext.Label"].fullmatch("Order 7")
    assert dict(to_locator("ClrFullClassName", "A.B").where) == {"type:FullName": "A.B"}
    # Numbers and booleans passed natively keep their exact types.
    assert dict(to_locator(["Count", "Flag"], [3, True]).where) == {
        "clr:Count": 3,
        "clr:Flag": True,
    }
    translated = translate(
        to_locator("PersistId", "15"), resolve_where(to_locator("PersistId", "15").where, "t"), None
    )
    assert [(p.kind, p.value) for p in translated.predicates] == [("equalsText", "15")]


@pytest.mark.parametrize(
    "name, key",
    [
        ("DataContext.ClrClassName", "type:Name@DataContext"),
        ("DataContext.ClrFullClassName", "type:FullName@DataContext"),
        ("datacontext.items.item[0].clrclassname", "type:Name@datacontext.items.item[0]"),
    ],
)
def test_nested_class_names_map_to_a_typed_path(name, key):
    locator = to_locator(name, "Order*" if key.startswith("type:Name") else "A.B")
    assert list(dict(locator.where)) == [key]
    assert key in dict(locator.where)


def test_indexed_property_names_are_accepted():
    locator = to_locator(["Items.Item[0].Name", "DataContext.Rows[3].Value"], ["a", "5"])
    assert dict(locator.where) == {
        "clr:Items.Item[0].Name": AsText("a"),
        "clr:DataContext.Rows[3].Value": AsText("5"),
    }
    for bad in ("Items[]", "Items[x]", "Items[0]x", "[0]", "Items.[0]"):
        with pytest.raises(ValueError, match="invalid property name"):
            to_locator(bad, "x")


def test_app_level_results_are_parents_that_resolve_in_their_own_window(monkeypatch):
    """A dialog found from the application anchors its children, whatever the main window holds."""
    from fakes import FakeElement

    from wintestkit import runtime
    from wintestkit.app import App
    from wintestkit.engine import query
    from wintestkit.errors import ElementNotFoundError
    from wintestkit.finders import find, find_all_children, find_child

    monkeypatch.setenv("WTK_BACKEND", "uia")
    runtime.reset()
    monkeypatch.setattr(query, "make_condition", lambda **props: props)
    main_edit = FakeElement("Edit", "Search", class_name="Edit")
    main = FakeElement("Window", "Orders", class_name="Window", children=[main_edit])
    dialog_edit = FakeElement("Edit", "File name", class_name="Edit")
    dialog_pane = FakeElement("Pane", "", class_name="Pane", children=[dialog_edit])
    dialog = FakeElement("Window", "Open", class_name="#32770", children=[dialog_pane])
    app = object.__new__(App)
    monkeypatch.setattr(app, "top_level_windows", lambda: [main, dialog])
    # The main window is not needed (and, here, not even available): the anchor is the dialog.
    monkeypatch.setattr(app, "main_window", lambda: pytest.fail("the main window was searched"))

    dlg = find_child(app, ["WndClass", "WndCaption"], ["#32770", "Open"], 1)
    assert dlg.resolve_once() is dialog
    assert find_child(dlg, "WndClass", "Edit", 5).resolve_once() is dialog_edit
    assert find_child(dlg, "WndClass", "Pane", 1).resolve_once() is dialog_pane
    assert find_child(
        find_child(dlg, "WndClass", "Pane", 1), "WndClass", "Edit", 1
    ).resolve_once() is (dialog_edit)
    assert [e.resolve_once() for e in find_all_children(dlg, "WndClass", "Edit", None)] == [
        dialog_edit
    ]
    # find() includes the parent itself, found in the application rather than in the main window.
    assert find(dlg, "WndClass", "#32770", 1).resolve_once() is dialog
    # An App-level link that matches nothing fails there, naming the link, not the child.
    gone = find_child(app, "WndCaption", "Nope", 1)
    with pytest.raises(ElementNotFoundError, match="Nope"):
        find_child(gone, "WndClass", "Edit", 1).resolve_once()
    runtime.reset()
