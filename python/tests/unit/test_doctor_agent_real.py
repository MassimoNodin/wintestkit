import os
import subprocess
import time
from dataclasses import replace

import pytest
from test_inspector_owned_integration import DOTNET, FIXTURE, PAYLOAD

from wintestkit import doctor
from wintestkit.config import AppConfig, load_config
from wintestkit.errors import InspectorUnavailableError
from wintestkit.inspector.probe import identify
from wintestkit.uia import win32

pytestmark = pytest.mark.skipif(
    os.name != "nt" or os.environ.get("WTK_INSPECTOR_REAL") != "1",
    reason="requires explicitly enabled owned Windows fixture",
)


def test_doctor_agent_real(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(PAYLOAD))
    env = os.environ.copy()
    env["DOTNET_ROOT_X64"] = DOTNET
    env["DOTNET_MULTILEVEL_LOOKUP"] = "0"
    target = subprocess.Popen(
        [str(FIXTURE / "WinTestKit.Fixture.exe")],
        cwd=FIXTURE,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                if identify(target.pid).wpf_loaded and win32.top_level_windows({target.pid}):
                    break
            except (OSError, InspectorUnavailableError):
                pass
            time.sleep(0.1)
        else:
            pytest.fail("fixture window did not appear")
        cfg = replace(
            load_config(tmp_path),
            backend="auto",
            app=AppConfig(path=FIXTURE / "WinTestKit.Fixture.exe"),
        )
        cfg = replace(cfg, inspector=replace(cfg.inspector, enabled=True))
        monkeypatch.setattr(
            doctor, "_app_pids", lambda cfg: ("WinTestKit.Fixture.exe", [target.pid])
        )
        check = doctor._check_wpf_agent(cfg)
        assert check.status == "ok", check
    finally:
        if target.poll() is None:
            target.terminate()
        target.wait(timeout=5)
