"""Opt-in real attachment to an unchanged, harness-owned WPF fixture."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from wintestkit.errors import InspectorUnavailableError
from wintestkit.inspector import bootstrap, launcher
from wintestkit.inspector.client import InspectorClient
from wintestkit.inspector.paths import PathSegment
from wintestkit.inspector.payload import load_payload
from wintestkit.inspector.pipe import WindowsPipe, _api
from wintestkit.inspector.probe import agent_active, identify
from wintestkit.inspector.sessions import SessionRegistry

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "wpf-inspector/tests/Fixtures/WpfFixture/bin/cells/net10.0-windows-x64"
PAYLOAD = ROOT / "inspector-payload/src"
DOTNET = r"C:\Users\massi\AppData\Local\wintestkit-dev\dotnet"

pytestmark = pytest.mark.skipif(
    os.name != "nt" or os.environ.get("WTK_INSPECTOR_REAL") != "1",
    reason="requires explicitly enabled owned Windows fixture",
)


def _hashes() -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in FIXTURE.iterdir()
        if path.suffix.lower() in {".exe", ".dll", ".config", ".json"}
    }


def _control(pid: int) -> dict[str, object]:
    kernel = _api()
    until = time.monotonic() + 2
    while True:
        handle = kernel.CreateFileW(
            rf"\\.\pipe\WinTestKit.Fixture.{pid}", 0xC0000000, 0, None, 3, 0x40000000, None
        )
        if handle != ctypes.c_void_p(-1).value:
            break
        error = ctypes.get_last_error()
        if error not in (2, 231) or time.monotonic() >= until:
            raise OSError(error, "Fixture control pipe not ready")
        time.sleep(0.01)
    pipe = WindowsPipe(handle)
    try:
        deadline = time.monotonic() + 2
        pipe.write(b'{"cmd":"counters"}\n', deadline)
        line = bytearray()
        while not line.endswith(b"\n") and len(line) < 65536:
            line.extend(pipe.read_exact(1, deadline))
        result = json.loads(line)
        assert isinstance(result, dict) and "error" not in result
        return result
    finally:
        pipe.close()


def test_owned_net10_x64_attach_read_detach(monkeypatch: pytest.MonkeyPatch) -> None:
    assert (FIXTURE / "WinTestKit.Fixture.exe").is_file()
    monkeypatch.syspath_prepend(str(PAYLOAD))
    before = _hashes()
    environment = os.environ.copy()
    environment["DOTNET_ROOT_X64"] = DOTNET
    environment["DOTNET_MULTILEVEL_LOOKUP"] = "0"
    target = subprocess.Popen(
        [str(FIXTURE / "WinTestKit.Fixture.exe")],
        cwd=FIXTURE,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    registry = SessionRegistry()
    try:
        until = time.monotonic() + 15
        while True:
            assert target.poll() is None, "Owned fixture exited during startup"
            try:
                facts = identify(target.pid)
                if facts.wpf_loaded and facts.runtime == "net10":
                    _control(target.pid)
                    break
            except (OSError, InspectorUnavailableError):
                pass
            assert time.monotonic() < until, "Owned fixture did not become ready"
            time.sleep(0.1)
        assert facts.architecture == "x64"
        assert _hashes() == before
        client = registry.attach(facts.identity, target_hwnd=None, deadline=time.monotonic() + 10)
        assert client.session.state == "ready"
        assert client.session.agent_version == "0.1.1rc2"
        assert client.session.architecture == "x64"
        roots = client.roots(deadline=time.monotonic() + 2)
        assert roots.items
        reference = roots.items[0].object_ref
        values, read_id = client.read(
            reference.object_id,
            reference.generation,
            [[PathSegment("type", "FullName")]],
            deadline=time.monotonic() + 2,
        )
        assert read_id and values[0].value.status == "ok" and values[0].value.as_python()
        assert client.members(
            reference.object_id, reference.generation, deadline=time.monotonic() + 2
        ).items
        second_registry = SessionRegistry()
        with pytest.raises(InspectorUnavailableError) as duplicate:
            second_registry.attach(facts.identity, target_hwnd=None, deadline=time.monotonic() + 2)
        assert duplicate.value.code == "alreadyAttached"
        second_registry.close_all()
        first_session_id = client.session.session_id
        registry.detach(client.session.session_id)
        assert registry.status(facts.identity).state == "detached"
        assert target.poll() is None
        _control(target.pid)
        until = time.monotonic() + 3
        while agent_active(target.pid) and time.monotonic() < until:
            time.sleep(0.05)
        assert not agent_active(target.pid)
        reattached = registry.attach(
            facts.identity, target_hwnd=None, deadline=time.monotonic() + 10
        )
        assert reattached.session.session_id != first_session_id
        assert reattached.roots(deadline=time.monotonic() + 2).items
        registry.detach(reattached.session.session_id)
        _control(target.pid)
        assert _hashes() == before
        until = time.monotonic() + 3
        while agent_active(target.pid) and time.monotonic() < until:
            time.sleep(0.05)
        live = registry.attach(facts.identity, target_hwnd=None, deadline=time.monotonic() + 10)
        target.terminate()
        target.wait(timeout=5)
        until = time.monotonic() + 2
        while registry.status(facts.identity).state != "exited" and time.monotonic() < until:
            time.sleep(0.01)
        assert registry.status(facts.identity).state == "exited"
        assert registry.status(facts.identity).error == "processExited"
        assert live.session.state != "ready"
    finally:
        registry.close_all()
        if target.poll() is None:
            target.terminate()
        target.wait(timeout=5)


@pytest.mark.parametrize("mismatch", ["token", "version"])
def test_owned_net10_x64_rejects_hello_mismatch(
    monkeypatch: pytest.MonkeyPatch, mismatch: str
) -> None:
    monkeypatch.syspath_prepend(str(PAYLOAD))
    before = _hashes()
    environment = os.environ.copy()
    environment["DOTNET_ROOT_X64"] = DOTNET
    environment["DOTNET_MULTILEVEL_LOOKUP"] = "0"
    target = subprocess.Popen(
        [str(FIXTURE / "WinTestKit.Fixture.exe")],
        cwd=FIXTURE,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    settings = None
    process = None
    try:
        until = time.monotonic() + 15
        while True:
            assert target.poll() is None
            try:
                facts = identify(target.pid)
                if facts.wpf_loaded and facts.runtime == "net10":
                    _control(target.pid)
                    break
            except (OSError, InspectorUnavailableError):
                pass
            assert time.monotonic() < until
            time.sleep(0.1)
        payload = load_payload()
        payload.verify()
        settings = bootstrap.create_bootstrap(
            facts.identity, facts.user_sid, payload.inspector_version
        )
        process = launcher.launch(
            payload.launcher_for("x64"), payload.agent_for("net10"), facts.identity, settings.path
        )
        deadline = time.monotonic() + 10
        connection = WindowsPipe.connect(settings.pipe_name, facts.identity, deadline)
        with pytest.raises(InspectorUnavailableError) as error:
            InspectorClient.authenticate(
                connection,
                facts,
                settings.session_id,
                "A" * 43 + "=" if mismatch == "token" else settings.token,
                "0.0.0" if mismatch == "version" else payload.inspector_version,
                deadline=deadline,
            )
        expected = "authenticationFailed" if mismatch == "token" else "agentVersionMismatch"
        assert error.value.code == expected
        assert not settings.path.exists() and target.poll() is None
        _control(target.pid)
        assert _hashes() == before
    finally:
        try:
            if process is not None:
                launcher.close_launcher(process)
        finally:
            if settings is not None:
                settings.cleanup()
            if target.poll() is None:
                target.terminate()
            target.wait(timeout=5)
