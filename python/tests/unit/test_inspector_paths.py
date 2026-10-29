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
        "clr:A[0]",
        "type:nope",
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
