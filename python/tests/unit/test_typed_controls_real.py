"""Live tests for the slider, date picker, expander and other typed controls of the Controls window."""

import datetime
import os
from dataclasses import replace

import pytest
from test_wpf_query_gate_real import _fixture_scenario, config

from wintestkit import runtime
from wintestkit.controls import (
    DatePicker,
    Expander,
    Hyperlink,
    ProgressBar,
    ScrollBar,
    Slider,
    StatusBar,
    Text,
    ToggleButton,
    ToolBar,
)
from wintestkit.engine.resolve import Scope
from wintestkit.errors import ActionError
from wintestkit.expect import expect
from wintestkit.model import Page, Window

pytest_plugins = ["test_wpf_query_gate_real"]

pytestmark = pytest.mark.skipif(
    os.name != "nt" or os.environ.get("WTK_INSPECTOR_REAL") != "1",
    reason="requires explicitly enabled owned Windows fixture",
)

WidgetPage = type(
    "WidgetPage",
    (Page,),
    {
        "window": Window(automation_id="ControlsWindow"),
        "effect": Text(automation_id="ControlsEffect"),
        "volume": Slider(automation_id="VolumeSlider"),
        "start": DatePicker(automation_id="StartDate"),
        "progress": ProgressBar(automation_id="LoadProgress"),
        "details": Expander(automation_id="DetailsExpander"),
        "details_text": Text(automation_id="DetailsText"),
        "bold": ToggleButton(automation_id="BoldToggle"),
        "help": Hyperlink(automation_id="HelpLink"),
        "tools": ToolBar(automation_id="MainToolBar"),
        "status": StatusBar(automation_id="MainStatusBar"),
        "scroll": ScrollBar(automation_id="HScroll"),
    },
)


@pytest.fixture
def controls(owned):
    scope, path = owned
    assert isinstance(scope, Scope)
    _fixture_scenario(scope.app.pids[0], "openControls", 0)
    return WidgetPage(scope.app), path


def settings(path, backend, mode):
    return replace(config(path, "agent"), backend=backend, input_mode=mode)


MODES = pytest.mark.parametrize("mode", ["mouse", "pattern"])
BACKENDS = pytest.mark.parametrize("backend", ["auto", "uia"])


@MODES
@BACKENDS
def test_slider_set_value(controls, backend, mode):
    page, path = controls
    with runtime.config_scope(settings(path, backend, mode)):
        assert (page.volume.minimum, page.volume.maximum) == (0, 100)
        assert page.volume.value == 20
        page.volume.set_value(65)
        expect(page.effect, timeout=5).to_have_text("Volume 65")
        assert page.volume.value == 65
        page.volume.set_value(30)
        assert page.volume.value == 30
        with pytest.raises(ActionError, match="outside the range"):
            page.volume.set_value(101)


@BACKENDS
def test_slider_steps_by_keys(controls, backend):
    page, path = controls
    with runtime.config_scope(settings(path, backend, "pattern")):
        page.volume.set_value(50)
        before = page.volume.value
        page.volume.increase(3)
        assert page.volume.value > before
        page.volume.decrease(3)
        assert page.volume.value == pytest.approx(before)


@BACKENDS
def test_progress_bar_reads(controls, backend):
    page, path = controls
    with runtime.config_scope(settings(path, backend, "pattern")):
        assert (page.progress.value, page.progress.minimum, page.progress.maximum) == (40, 0, 100)


@BACKENDS
def test_scroll_bar_pattern_and_mouse(controls, backend):
    page, path = controls
    with runtime.config_scope(settings(path, backend, "pattern")):
        assert page.scroll.value == 10
        page.scroll.set_value(40)
        assert page.scroll.value == 40
        assert (page.scroll.minimum, page.scroll.maximum) == (0, 100)
    with runtime.config_scope(settings(path, backend, "mouse")):
        with pytest.raises(ActionError, match="needs input_mode pattern"):
            page.scroll.set_value(60)
        page.scroll.set_value(60, mode="pattern")
        assert page.scroll.value == 60


@MODES
@BACKENDS
def test_date_picker(controls, backend, mode):
    page, path = controls
    with runtime.config_scope(settings(path, backend, mode)):
        assert page.start.date == datetime.date(2026, 1, 15)
        assert page.start.value
        page.start.set_date(datetime.date(2026, 3, 9))
        expect(page.effect, timeout=5).to_have_text("Date 2026-03-09")
        assert page.start.date == datetime.date(2026, 3, 9)


@MODES
@BACKENDS
def test_expander(controls, backend, mode):
    page, path = controls
    with runtime.config_scope(settings(path, backend, mode)):
        assert not page.details.is_expanded()
        page.details.expand()
        assert page.details.is_expanded()
        expect(page.details_text, timeout=5).to_be_visible()
        page.details.collapse()
        assert not page.details.is_expanded()


@MODES
@BACKENDS
def test_toggle_button(controls, backend, mode):
    page, path = controls
    with runtime.config_scope(settings(path, backend, mode)):
        assert not page.bold.is_checked()
        page.bold.check()
        expect(page.effect, timeout=5).to_have_text("Bold on")
        assert page.bold.is_checked()
        page.bold.click()
        expect(page.effect, timeout=5).to_have_text("Bold off")
        page.bold.toggle()
        assert page.bold.is_checked()
        page.bold.uncheck()
        assert not page.bold.is_checked()


@MODES
@BACKENDS
def test_hyperlink_click(controls, backend, mode):
    page, path = controls
    with runtime.config_scope(settings(path, backend, mode)):
        if backend == "auto":
            # The agent has neither geometry nor an automation peer for a hyperlink.
            with pytest.raises(ActionError, match="cannot act on"):
                page.help.click()
            return
        page.help.click()
        expect(page.effect, timeout=5).to_have_text("Link clicked")


@MODES
@BACKENDS
def test_toolbar_and_status_bar(controls, backend, mode):
    page, path = controls
    with runtime.config_scope(settings(path, backend, mode)):
        page.tools.click_button("New")
        expect(page.effect, timeout=5).to_have_text("Tool new")
        with pytest.raises(ActionError, match="no button 'Missing'"):
            page.tools.click_button("Missing")
        assert page.status.texts() == ["Status ready"]
