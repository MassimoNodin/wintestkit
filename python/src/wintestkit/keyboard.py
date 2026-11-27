"""Key presses that are not tied to an element, sent to the foreground window of the app under test.

Nothing is activated: the foreground window must already belong to the application under test,
otherwise the call is refused. To press keys into a specific window, use ``window.press``.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from wintestkit import runtime
from wintestkit.errors import ActionError
from wintestkit.uia import input, win32

_TARGET = "keyboard"
_LOCATOR = "foreground window"


def _check_foreground() -> None:
    """Refuse unless the foreground window belongs to the application under test."""
    __tracebackhide__ = True
    app = runtime.current_app()
    if app is None:
        raise ActionError(
            "There is no application under test to send keys to: use wintestkit.keyboard in a "
            "test that uses the `app` fixture (or a page bound to an App)"
        )
    hwnd = win32.GetForegroundWindow()
    if not hwnd or win32.window_pid(hwnd) not in set(app.pids):
        raise ActionError(
            f"The foreground window does not belong to {app.process_name}; refusing to send keys. "
            "Activate one of its windows first (window.activate())"
        )


def press(keys: str, *, secret: bool = False) -> None:
    """Press key combinations such as ``"Ctrl+S Enter"`` in the foreground window."""
    __tracebackhide__ = True
    args = {"keys": keys}
    with runtime.step("press", _TARGET, _LOCATOR, args, secret=True) as record:
        record.sensitive = True
        record.set_arguments(args, secret=secret)
        _check_foreground()
        input.press(keys)


def keys(text: str, *, secret: bool = False) -> None:
    """Send a migrated key string (``"^s"``, ``"[Hold]![F5]"``) to the foreground window.

    The grammar is the one of ``finders.send_keys`` (see ``wintestkit.keystrings``): ``^`` Ctrl,
    ``!`` Alt, ``~`` Shift, ``[Enter]``-style names, ``[Hold]`` and ``[Release]``. This is the
    global form: the keys go to whatever has focus in the foreground window, which must belong
    to the application under test.
    """
    __tracebackhide__ = True
    from wintestkit.keystrings import parse_keys, play_keys

    segments = parse_keys(text)
    args = {"keys": text}
    with runtime.step("keys", _TARGET, _LOCATOR, args, secret=True) as record:
        record.sensitive = True
        record.set_arguments(args, secret=secret)
        _check_foreground()
        play_keys(segments)


def type(text: str, *, secret: bool = False) -> None:
    """Type text into the foreground window."""
    __tracebackhide__ = True
    args = {"text": text}
    with runtime.step("type", _TARGET, _LOCATOR, args, secret=True) as record:
        record.sensitive = True
        record.set_arguments(args, secret=secret)
        _check_foreground()
        input.type_text(text)


@contextmanager
def hold(modifiers: str) -> Generator[None]:
    """Hold modifier keys (``"Ctrl+Shift"``) down for the block, e.g. around clicks.

    The modifiers are always released, also when the block raises.
    """
    __tracebackhide__ = True
    codes = input.parse_modifiers(modifiers)
    if not codes:
        raise ValueError("hold() needs at least one modifier, such as 'Ctrl' or 'Shift+Alt'")
    with runtime.step("hold", _TARGET, _LOCATOR, {"modifiers": modifiers}):
        _check_foreground()
        with input.hold_modifiers(codes):
            yield
