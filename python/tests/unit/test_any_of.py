"""any_of: OR across alternative property groups in locators."""

import re
from typing import Any

import pytest
from fakes import FakeApp, FakeElement

from wintestkit import Button, Element, Elements
from wintestkit.engine import query
from wintestkit.engine.locator import Locator, expand_alternatives
from wintestkit.engine.resolve import Scope, resolve, resolve_all, wait_link
from wintestkit.errors import AmbiguousElementError, ElementNotFoundError


@pytest.fixture(autouse=True)
def fake_conditions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(query, "make_condition", lambda **props: props)


class Tree:
    def __init__(self) -> None:
        self.sign_in = FakeElement("Button", "Sign in", class_name="Button")
        self.ok = FakeElement("Button", "OK", automation_id="Ok", class_name="Button")
        self.status = FakeElement("Text", "Ready", automation_id="StatusText")
        self.window = FakeElement(
            "Window", "Main", class_name="Window", children=[self.sign_in, self.ok, self.status]
        )
        self.app = FakeApp([self.window])
        self.scope = Scope(self.app)  # type: ignore[arg-type]


@pytest.fixture
def tree() -> Tree:
    return Tree()


def alternatives(*mappings: dict[str, Any], **fields: Any) -> Locator:
    return Locator(
        any_of=tuple(Locator(**mapping) for mapping in mappings),
        **fields,
    )


# -- construction and validation ------------------------------------------------------------------


def test_elements_accept_any_of_dicts() -> None:
    element = Element(any_of=[{"automation_id": "Ok"}, {"name": "OK", "ClassName": "Button"}])
    first, second = element._own.any_of
    assert first.automation_id == "Ok"
    assert second.name == "OK"
    assert second.where == (("ClassName", "Button"),)
    assert not element._own.is_empty()
    assert Elements(control_type="Button", any_of=[{"name": "A"}, {"name": "B"}])._own.any_of
    button = Button(any_of=[{"automation_id": "A"}, {"clr:Name": "B"}])
    assert button._own.any_of[1].where == (("clr:Name", "B"),)


@pytest.mark.parametrize(
    "bad",
    [
        [{"name": "A"}],
        [{"name": "A"}, {}],
    ],
)
def test_invalid_alternatives_are_rejected(bad: list[dict[str, Any]]) -> None:
    with pytest.raises((ValueError, TypeError)):
        Element(any_of=bad)


def test_alternative_cannot_hold_structure() -> None:
    inner = alternatives({"automation_id": "A"}, {"automation_id": "B"})
    with pytest.raises(ValueError, match="only properties"):
        Locator(any_of=(Locator(name="A"), Locator(name="B", any_of=inner.any_of)))
    with pytest.raises(ValueError, match="only properties"):
        Locator(any_of=(Locator(name="A"), Locator(name="B", depth=2)))
    with pytest.raises(ValueError, match="only properties"):
        Locator(any_of=(Locator(name="A"), Locator(name="B", within=Locator(name="C"))))


def test_conflicting_alternative_fails_at_construction() -> None:
    with pytest.raises(ValueError, match="conflicts"):
        Locator(control_type="Button", any_of=(Locator(control_type="Edit"), Locator(name="x")))
    with pytest.raises(ValueError, match="conflicts"):
        Locator(
            where=(("HelpText", "a"),),
            any_of=(Locator(where=(("HelpText", "b"),)), Locator(name="x")),
        )


def test_expand_alternatives_merges_own_properties() -> None:
    link = alternatives(
        {"automation_id": "Ok"},
        {"name": "OK", "where": (("HelpText", "h"),)},
        control_type="Button",
        index=2,
        depth=1,
    )
    expanded = expand_alternatives(link)
    assert [alt.describe_link() for alt in expanded] == [
        'Button[id="Ok", depth=1]',
        'Button[name="OK", depth=1, HelpText="h"]',
    ]
    assert all(alt.index is None and not alt.any_of for alt in expanded)
    plain = Locator(name="x")
    assert expand_alternatives(plain) == [plain]


def test_describe_and_round_trip() -> None:
    locator = alternatives(
        {"automation_id": "Ok"},
        {"name": re.compile("^ok$", re.IGNORECASE), "control_type": "Button"},
        control_type="Button",
    )
    assert locator.describe() == ('Button[any_of=(id="Ok" | name=/^ok$/i, control_type=Button)]')
    assert Locator.from_dict(locator.to_dict()) == locator
    assert locator.to_dict()["anyOf"][0] == {"automationId": "Ok"}


# -- resolution -----------------------------------------------------------------------------------


def test_union_follows_alternative_order(tree: Tree) -> None:
    locator = alternatives({"automation_id": "StatusText"}, {"name": "Sign in"})
    assert resolve_all(tree.scope, locator) == [tree.status, tree.sign_in]


def test_union_drops_duplicates(tree: Tree) -> None:
    locator = alternatives({"name": "Sign in"}, {"class_name": "Button"})
    assert resolve_all(tree.scope, locator) == [tree.sign_in, tree.ok]


def test_single_matching_alternative_resolves(tree: Tree) -> None:
    locator = alternatives({"automation_id": "Nope"}, {"automation_id": "StatusText"})
    assert resolve(tree.scope, locator) is tree.status


def test_alternatives_matching_different_elements_are_ambiguous(tree: Tree) -> None:
    locator = alternatives({"automation_id": "StatusText"}, {"name": "Sign in"})
    with pytest.raises(AmbiguousElementError) as exc_info:
        resolve(tree.scope, locator)
    assert exc_info.value.diagnostic.match_count == 2
    assert "any_of=" in str(exc_info.value)


def test_index_applies_to_the_union(tree: Tree) -> None:
    locator = alternatives({"automation_id": "StatusText"}, {"name": "Sign in"})
    assert resolve(tree.scope, locator.with_index(0)) is tree.status
    assert resolve(tree.scope, locator.with_index(1)) is tree.sign_in


def test_index_out_of_range_reports_the_union(tree: Tree) -> None:
    locator = alternatives({"automation_id": "StatusText"}, {"name": "Sign in"}, index=2)
    with pytest.raises(ElementNotFoundError) as exc_info:
        resolve(tree.scope, locator)
    diagnostic = exc_info.value.diagnostic
    assert diagnostic.kind == "index_out_of_range"
    assert diagnostic.match_count == 2


def test_not_found_lists_closest_candidates(tree: Tree) -> None:
    locator = alternatives({"automation_id": "Nope"}, {"name": "Sign In", "control_type": "Button"})
    with pytest.raises(ElementNotFoundError) as exc_info:
        resolve(tree.scope, locator)
    diagnostic = exc_info.value.diagnostic
    assert diagnostic.kind == "not_found"
    assert diagnostic.candidates[0].info.name == "Sign in"


def test_wait_link_falls_back_to_polling(tree: Tree) -> None:
    locator = alternatives({"automation_id": "Ok"}, {"name": "OK"})
    assert wait_link(tree.scope, locator, "visible") == (False, None)
    outer = Locator(control_type="Button", name="Sign in", within=locator)
    assert wait_link(tree.scope, outer, "visible") == (False, None)
