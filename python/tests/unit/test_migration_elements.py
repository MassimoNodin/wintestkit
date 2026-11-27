"""Migrated element operations: positioned clicks, drag, wheel, size, activate, close, refresh."""

from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeApp, FakeElement

from wintestkit import model, runtime
from wintestkit.config import load_config
from wintestkit.engine import actions, waits
from wintestkit.errors import ActionError, ElementNotFoundError
from wintestkit.model import Element, Page, Window
from wintestkit.uia.element import Rect

SHIFT, CTRL = 0x10, 0x11


class OrdersPage(Page):
    window = Window(title="Orders")
    grid = Element(automation_id="OrderGrid")
    save = Element(automation_id="Save")


@pytest.fixture(autouse=True)
def steps(tmp_path: Path) -> Generator[list[runtime.StepRecord]]:
    runtime.reset()
    runtime.set_config(load_config(tmp_path, {"timeout": 1.0}))
    records: list[runtime.StepRecord] = []
    runtime.add_step_listener(records.append)
    yield records
    runtime.reset()


@pytest.fixture
def grid(monkeypatch: pytest.MonkeyPatch) -> FakeElement:
    element = FakeElement(
        "DataGrid", "Orders", automation_id="OrderGrid", rect=Rect(10, 20, 800, 100)
    )
    monkeypatch.setattr(model, "resolve", lambda scope, locator: element)
    return element


@pytest.fixture
def page() -> OrdersPage:
    return OrdersPage(FakeApp([FakeElement("Window", "Orders")]))  # type: ignore[arg-type]


def record_calls(monkeypatch: pytest.MonkeyPatch, *names: str) -> list[tuple[str, Any, Any]]:
    calls: list[tuple[str, Any, Any]] = []
    for name in names:
        monkeypatch.setattr(
            actions,
            name,
            lambda el, *args, _name=name, **kwargs: calls.append((_name, args, kwargs)) or "mouse",
        )
    return calls


def test_the_size_of_an_element_is_its_current_rectangle(
    page: OrdersPage, grid: FakeElement
) -> None:
    assert page.grid.width == 800
    assert page.grid.height == 100
    assert page.grid.rect == Rect(10, 20, 800, 100)
    grid.rect = Rect(0, 0, 640.4, 99.6)
    assert (page.grid.width, page.grid.height) == (640, 100)


def test_an_element_without_a_rectangle_has_no_size(page: OrdersPage, grid: FakeElement) -> None:
    grid.rect = None
    with pytest.raises(ActionError, match="no on-screen rectangle"):
        _ = page.grid.width


def test_click_at_the_centre_with_shift(
    page: OrdersPage, grid: FakeElement, monkeypatch: pytest.MonkeyPatch, steps: list[Any]
) -> None:
    calls = record_calls(monkeypatch, "click")
    page.grid.click(x=-1, y=-1, modifiers="Shift")
    assert calls == [
        (
            "click",
            (),
            {"mode": "mouse", "button": "left", "offset": (-1, -1), "modifiers": (SHIFT,)},
        )
    ]
    assert steps[0].args["modifiers"] == "Shift" and (steps[0].args["x"], steps[0].args["y"]) == (
        -1,
        -1,
    )


