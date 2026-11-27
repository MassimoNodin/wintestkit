"""Managed reads and locators on WinForms controls, live: a pure WinForms fixture and a WPF-hosted control.

Run with WTK_INSPECTOR_REAL=1 on a desktop session after `scripts/publish_fixtures.ps1`. It launches the
owned fixtures itself and reads the native members of a custom control (an int property, a nested
object with a string property, a list read by position), matches controls by managed keys in a
locator, and checks that a password box is never exposed. Written for a live run; the logic it
checks is covered without a desktop by test_winforms_managed.py and the agent unit tests.
"""

import os
import re
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from live_dotnet import live_dotnet_root
from test_inspector_owned_integration import PAYLOAD

from wintestkit import finders, runtime
from wintestkit.app import App
from wintestkit.config import load_config
from wintestkit.engine.locator import Locator, WindowLocator
from wintestkit.engine.property_read import read_property
from wintestkit.engine.resolve import Scope, resolve, resolve_all
from wintestkit.errors import ActionError, InspectorUnavailableError
from wintestkit.inspector.probe import identify
from wintestkit.uia import win32

ROOT = Path(__file__).resolve().parents[3]
WINFORMS = ROOT / "wpf-inspector/tests/Fixtures/WinFormsFixture/bin/cells/net10.0-windows-x64"
WPF = ROOT / "wpf-inspector/tests/Fixtures/WpfFixture/bin/cells/net10.0-windows-x64"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.name != "nt" or os.environ.get("WTK_INSPECTOR_REAL") != "1",
        reason="requires explicitly enabled owned Windows fixture",
    ),
]


def launch(folder: Path, executable: str, *arguments: str) -> Iterator[App]:
    path = folder / executable
    if not path.exists():
        pytest.skip("publish the fixtures first")
    environment = os.environ.copy()
    environment["DOTNET_ROOT_X64"] = live_dotnet_root()
    environment["DOTNET_MULTILEVEL_LOOKUP"] = "0"
    target = subprocess.Popen(
        [str(path), *arguments],
        cwd=folder,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        until = time.monotonic() + 30
        while True:
            assert target.poll() is None
            try:
                identify(target.pid)
                if win32.top_level_windows({target.pid}):
                    break
            except (OSError, InspectorUnavailableError):
                pass
            assert time.monotonic() < until, "owned fixture did not become ready"
            time.sleep(0.1)
        yield App.attach(pid=target.pid)
    finally:
        runtime.reset()
        if target.poll() is None:
            target.terminate()
        target.wait(timeout=5)


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    runtime.reset()
    monkeypatch.syspath_prepend(str(PAYLOAD))
    cfg = load_config(
        tmp_path,
        {"backend": "auto", "inspector.enabled": True, "inspector.attach": "on-demand"},
    )
    with runtime.config_scope(cfg):
        yield
    runtime.reset()


@pytest.fixture
def winforms(config: None) -> Iterator[App]:
    yield from launch(WINFORMS, "WinTestKit.WinFormsFixture.exe")


@pytest.fixture
def hosted(config: None) -> Iterator[App]:
    yield from launch(WPF, "WinTestKit.Fixture.exe", "--scenario", "openHostedWinForms")


def hosted_window(app: App) -> Scope:
    until = time.monotonic() + 15
    while not any(w.automation_id == "HostedWinFormsWindow" for w in app.top_level_windows()):
        assert time.monotonic() < until, "the hosted WinForms window did not open"
        time.sleep(0.1)
    return Scope(app, WindowLocator(automation_id="HostedWinFormsWindow"))


# -- a pure WinForms process ------------------------------------------------------------------------


def test_get_reads_the_native_members_of_a_winforms_control(winforms: App) -> None:
    chart = finders.find_child(winforms, "WinFormsControlName", "seriesChart1", depth=None)
    assert chart.get("clr:SeriesCount") == 3
    assert chart.get("clr:Footer.Text") == "Page 1 of 2"
    assert chart.get("clr:Footer.Pages") == 2
    assert chart.get("clr:SeriesTitles[1]") == "Beta"
    assert chart.get("type:Name") == "SeriesChartControl"
    assert chart.get("type:FullName") == "WinTestKit.WinFormsFixture.SeriesChartControl"
    # The agent was attached on demand, only because a managed key was read.
    assert runtime.inspector_attached_processes()


def test_where_matches_winforms_controls_by_managed_keys(winforms: App) -> None:
    scope = Scope(winforms)
    by_value = resolve(
        scope, Locator(where=(("type:Name", "SeriesChartControl"), ("clr:SeriesCount", 3)))
    )
    assert by_value.automation_id == "seriesChart1"
    nested = resolve(scope, Locator(where=(("clr:Footer.Text", re.compile("^Page 1 of")),)))
    assert nested.automation_id == "seriesChart1"
    assert resolve_all(scope, Locator(where=(("clr:SeriesCount", 99),))) == []
    named = resolve(scope, Locator(where=(("type:Name", "Button"), ("clr:Name", "button2"))))
    assert named.name == "Cancel"


def test_migrated_finder_names_map_to_the_control(winforms: App) -> None:
    chart = finders.find_child(
        winforms,
        ["WinFormsControlName", "ClrClassName", "SeriesCount"],
        ["seriesChart1", "SeriesChartControl", "3"],
        depth=None,
    )
    assert chart.get("clr:Footer.Text") == "Page 1 of 2"
    full = finders.find_child(
        winforms, "ClrFullClassName", "WinTestKit.WinFormsFixture.SeriesChartControl", depth=None
    )
    assert full.get("clr:SeriesCount") == 3


def test_a_password_box_is_never_exposed(winforms: App) -> None:
    box = finders.find_child(winforms, "WinFormsControlName", "passwordBox", depth=None)
    with pytest.raises(ActionError, match="redacted"):
        box.get("clr:Text")
    assert resolve_all(Scope(winforms), Locator(where=(("clr:Text", "hunter2"),))) == []


def test_a_plain_lookup_does_not_attach_the_agent(winforms: App) -> None:
    button = finders.find_child(winforms, "WinFormsControlName", "button1", depth=None)
    assert button.get("name") == "OK"
    assert not runtime.inspector_attached_processes()


# -- a WinForms control hosted in a WPF window --------------------------------------------------------


def test_a_hosted_control_is_read_and_found_by_managed_keys(hosted: App) -> None:
    scope = hosted_window(hosted)
    chart = finders.find_child(scope, "ClrClassName", "HostedSeriesChart", depth=None)
    assert chart.get("clr:SeriesCount") == 7
    assert chart.get("clr:Footer.Text") == "Page 1 of 2"
    by_value = resolve(scope, Locator(where=(("clr:SeriesCount", 7),)))
    assert by_value.get("type:Name") == "HostedSeriesChart"
    by_name = finders.find_child(scope, "WinFormsControlName", "hostedSeriesChart", depth=None)
    assert by_name.get("type:Name") == "HostedSeriesChart"


def test_a_hosted_control_found_by_uia_reads_like_any_winforms_control(hosted: App) -> None:
    scope = hosted_window(hosted)
    window = scope.app.top_level_windows()[0]
    hosted_control = next(
        element
        for element in _walk(window)
        if element.class_name.startswith("WindowsForms") and element.automation_id
    )
    assert read_property(hosted_control, "clr:SeriesCount") == 7


def _walk(element: Any) -> Iterator[Any]:
    for child in element.children():
        yield child
        yield from _walk(child)
