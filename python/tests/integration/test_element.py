"""Integration tests for UIAElement against the demo app."""

import pytest
from support import DemoProcess

from wintestkit.uia import com, element, win32
from wintestkit.uia.constants import TreeScope
from wintestkit.uia.element import UIAElement

pytestmark = pytest.mark.integration


def main_window(demo: DemoProcess) -> UIAElement:
    return element.from_handle(demo.hwnd)


def find_status(window: UIAElement) -> UIAElement:
    found = window.find_first(
        TreeScope.Descendants, com.create_condition(automation_id="StatusText")
    )
    assert found is not None
    return found


def test_main_window_children_and_info(demo_process: DemoProcess) -> None:
    window = main_window(demo_process)
    assert window.control_type == "Window"
    assert window.framework_id == "WPF"
    assert window.children()
    info = window.info(with_patterns=True)
    assert info.name == "WTK Demo"
    assert info.patterns is not None
    assert "Window" in info.patterns


def test_status_info_matches_expected(demo_process: DemoProcess) -> None:
    status = find_status(main_window(demo_process))
    info = status.info()
    assert info.control_type == "Text"
    assert info.automation_id == "StatusText"
    assert info.name == "Ready"
    assert info.class_name == "TextBlock"
    assert info.rect is not None
    assert info.runtime_id
    assert status.is_alive()


def test_cached_and_live_reads_agree(demo_process: DemoProcess) -> None:
    window = main_window(demo_process)
    live = {w.runtime_id: w.info() for w in window.find_all(TreeScope.Descendants)}
    cached = {w.runtime_id: w.info() for w in window.find_all(TreeScope.Descendants, cached=True)}
    assert live.keys() == cached.keys()
    # Focus and enabled state are stable on an idle app; compare everything else too.
    for runtime_id, info in live.items():
        assert cached[runtime_id] == info


def test_find_first_and_parent_and_same_as(demo_process: DemoProcess) -> None:
    window = main_window(demo_process)
    status = find_status(window)
    parent = status.parent()
    assert parent is not None
    assert parent.same_as(parent)
    assert not status.same_as(parent)
    assert (
        window.find_first(TreeScope.Descendants, com.create_condition(automation_id="Nope")) is None
    )


def test_from_point_and_from_handle(demo_process: DemoProcess) -> None:
    window = main_window(demo_process)
    sign_in = window.find_first(
        TreeScope.Descendants, com.create_condition(control_type=50000, name="Sign in")
    )
    assert sign_in is not None
    rect = sign_in.rect
    assert rect is not None
    assert win32.bring_to_foreground(demo_process.hwnd)
    hit = element.from_point(*rect.center)
    assert hit is not None
    # Record which element WPF returns at the centre of a button: the button or its text child.
    print(f"from_point(centre of Sign in) -> {hit.info().short()}")
    assert hit.process_id == demo_process.pid
    assert hit.name == "Sign in"
    assert hit.control_type in {"Button", "Text"}

    by_handle = element.from_handle(window.native_window_handle)
    assert by_handle.same_as(window)


def test_get_property_and_errors(demo_process: DemoProcess) -> None:
    status = find_status(main_window(demo_process))
    assert status.get_property("AutomationId") == "StatusText"
    with pytest.raises(ValueError, match="Nope"):
        status.get_property("Nope")
    assert "UIAElement" in repr(status)
