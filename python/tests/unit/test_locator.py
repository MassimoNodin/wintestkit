"""Unit tests for the locator data model."""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from wintestkit.engine.locator import (
    ItemSelector,
    Locator,
    WindowLocator,
    describe_matcher,
    match_value,
    matcher_from_data,
    matcher_to_data,
)

DESCRIBE_CASES: list[dict[str, Any]] = json.loads(
    (Path(__file__).parents[1] / "contract" / "fixtures" / "describe_cases.json").read_text(
        encoding="utf-8"
    )
)


@pytest.mark.parametrize("case", DESCRIBE_CASES, ids=[c["describe"] for c in DESCRIBE_CASES])
def test_describe_cases_and_round_trip(case: dict[str, Any]) -> None:
    locator = Locator.from_dict(case["locator"])
    assert locator.describe() == case["describe"]
    assert Locator.from_dict(locator.to_dict()) == locator


def test_describe_case_count() -> None:
    assert len(DESCRIBE_CASES) >= 12


def test_match_value() -> None:
    assert match_value("abc", "abc")
    assert not match_value("abc", "abcd")
    assert not match_value("abc", "ABC")
    assert match_value(re.compile(r"^Item \d+$"), "Item 42")
    assert match_value(re.compile("ite", re.IGNORECASE), "an Item here")
    assert not match_value(re.compile(r"^\d+$"), "x1")


def test_matcher_data_round_trip() -> None:
    assert matcher_to_data("x") == "x"
    pattern = re.compile("a+", re.IGNORECASE | re.DOTALL)
    data = matcher_to_data(pattern)
    assert data == {"regex": "a+", "flags": "is"}
    assert matcher_from_data(data) == pattern
    assert matcher_to_data(re.compile("plain")) == {"regex": "plain"}
    assert matcher_from_data({"regex": "plain"}) == re.compile("plain")


def test_matcher_from_data_rejects_bad_input() -> None:
    with pytest.raises(ValueError, match="flag"):
        matcher_from_data({"regex": "a", "flags": "z"})
    with pytest.raises(ValueError, match="invalid matcher"):
        matcher_from_data(5)


def test_describe_matcher() -> None:
    assert describe_matcher("Sign in") == '"Sign in"'
    assert describe_matcher(re.compile(r"^Item \d+$", re.IGNORECASE)) == r"/^Item \d+$/i"


def test_control_type_is_normalized() -> None:
    assert Locator(control_type="buttoncontroltype", name="x").control_type == "Button"


def test_validation_errors() -> None:
    with pytest.raises(ValueError, match="at least one property"):
        Locator()
    with pytest.raises(ValueError, match="at least one property"):
        Locator(within=Locator(name="x"))
    with pytest.raises(ValueError, match="index"):
        Locator(name="x", index=-1)
    with pytest.raises(ValueError, match="depth"):
        Locator(name="x", depth=0)
    with pytest.raises(ValueError, match="control type"):
        Locator(control_type="Nope")
    with pytest.raises(ValueError, match="column"):
        ItemSelector("cell", 1)
    with pytest.raises(ValueError, match="row"):
        ItemSelector("row", -1)
    with pytest.raises(ValueError, match="window index"):
        WindowLocator(index=-2)


def test_unknown_dict_keys_rejected() -> None:
    with pytest.raises(ValueError, match="bogus"):
        Locator.from_dict({"name": "x", "bogus": 1})
    with pytest.raises(ValueError, match="bogus"):
        WindowLocator.from_dict({"bogus": 1})


def test_chain_order() -> None:
    inner = Locator(control_type="Group", name="G")
    outer = Locator(control_type="Pane", name="P")
    leaf = Locator(
        control_type="Button",
        name="B",
        within=Locator(control_type="Group", name="G", within=outer),
    )
    assert [link.control_type for link in leaf.chain()] == ["Pane", "Group", "Button"]
    assert inner.chain() == [inner]


def test_with_index_and_with_item_return_copies() -> None:
    base = Locator(control_type="DataGrid", name="Grid")
    indexed = base.with_index(2)
    assert indexed.index == 2
    assert base.index is None
    item = ItemSelector("row", 1)
    assert base.with_item(item).item == item
    assert base.item is None


def test_exact_and_regex_props() -> None:
    loc = Locator(
        automation_id="A",
        name=re.compile("n+"),
        control_type="Button",
        class_name=re.compile("c", re.IGNORECASE),
    )
    assert loc.exact_props() == {"automation_id": "A", "control_type": 50000}
    assert loc.regex_props() == {"name": re.compile("n+"), "class_name": re.compile("c", re.I)}
    only_name = Locator(name="x")
    assert only_name.exact_props() == {"name": "x"}
    assert only_name.regex_props() == {}


def test_is_empty() -> None:
    assert Locator(index=0).is_empty()
    assert not Locator(name="x").is_empty()
    assert WindowLocator().is_empty()
    assert not WindowLocator(title="x").is_empty()
    assert not WindowLocator(index=0).is_empty()


def test_to_dict_omits_none_keys() -> None:
    assert Locator(name="x").to_dict() == {"name": "x"}
    assert WindowLocator(title="T", process="p.exe").to_dict() == {"title": "T", "process": "p.exe"}
    assert ItemSelector("row", 2).to_dict() == {"kind": "row", "row": 2}


def test_locators_are_hashable_and_frozen() -> None:
    a = Locator(name="x", control_type="Button")
    b = Locator(name="x", control_type="Button")
    assert hash(a) == hash(b)
    with pytest.raises(AttributeError):
        a.name = "y"  # type: ignore[misc]
