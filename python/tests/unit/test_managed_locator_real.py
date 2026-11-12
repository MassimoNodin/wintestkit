"""S8 end-to-end queries instrument only the unchanged fixture launched here."""

import os
import re
import subprocess
import time

import pytest
from live_dotnet import live_dotnet_root
from test_inspector_owned_integration import FIXTURE, PAYLOAD, _control, _hashes
from test_managed_server_real import _fixture_counters

from wintestkit import runtime
from wintestkit.app import App
from wintestkit.config import load_config
from wintestkit.engine.locator import Locator, WindowLocator
from wintestkit.engine.resolve import Scope, resolve, resolve_window
from wintestkit.errors import InspectorReadError, InspectorUnavailableError
from wintestkit.inspector.probe import identify
from wintestkit.model import Page, Window
from wintestkit.uia import win32

pytestmark = pytest.mark.skipif(
    os.name != "nt" or os.environ.get("WTK_INSPECTOR_REAL") != "1",
    reason="requires explicitly enabled owned Windows fixture",
)


def test_owned_fixture_managed_locator(tmp_path, monkeypatch):
    runtime.reset()
    monkeypatch.syspath_prepend(str(PAYLOAD))
    cfg = load_config(
        tmp_path,
        {
            "backend": "auto",
            "inspector.enabled": True,
            "inspector.attach": "on-demand",
            "property_aliases": {"ClrFullClassName": "type:FullName"},
        },
    )
    before = _hashes()
    environment = os.environ.copy()
    environment["DOTNET_ROOT_X64"] = live_dotnet_root()
    environment["DOTNET_MULTILEVEL_LOOKUP"] = "0"
    target = subprocess.Popen(
        [str(FIXTURE / "WinTestKit.Fixture.exe"), "--scenario", "openSecondWindow"],
        cwd=FIXTURE,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        until = time.monotonic() + 15
        while True:
            assert target.poll() is None
            try:
                facts = identify(target.pid)
                if facts.wpf_loaded and win32.top_level_windows({target.pid}):
                    _control(target.pid)
                    break
            except (OSError, InspectorUnavailableError):
                pass
            assert time.monotonic() < until, "owned fixture did not become ready"
            time.sleep(0.1)
        scope = Scope(App.attach(pid=target.pid))
        until = time.monotonic() + 10
        while not any(w.automation_id == "SecondWindow" for w in scope.app.top_level_windows()):
            assert time.monotonic() < until, "second fixture window did not open"
            time.sleep(0.1)
        with runtime.config_scope(cfg):
            for where in (
                (("type:FullName", "WinTestKit.Fixture.MainWindow"),),
                (("ClrFullClassName", re.compile(r"Fixture\.MainWindow$")),),
                (("clr:Title", "WinTestKit WPF Fixture"),),
            ):
                assert resolve_window(scope.app, WindowLocator(where=where)).name == (
                    "WinTestKit WPF Fixture"
                )
            assert (
                resolve_window(
                    scope.app,
                    WindowLocator(
                        automation_id="SecondWindow", where=(("type:Is", "System.Windows.Window"),)
                    ),
                ).automation_id
                == "SecondWindow"
            )

            class FixturePage(Page):
                window = Window(where={"type:FullName": "WinTestKit.Fixture.MainWindow"})

            assert FixturePage(scope.app).window.title == "WinTestKit WPF Fixture"
            scope = Scope(
                scope.app,
                WindowLocator(where=(("type:FullName", "WinTestKit.Fixture.MainWindow"),)),
            )
            locator = Locator(
                automation_id="FixtureControl",
                where=(
                    ("ClrFullClassName", "WinTestKit.Fixture.FixtureControl"),
                    ("field:PublicField", "public field"),
                    ("clr:DataContext.Customer.Address.City", re.compile("^Sydney$")),
                    (
                        "dp:WinTestKit.Fixture|WinTestKit.Fixture.FixtureControl::DefaultValue",
                        "default",
                    ),
                ),
            )
            selected = resolve(scope, locator)
            assert selected.automation_id == "FixtureControl"
            assert runtime.inspector_sessions().status(facts.identity).state == "ready"
            password_before = _control(target.pid).get("Password", 0)
            with pytest.raises(InspectorReadError, match="redacted"):
                resolve(
                    scope, Locator(automation_id="FixtureControl", where=(("clr:Password", "x"),))
                )
            assert _control(target.pid).get("Password", 0) == password_before
            runtime.close_inspector_sessions()
        assert target.poll() is None
        _fixture_counters(target.pid)
        assert _hashes() == before
    finally:
        runtime.reset()
        if target.poll() is None:
            target.terminate()
        target.wait(timeout=5)
