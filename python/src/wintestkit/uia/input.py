# pyright: basic
"""Synthetic mouse and keyboard input through ``SendInput``."""

from __future__ import annotations

import ctypes
import time
from dataclasses import dataclass
from typing import Literal

from wintestkit.errors import ActionError
from wintestkit.uia import win32

INPUT_SETTLE_S = 0.02
WHEEL_DELTA = 120

MouseButton = Literal["left", "right", "middle"]

_BUTTON_FLAGS: dict[str, tuple[int, int]] = {
    "left": (win32.MOUSEEVENTF_LEFTDOWN, win32.MOUSEEVENTF_LEFTUP),
    "right": (win32.MOUSEEVENTF_RIGHTDOWN, win32.MOUSEEVENTF_RIGHTUP),
    "middle": (win32.MOUSEEVENTF_MIDDLEDOWN, win32.MOUSEEVENTF_MIDDLEUP),
}

# -- key grammar (pure) --------------------------------------------------------------------------

_MODIFIERS: dict[str, int] = {
    "ctrl": 0x11,
    "control": 0x11,
    "shift": 0x10,
    "alt": 0x12,
    "win": 0x5B,
}

_NAMED_KEYS: dict[str, int] = {
    "enter": 0x0D,
    "return": 0x0D,
    "tab": 0x09,
    "esc": 0x1B,
    "escape": 0x1B,
    "space": 0x20,
    "backspace": 0x08,
    "delete": 0x2E,
    "del": 0x2E,
    "insert": 0x2D,
    "ins": 0x2D,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pgup": 0x21,
    "pagedown": 0x22,
    "pgdn": 0x22,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
    "plus": 0xBB,
    "minus": 0xBD,
    "comma": 0xBC,
    "period": 0xBE,
    "apps": 0x5D,
}

_EXTENDED_KEYS = frozenset({0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5D})


@dataclass(frozen=True)
class KeyCombo:
    """One key press with held modifiers, as virtual-key codes."""

    modifiers: tuple[int, ...]
    key: int


def _key_code(token: str) -> int | None:
    lower = token.lower()
    if lower in _NAMED_KEYS:
        return _NAMED_KEYS[lower]
    if len(token) == 1 and token.isascii() and token.isalnum():
        return ord(token.upper())
    if lower.startswith("f") and lower[1:].isdigit() and 1 <= int(lower[1:]) <= 24:
        return 0x70 + int(lower[1:]) - 1
    return None


def parse_keys(keys: str) -> list[KeyCombo]:
    """Parse ``"Ctrl+S"``, ``"Ctrl+A Delete"`` etc. into key combos."""
    combos: list[KeyCombo] = []
    for combo_text in keys.split():
        tokens = combo_text.split("+")
        modifiers: list[int] = []
        for token in tokens[:-1]:
            code = _MODIFIERS.get(token.lower())
            if code is None:
                raise ValueError(f"unknown modifier {token!r} in {combo_text!r}")
            modifiers.append(code)
        last = tokens[-1]
        key = _key_code(last)
        if key is None:
            modifier_key = _MODIFIERS.get(last.lower())
            if modifier_key is None:
                raise ValueError(f"unknown key {last!r} in {combo_text!r}")
            key = modifier_key
        combos.append(KeyCombo(tuple(modifiers), key))
    if not combos:
        raise ValueError("no keys given")
    return combos


# -- SendInput plumbing --------------------------------------------------------------------------


def _send(events: list[win32.INPUT]) -> None:
    if not events:
        return
    array = (win32.INPUT * len(events))(*events)
    sent = win32.SendInput(len(events), array, ctypes.sizeof(win32.INPUT))
    if sent != len(events):
        raise ActionError(
            f"input was blocked (sent {sent} of {len(events)} events); the target window may run "
            "with higher privileges (UIPI) or the desktop may be locked"
        )


