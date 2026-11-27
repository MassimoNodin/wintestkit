"""Slider, scroll bar, progress bar, date picker, expander, toggle button, hyperlink, tool bar and
status bar: validation, the pattern and mouse paths, and the errors."""

import datetime
import re
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeApp, FakeElement

from wintestkit import model, runtime
from wintestkit.config import load_config
from wintestkit.controls import (
    DatePicker,
    Expander,
    Hyperlink,
    ProgressBar,
    ScrollBar,
    Slider,
    StatusBar,
    ToggleButton,
    ToolBar,
)
from wintestkit.engine import actions, dates, waits, widgets
from wintestkit.errors import ActionError, ElementTypeError
from wintestkit.model import Page, Window
from wintestkit.uia import patterns


class Widgets(Page):
    window = Window(title="Demo")

    volume = Slider(automation_id="Volume")
    scroll = ScrollBar(automation_id="Scroll")
    progress = ProgressBar(automation_id="Progress")
    start = DatePicker(automation_id="Start")
    details = Expander(automation_id="Details")
    bold = ToggleButton(automation_id="Bold")
    link = Hyperlink(automation_id="Link")
    tools = ToolBar(automation_id="Tools")
    status = StatusBar(automation_id="Status")


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture(autouse=True)
def runtime_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    runtime.reset()
    runtime.set_config(load_config(tmp_path, {"timeout": 10.0}))
    fake = FakeTime()
    monkeypatch.setattr(waits, "_clock", fake.clock)
    monkeypatch.setattr(waits, "_sleep", fake.sleep)
    yield
    runtime.reset()


class World:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.element = FakeElement("Slider", "thing", class_name="Slider")
        self.supported: set[str] = set()
        monkeypatch.setattr(model, "resolve", lambda scope, locator: self.element)
        monkeypatch.setattr(patterns, "has_pattern", lambda el, name: name in self.supported)


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> World:
    return World(monkeypatch)


@pytest.fixture
def page() -> Widgets:
    return Widgets(FakeApp([FakeElement("Window", "Demo")]))  # type: ignore[arg-type]


def set_mode(tmp_path: Path, mode: str) -> None:
    runtime.set_config(load_config(tmp_path, {"timeout": 10.0, "input_mode": mode}))


# -- validation -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "attribute,control_type,class_name",
    [
        ("volume", "Slider", "Slider"),
        ("scroll", "ScrollBar", "ScrollBar"),
        ("progress", "ProgressBar", "ProgressBar"),
        ("start", "Custom", "DatePicker"),
        ("details", "Group", "Expander"),
        ("link", "Hyperlink", "Hyperlink"),
        ("tools", "ToolBar", "ToolBar"),
        ("status", "StatusBar", "StatusBar"),
    ],
)
def test_matching_type_passes_and_other_types_fail(
    page: Widgets, world: World, attribute: str, control_type: str, class_name: str
) -> None:
    world.element = FakeElement(control_type, "x", class_name=class_name)
    assert getattr(page, attribute).resolve() is world.element
    world.element = FakeElement("Text", "x", class_name="TextBlock")
    with pytest.raises(ElementTypeError):
        getattr(page, attribute).resolve()


def test_date_picker_is_recognised_by_class_not_control_type(page: Widgets, world: World) -> None:
    world.element = FakeElement("Group", "x", class_name="MyDatePicker")
    assert page.start.resolve() is world.element
    world.element = FakeElement("Custom", "x", class_name="Calendar")
    with pytest.raises(ElementTypeError, match="not a DatePicker"):
        page.start.resolve()


def test_a_group_is_an_expander_only_by_class(page: Widgets, world: World) -> None:
    world.element = FakeElement("Group", "x", class_name="GroupBox")
    with pytest.raises(ElementTypeError, match="not a Group of class Expander"):
        page.details.resolve()
    world.element = FakeElement("Button", "x", class_name="Expander")
    with pytest.raises(ElementTypeError):
        page.details.resolve()


