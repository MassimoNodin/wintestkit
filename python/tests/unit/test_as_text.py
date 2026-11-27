"""AsText: loose comparison of managed values by their invariant text."""

import re

import pytest

import wintestkit
from wintestkit import AsText
from wintestkit.engine.locator import Locator
from wintestkit.engine.properties import normalize_where, resolve_where, text_matches
from wintestkit.engine.property_read import property_matches
from wintestkit.errors import InvalidLocatorError


def test_public_name_and_value_semantics():
    assert wintestkit.AsText is AsText
    assert AsText("15") == AsText("15") and AsText("15") != AsText("16")
    assert hash(AsText("15")) == hash(AsText("15"))
    with pytest.raises(TypeError):
        AsText(15)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "text, actual, expected",
    [
        ("15", 15, True),
        ("15", "15", True),
        ("16", 15, False),
        ("True", True, True),
        ("true", True, True),
        ("False", True, False),
        ("1", True, False),
        ("1.5", 1.5, True),
        ("1.50", 1.5, True),
        ("15.0", 15, True),
        ("abc", 15, False),
        ("x", None, False),
        ("", "", True),
    ],
)
def test_text_comparison(text, actual, expected):
    assert text_matches(AsText(text), actual) is expected
    assert property_matches(actual, AsText(text)) is expected


def test_accepted_only_for_managed_keys():
    assert normalize_where({"clr:Id": AsText("1"), "type:Name": AsText("X")}, {}) == (
        ("clr:Id", AsText("1")),
        ("type:Name", AsText("X")),
    )
    with pytest.raises(TypeError, match="HelpText"):
        normalize_where({"HelpText": AsText("x")}, {})
    with pytest.raises(InvalidLocatorError):
        normalize_where({"type:Is": AsText("X")}, {})
    assert resolve_where((("clr:Id", AsText("1")),), "owner")[0].value == AsText("1")


def test_locator_description_and_data_round_trip():
    locator = Locator(automation_id="a", where=(("clr:Id", AsText('1"2')), ("clr:Other", "x")))
    assert 'clr:Id=AsText("1\\"2")' in locator.describe()
    data = locator.to_dict()
    assert data["where"]["clr:Id"] == {"asText": '1"2'}
    assert Locator.from_dict(data) == locator
    with pytest.raises(ValueError, match="unknown"):
        Locator.from_dict({"automationId": "a", "where": {"clr:Id": {"asText": "1", "x": 1}}})
    # Regex matchers keep their own data shape.
    pattern = Locator(automation_id="a", where=(("clr:Id", re.compile("^1")),))
    assert Locator.from_dict(pattern.to_dict()) == pattern
