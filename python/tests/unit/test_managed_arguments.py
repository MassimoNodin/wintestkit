"""Exact CLR argument encodings for managed calls."""

from decimal import Decimal as PythonDecimal
from enum import Enum as PythonEnum

import pytest

from wintestkit import Decimal, Double, Enum, Int32, Int64, Null, Single
from wintestkit.inspector.write_policy import parse_write_allowlist
from wintestkit.managed import argument, encode_argument


@pytest.mark.parametrize(
    "value,expected",
    [
        (Int32(4), {"type": "System.Int32", "value": 4}),
        (Int64(4), {"type": "System.Int64", "value": 4}),
        (Single(1.5), {"type": "System.Single", "value": 1.5}),
        (Double(1.5), {"type": "System.Double", "value": 1.5}),
        (Decimal("1.25"), {"type": "System.Decimal", "value": "1.25"}),
        (PythonDecimal("1.25"), {"type": "System.Decimal", "value": "1.25"}),
        (Enum("Ns.Choice", "First"), {"type": "Ns.Choice", "enum": "First"}),
        (Enum("Ns.Choice", 1), {"type": "Ns.Choice", "enum": 1}),
        (Null("System.String"), {"type": "System.String", "null": True}),
    ],
)
def test_encoding(value, expected):
    assert encode_argument(value) == expected


def test_range_and_ambiguous_values():
    for value in (-(2**31) - 1, 2**31):
        with pytest.raises(ValueError, match="Int32"):
            Int32(value)
    with pytest.raises(ValueError, match="Single"):
        Single(1e100)
    with pytest.raises(ValueError, match="Null"):
        argument(None)

    class Choice(PythonEnum):
        FIRST = 1

    with pytest.raises(ValueError, match="Enum"):
        argument(Choice.FIRST)


def test_nullable_allowlist():
    _, policy = parse_write_allowlist(["Ns.Control.M(System.Nullable`1[System.Int32])"])
    assert policy["methods"][0]["memberKey"] == "M(System.Nullable`1[System.Int32])"
