"""Opt-in live smoke of every published fixture cell."""

import os
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest
from live_dotnet import live_dotnet_root
from test_inspector_owned_integration import PAYLOAD, ROOT, _control
from test_wpf_query_gate_real import _fixture_scenario, config

from wintestkit import runtime
from wintestkit.app import App
from wintestkit.backends import WpfElement
from wintestkit.controls import TextBox
from wintestkit.engine.locator import Locator
from wintestkit.engine.resolve import Scope, resolve
from wintestkit.expect import expect
from wintestkit.inspector.event_waiter import EventWaiter
from wintestkit.model import Element, Page

pytestmark = pytest.mark.skipif(
    os.name != "nt" or os.environ.get("WTK_INSPECTOR_REAL") != "1",
    reason="requires explicitly enabled owned Windows fixture",
)


class MatrixPage(Page):
    noop = Element(automation_id="NestedButton")
    button = Element(automation_id="FancyAutomationId")
    source = TextBox(automation_id="BindingSource")
    bound = Element(automation_id="ElementNameBinding")


@pytest.mark.parametrize("runtime_name", ["net48", "net8", "net10"])
@pytest.mark.parametrize("architecture", ["x86", "x64"])
def test_matrix_cell(runtime_name, architecture, tmp_path, monkeypatch):
    tfm = {"net48": "net48", "net8": "net8.0-windows", "net10": "net10.0-windows"}[runtime_name]
    major = {"net48": "4", "net8": "8", "net10": "10"}[runtime_name]
    fixture = ROOT / f"wpf-inspector/tests/Fixtures/WpfFixture/bin/cells/{tfm}-{architecture}"
    executable = fixture / "WinTestKit.Fixture.exe"
    assert executable.is_file(), (
        f"{runtime_name}/{architecture}: published fixture missing: {executable}"
    )
    dotnet = Path(
        os.environ.get(
            f"WTK_MATRIX_DOTNET_ROOT_{architecture.upper()}",
            live_dotnet_root()
            if architecture == "x64" and runtime_name == "net10"
            else r"C:\Program Files\dotnet"
            if architecture == "x64"
            else r"C:\Program Files (x86)\dotnet",
        )
    )
    if runtime_name != "net48":
        for framework in ("Microsoft.NETCore.App", "Microsoft.WindowsDesktop.App"):
            shared = dotnet / "shared" / framework
            assert shared.is_dir() and any(
                p.is_dir() and p.name.startswith(major + ".") for p in shared.iterdir()
            ), f"{runtime_name}/{architecture}: {framework} {major} runtime missing in {shared}"
    monkeypatch.syspath_prepend(str(PAYLOAD))
    runtime.reset()
    cfg = replace(
        config(tmp_path, "agent"),
        backend="auto",
        inspector=replace(config(tmp_path, "agent").inspector, attach="on-launch"),
    )
    app = None
    try:
        with runtime.config_scope(cfg):
            app = App.launch(
                executable,
                cwd=fixture,
                env={
                    f"DOTNET_ROOT_{architecture.upper()}": str(dotnet),
                    "DOTNET_MULTILEVEL_LOOKUP": "0",
                },
                owned_only=True,
            )
            pid = app.pids[0]
            _control(pid)
            scope = Scope(app)
            target = resolve(scope, Locator(automation_id="FancyAutomationId"))
            assert isinstance(target, WpfElement)
            client = target.client
            assert client.session.architecture == architecture
            assert (
                client.session.runtime_version
                and client.session.runtime_version.split(".")[0] == major
            )
            print(
                f"MATRIX_HELLO {runtime_name} {architecture} {tfm} {client.session.runtime_version}",
                flush=True,
            )
            state = client.state_get(target.ref, timeout_ms=2000, deadline=time.monotonic() + 5)
            assert state.enabled and state.bounds is not None and state.window_handle is not None
            bounds = state.bounds
            hit = client.hit_test(
                state.window_handle,
                bounds.x + bounds.width / 2,
                bounds.y + bounds.height / 2,
                timeout_ms=2000,
                deadline=time.monotonic() + 5,
            )
            assert hit is not None
            pending = [target.ref]
            while pending and hit.handle not in pending:
                current = pending.pop()
                children = client.children(
                    current.object_id, current.generation, "visual", deadline=time.monotonic() + 5
                )
                assert children.complete
                pending.extend(node.object_ref for node in children.items)
            assert hit.handle in pending
            page = MatrixPage(app)
            page.noop.click(mode="pattern")
            page.button.click(mode="mouse")
            page.source.focus()
            page.source.press("Ctrl+A Backspace h i")
            expect(page.bound, timeout=5).to_have_text("hi")
            with EventWaiter(client, {"treeChanged"}) as waiter:
                while waiter.wait(0.2) != "timeout":
                    pass
                trigger = threading.Timer(0.2, _fixture_scenario, args=(pid, "addDynamic", 42))
                trigger.start()
                try:
                    assert waiter.wait(3, fallback=3) == "event"
                finally:
                    trigger.join()
            assert resolve(scope, Locator(automation_id="Dynamic42"))
            app.close()
            assert not runtime.inspector_sessions()._entries  # pyright: ignore[reportPrivateUsage]
            app = None
    finally:
        if app is not None:
            app.close()
        runtime.reset()
