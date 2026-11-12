"""WPF query translation and UIA remapping."""

import re

import pytest

from wintestkit.config import load_config
from wintestkit.engine.locator import Locator
from wintestkit.engine.properties import resolve_where
from wintestkit.engine.wpf_query import UnsupportedQuery, translate
from wintestkit.errors import InvalidLocatorError
from wintestkit.inspector.models import ObjectRef, TypeInfo

TYPE = TypeInfo("T", "Demo.T", "Demo", "Demo.T, Demo", ())


def ref(i):
    return ObjectRef("session", str(i), 1, TYPE, "dispatcher")


def wire(locator):
    return translate(locator, resolve_where(locator.where, "test", locator.taken()), ref(0))


def test_translation_all_kinds():
    locator = Locator(
        automation_id="id",
        name=re.compile("a.*", re.I | re.M | re.S),
        class_name="Button",
        control_type="button",
        where=(
            ("clr:Name", "x"),
            ("field:State", True),
            ("dp:Asm|Demo.Owner::Value", 1),
            ("type:FullName", "Demo.T"),
            ("type:Is", "Demo.Base"),
        ),
    )
    result = wire(locator)
    assert result.scope.handle == ref(0) and result.depth == 256 and result.limit == 200
    assert result.depth_mode == "peers"
    assert wire(Locator(name="x", depth=1)).depth == 1
    assert [p.kind for p in result.predicates] == [
        "equals",
        "regex",
        "equals",
        "equals",
        "equals",
        "equals",
        "equals",
        "equals",
        "assignableTo",
    ]
    assert result.predicates[1].flags == ("ignoreCase", "multiline", "singleline")
    assert result.predicates[3].value == "Button"


@pytest.mark.parametrize("pattern", [r"\d", "(?=x)", "a{10001}", "[é]", "a++"])
def test_regex_rejected(pattern):
    with pytest.raises(UnsupportedQuery):
        wire(Locator(name=re.compile(pattern), where=(("clr:X", 1),)))


@pytest.mark.parametrize("pattern", ["a(?:b|c){1,3}?", "^[a-z]+$"])
def test_regex_accepted(pattern):
    assert (
        wire(Locator(name=re.compile(pattern), where=(("clr:X", 1),))).predicates[0].kind == "regex"
    )


@pytest.mark.parametrize(
    "pattern,text,ignore_case,expected",
    [
        ("é", "café", False, True),
        ("é", "É", True, False),
        ("é", "é", True, True),
        ("☃", "☃", True, True),
        ("😀+", "😀😀", False, True),
        (r"^.\Z", "😀", False, True),
        (r"^[^a]\Z", "😀", False, True),
        (r"b\Z", "ab\n", False, False),
        ("b$", "ab\n", False, True),
        (r"^café.*\Z", "café noir", False, True),
        (r"^café.*\Z", "café\n", False, False),
    ],
)
def test_shared_reference_cases(pattern, text, ignore_case, expected):
    # The agent runs the same table; ASCII flag models its case-folding contract.
    compiled = re.compile(pattern, re.ASCII | (re.I if ignore_case else 0))
    assert bool(compiled.search(text)) is expected
    if ignore_case and any(ord(c) > 127 and c.isalpha() for c in pattern):
        with pytest.raises(UnsupportedQuery, match="non-ASCII letter"):
            wire(Locator(name=re.compile(pattern, re.I)))
    else:
        result = wire(Locator(name=re.compile(pattern, re.I if ignore_case else 0)))
        assert result.predicates[0].pattern == pattern.replace(r"\Z", r"\z")


def test_fallbacks_and_type_is_validation():
    for locator in (
        Locator(where=(("HelpText", "x"), ("clr:X", 1))),
        Locator(name=re.compile("a", re.X), where=(("clr:X", 1),)),
        Locator(where=tuple((f"clr:P{i}", 1) for i in range(33))),
    ):
        with pytest.raises(UnsupportedQuery):
            wire(locator)
    with pytest.raises(InvalidLocatorError):
        Locator(where=(("type:Is", re.compile("X")),))


def test_removed_query_config_is_rejected(tmp_path):
    from wintestkit.errors import ConfigError

    with pytest.raises(ConfigError, match=r"inspector\.query"):
        load_config(tmp_path, overrides={"inspector.query": "agent"})
