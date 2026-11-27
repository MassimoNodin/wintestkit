"""Every key string a migrated suite sends, parsed and played exactly as its author expects."""

from collections.abc import Generator
from typing import Any

import pytest

from wintestkit import finders, keyboard, keystrings, runtime
from wintestkit.errors import ActionError
from wintestkit.uia import input as press

CTRL, ALT, SHIFT = 0x11, 0x12, 0x10

# Key-only strings and the combination each one presses, in the press grammar of ``keyboard.press``.
KEY_ONLY = {
    "[Enter]": "Enter",
    "^a": "Ctrl+A",
    "[Del]": "Delete",
    "[BS]": "Backspace",
    "^v": "Ctrl+V",
    "^e": "Ctrl+E",
    "[Down]": "Down",
    "^A": "Ctrl+A",
    "![Down]": "Alt+Down",
    "^t": "Ctrl+T",
    "^[Del]": "Ctrl+Delete",
    "~[F4]": "Shift+F4",
    "[Tab]": "Tab",
    "![Right]": "Alt+Right",
    "^n": "Ctrl+N",
    "[Win]": "Win",
    "^p": "Ctrl+P",
    "^c": "Ctrl+C",
    "[F5]": "F5",
    "[Hold]![F5]": "Alt+F5",
    "![F8]": "Alt+F8",
    "^s": "Ctrl+S",
    "^i": "Ctrl+I",
    "[F11]": "F11",
    "^o": "Ctrl+O",
    "^[F4]": "Ctrl+F4",
    "[Hold]^[Hold]![F8]": "Ctrl+Alt+F8",
    "^[Right]": "Ctrl+Right",
    "^[Left]": "Ctrl+Left",
    "^[Up]": "Ctrl+Up",
    "^[Down]": "Ctrl+Down",
}

TEXT = ["5", "hello"]


@pytest.mark.parametrize(("text", "pressed"), KEY_ONLY.items())
def test_every_key_string_of_the_suite_parses_to_its_combination(text: str, pressed: str) -> None:
    assert finders.to_keys(text) == pressed
    # The converted form is valid input of ``keyboard.press`` too.
    assert press.parse_keys(pressed)
    assert all(segment.kind != "text" for segment in keystrings.parse_keys(text))


@pytest.mark.parametrize("text", TEXT)
def test_plain_text_is_typed(text: str) -> None:
    (segment,) = keystrings.parse_keys(text)
    assert (segment.kind, segment.text) == ("text", text)
    assert finders.to_keys(text) is None


def test_the_finders_names_are_the_key_grammar() -> None:
    assert finders.parse_keys is keystrings.parse_keys
    assert finders.to_keys is keystrings.to_keys
    assert finders.KeySegment is keystrings.KeySegment


@pytest.mark.parametrize(
    ("text", "kinds"),
    [
        ("hello[Enter]", ["text", "key"]),
        ("ab^cd", ["text", "key", "text"]),
        ("5[Tab]5[Tab]", ["text", "key", "text", "key"]),
        ("[Del]hello", ["key", "text"]),
        ("^a[Del]new text[Enter]", ["key", "key", "text", "key"]),
        ("~[Tab]x", ["key", "text"]),
    ],
)
def test_text_mixed_with_keys(text: str, kinds: list[str]) -> None:
    assert [segment.kind for segment in keystrings.parse_keys(text)] == kinds


def test_a_modifier_applies_to_the_next_key_only() -> None:
    first, second = keystrings.parse_keys("^a[Del]")
    assert first.combo is not None and first.combo.modifiers == (CTRL,)
    assert second.combo is not None and second.combo.modifiers == ()


def test_uppercase_after_a_modifier_is_the_same_key() -> None:
    assert keystrings.parse_keys("^A") == [
        keystrings.KeySegment("key", "A", press.KeyCombo((CTRL,), 0x41))
    ]
    assert keystrings.parse_keys("^a")[0].combo == keystrings.parse_keys("^A")[0].combo


def test_modifier_prefixes_combine() -> None:
    (segment,) = keystrings.parse_keys("^~[Tab]")
    assert segment.combo == press.KeyCombo((CTRL, SHIFT), 0x09)


# -- [Hold] ---------------------------------------------------------------------------------------


def test_hold_in_front_of_a_prefix_holds_it_until_the_end() -> None:
    assert [(s.kind, s.modifiers) for s in keystrings.parse_keys("[Hold]![F5]")] == [
        ("hold", (ALT,)),
        ("key", ()),
    ]


def test_hold_chain_holds_both_modifiers() -> None:
    segments = keystrings.parse_keys("[Hold]^[Hold]![F8]")
    assert [s.kind for s in segments] == ["hold", "hold", "key"]
    assert [s.modifiers for s in segments[:2]] == [(CTRL,), (ALT,)]
    assert segments[2].combo == press.KeyCombo((), 0x77)