def test_toggle_button_needs_the_toggle_pattern_and_a_button_still_accepts_it(
    page: Widgets, world: World
) -> None:
    world.element = FakeElement("Button", "b", class_name="ToggleButton")
    world.supported = {"Toggle"}
    assert page.bold.resolve() is world.element
    world.supported = {"Invoke"}
    with pytest.raises(ElementTypeError, match="Toggle pattern"):
        page.bold.resolve()
    # A plain Button declaration keeps accepting toggle buttons.
    world.supported = {"Toggle"}

    from wintestkit.controls import Button

    class Declared(Page):
        window = Window(title="Demo")
        b = Button(automation_id="B")

    assert Declared(FakeApp([FakeElement("Window", "Demo")])).b.resolve() is world.element  # type: ignore[arg-type]


# -- range controls -------------------------------------------------------------------------------


class RangeWorld:
    """A slider whose value the fake keys move by a small or large change."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, value: float = 20.0) -> None:
        self.value = value
        self.minimum, self.maximum, self.small, self.large = 0.0, 100.0, 1.0, 10.0
        self.read_only = False
        self.reversed = False
        self.keys: list[str] = []
        self.clicked: list[Any] = []
        self.set: list[float] = []
        monkeypatch.setattr(patterns, "range_info", self._info)
        monkeypatch.setattr(patterns, "set_range_value", self._set)
        monkeypatch.setattr(actions, "press", self._press)
        monkeypatch.setattr(actions, "_mouse_click", lambda el, *a, **k: self.clicked.append(el))

    def _info(self, el: Any) -> patterns.RangeInfo:
        return patterns.RangeInfo(
            self.value, self.minimum, self.maximum, self.small, self.large, self.read_only
        )

    def _set(self, el: Any, value: float) -> None:
        self.set.append(value)
        self.value = value

    def _press(self, el: Any, keys: str) -> None:
        for key in keys.split():
            self.keys.append(key)
            sign = -1 if self.reversed else 1
            delta = {
                "Right": self.small,
                "Left": -self.small,
                "PageUp": self.large,
                "PageDown": -self.large,
            }.get(key)
            if key == "Home":
                self.value = self.minimum
            elif key == "End":
                self.value = self.maximum
            elif delta is not None:
                self.value = min(self.maximum, max(self.minimum, self.value + sign * delta))


@pytest.fixture
def slider(monkeypatch: pytest.MonkeyPatch, world: World) -> RangeWorld:
    world.element = FakeElement("Slider", "v", class_name="Slider")
    world.element.children_list.append(FakeElement("Thumb", "thumb"))
    return RangeWorld(monkeypatch)


def test_range_reads(page: Widgets, slider: RangeWorld) -> None:
    assert (page.volume.value, page.volume.minimum, page.volume.maximum) == (20, 0, 100)


def test_slider_pattern_sets_the_value(page: Widgets, slider: RangeWorld, tmp_path: Path) -> None:
    set_mode(tmp_path, "pattern")
    page.volume.set_value(65)
    assert slider.set == [65]
    assert slider.keys == [] and slider.clicked == []


def test_slider_mouse_clicks_the_thumb_and_uses_keys(
    page: Widgets, slider: RangeWorld, tmp_path: Path
) -> None:
    set_mode(tmp_path, "mouse")
    page.volume.set_value(35)
    assert slider.set == []
    assert [e.control_type for e in slider.clicked] == ["Thumb"]
    assert slider.value == 35
    assert slider.keys == ["PageUp"] + ["Right"] * 5


def test_slider_mouse_goes_down_and_handles_a_fractional_change(
    page: Widgets, slider: RangeWorld, tmp_path: Path
) -> None:
    set_mode(tmp_path, "mouse")
    page.volume.set_value(12.0)
    assert slider.value == 12
    assert slider.keys == ["Left"] * 8


def test_slider_mouse_uses_home_and_end(page: Widgets, slider: RangeWorld, tmp_path: Path) -> None:
    set_mode(tmp_path, "mouse")
    page.volume.set_value(100)
    assert slider.keys == ["End"]
    page.volume.set_value(0, mode="mouse")
    assert slider.keys == ["End", "Home"]


def test_slider_mouse_copes_with_a_reversed_direction(
    page: Widgets, slider: RangeWorld, tmp_path: Path
) -> None:
    set_mode(tmp_path, "mouse")
    slider.reversed = True
    page.volume.set_value(25)
    assert slider.value == 25


def test_slider_mouse_errors_when_it_cannot_move(
    page: Widgets, slider: RangeWorld, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_mode(tmp_path, "mouse")
    monkeypatch.setattr(actions, "press", lambda el, keys: None)
    with pytest.raises(ActionError, match="did not move"):
        page.volume.set_value(50)


def test_slider_mouse_needs_a_thumb(
    page: Widgets, slider: RangeWorld, world: World, tmp_path: Path
) -> None:
    set_mode(tmp_path, "mouse")
    world.element = FakeElement("Slider", "v", class_name="Slider")
    with pytest.raises(ActionError, match="no thumb"):
        page.volume.set_value(50)


@pytest.mark.parametrize("mode", ["pattern", "mouse"])
def test_slider_rejects_out_of_range_and_read_only(
    page: Widgets, slider: RangeWorld, tmp_path: Path, mode: str
) -> None:
    set_mode(tmp_path, mode)
    with pytest.raises(ActionError, match="outside the range 0 to 100"):
        page.volume.set_value(101)
    slider.read_only = True
    with pytest.raises(ActionError, match="read-only"):
        page.volume.set_value(5)
    assert slider.set == [] and slider.keys == []


def test_slider_pattern_reports_a_value_that_did_not_stick(
    page: Widgets, slider: RangeWorld, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_mode(tmp_path, "pattern")
    monkeypatch.setattr(patterns, "set_range_value", lambda el, value: None)
    with pytest.raises(ActionError, match="is at 20, not 65"):
        page.volume.set_value(65)


def test_slider_steps_press_arrows(page: Widgets, slider: RangeWorld) -> None:
    page.volume.increase(3)
    page.volume.decrease()
    assert slider.keys == ["Right"] * 3 + ["Left"]
    with pytest.raises(ValueError, match="at least 1"):
        page.volume.increase(0)


def test_scroll_bar_pattern_and_mouse(
    page: Widgets, slider: RangeWorld, world: World, tmp_path: Path
) -> None:
    world.element = FakeElement("ScrollBar", "s", class_name="ScrollBar")
    set_mode(tmp_path, "pattern")
    page.scroll.set_value(40)
    assert slider.set == [40]
    set_mode(tmp_path, "mouse")
    with pytest.raises(ActionError, match="needs input_mode pattern or mode='pattern'"):
        page.scroll.set_value(60)
    page.scroll.set_value(60, mode="pattern")
    assert slider.set == [40, 60]
    assert slider.clicked == [] and slider.keys == []


def test_progress_bar_is_read_only(page: Widgets, slider: RangeWorld, world: World) -> None:
    world.element = FakeElement("ProgressBar", "p", class_name="ProgressBar")
    assert page.progress.value == 20
    assert not hasattr(page.progress, "set_value")


def test_wpf_slider_pattern_uses_the_agent_verb(monkeypatch: pytest.MonkeyPatch) -> None:
    from wintestkit.backends import WpfElement
    from wintestkit.inspector.models import ObjectRef, TypeInfo

    sent: list[tuple[Any, ...]] = []

    class Client:
        def release(self, *args: Any, **kwargs: Any) -> None:
            pass

    client = Client()
    ref = ObjectRef("s", "o", 1, TypeInfo("T", "T", "A", "T, A", ()), "d")
    el = WpfElement(client, ref, 1)  # type: ignore[arg-type]
    state = {"value": 20.0}

    def info(_: Any) -> patterns.RangeInfo:
        return patterns.RangeInfo(state["value"], 0, 100, 1, 10, False)

    monkeypatch.setattr(patterns, "range_info", info)
    monkeypatch.setattr(el, "as_uia", lambda: pytest.fail("no UIA mapping expected"))

    def fake_act(target: Any, verb: str, pattern: Any = None, value: Any = None) -> None:
        sent.append((verb, pattern, value))
        state["value"] = value

    monkeypatch.setattr(actions, "_wpf_act", fake_act)
    widgets.set_range_by_pattern(el, 55)
    assert sent == [("set_range", "RangeValue", 55)]


# -- dates ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pattern,text",
    [
        ("d/M/yyyy", "9/3/2026"),
        ("dd/MM/yyyy", "09/03/2026"),
        ("M/d/yyyy", "3/9/2026"),
        ("yyyy-MM-dd", "2026-03-09"),
        ("dd.MM.yy", "09.03.26"),
    ],
)
def test_dates_round_trip_in_every_order(pattern: str, text: str) -> None:
    day = datetime.date(2026, 3, 9)
    assert dates.format_date(day, pattern) == text
    assert dates.parse_date(text, pattern) == day


def test_dates_parse_iso_first_and_report_junk() -> None:
    assert dates.parse_date("2026-03-09", "dd/MM/yyyy") == datetime.date(2026, 3, 9)
    assert dates.parse_date("  ", "dd/MM/yyyy") is None
    with pytest.raises(ActionError, match="Cannot read 'soon'"):
        dates.parse_date("soon", "dd/MM/yyyy")
    with pytest.raises(ActionError, match="Cannot read '31/02/2026'"):
        dates.parse_date("31/02/2026", "dd/MM/yyyy")
    with pytest.raises(ActionError, match="uses names"):
        dates.format_date(datetime.date(2026, 3, 9), "dddd d MMMM yyyy")


def test_the_system_short_date_format_is_a_pattern() -> None:
    pattern = dates.system_short_date_format()
    assert datetime.date(2026, 3, 9) == dates.parse_date(
        dates.format_date(datetime.date(2026, 3, 9), pattern), pattern
    )


class DateWorld:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, world: World, text: str = "") -> None:
        self.text = text
        self.log: list[tuple[str, str]] = []
        self.commits_that_stick = {"Enter"}
        world.element = FakeElement("Custom", "d", class_name="DatePicker")
        self.edit = world.element.add(FakeElement("Edit", "text"))
        self.typed = ""
        monkeypatch.setattr(dates, "system_short_date_format", lambda: "dd/MM/yyyy")
        monkeypatch.setattr(actions, "get_value", lambda el: self.text)
        monkeypatch.setattr(actions, "type_text", self._type)
        monkeypatch.setattr(actions, "press", self._press)
        monkeypatch.setattr(
            actions, "_mouse_click", lambda el, *a, **k: self.log.append(("click", ""))
        )

    def _type(self, el: Any, text: str, **kwargs: Any) -> str:
        self.typed = text
        self.log.append(("type", f"{text}|{kwargs.get('keys', False)}"))
        return "keys"

    def _press(self, el: Any, keys: str) -> None:
        self.log.append(("press", keys))
        if keys in self.commits_that_stick:
            self.text = self.typed


def test_date_reads(page: Widgets, world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    DateWorld(monkeypatch, world, "15/01/2026")
    assert page.start.value == "15/01/2026"
    assert page.start.date == datetime.date(2026, 1, 15)


def test_empty_date_is_none(page: Widgets, world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    DateWorld(monkeypatch, world, "")
    assert page.start.date is None


def test_set_date_by_pattern_types_and_commits_with_enter(
    page: Widgets, world: World, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dw = DateWorld(monkeypatch, world, "15/01/2026")
    set_mode(tmp_path, "pattern")
    page.start.set_date(datetime.date(2026, 3, 9))
    assert dw.log == [("type", "09/03/2026|False"), ("press", "Enter")]
    assert page.start.date == datetime.date(2026, 3, 9)


def test_set_date_by_mouse_clicks_and_types_keys(
    page: Widgets, world: World, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dw = DateWorld(monkeypatch, world)
    set_mode(tmp_path, "mouse")
    page.start.set_date(datetime.date(2026, 3, 9))
    assert dw.log == [("click", ""), ("type", "09/03/2026|True"), ("press", "Enter")]


def test_set_date_falls_back_to_tab_and_reports_when_nothing_sticks(
    page: Widgets, world: World, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dw = DateWorld(monkeypatch, world, "15/01/2026")
    set_mode(tmp_path, "pattern")
    dw.commits_that_stick = {"Tab"}
    page.start.set_date(datetime.date(2026, 3, 9))
    assert [entry for entry in dw.log if entry[0] == "press"] == [
        ("press", "Enter"),
        ("press", "Tab"),
    ]
    dw.commits_that_stick = set()
    dw.text = "15/01/2026"
    with pytest.raises(ActionError, match="shows '15/01/2026' after typing '10/03/2026'"):
        page.start.set_date(datetime.date(2026, 3, 10))


def test_date_picker_without_a_text_box_errors(
    page: Widgets, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.element = FakeElement("Custom", "d", class_name="DatePicker")
    with pytest.raises(ActionError, match="no text box"):
        page.start.value  # noqa: B018


# -- expander -------------------------------------------------------------------------------------


class ExpanderWorld:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, world: World) -> None:
        self.expanded = False
        self.log: list[str] = []
        world.element = FakeElement("Group", "Details", class_name="Expander")
        world.element.add(FakeElement("Button", "Details", class_name="ToggleButton"))
        monkeypatch.setattr(actions, "is_expanded", lambda el: self.expanded)
        monkeypatch.setattr(actions, "expand", self._expand)
        monkeypatch.setattr(actions, "collapse", self._collapse)
        monkeypatch.setattr(actions, "_mouse_click", self._click)
        self.sticks = True

    def _expand(self, el: Any, *, mode: str = "pattern") -> None:
        self.log.append(f"expand:{mode}")
        self.expanded = True

    def _collapse(self, el: Any, *, mode: str = "pattern") -> None:
        self.log.append(f"collapse:{mode}")
        self.expanded = False

    def _click(self, el: Any, *a: Any, **k: Any) -> None:
        self.log.append(f"click:{el.control_type}")
        if self.sticks:
            self.expanded = not self.expanded


def test_expander_pattern(page: Widgets, world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    ew = ExpanderWorld(monkeypatch, world)
    page.details.expand(mode="pattern")
    assert page.details.is_expanded()
    page.details.collapse(mode="pattern")
    assert not page.details.is_expanded()
    assert ew.log == ["expand:pattern", "collapse:pattern"]


def test_expander_mouse_clicks_the_header_toggle_once(
    page: Widgets, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    ew = ExpanderWorld(monkeypatch, world)
    page.details.expand(mode="mouse")
    page.details.expand(mode="mouse")  # already expanded: no second click
    page.details.collapse(mode="mouse")
    assert ew.log == ["click:Button", "click:Button"]


def test_expander_mouse_reports_a_click_that_did_not_toggle(
    page: Widgets, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    ew = ExpanderWorld(monkeypatch, world)
    ew.sticks = False
    with pytest.raises(ActionError, match="to be expanded"):
        page.details.expand(mode="mouse")


def test_expander_mouse_needs_a_header_button(
    page: Widgets, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    ExpanderWorld(monkeypatch, world)
    world.element = FakeElement("Group", "Details", class_name="Expander")
    with pytest.raises(ActionError, match="no header button"):
        page.details.expand(mode="mouse")


# -- toggle button, hyperlink, tool bar and status bar --------------------------------------------


def test_toggle_button_checks_and_clicks(
    page: Widgets, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.element = FakeElement("Button", "Bold", class_name="ToggleButton")
    world.supported = {"Toggle"}
    log: list[str] = []
    monkeypatch.setattr(
        actions, "set_checked", lambda el, checked, **kwargs: log.append(f"set:{checked}")
    )
    monkeypatch.setattr(actions, "toggle", lambda el, **kwargs: log.append("toggle"))
    monkeypatch.setattr(actions, "is_checked", lambda el: True)
    monkeypatch.setattr(actions, "click", lambda el, **k: log.append("click") or "toggle")
    page.bold.check()
    page.bold.uncheck()
    page.bold.toggle()
    page.bold.click()
    assert page.bold.is_checked()
    assert log == ["set:True", "set:False", "toggle", "click"]


def test_hyperlink_clicks(page: Widgets, world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    world.element = FakeElement("Hyperlink", "Help", class_name="Hyperlink")
    log: list[Any] = []
    monkeypatch.setattr(actions, "click", lambda el, **k: log.append(k["mode"]) or "invoke")
    page.link.click(mode="mouse")
    assert log == ["mouse"]


def toolbar(world: World) -> FakeElement:
    world.element = FakeElement("ToolBar", "Tools", class_name="ToolBar")
    world.element.add(FakeElement("Button", "New", automation_id="ToolNew"))
    holder = world.element.add(FakeElement("Group", "overflow"))
    holder.add(FakeElement("Button", "Save", automation_id="ToolSave"))
    return world.element


def test_toolbar_clicks_a_button_by_name_id_or_regex(
    page: Widgets, world: World, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    toolbar(world)
    clicked: list[tuple[str, str]] = []
    monkeypatch.setattr(
        actions, "click", lambda el, *, mode, **k: clicked.append((el.name, mode)) or "invoke"
    )
    set_mode(tmp_path, "mouse")
    page.tools.click_button("New")
    page.tools.click_button("ToolSave", mode="pattern")
    page.tools.click_button(re.compile("^Sa"))
    assert clicked == [("New", "mouse"), ("Save", "pattern"), ("Save", "mouse")]


def test_toolbar_lists_its_buttons_when_one_is_missing(
    page: Widgets, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    toolbar(world)
    monkeypatch.setattr(actions, "click", lambda el, **k: pytest.fail("must not click"))
    with pytest.raises(ActionError, match=r"no button 'Open'; its buttons: 'New', 'Save'"):
        page.tools.click_button("Open")


def test_status_bar_lists_the_leaf_texts(page: Widgets, world: World) -> None:
    world.element = FakeElement("StatusBar", "Status", class_name="StatusBar")
    first = world.element.add(FakeElement("Text", "Status ready", class_name="StatusBarItem"))
    first.add(FakeElement("Text", "Status ready", class_name="TextBlock"))
    world.element.add(FakeElement("Text", "Line 3", class_name="StatusBarItem"))
    world.element.add(FakeElement("Text", "", class_name="StatusBarItem"))
    assert page.status.texts() == ["Status ready", "Line 3"]


def test_checkable_modes_follow_configuration_and_override(
    page: Widgets, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dataclasses

    world.element = FakeElement("Button", "Bold", class_name="ToggleButton")
    world.supported = {"Toggle"}
    runtime.set_config(dataclasses.replace(runtime.get_config(), input_mode="mouse"))
    modes: list[str] = []
    monkeypatch.setattr(actions, "set_checked", lambda el, checked, **kw: modes.append(kw["mode"]))
    monkeypatch.setattr(actions, "toggle", lambda el, **kw: modes.append(kw["mode"]))
    page.bold.check()
    page.bold.uncheck(mode="pattern")
    page.bold.toggle()
    page.bold.toggle(mode="pattern")
    assert modes == ["mouse", "pattern", "mouse", "pattern"]
