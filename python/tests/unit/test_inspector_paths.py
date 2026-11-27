"""Managed locator grammar tests."""

import pytest

from wintestkit.errors import InvalidLocatorError
from wintestkit.inspector.paths import parse_managed_key


@pytest.mark.parametrize(
    ("key", "kinds", "names"),
    [
        ("type:FullName", ["type"], ["FullName"]),
        (r"clr:DataContext.A\.B", ["property", "property"], ["DataContext", "A.B"]),
        ("field:First.Next", ["field", "property"], ["First", "Next"]),
        (r"dp:Asm|Example.Owner::Property/A\/B", ["dependency", "property"], ["Property", "A/B"]),
        ("clr:Items[0]", ["property"], ["Items[0]"]),
        ("clr:Items[0].Name", ["property", "property"], ["Items[0]", "Name"]),
        ("clr:DataContext.Rows[3].Value", ["property"] * 3, ["DataContext", "Rows[3]", "Value"]),
        ("clr:Items[-1]", ["property"], ["Items[-1]"]),
        ("field:items[2].X", ["field", "property"], ["items[2]", "X"]),
        # The .NET indexer spelling Item[n] is the same as Name[n].
        ("clr:Items.Item[0].Name", ["property", "property"], ["Items[0]", "Name"]),
        ("clr:DataContext.Items.Item[4]", ["property", "property"], ["DataContext", "Items[4]"]),
        ("clr:Item[0]", ["property"], ["Item[0]"]),
        ("clr:Items[0].Item[1]", ["property", "property"], ["Items[0]", "Item[1]"]),
        (r"dp:Asm|Owner::P/Items[1]", ["dependency", "property"], ["P", "Items[1]"]),
        # A nested type reads the runtime type of the value at a path.
        ("type:Name@DataContext", ["property", "type"], ["DataContext", "Name"]),
        (
            "type:FullName@DataContext.Items.Item[0]",
            ["property", "property", "type"],
            ["DataContext", "Items[0]", "FullName"],
        ),
        # The object tree: migration text and the same-type ordinal.
        ("wpf:Text", ["object"], ["Text"]),
        ("wpf:Ordinal", ["object"], ["Ordinal"]),
    ],
)
def test_parse(key: str, kinds: list[str], names: list[str]) -> None:
    path = parse_managed_key(key)
    assert path.canonical == key
    assert [s.kind for s in path.segments] == kinds
    assert [s.name for s in path.segments] == names
    assert len(path.to_json()) == len(kinds)


@pytest.mark.parametrize(
    "key",
    [
        "clr:",
        "clr:A..B",
        r"clr:A\q",
        "clr:A[",
        "clr:A[]",
        "clr:A[x]",
        "clr:A[0]B",
        "clr:A[1234567890]",
        "clr:[0]",
        "clr:A.[0]",
        "clr:A[0][1]",
        "type:nope",
        "type:Is@A",
        "type:Name@",
        "wpf:",
        "wpf:text",
        "wpf:Text.Length",
        "wpf:Items[0]",
        "dp:Asm|Owner::Prop/",
        "clr:" + ".".join(["a"] * 9),
        "clr:" + "x" * 1021,
    ],
)
def test_invalid(key: str) -> None:
    with pytest.raises(InvalidLocatorError):
        parse_managed_key(key)


def test_invalid_unicode_reports_locator_error() -> None:
    with pytest.raises(InvalidLocatorError):
        parse_managed_key("clr:\ud800")