def test_hold_in_front_of_several_prefixes_holds_them_all() -> None:
    segments = keystrings.parse_keys("[Hold]^!x")
    assert [s.kind for s in segments] == ["hold", "hold", "key"]
    assert segments[2].combo == press.KeyCombo((), ord("X"))


def test_hold_after_the_prefix_still_works_and_release_ends_it() -> None:
    assert [s.kind for s in keystrings.parse_keys("^[Hold]a[Release]b")] == [
        "hold",
        "key",
        "release",
        "text",
    ]


@pytest.mark.parametrize("bad", ["[Hold]", "[Hold]a", "[Hold][Enter]", "x[Hold]"])
def test_hold_without_a_modifier_is_an_error(bad: str) -> None:
    with pytest.raises(ValueError, match="Hold"):
        keystrings.parse_keys(bad)


# -- playing --------------------------------------------------------------------------------------


@pytest.fixture
def events(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    sent: list[Any] = []
    monkeypatch.setattr(press, "_key_event", lambda key, up: (key, up))
    monkeypatch.setattr(press, "_send", lambda batch: sent.extend(batch))
    monkeypatch.setattr(press, "type_text", lambda text: sent.append(text))
    return sent


def test_hold_chain_presses_the_modifiers_around_the_key_and_frees_them(events: list[Any]) -> None:
    keystrings.play_keys(keystrings.parse_keys("[Hold]^[Hold]![F8]"))
    assert events == [
        (CTRL, False),
        (ALT, False),
        (0x77, False),
        (0x77, True),
        (ALT, True),
        (CTRL, True),
    ]


def test_single_hold_with_a_function_key(events: list[Any]) -> None:
    keystrings.play_keys(keystrings.parse_keys("[Hold]![F5]"))
    assert events == [(ALT, False), (0x74, False), (0x74, True), (ALT, True)]


def test_a_prefix_without_hold_wraps_the_key(events: list[Any]) -> None:
    keystrings.play_keys(keystrings.parse_keys("^[Del]"))
    assert events == [(CTRL, False), (0x2E, False), (0x2E, True), (CTRL, True)]


def test_text_and_keys_are_sent_in_order(events: list[Any]) -> None:
    keystrings.play_keys(keystrings.parse_keys("hello[Enter]"))
    assert events == ["hello", (0x0D, False), (0x0D, True)]


def test_held_modifiers_are_freed_when_a_key_cannot_be_sent(
    events: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(batch: list[Any]) -> None:
        events.extend(batch)
        if (0x74, False) in batch:
            raise ActionError("blocked")

    monkeypatch.setattr(press, "_send", refuse)
    with pytest.raises(ActionError):
        keystrings.play_keys(keystrings.parse_keys("[Hold]![F5]"))
    assert events[-1] == (ALT, True)


# -- the desktop-level form -----------------------------------------------------------------------


@pytest.fixture
def steps() -> Generator[list[runtime.StepRecord]]:
    runtime.reset()
    recorded: list[runtime.StepRecord] = []
    runtime.add_step_listener(recorded.append)
    yield recorded
    runtime.reset()


def test_desktop_keys_send_the_migrated_grammar(
    steps: list[runtime.StepRecord], events: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(keyboard, "_check_foreground", lambda: None)
    keyboard.keys("^s")
    keyboard.keys("[Hold]^[Hold]![F8]")
    keyboard.keys("hello[Enter]")
    keyboard.keys("^v", secret=True)
    assert events[:4] == [(CTRL, False), (0x53, False), (0x53, True), (CTRL, True)]
    assert events[4:10] == [
        (CTRL, False),
        (ALT, False),
        (0x77, False),
        (0x77, True),
        (ALT, True),
        (CTRL, True),
    ]
    assert events[10:13] == ["hello", (0x0D, False), (0x0D, True)]
    assert [step.action for step in steps] == ["keys"] * 4
    assert steps[0].args == {"keys": "^s"}
    assert steps[3].args == {"keys": "***"}  # secret input is never logged


def test_desktop_keys_refuse_a_foreground_that_is_not_the_application(
    steps: list[runtime.StepRecord], events: list[Any]
) -> None:
    runtime.set_current_app(None)
    with pytest.raises(ActionError, match="no application under test"):
        keyboard.keys("^s")
    assert events == []
    assert steps[0].status == "failed"


def test_desktop_keys_reject_a_bad_string_before_any_input(events: list[Any]) -> None:
    with pytest.raises(ValueError, match="dangling"):
        keyboard.keys("^")
    assert events == []