def test_click_at_a_position_computed_from_the_width(
    page: OrdersPage, grid: FakeElement, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = record_calls(monkeypatch, "click")
    page.grid.click(x=page.grid.width - 320, y=40)
    assert calls[0][2]["offset"] == (480, 40)


def test_click_on_one_axis_at_the_centre(
    page: OrdersPage, grid: FakeElement, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = record_calls(monkeypatch, "click")
    page.grid.click(x=-1, y=5)
    assert calls[0][2]["offset"] == (-1, 5)


def test_double_click_and_right_click_take_positions_and_modifiers(
    page: OrdersPage, grid: FakeElement, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = record_calls(monkeypatch, "double_click", "right_click")
    page.grid.double_click(x=-1, y=-1, modifiers="Ctrl")
    page.grid.right_click(x=30, y=-1)
    assert calls == [
        ("double_click", (), {"offset": (-1, -1), "modifiers": (CTRL,)}),
        ("right_click", (), {"offset": (30, -1), "modifiers": ()}),
    ]


def test_drag_from_a_point_by_a_delta_holding_shift(
    page: OrdersPage, grid: FakeElement, monkeypatch: pytest.MonkeyPatch, steps: list[Any]
) -> None:
    calls = record_calls(monkeypatch, "drag_by")
    page.grid.drag(-1, 40, -30, 15, modifiers="Shift")
    assert calls == [
        (
            "drag_by",
            (-30, 15),
            {"source_offset": (-1, 40), "button": "left", "modifiers": (SHIFT,)},
        )
    ]
    assert steps[0].action == "drag_by"
    assert steps[0].args == {"dx": -30, "dy": 15, "modifiers": "Shift", "source_offset": [-1, 40]}


def test_drag_validates_its_modifiers_before_any_step(
    page: OrdersPage, grid: FakeElement, steps: list[Any]
) -> None:
    with pytest.raises(ActionError, match="unknown modifier"):
        page.grid.drag(1, 1, 5, 5, modifiers="Hyper")
    assert steps == []


def test_mouse_wheel_is_scroll(
    page: OrdersPage, grid: FakeElement, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = record_calls(monkeypatch, "scroll")
    page.grid.scroll(-3)
    page.grid.scroll(5, x=-1, y=-1)
    assert calls == [
        ("scroll", (-3,), {"offset": None, "horizontal": False}),
        ("scroll", (5,), {"offset": (-1, -1), "horizontal": False}),
    ]


def test_activate_and_close_act_on_the_window_of_the_element(
    page: OrdersPage, grid: FakeElement, monkeypatch: pytest.MonkeyPatch, steps: list[Any]
) -> None:
    seen: list[tuple[str, Any]] = []
    monkeypatch.setattr(actions, "activate_window", lambda el: seen.append(("activate", el)))
    monkeypatch.setattr(actions, "close_window_of", lambda el: seen.append(("close", el)))
    page.grid.activate()
    page.grid.close()
    assert seen == [("activate", grid), ("close", grid)]
    assert [step.action for step in steps] == ["activate", "close"]


def test_closing_posts_the_close_request_to_the_window_of_the_element(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from wintestkit.uia import win32

    element = FakeElement("Button", "Save")
    posted: list[tuple[int, int]] = []
    monkeypatch.setattr(actions, "_window_target", lambda el: (77, element.process_id))
    monkeypatch.setattr(win32, "IsWindow", lambda hwnd: True)
    monkeypatch.setattr(win32, "window_pid", lambda hwnd: element.process_id)
    monkeypatch.setattr(
        win32, "PostMessageW", lambda hwnd, msg, wparam, lparam: posted.append((hwnd, msg)) or True
    )
    actions.close_window_of(element)
    assert posted == [(77, win32.WM_CLOSE)]
    monkeypatch.setattr(win32, "window_pid", lambda hwnd: 999)
    with pytest.raises(ActionError, match="no longer available"):
        actions.close_window_of(element)
    assert len(posted) == 1  # a window of another process is never closed


def test_refresh_looks_the_element_up_again_and_returns_it(
    page: OrdersPage, grid: FakeElement, monkeypatch: pytest.MonkeyPatch
) -> None:
    looked_up: list[Any] = []
    monkeypatch.setattr(model, "resolve", lambda scope, locator: looked_up.append(locator) or grid)
    bound = page.grid
    assert bound.refresh() is bound
    assert page.window.refresh() is not None
    assert len(looked_up) == 1


def test_refresh_of_a_missing_element_fails_like_any_lookup(
    page: OrdersPage, monkeypatch: pytest.MonkeyPatch
) -> None:
    from wintestkit.engine.diagnose import Diagnostic

    def missing(scope: Any, locator: Any) -> None:
        raise ElementNotFoundError(
            Diagnostic(
                kind="not_found",
                message="No element matches",
                locator="x",
                searched_in="Window",
                match_count=0,
            )
        )

    monkeypatch.setattr(model, "resolve", missing)
    monkeypatch.setattr(waits, "_clock", lambda: 0.0)
    monkeypatch.setattr(waits, "_sleep", lambda seconds: None)
    with pytest.raises(ElementNotFoundError):
        page.save.refresh(timeout=0)
