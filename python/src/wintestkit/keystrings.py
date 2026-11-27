"""The key-string grammar of migrated suites, parsed once and played anywhere.

``^`` is Ctrl, ``!`` is Alt and ``~`` is Shift; ``[Enter]``, ``[F5]`` and the other bracketed names
are single keys; a doubled ``^ ! ~ [`` is that literal character; everything else is typed text.
A modifier prefix applies to the next key only. ``[Hold]`` keeps modifiers down until ``[Release]``
or the end of the string, and is written either after the prefix (``^[Hold]a[Release]``) or in
front of it (``[Hold]^[Hold]![F8]`` holds Ctrl and Alt, then presses F8).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any, cast

from wintestkit.uia import input as keyboard

__all__ = ["KeySegment", "parse_keys", "play_keys", "to_keys"]


@dataclass(frozen=True)
class KeySegment:
    """A literal, key combination, or modifier hold/release command."""

    kind: str
    text: str = ""
    combo: keyboard.KeyCombo | None = None
    modifiers: tuple[int, ...] = ()


_PREFIXES = {"^": 0x11, "!": 0x12, "~": 0x10}
_KEY_NAMES = {
    "bs": "Backspace",
    "del": "Delete",
    "ins": "Insert",
    "esc": "Escape",
    "prtsc": "PrintScreen",
    "win": "Win",
    "apps": "Apps",
    "pause": "Pause",
    "capslock": "CapsLock",
    "numlock": "NumLock",
    "scrolllock": "ScrollLock",
}
_EXTRA_KEYS = {
    "PrintScreen": 0x2C,
    "Pause": 0x13,
    "CapsLock": 0x14,
    "NumLock": 0x90,
    "ScrollLock": 0x91,
    "Win": 0x5B,
}
_ALLOWED_NAMES = {
    "enter",
    "tab",
    "bs",
    "del",
    "ins",
    "esc",
    "home",
    "end",
    "pageup",
    "pagedown",
    "up",
    "down",
    "left",
    "right",
    "win",
    "apps",
    "pause",
    "capslock",
    "numlock",
    "scrolllock",
    "prtsc",
    "space",
}
_HOLD_AHEAD = "[Hold] must be followed by modifier prefixes such as ^ ! ~"


def parse_keys(text: str) -> list[KeySegment]:
    """Parse migration key strings into text, key, and modifier segments."""
    segments: list[KeySegment] = []
    pending: list[int] = []
    held: list[int] = []
    # ``[Hold]`` in front of modifier prefixes: they go down at once and stay down.
    hold_ahead = False
    hold_ahead_count = 0
    position = 0
    while position < len(text):
        char = text[position]
        if char in _PREFIXES and (position + 1 >= len(text) or text[position + 1] != char):
            modifier = _PREFIXES[char]
            position += 1
            if hold_ahead:
                hold_ahead_count += 1
                if modifier not in held:
                    held.append(modifier)
                    segments.append(KeySegment("hold", modifiers=(modifier,)))
            elif modifier not in pending and modifier not in held:
                pending.append(modifier)
            continue
        if char in "^!~[" and position + 1 < len(text) and text[position + 1] == char:
            value = char
            position += 2
            named = False
        elif char == "[":
            end = text.find("]", position + 1)
            if end < 0:
                raise ValueError(f"unclosed bracket at position {position}")
            value = text[position + 1 : end]
            position = end + 1
            named = True
        else:
            value = char
            position += 1
            named = False
        if hold_ahead:
            if not hold_ahead_count:
                raise ValueError(_HOLD_AHEAD)
            hold_ahead = False
        if named and value.casefold() == "hold":
            if not pending:
                hold_ahead = True
                hold_ahead_count = 0
                continue
            held.extend(pending)
            segments.append(KeySegment("hold", modifiers=tuple(pending)))
            pending.clear()
            continue
        if named and value.casefold() == "release":
            if pending:
                raise ValueError("modifier prefix before [Release]")
            segments.append(KeySegment("release", modifiers=tuple(held)))
            held.clear()
            continue
        if named:
            name = value.casefold()
            if name not in _ALLOWED_NAMES and not (
                name.startswith("f") and name[1:].isdigit() and 1 <= int(name[1:]) <= 24
            ):
                raise ValueError(f"unknown bracketed key [{value}]")
            canonical = _KEY_NAMES.get(name, value.capitalize())
            code = _EXTRA_KEYS.get(canonical) or cast(Any, keyboard)._key_code(canonical)
            assert code is not None
            segments.append(KeySegment("key", canonical, keyboard.KeyCombo(tuple(pending), code)))
        elif pending or held:
            code = cast(Any, keyboard)._key_code(value)
            if code is None:
                raise ValueError(f"modifier prefix cannot be applied to {value!r}")
            segments.append(
                KeySegment("key", value.upper(), keyboard.KeyCombo(tuple(pending), code))
            )
        elif segments and segments[-1].kind == "text":
            segments[-1] = replace(segments[-1], text=segments[-1].text + value)
        else:
            segments.append(KeySegment("text", value))
        pending.clear()
    if hold_ahead:
        raise ValueError(_HOLD_AHEAD)
    if pending:
        raise ValueError("dangling modifier prefix at end of key string")
    return segments


def to_keys(text: str) -> str | None:
    """Convert key-only input to press syntax, or return None for literal text."""
    segments = parse_keys(text)
    if any(segment.kind == "text" for segment in segments):
        return None
    names = {0x11: "Ctrl", 0x12: "Alt", 0x10: "Shift"}
    held: list[int] = []
    result: list[str] = []
    for segment in segments:
        if segment.kind == "hold":
            held.extend(segment.modifiers)
        elif segment.kind == "release":
            held.clear()
        elif segment.combo is not None:
            modifiers = [*held, *segment.combo.modifiers]
            result.append("+".join([*(names[modifier] for modifier in modifiers), segment.text]))
    return " ".join(result)


def play_keys(segments: Sequence[KeySegment]) -> None:
    """Send parsed segments to whatever has the keyboard focus; held modifiers are always freed."""
    __tracebackhide__ = True
    held: list[int] = []
    try:
        for segment in segments:
            if segment.kind == "text":
                keyboard.type_text(segment.text)
            elif segment.kind == "hold":
                for modifier in segment.modifiers:
                    cast(Any, keyboard)._send([cast(Any, keyboard)._key_event(modifier, up=False)])
                    held.append(modifier)
            elif segment.kind == "release":
                while held:
                    cast(Any, keyboard)._send([cast(Any, keyboard)._key_event(held.pop(), up=True)])
            else:
                combo = segment.combo
                assert combo is not None
                events = [
                    cast(Any, keyboard)._key_event(modifier, up=False)
                    for modifier in combo.modifiers
                ]
                events += [
                    cast(Any, keyboard)._key_event(combo.key, up=False),
                    cast(Any, keyboard)._key_event(combo.key, up=True),
                ]
                events += [
                    cast(Any, keyboard)._key_event(modifier, up=True)
                    for modifier in reversed(combo.modifiers)
                ]
                cast(Any, keyboard)._send(events)
    finally:
        while held:
            cast(Any, keyboard)._send([cast(Any, keyboard)._key_event(held.pop(), up=True)])
