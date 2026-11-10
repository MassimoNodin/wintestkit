import re

import pytest

from wintestkit.engine.properties import resolve_where
from wintestkit.engine.wpf_query import translate
from wintestkit.testcomplete import to_locator


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
    assert (
        locator.automation_id,
        locator.class_name,
        locator.name,
        locator.index,
        locator.depth,
    ) == ("save", "Button", "Save", 1, 1)
    assert dict(locator.where) == {
        "type:FullName": "Example.Button",
        "clr:IsVisible": True,
        "clr:IsEnabled": False,
    }


def test_names_and_paths():
    locator = to_locator(["wPfCoNtRoLnAmE", "DataContext.Status", "Custom"], ["x", "Ready", 3])
    assert locator.automation_id == "x"
    assert dict(locator.where) == {"clr:DataContext.Status": "Ready", "clr:Custom": 3}
    assert to_locator("CLrClAsSnAmE", "Button").class_name == "Button"


@pytest.mark.parametrize("name", ["", "1abc", "a..b", "a-b", "DataContext[0]", "a b"])
def test_invalid_names(name):
    with pytest.raises(ValueError, match="invalid TestComplete property name"):
        to_locator(name, "x")


def test_name_rejected_and_list_shape():
    with pytest.raises(ValueError, match="mapped properties"):
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
    for value in (0, -1, True, "1"):
        with pytest.raises(ValueError, match="positive integer"):
            to_locator("WPFControlOrdinalNo", value)
    assert to_locator("WPFControlOrdinalNo", 1).index == 0


def test_wildcards_and_wpf_translation():
    locator = to_locator("WPFControlText", r"a.[x]+(b)\?*z")
    pattern = locator.name
    assert isinstance(pattern, re.Pattern)
    assert pattern.search("a.[x]+(b)\\Qanythingz")
    assert not pattern.search("prefixa.[x]+(b)\\Qanythingz")
    assert not pattern.search("aX[x]+(b)\\Qanythingz")
    assert not pattern.search("a.[x]+(b)\\z")
    assert not pattern.search("a.[x]+(b)\\Qanythingzsuffix")
    assert translate(locator, (), None).predicates
    assert to_locator("WPFControlText", "a.b").name == "a.b"


def test_depth_and_managed_wildcard_translation():
    locator = to_locator("DataContext.Status", "Ready*", depth=2)
    assert locator.depth == 2
    assert translate(locator, resolve_where(locator.where, "test"), None).depth == 2
    assert to_locator("WPFControlName", "x").depth is None
    with pytest.raises(ValueError, match="depth"):
        to_locator("WPFControlName", "x", depth=0)


def test_unicode_wildcard_strict_end():
    locator = to_locator("WPFControlText", "café?")
    assert isinstance(locator.name, re.Pattern)
    assert locator.name.search("café!")
    assert not locator.name.search("café!\n")
    assert translate(locator, (), None).predicates[0].pattern == r"^café.\z"


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
    from wintestkit.testcomplete import find, find_all_children, find_child

    page, group, first, second = helper_tree
    assert find_child(page.container, "WPFControlName", "Match*", 1).resolve_once() is first
    assert [
        item.resolve_once() for item in find_all_children(page.container, "ClrClassName", "Button")
    ] == [first, second]
    missing = find_child(page, "WPFControlName", "Match1", 1)
    assert not missing.exists()
    with pytest.raises(ElementNotFoundError, match="out of range"):
        missing.resolve_once()
    assert find_child(page, "WPFControlName", "Match1", 2).resolve_once() is first
    with pytest.raises(AmbiguousElementError):
        find_child(page.container, "ClrClassName", "Button", strict=True).resolve_once()
    assert find(page.container, "WPFControlName", "Group").resolve_once() is group
    assert find(page.container, "WPFControlName", "Match2").resolve_once() is second
