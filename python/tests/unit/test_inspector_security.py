"""Bootstrap, launcher, process and pipe identity security checks."""

from __future__ import annotations

import base64
import ctypes
import json
import os
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from wintestkit.errors import InspectorUnavailableError
from wintestkit.inspector import bootstrap, launcher, pipe, probe, sessions
from wintestkit.inspector.models import ProcessFacts, ProcessIdentity

IDENTITY = ProcessIdentity(42, "2026-10-29T00:00:00Z")


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL API")
def test_real_private_bootstrap_is_one_use_and_cleaned(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(bootstrap, "_local_app_data", lambda: tmp_path)
    sid, _, _ = probe.current_security()
    settings = bootstrap.create_bootstrap(IDENTITY, sid, "1")
    try:
        document = json.loads(settings.path.read_text(encoding="utf-8"))
        assert set(document) == {"schemaVersion", "protocolMajor", "protocolMinor", "sessionId", "process", "pipeName", "token", "clientSid", "expiresUtc", "requestTimeoutMs", "idleTimeoutMs", "agentVersion", "redactNames"}
        assert document["redactNames"] == []
        assert len(base64.b64decode(document["token"], validate=True)) == 32
        assert document["clientSid"] == sid and document["process"] == IDENTITY.to_json()
        assert document["requestTimeoutMs"] == 2000 and document["idleTimeoutMs"] == 300000
        assert settings.token not in repr(settings)
    finally:
        settings.cleanup()
    assert not settings.path.exists() and not settings.directory.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL API")
def test_bootstrap_failure_removes_session_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(bootstrap, "_local_app_data", lambda: tmp_path)
    def reject(handle: Any, sid: str) -> None:
        raise InspectorUnavailableError("ACL rejected", code="accessDenied")
    monkeypatch.setattr(bootstrap, "_verify_acl", reject)
    with pytest.raises(InspectorUnavailableError):
        bootstrap.create_bootstrap(IDENTITY, probe.current_security()[0], "1")
    assert not list((tmp_path / "WinTestKit/inspector/bootstrap").iterdir())


def test_reparse_point_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    child = tmp_path / "child"
    child.mkdir()
    original = Path.lstat
    def fake_lstat(path: Path) -> Any:
        if path == child:
            return SimpleNamespace(st_mode=0, st_file_attributes=0x400)
        return original(path)
    monkeypatch.setattr(Path, "lstat", fake_lstat)
    with pytest.raises(InspectorUnavailableError) as error:
        bootstrap._no_reparse(child, tmp_path)
    assert error.value.code == "accessDenied"


def test_pipe_server_pid_is_verified_before_authentication(monkeypatch: pytest.MonkeyPatch) -> None:
    closed: list[int] = []
    def server_pid(handle: int, output: Any) -> bool:
        ctypes.cast(output, ctypes.POINTER(ctypes.c_ulong))[0] = 43
        return True
    api = SimpleNamespace(CreateFileW=lambda *args: 123, GetNamedPipeServerProcessId=server_pid,
                          CloseHandle=lambda handle: closed.append(handle))
    monkeypatch.setattr(pipe, "_api", lambda: api)
    with pytest.raises(InspectorUnavailableError) as error:
        pipe.WindowsPipe.connect("WinTestKit.Inspector.42.session", IDENTITY, time.monotonic() + 1)
    assert error.value.code == "processReused" and closed == [123]


@pytest.mark.skipif(os.name != "nt", reason="Windows process creation flags")
def test_launcher_uses_fixed_arguments_without_token_or_inherited_handles(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, Any] = {}
    def popen(args: list[str], **kwargs: Any) -> Any:
        captured.update(args=args, **kwargs)
        return SimpleNamespace()
    monkeypatch.setattr(subprocess, "Popen", popen)
    executable = tmp_path / "path with spaces" / "launcher.exe"
    agent = tmp_path / "agents" / "agent.dll"
    bootstrap_path = tmp_path / "bootstrap" / "random.json"
    launcher.launch(executable, agent, IDENTITY, bootstrap_path)
    assert captured["args"] == [str(executable), "--targetPID", "42", "--assembly", str(agent), "--className", "WinTestKit.Inspector.Agent.EntryPoint", "--methodName", "Start", "--settingsFile", str(bootstrap_path)]
    assert captured["shell"] is False and captured["close_fds"] is True
    assert captured["creationflags"] & subprocess.CREATE_NO_WINDOW
    assert "--targetHwnd" not in captured["args"] and "--token" not in captured["args"]


@pytest.mark.parametrize("mismatch", ["user", "integrity", "session", "identity", "wpf", "runtime", "architecture"])
def test_probe_facts_reject_unsafe_targets(monkeypatch: pytest.MonkeyPatch, mismatch: str) -> None:
    monkeypatch.setattr(probe, "current_security", lambda: ("sid", "medium", 1))
    monkeypatch.setattr(probe, "controller_supported", lambda: True)
    values: dict[str, Any] = {"identity": IDENTITY, "executable": "app.exe", "architecture": "x64", "runtime": "net10", "wpf_loaded": True, "session_id": 1, "user_sid": "sid", "integrity": "medium"}
    changes = {"user": ("user_sid", "other"), "integrity": ("integrity", "high"), "session": ("session_id", 2), "identity": ("identity", ProcessIdentity(42, "2026-10-29T00:00:01Z")), "wpf": ("wpf_loaded", False), "runtime": ("runtime", None), "architecture": ("architecture", "arm64")}
    key, value = changes[mismatch]
    values[key] = value
    with pytest.raises(InspectorUnavailableError):
        sessions._validate_facts(ProcessFacts(**values), IDENTITY)


@pytest.mark.parametrize("result", [1260, 577, 0xC0000428])
def test_policy_block_is_not_generic_failure(result: int) -> None:
    process = SimpleNamespace(poll=lambda: result)
    with pytest.raises(InspectorUnavailableError) as error:
        launcher.policy_failure(process, Path("launcher.exe"))
    assert error.value.code == "blockedByPolicy"
