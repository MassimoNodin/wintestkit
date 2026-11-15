"""has=: keep only matches that contain a descendant matching a child locator."""

from typing import Any

import pytest
from fakes import FakeApp, FakeElement

from wintestkit import Button, Element, Elements, Window
from wintestkit.engine import query
from wintestkit.engine import resolve as resolve_module
from wintestkit.engine.locator import ItemSelector, Locator, WindowLocator
from wintestkit.engine.resolve import Scope, resolve, resolve_all, wait_link
from wintestkit.engine.wpf_query import UnsupportedQuery, translate
from wintestkit.errors import (
    AmbiguousElementError,
    ElementNotFoundError,
    InspectorLimitError,
)


@pytest.fixture(autouse=True)
def fake_conditions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(query, "make_condition", lambda **props: props)


class Tree:
    def __init__(self) -> None:
        self.ok = FakeElement("Button", "OK", automation_id="Ok")
        self.cancel = FakeElement("Button", "Cancel", automation_id="Cancel")
        self.deep_ok = FakeElement("Button", "OK", automation_id="Ok")
        self.inner = FakeElement("Pane", "Inner", children=[self.deep_ok])
        self.with_ok = FakeElement("Group", "Panel", automation_id="A", children=[self.ok])
        self.with_cancel = FakeElement("Group", "Panel", automation_id="B", children=[self.cancel])
        self.with_deep = FakeElement("Group", "Panel", automation_id="C", children=[self.inner])
        self.empty = FakeElement("Group", "Panel", automation_id="D")
        self.window = FakeElement(
            "Window",
            "Main",
            children=[self.with_ok, self.with_cancel, self.with_deep, self.empty],
        )
        self.app = FakeApp([self.window])
        self.scope = Scope(self.app)  # type: ignore[arg-type]


@pytest.fixture
def tree() -> Tree:
    return Tree()


def group(**fields: Any) -> Locator:
    return Locator(control_type="Group", name="Panel", **fields)


OK = Locator(control_type="Button", automation_id="Ok")
CANCEL = Locator(automation_id="Cancel")
MISSING = Locator(control_type="Button", automation_id="Nope")


# -- construction and validation ------------------------------------------------------------------


def test_elements_accept_an_element_or_a_locator() -> None:
    typed = Element(control_type="Group", has=Button(automation_id="Ok"))
    assert typed._own.has == Locator(automation_id="Ok")
    assert Element(control_type="Group", has=OK)._own.has == OK
    assert Elements(control_type="Group", has=OK)._own.has == OK
    assert not Element(has=OK)._own.is_empty()


def test_child_declarations_take_has() -> None:
    panel = Element(automation_id="P")
    assert panel.Element(control_type="Group", has=OK)._own.has == OK


def test_has_may_use_where_any_of_and_depth() -> None:
    child = Locator(
        depth=2,
        where=(("HelpText", "x"),),
        any_of=(Locator(name="A"), Locator(name="B")),
    )
    assert Element(control_type="Group", has=child)._own.has == child


def test_has_rejects_structure() -> None:
    with pytest.raises(ValueError, match="has="):
        Locator(name="G", has=Locator(name="A", index=1))
    with pytest.raises(ValueError, match="has="):
        Locator(name="G", has=Locator(name="A", within=Locator(name="B")))
    with pytest.raises(ValueError, match="has="):
        Locator(name="G", has=Locator(name="A", has=OK))
    with pytest.raises(ValueError, match="has="):
        Locator(name="G", has=Locator(name="A", window=WindowLocator(title="W")))
    with pytest.raises(ValueError, match="has="):
        Locator(name="G", has=Locator(name="A", item=ItemSelector("row", 0)))
    with pytest.raises(ValueError, match="has="):
        Element(name="G", has=Element(name="A", within=Element(name="B")))
    with pytest.raises(ValueError, match="has="):
        Element(name="G", has=Element(name="A", window=Window(title="W")))
    with pytest.raises(TypeError):
        Element(name="G", has="Ok")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        Element(name="G", has=Elements(name="A"))  # type: ignore[arg-type]


def test_has_needs_a_property() -> None:
    with pytest.raises(ValueError):
        Locator(name="G", has=Locator(index=0))


def test_any_of_alternatives_cannot_hold_has() -> None:
    with pytest.raises(ValueError, match="only properties"):
        Locator(any_of=(Locator(name="A"), Locator(name="B", has=OK)))


def test_describe_and_round_trip() -> None:
    locator = Locator(control_type="Group", has=OK)
    assert locator.describe() == 'Group[has=Button[id="Ok"]]'
    assert Locator.from_dict(locator.to_dict()) == locator
    assert locator.to_dict()["has"] == {"automationId": "Ok", "controlType": "Button"}
    nested = group(has=Locator(depth=2, any_of=(Locator(name="A"), Locator(name="B"))))
    assert nested.describe() == (
        'Group[name="Panel", has=*[depth=2, any_of=(name="A" | name="B")]]'
    )
    assert Locator.from_dict(nested.to_dict()) == nested


