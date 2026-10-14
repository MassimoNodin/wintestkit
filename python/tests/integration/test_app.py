"""Integration tests for App launch / attach / close against the demo app."""

import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from support import window_props

from wintestkit.app import App
from wintestkit.engine.locator import WindowLocator
from wintestkit.errors import AppError, AppNotRunningError, WindowNotFoundError
from wintestkit.uia import com, patterns, win32
from wintestkit.uia.constants import TreeScope

pytestmark = pytest.mark.integration


@pytest.fixture
def app(demo_app_path: Path) -> Iterator[App]:
    launched = App.launch(demo_app_path)
    try:
        yield launched
    finally:
        launched.kill()


def wait_for(predicate: object, timeout: float = 5.0) -> bool:
    assert callable(predicate)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return bool(predicate())


def click_button(app: App, name: str) -> None:
    window = app.main_window()
    button = window.find_first(
        TreeScope.Descendants, com.create_condition(control_type=50000, name=name)
    )
    assert button is not None
    patterns.invoke(button)


def test_launch_waits_for_slow_start(demo_app_path: Path) -> None:
    started = time.monotonic()
    app = App.launch(demo_app_path, args=["--slow-start", "1500"])
    try:
        elapsed = time.monotonic() - started
        assert elapsed >= 1.3
        assert app.launched
        assert app.process_name == "DemoApp.exe"
        assert app.is_running()
        assert app.main_window().name == "WTK Demo"
    finally:
        app.kill()
    assert not app.is_running()


def test_main_window_and_windows(app: App) -> None:
    window = app.main_window(timeout=1.0)
    assert window.name == "WTK Demo"
    assert [w.name for w in app.top_level_windows()] == ["WTK Demo"]
    assert len(app.pids) == 1


def test_attach_by_name_and_pid(app: App) -> None:
    by_name = App.attach(process="DemoApp.exe")
    assert not by_name.launched
    assert app.pids[0] in by_name.pids
    assert by_name.main_window(timeout=1.0).name in {"WTK Demo"}
    by_pid = App.attach(pid=app.pids[0])
    assert by_pid.pids == app.pids
    assert by_pid.process_name == "DemoApp.exe"


def test_attach_errors() -> None:
    with pytest.raises(AppNotRunningError):
        App.attach(process="definitely-not-running-wtk.exe")
    with pytest.raises(AppNotRunningError):
        App.attach(pid=2**22 - 4)
    with pytest.raises(ValueError, match="process name or a pid"):
        App.attach()


def test_dialog_and_message_box_are_top_level_windows(app: App) -> None:
    main = app.main_window()
    click_button(app, "Open dialog")
    assert wait_for(lambda: "WTK Demo - Dialog" in window_props(app, "name"))
    dialog = next(w for w in app.top_level_windows() if w.name == "WTK Demo - Dialog")
    assert win32.window_owner(dialog.native_window_handle) == main.native_window_handle
    assert app.main_window().name == "WTK Demo"  # owned windows are never the main window
    patterns.window_close(dialog)
    assert wait_for(lambda: "WTK Demo - Dialog" not in window_props(app, "name"))

    click_button(app, "Show message")
    assert wait_for(lambda: "#32770" in window_props(app, "class_name"))
    box = next(w for w in app.top_level_windows() if w.class_name == "#32770")
    assert box.name == "WTK Demo Message"
    assert win32.window_owner(box.native_window_handle) != 0


def test_close_exits_the_app(demo_app_path: Path) -> None:
    app = App.launch(demo_app_path)
    app.close(timeout=10)
    assert not app.is_running()


def test_close_dismisses_open_message_box(app: App) -> None:
    click_button(app, "Show message")
    assert wait_for(lambda: "#32770" in window_props(app, "class_name"))
    started = time.monotonic()
    app.close(timeout=10)
    assert not app.is_running()
    assert time.monotonic() - started < 9


def test_context_manager_closes_launched_app(demo_app_path: Path) -> None:
    with App.launch(demo_app_path) as app:
        assert app.is_running()
    assert not app.is_running()


def test_launch_missing_executable_raises(tmp_path: Path) -> None:
    with pytest.raises(AppError, match="not found"):
        App.launch(tmp_path / "missing.exe")


def test_launch_timeout_kills_the_process(demo_app_path: Path) -> None:
    started = time.monotonic()
    with pytest.raises(AppError, match="did not show a window within"):
        App.launch(demo_app_path, args=["--slow-start", "6000"], startup_timeout=1.0)
    assert time.monotonic() - started < 8


def test_main_window_not_found_has_diagnostic(app: App) -> None:
    app.close()
    with pytest.raises(AppNotRunningError):
        app.main_window()


def test_window_diagnostic_lists_open_windows(app: App) -> None:
    from wintestkit.engine.diagnose import diagnose_window

    diagnostic = diagnose_window(app, WindowLocator(title="Foo"), [])
    assert diagnostic.kind == "window_not_found"
    assert diagnostic.message == (
        'No window matches Window[title="Foo"] for DemoApp.exe (open windows: "WTK Demo")'
    )
    assert diagnostic.candidates[0].mismatches[0].property == "title"
    assert "WindowNotFoundError" in WindowNotFoundError(diagnostic).to_dict()["type"]
