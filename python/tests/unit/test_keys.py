"""Unit tests for the key grammar and Win32 structure layout."""

import ctypes

import pytest

from wintestkit.uia import win32
from wintestkit.uia.input import KeyCombo, parse_keys


def test_single_key() -> None:
    assert parse_keys("Enter") == [KeyCombo((), 0x0D)]


def test_letter_and_digit_case_insensitive() -> None:
    assert parse_keys("a") == [KeyCombo((), 0x41)]
    assert parse_keys("Z") == [KeyCombo((), 0x5A)]
    assert parse_keys("7") == [KeyCombo((), 0x37)]


def test_modifier_combo() -> None:
    assert parse_keys("Ctrl+S") == [KeyCombo((0x11,), 0x53)]
    assert parse_keys("ctrl+s") == parse_keys("CTRL+S")
    assert parse_keys("Control+S") == parse_keys("Ctrl+S")


def test_multiple_modifiers_keep_order() -> None:
    assert parse_keys("Ctrl+Shift+Tab") == [KeyCombo((0x11, 0x10), 0x09)]
    assert parse_keys("Win+Alt+D") == [KeyCombo((0x5B, 0x12), 0x44)]


def test_multiple_combos() -> None:
    assert parse_keys("Ctrl+A Delete") == [KeyCombo((0x11,), 0x41), KeyCombo((), 0x2E)]
    assert len(parse_keys("  Tab   Tab  Enter ")) == 3


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("Alt+F4", 0x73),
        ("F1", 0x70),
        ("f12", 0x7B),
        ("F24", 0x87),
        ("Esc", 0x1B),
        ("Escape", 0x1B),
        ("Return", 0x0D),
        ("Space", 0x20),
        ("Backspace", 0x08),
        ("Del", 0x2E),
        ("Ins", 0x2D),
        ("Home", 0x24),
        ("End", 0x23),
        ("PgUp", 0x21),
        ("PageDown", 0x22),
        ("Up", 0x26),
        ("Down", 0x28),
        ("Left", 0x25),
        ("Right", 0x27),
        ("Plus", 0xBB),
        ("Minus", 0xBD),
        ("Comma", 0xBC),
        ("Period", 0xBE),
        ("Apps", 0x5D),
    ],
)
def test_named_keys(text: str, code: int) -> None:
    assert parse_keys(text)[-1].key == code


def test_lone_modifier_is_a_key() -> None:
    assert parse_keys("Alt") == [KeyCombo((), 0x12)]
    assert parse_keys("Ctrl+Shift") == [KeyCombo((0x11,), 0x10)]


@pytest.mark.parametrize("bad", ["Foo", "Ctrl+Foo", "F25", "F0", "Foo+S", "Ctrl+", "+S", "Ctrl++"])
def test_unknown_tokens_raise(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_keys(bad)


def test_error_names_the_token() -> None:
    with pytest.raises(ValueError, match="Bogus"):
        parse_keys("Ctrl+Bogus")
    with pytest.raises(ValueError, match="Nope"):
        parse_keys("Nope+S")


def test_empty_raises() -> None:
    with pytest.raises(ValueError, match="no keys"):
        parse_keys("   ")


def test_input_structure_sizes_match_win32_abi() -> None:
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        assert ctypes.sizeof(win32.INPUT) == 40
        assert ctypes.sizeof(win32.MSLLHOOKSTRUCT) == 32
        assert ctypes.sizeof(win32.KBDLLHOOKSTRUCT) == 24
        assert ctypes.sizeof(win32.WNDCLASSEXW) == 80
        assert ctypes.sizeof(win32.PROCESSENTRY32W) == 568
    assert ctypes.sizeof(win32.BITMAPINFOHEADER) == 40