# -- resolution -----------------------------------------------------------------------------------


def test_has_filters_candidates(tree: Tree) -> None:
    assert resolve_all(tree.scope, group(has=OK)) == [tree.with_ok, tree.with_deep]
    assert resolve(tree.scope, group(has=CANCEL)) is tree.with_cancel


def test_depth_limits_the_child_search(tree: Tree) -> None:
    shallow = group(has=Locator(automation_id="Ok", depth=1))
    assert resolve(tree.scope, shallow) is tree.with_ok


def test_has_combines_with_any_of(tree: Tree) -> None:
    locator = Locator(
        control_type="Group",
        any_of=(
            Locator(automation_id="A"),
            Locator(automation_id="B"),
            Locator(automation_id="D"),
        ),
        has=Locator(any_of=(Locator(automation_id="Ok"), Locator(automation_id="Cancel"))),
    )
    assert resolve_all(tree.scope, locator) == [tree.with_ok, tree.with_cancel]


def test_ambiguity_is_judged_after_filtering(tree: Tree) -> None:
    # Four groups share the name; only one holds Cancel, two hold Ok.
    assert resolve(tree.scope, group(has=CANCEL)) is tree.with_cancel
    with pytest.raises(AmbiguousElementError) as exc_info:
        resolve(tree.scope, group(has=OK))
    assert exc_info.value.diagnostic.match_count == 2


def test_index_applies_after_filtering(tree: Tree) -> None:
    assert resolve(tree.scope, group(has=OK, index=0)) is tree.with_ok
    assert resolve(tree.scope, group(has=OK, index=1)) is tree.with_deep
    with pytest.raises(ElementNotFoundError) as exc_info:
        resolve(tree.scope, group(has=OK, index=2))
    assert exc_info.value.diagnostic.kind == "index_out_of_range"
    assert exc_info.value.diagnostic.match_count == 2


def test_has_inside_a_within_chain(tree: Tree) -> None:
    outer = Locator(control_type="Group", automation_id="A", has=OK)
    inner = Locator(control_type="Button", within=outer)
    assert resolve(tree.scope, inner) is tree.ok


def test_candidate_bound() -> None:
    limit = resolve_module.MAX_HAS_CANDIDATES
    assert limit == 200
    groups = [FakeElement("Group", "Panel") for _ in range(limit + 1)]
    over = Scope(FakeApp([FakeElement("Window", "Main", children=groups)]))  # type: ignore[arg-type]
    with pytest.raises(InspectorLimitError, match="200 candidates"):
        resolve_all(over, group(has=OK))
    at_limit = Scope(FakeApp([FakeElement("Window", "Main", children=groups[:limit])]))  # type: ignore[arg-type]
    assert resolve_all(at_limit, group(has=OK)) == []


# -- waits and wire queries -----------------------------------------------------------------------


def test_wait_link_falls_back_to_polling(tree: Tree) -> None:
    locator = group(has=OK)
    assert wait_link(tree.scope, locator, "visible") == (False, None)
    outer = Locator(control_type="Button", within=locator)
    assert wait_link(tree.scope, outer, "visible") == (False, None)


def test_translate_refuses_has() -> None:
    with pytest.raises(UnsupportedQuery):
        translate(group(has=OK), (), None)


# -- diagnostics ----------------------------------------------------------------------------------


def test_not_found_says_candidates_lacked_the_child(tree: Tree) -> None:
    with pytest.raises(ElementNotFoundError) as exc_info:
        resolve(tree.scope, group(has=MISSING))
    diagnostic = exc_info.value.diagnostic
    assert diagnostic.kind == "not_found"
    assert '4 elements matched Group[name="Panel"]' in diagnostic.message
    assert 'but none contains Button[id="Nope"]' in diagnostic.message
    assert len(diagnostic.candidates) == 4


def test_index_with_nothing_kept_reports_the_missing_child(tree: Tree) -> None:
    with pytest.raises(ElementNotFoundError) as exc_info:
        resolve(tree.scope, group(has=MISSING, index=0))
    assert "but none contains" in exc_info.value.diagnostic.message


def test_no_candidates_at_all_gives_the_plain_not_found(tree: Tree) -> None:
    with pytest.raises(ElementNotFoundError) as exc_info:
        resolve(tree.scope, Locator(control_type="Group", name="Other", has=OK))
    assert "none contains" not in exc_info.value.diagnostic.message
    assert "has=" in exc_info.value.diagnostic.message
