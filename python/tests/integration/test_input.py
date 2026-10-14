"""Integration tests for SendInput-based mouse and keyboard input."""

import time

import pytest
from conftest import DemoProcess

from wintestkit.errors import ActionError  # noqa: F401
from wintestkit.uia import com, element, input, win32
from wintestkit.uia.constants import TreeScope
from wintestkit.uia.element import UIAElement

pytestmark = pytest.mark.integration


def username_box(demo: DemoProcess) -> UIAElement:
    window = element.from_handle(demo.hwnd)
    found = window.find_first(
        TreeScope.Descendants, com.create_condition(control_type=50004, class_name="TextBox")
    )
    assert found is not None
    return found


def read_value(box: UIAElement) -> str:
    return str(
        box.raw.GetCurrentPattern(10002)
        .QueryInterface(com.uia_module().IUIAutomationValuePattern)
        .CurrentValue
    )


def wait_value(box: UIAElement, expected: str, timeout: float = 3.0) -> None:
    """SendInput is asynchronous: poll until the app has processed the queued keys."""
    deadline = time.monotonic() + timeout
    while read_value(box) != expected and time.monotonic() < deadline:
        time.sleep(0.05)
    assert read_value(box) == expected


def test_click_type_and_clear(demo_process: DemoProcess) -> None:
    assert win32.bring_to_foreground(demo_process.hwnd)
    box = username_box(demo_process)
    rect = box.rect
    assert rect is not None
    input.click(*rect.center)
    input.type_text("héllo")
    wait_value(box, "héllo")
    input.press("Ctrl+A Delete")
    wait_value(box, "")
    input.type_text("a\tb")  # Tab moves focus away from the box
    wait_value(box, "a")


def test_type_text_outside_bmp(demo_process: DemoProcess) -> None:
    assert win32.bring_to_foreground(demo_process.hwnd)
    box = username_box(demo_process)
    box.set_focus()
    input.type_text("x😀y")
    wait_value(box, "x😀y")


def test_mouse_wheel_and_move_do_not_raise(demo_process: DemoProcess) -> None:
    assert win32.bring_to_foreground(demo_process.hwnd)
    rect = username_box(demo_process).rect
    assert rect is not None
    input.move_mouse(*rect.center)
    input.scroll_wheel(*rect.center, clicks=-1)
    input.click(*rect.center, button="right")
    input.press("Esc")
