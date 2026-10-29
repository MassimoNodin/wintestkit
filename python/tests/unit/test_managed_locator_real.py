"""S8 end-to-end queries instrument only the unchanged fixture launched here."""

import os
import re
import subprocess
import time

import pytest
from test_inspector_owned_integration import DOTNET, FIXTURE, PAYLOAD, _control, _hashes
from test_managed_server_real import _fixture_counters

from wintestkit import runtime
from wintestkit.app import App
from wintestkit.config import load_config
from wintestkit.engine.locator import Locator
from wintestkit.engine.resolve import Scope, resolve
from wintestkit.errors import InspectorReadError, InspectorUnavailableError
from wintestkit.inspector.probe import identify
from wintestkit.uia import win32

pytestmark = pytest.mark.skipif(
    os.name != "nt" or os.environ.get("WTK_INSPECTOR_REAL") != "1",
    reason="requires explicitly enabled owned Windows fixture",
)


def test_owned_fixture_managed_locator(tmp_path, monkeypatch):
    runtime.reset()
    monkeypatch.syspath_prepend(str(PAYLOAD))
    cfg = load_config(tmp_path, {
        "inspector.enabled": True, "inspector.attach": "on-demand",
        "property_aliases": {"ClrFullClassName": "type:FullName"},
    })
    before = _hashes()
    environment = os.environ.copy()
    environment["DOTNET_ROOT_X64"] = DOTNET
    environment["DOTNET_MULTILEVEL_LOOKUP"] = "0"
    target = subprocess.Popen(
        [str(FIXTURE / "WinTestKit.Fixture.exe")], cwd=FIXTURE, env=environment,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
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
        with runtime.config_scope(cfg):
            locator = Locator(automation_id="FixtureControl", where=(
                ("ClrFullClassName", "WinTestKit.Fixture.FixtureControl"),
                ("field:PublicField", "public field"),
                ("clr:DataContext.Customer.Address.City", re.compile("^Sydney$")),
                ("dp:WinTestKit.Fixture|WinTestKit.Fixture.FixtureControl::DefaultValue", "default"),
            ))
            selected = resolve(scope, locator)
            assert selected.automation_id == "FixtureControl"
            assert runtime.inspector_sessions().status(facts.identity).state == "ready"
            password_before = _control(target.pid).get("Password", 0)
            with pytest.raises(InspectorReadError, match="redacted"):
                resolve(scope, Locator(automation_id="FixtureControl", where=(("clr:Password", "x"),)))
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