def _mouse_event(flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> win32.INPUT:
    event = win32.INPUT()
    event.type = win32.INPUT_MOUSE
    event.mi.dx = dx
    event.mi.dy = dy
    event.mi.mouseData = data & 0xFFFFFFFF
    event.mi.dwFlags = flags
    return event


def _key_event(vk: int, up: bool) -> win32.INPUT:
    event = win32.INPUT()
    event.type = win32.INPUT_KEYBOARD
    event.ki.wVk = vk
    event.ki.wScan = win32.MapVirtualKeyW(vk, 0)
    flags = win32.KEYEVENTF_KEYUP if up else 0
    if vk in _EXTENDED_KEYS:
        flags |= win32.KEYEVENTF_EXTENDEDKEY
    event.ki.dwFlags = flags
    return event


def _unicode_event(unit: int, up: bool) -> win32.INPUT:
    event = win32.INPUT()
    event.type = win32.INPUT_KEYBOARD
    event.ki.wVk = 0
    event.ki.wScan = unit
    event.ki.dwFlags = win32.KEYEVENTF_UNICODE | (win32.KEYEVENTF_KEYUP if up else 0)
    return event


def _absolute(x: int, y: int) -> tuple[int, int]:
    screen = win32.virtual_screen_rect()
    nx = round((x - screen.left) * 65535 / max(screen.width - 1, 1))
    ny = round((y - screen.top) * 65535 / max(screen.height - 1, 1))
    return nx, ny


def _move_event(x: int, y: int) -> win32.INPUT:
    nx, ny = _absolute(x, y)
    flags = win32.MOUSEEVENTF_MOVE | win32.MOUSEEVENTF_ABSOLUTE | win32.MOUSEEVENTF_VIRTUALDESK
    return _mouse_event(flags, nx, ny)


# -- mouse ---------------------------------------------------------------------------------------


def move_mouse(x: int, y: int) -> None:
    """Move the cursor to physical screen coordinates."""
    _send([_move_event(x, y)])


def click(x: int, y: int, button: MouseButton = "left", count: int = 1) -> None:
    """Click ``count`` times at physical screen coordinates."""
    down, up = _BUTTON_FLAGS[button]
    events = [_move_event(x, y)]
    for _ in range(count):
        events.append(_mouse_event(down))
        events.append(_mouse_event(up))
    _send(events)
    time.sleep(INPUT_SETTLE_S)


def mouse_down(button: MouseButton = "left") -> None:
    _send([_mouse_event(_BUTTON_FLAGS[button][0])])


def mouse_up(button: MouseButton = "left") -> None:
    _send([_mouse_event(_BUTTON_FLAGS[button][1])])


def scroll_wheel(x: int, y: int, clicks: int) -> None:
    """Scroll the wheel at a position; positive ``clicks`` scroll up."""
    _send([_move_event(x, y), _mouse_event(win32.MOUSEEVENTF_WHEEL, data=clicks * WHEEL_DELTA)])
    time.sleep(INPUT_SETTLE_S)


# -- keyboard ------------------------------------------------------------------------------------


def press(keys: str) -> None:
    """Press key combos such as ``"Ctrl+S"`` or ``"Ctrl+A Delete"``."""
    for combo in parse_keys(keys):
        events = [_key_event(vk, up=False) for vk in combo.modifiers]
        events.append(_key_event(combo.key, up=False))
        events.append(_key_event(combo.key, up=True))
        events.extend(_key_event(vk, up=True) for vk in reversed(combo.modifiers))
        _send(events)
    time.sleep(INPUT_SETTLE_S)


def _utf16_units(char: str) -> list[int]:
    data = char.encode("utf-16-le")
    return [int.from_bytes(data[i : i + 2], "little") for i in range(0, len(data), 2)]


def type_text(text: str, interval: float = 0.0) -> None:
    """Type text using Unicode key events; ``\\n`` presses Enter and ``\\t`` presses Tab."""
    for char in text:
        if char == "\n":
            events = [_key_event(0x0D, up=False), _key_event(0x0D, up=True)]
        elif char == "\t":
            events = [_key_event(0x09, up=False), _key_event(0x09, up=True)]
        else:
            units = _utf16_units(char)
            events = [_unicode_event(u, up=False) for u in units]
            events += [_unicode_event(u, up=True) for u in units]
        _send(events)
        if interval > 0:
            time.sleep(interval)
    time.sleep(INPUT_SETTLE_S)
