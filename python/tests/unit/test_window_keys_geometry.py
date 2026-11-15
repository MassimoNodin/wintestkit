"""Window key presses, the ``keyboard`` module and window geometry, with Windows calls mocked."""

from pathlib import Path
from typing import Any

import pytest
from fakes import FakeApp, FakeElement

from wintestkit import finders, keyboard, model, runtime
from wintestkit.config import load_config
from wintestkit.engine import actions
from wintestkit.errors import ActionError
from wintestkit.model import Page, Window
from wintestkit.uia import input, patterns, win32
from wintestkit.uia.element import Rect

HWND = 100


class DemoPage(Page):
    window = Window(title="WTK Demo")


class World:
    """The mocked desktop: foreground window, sent input and window calls, in order."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.dialog = FakeElement("Window", "WTK Demo")
        self.foreground = 999
        self.accepts_foreground = True
        self.log: list[tuple[Any, ...]] = []
        self.state = "normal"
        self.can_move = True
        self.can_resize = True
        self.window_pos_ok = True
        self.events: list[tuple[int, bool]] = []
        self.send_failure: BaseException | None = None
        monkeypatch.setattr(model, "resolve_window", lambda app, locator: self.dialog)
        monkeypatch.setattr(actions, "_top_level_hwnd", lambda element: HWND)
        monkeypatch.setattr(win32, "IsWindow", lambda hwnd: True)
        monkeypatch.setattr(win32, "window_pid", self._pid)
        monkeypatch.setattr(win32, "window_owner", lambda hwnd: 0)
        monkeypatch.setattr(win32, "GetForegroundWindow", lambda: self.foreground)
        monkeypatch.setattr(win32, "bring_to_foreground", self._bring)
        monkeypatch.setattr(win32, "move_resize_window", self._set_pos)
        monkeypatch.setattr(input, "press", lambda keys: self.log.append(("press", keys)))
        monkeypatch.setattr(input, "type_text", lambda text: self.log.append(("type", text)))
        monkeypatch.setattr(patterns, "window_visual_state", lambda el: self.state)
        monkeypatch.setattr(
            patterns,
            "transform_can",
            lambda el, what: (
                (self.can_move and what == "move") or (self.can_resize and what == "resize")
            ),
        )
        monkeypatch.setattr(
            patterns, "transform_move", lambda el, x, y: self.log.append(("tmove", x, y))
        )
        monkeypatch.setattr(
            patterns, "transform_resize", lambda el, w, h: self.log.append(("tresize", w, h))
        )
        monkeypatch.setattr(input, "_key_event", lambda vk, up: (vk, up))
        monkeypatch.setattr(input, "_send", self._send)

    def _pid(self, hwnd: int) -> int:
        return 1

    def _bring(self, hwnd: int) -> bool:
        self.log.append(("bring", hwnd))
        if self.accepts_foreground:
            self.foreground = hwnd
        return self.accepts_foreground

    def _set_pos(self, hwnd: int, **kwargs: int) -> bool:
        self.log.append(("setpos", hwnd, kwargs))
        return self.window_pos_ok

    def _send(self, events: list[Any]) -> None:
        self.events.extend(events)
        if self.send_failure is not None:
            raise self.send_failure


@pytest.fixture(autouse=True)
def runtime_setup(tmp_path: Path) -> list[runtime.StepRecord]:
    runtime.reset()
    runtime.set_config(load_config(tmp_path, {"timeout": 1.0}))
    records: list[runtime.StepRecord] = []
    runtime.add_step_listener(records.append)
    yield records  # type: ignore[misc]
    runtime.reset()


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> World:
    return World(monkeypatch)


@pytest.fixture
def window(world: World) -> model.BoundWindow:
    return DemoPage(FakeApp([world.dialog])).window  # type: ignore[arg-type]


# -- BoundWindow.press / type ---------------------------------------------------------------------


def test_press_activates_the_window_before_sending(
    world: World, window: model.BoundWindow, runtime_setup: list[runtime.StepRecord]
) -> None:
    window.press("Ctrl+S Enter")
    window.type("abc")
    assert world.log == [("bring", HWND), ("press", "Ctrl+S Enter"), ("type", "abc")]
    assert [(r.action, r.args) for r in runtime_setup] == [
        ("press", {"keys": "Ctrl+S Enter"}),
        ("type", {"text": "abc"}),
    ]


def test_press_skips_activation_when_the_window_already_has_the_foreground(
    world: World, window: model.BoundWindow
) -> None:
    world.foreground = HWND
    window.press("Tab")
    assert world.log == [("press", "Tab")]


def test_press_refuses_when_windows_denies_the_foreground(
    world: World, window: model.BoundWindow
) -> None:
    world.accepts_foreground = False
    with pytest.raises(ActionError, match="Cannot activate"):
        window.press("Tab")
    with pytest.raises(ActionError, match="Cannot activate"):
        window.type("abc")
    assert [entry[0] for entry in world.log] == ["bring", "bring"]


def test_press_refuses_a_window_of_another_process(
    world: World, window: model.BoundWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(win32, "window_pid", lambda hwnd: 2)
    with pytest.raises(ActionError, match="refusing global input"):
        window.press("Tab")
    assert world.log == []


def test_secret_window_input_is_redacted(
    world: World, window: model.BoundWindow, runtime_setup: list[runtime.StepRecord]
) -> None:
    window.press("h u n t e r 2", secret=True)
    window.type("hunter2", secret=True)
    assert [r.args for r in runtime_setup] == [{"keys": "***"}, {"text": "***"}]
    world.accepts_foreground = False
    world.foreground = 999
    with pytest.raises(ActionError, match="Sensitive action failed"):
        window.type("hunter2", secret=True)
    assert runtime_setup[-1].args == {"text": "***"}
    assert "hunter2" not in str(runtime_setup[-1].error)


def test_send_keys_accepts_a_window_target(world: World, window: model.BoundWindow) -> None:
    finders.send_keys(window, "[Tab]")
    assert world.log[0] == ("bring", HWND)
    assert world.events == [(0x09, False), (0x09, True)]


# -- wintestkit.keyboard --------------------------------------------------------------------------


def test_keyboard_refuses_without_an_application(world: World) -> None:
    with pytest.raises(ActionError, match="no application under test"):
        keyboard.press("Tab")
    assert world.log == []


def test_keyboard_sends_to_the_foreground_window_of_the_app_without_activating(
    world: World, runtime_setup: list[runtime.StepRecord]
) -> None:
    runtime.set_current_app(FakeApp([]))  # type: ignore[arg-type]
    world.foreground = HWND
    keyboard.press("Ctrl+S")
    keyboard.type("abc")
    assert world.log == [("press", "Ctrl+S"), ("type", "abc")]
    assert [(r.action, r.target, r.args) for r in runtime_setup] == [
        ("press", "keyboard", {"keys": "Ctrl+S"}),
        ("type", "keyboard", {"text": "abc"}),
    ]


def test_keyboard_refuses_when_another_process_is_in_front(
    world: World, monkeypatch: pytest.MonkeyPatch, runtime_setup: list[runtime.StepRecord]
) -> None:
    runtime.set_current_app(FakeApp([]))  # type: ignore[arg-type]
    monkeypatch.setattr(win32, "window_pid", lambda hwnd: 2)
    world.foreground = HWND
    with pytest.raises(ActionError, match=r"does not belong to DemoApp.exe"):
        keyboard.press("Tab")
    with pytest.raises(ActionError, match=r"does not belong to DemoApp.exe"):
        keyboard.type("abc")
    assert world.log == []
    assert world.events == []
    assert [r.status for r in runtime_setup] == ["failed", "failed"]


def test_keyboard_secret_is_redacted(world: World, runtime_setup: list[runtime.StepRecord]) -> None:
    runtime.set_current_app(FakeApp([]))  # type: ignore[arg-type]
    world.foreground = HWND
    keyboard.type("hunter2", secret=True)
    assert runtime_setup[0].args == {"text": "***"}


def test_hold_presses_and_always_releases_modifiers(world: World) -> None:
    runtime.set_current_app(FakeApp([]))  # type: ignore[arg-type]
    world.foreground = HWND
    with keyboard.hold("Ctrl+Shift"):
        assert world.events == [(0x11, False), (0x10, False)]
    assert world.events[2:] == [(0x10, True), (0x11, True)]


def test_hold_releases_when_the_block_raises(
    world: World, runtime_setup: list[runtime.StepRecord]
) -> None:
    runtime.set_current_app(FakeApp([]))  # type: ignore[arg-type]
    world.foreground = HWND
    with pytest.raises(RuntimeError, match="boom"), keyboard.hold("Alt"):
        raise RuntimeError("boom")
    assert world.events == [(0x12, False), (0x12, True)]
    assert runtime_setup[-1].action == "hold"
    assert runtime_setup[-1].args == {"modifiers": "Alt"}


def test_hold_refuses_foreign_foreground_and_bad_modifiers(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime.set_current_app(FakeApp([]))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="at least one modifier"), keyboard.hold(""):
        pass
    with pytest.raises(ValueError, match="unknown modifier"), keyboard.hold("Hyper"):
        pass
    monkeypatch.setattr(win32, "window_pid", lambda hwnd: 2)
    world.foreground = HWND
    with pytest.raises(ActionError, match="does not belong"), keyboard.hold("Ctrl"):
        pass
    assert world.events == []


# -- geometry -------------------------------------------------------------------------------------


def test_move_and_resize_use_the_transform_pattern(
    world: World, window: model.BoundWindow, runtime_setup: list[runtime.StepRecord]
) -> None:
    window.move(10, 20)
    window.resize(640, 480)
    assert world.log == [("tmove", 10, 20), ("tresize", 640, 480)]
    assert [(r.action, r.args) for r in runtime_setup] == [
        ("window.move", {"x": 10, "y": 20}),
        ("window.resize", {"width": 640, "height": 480}),
    ]


def test_move_and_resize_fall_back_to_set_window_pos(
    world: World, window: model.BoundWindow
) -> None:
    world.can_move = world.can_resize = False
    window.move(10, 20)
    window.resize(640, 480)
    assert world.log == [
        ("setpos", HWND, {"x": 10, "y": 20}),
        ("setpos", HWND, {"width": 640, "height": 480}),
    ]


def test_geometry_failure_when_windows_rejects_the_change(
    world: World, window: model.BoundWindow
) -> None:
    world.can_move = world.can_resize = False
    world.window_pos_ok = False
    with pytest.raises(ActionError, match="cannot be moved"):
        window.move(1, 2)
    with pytest.raises(ActionError, match="cannot be resized"):
        window.resize(10, 10)


@pytest.mark.parametrize("state", ["maximized", "minimized"])
def test_move_and_resize_refuse_a_maximized_or_minimized_window(
    world: World, window: model.BoundWindow, state: str
) -> None:
    world.state = state
    with pytest.raises(ActionError, match=f"{state} window; call restore"):
        window.move(1, 2)
    with pytest.raises(ActionError, match=f"{state} window; call restore"):
        window.resize(100, 100)
    assert world.log == []


def test_resize_rejects_a_non_positive_size(window: model.BoundWindow) -> None:
    with pytest.raises(ValueError, match="positive"):
        window.resize(0, 100)


def test_rect_reads_the_current_bounds(world: World, window: model.BoundWindow) -> None:
    world.dialog.rect = Rect(5, 6, 700, 500)
    assert window.rect == Rect(5, 6, 700, 500)
    world.dialog.rect = None
    with pytest.raises(ActionError, match="no on-screen rectangle"):
        window.rect  # noqa: B018


def test_activate_and_is_active(
    world: World, window: model.BoundWindow, runtime_setup: list[runtime.StepRecord]
) -> None:
    assert window.is_active() is False
    window.activate()
    assert window.is_active() is True
    assert world.log == [("bring", HWND)]
    assert runtime_setup[-1].action == "window.activate"
    window.activate()  # already in front: nothing more to do
    assert world.log == [("bring", HWND)]


def test_is_active_counts_an_owned_dialog_in_front(
    world: World, window: model.BoundWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.foreground = 555
    monkeypatch.setattr(win32, "window_owner", lambda hwnd: HWND if hwnd == 555 else 0)
    assert window.is_active() is True


def test_activate_fails_when_windows_refuses(world: World, window: model.BoundWindow) -> None:
    world.accepts_foreground = False
    with pytest.raises(ActionError, match="refused to bring"):
        window.activate()
