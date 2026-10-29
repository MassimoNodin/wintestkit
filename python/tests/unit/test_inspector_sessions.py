"""Session registry concurrency, identity and cancellation behavior."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from test_inspector_client import FACTS, IDENTITY, ScriptedTransport, session

from wintestkit.errors import InspectorUnavailableError
from wintestkit.inspector import probe, sessions
from wintestkit.inspector.client import InspectorClient


def test_concurrent_attaches_share_one_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = sessions.SessionRegistry()
    started, release = threading.Event(), threading.Event()
    calls: list[int] = []
    transport = ScriptedTransport(lambda request: {"id": request["id"], "result": {"closed": True}})
    client = InspectorClient(transport, session())
    def attach(*args: Any) -> InspectorClient:
        calls.append(1)
        started.set()
        assert release.wait(2)
        return client
    monkeypatch.setattr(registry, "_attach_owned", attach)
    monkeypatch.setattr(probe, "current_identity", lambda pid: IDENTITY)
    try:
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = [executor.submit(registry.attach, IDENTITY, target_hwnd=None, deadline=time.monotonic() + 3) for _ in range(6)]
            assert started.wait(1)
            time.sleep(0.05)
            release.set()
            assert all(future.result() is client for future in futures)
        assert len(calls) == 1 and registry.get(IDENTITY) is client
        registry.detach("session")
        assert client.session.state == "detached"
    finally:
        release.set()
        registry.close_all()


def test_waiting_caller_deadline_does_not_cancel_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = sessions.SessionRegistry()
    started, release = threading.Event(), threading.Event()
    transport = ScriptedTransport(lambda request: {"id": request["id"], "result": {"closed": True}})
    client = InspectorClient(transport, session())
    def attach(*args: Any) -> InspectorClient:
        started.set()
        assert release.wait(2)
        return client
    monkeypatch.setattr(registry, "_attach_owned", attach)
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            owner = executor.submit(registry.attach, IDENTITY, target_hwnd=None, deadline=time.monotonic() + 3)
            assert started.wait(1)
            with pytest.raises(InspectorUnavailableError) as error:
                registry.attach(IDENTITY, target_hwnd=None, deadline=time.monotonic() + 0.05)
            assert error.value.code == "timeout"
            release.set()
            assert owner.result() is client
    finally:
        release.set()
        registry.close_all()


def test_close_all_cancels_inflight_attach(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = sessions.SessionRegistry()
    started = threading.Event()
    def attach(identity: Any, hwnd: Any, deadline: float, entry: Any) -> InspectorClient:
        started.set()
        assert entry.cancel.wait(2)
        sessions._remaining(deadline, entry.cancel)
        raise AssertionError("unreachable")
    monkeypatch.setattr(registry, "_attach_owned", attach)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(registry.attach, IDENTITY, target_hwnd=None, deadline=time.monotonic() + 3)
        assert started.wait(1)
        registry.close_all()
        with pytest.raises(InspectorUnavailableError) as error:
            future.result()
    assert error.value.code == "cancelled"


def test_existing_session_revalidates_process_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = sessions.SessionRegistry()
    transport = ScriptedTransport(lambda request: {"id": request["id"], "result": {"closed": True}})
    client = InspectorClient(transport, session())
    attempts = 0

    def attach(*args: Any) -> InspectorClient:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return client
        raise InspectorUnavailableError("Target process exited", code="processExited")

    monkeypatch.setattr(registry, "_attach_owned", attach)
    monkeypatch.setattr(probe, "current_identity", lambda pid: (_ for _ in ()).throw(
        InspectorUnavailableError("Target process exited", code="processExited")
    ))
    try:
        assert registry.attach(IDENTITY, target_hwnd=None, deadline=time.monotonic() + 1) is client
        with pytest.raises(InspectorUnavailableError) as error:
            registry.attach(IDENTITY, target_hwnd=None, deadline=time.monotonic() + 1)
        assert error.value.code == "processExited"
        assert transport.closed and client.session.state == "exited"
        assert attempts == 2
    finally:
        registry.close_all()


@pytest.mark.parametrize("failure", ["bootstrap", "launcher"])
def test_attach_cleanup_failure_closes_authenticated_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str
) -> None:
    transport = ScriptedTransport(lambda request: {"id": request["id"], "result": {"closed": True}})
    client = InspectorClient(transport, session())
    cleanup: list[str] = []

    def finish(resource: str) -> None:
        cleanup.append(resource)
        if resource == failure:
            raise OSError("cleanup failed")

    payload = SimpleNamespace(
        verify=lambda: None,
        inspector_version="1",
        launcher_for=lambda architecture: tmp_path / "launcher.exe",
        agent_for=lambda runtime: tmp_path / "agent.dll",
    )
    settings = SimpleNamespace(
        path=tmp_path / "consumed.json", session_id="session", pipe_name="pipe", token="token",
        cleanup=lambda: finish("bootstrap"),
    )
    monkeypatch.setattr(probe, "identify", lambda pid: FACTS)
    monkeypatch.setattr(probe, "current_identity", lambda pid: IDENTITY)
    monkeypatch.setattr(probe, "agent_active", lambda pid: False)
    monkeypatch.setattr(sessions, "_validate_facts", lambda *args: None)
    monkeypatch.setattr(sessions, "_payload_path", lambda payload, path: path)
    monkeypatch.setattr(sessions.bootstrap, "create_bootstrap", lambda *args, **kwargs: settings)
    monkeypatch.setattr(sessions.launcher, "launch", lambda *args: object())
    monkeypatch.setattr(sessions.launcher, "close_launcher", lambda process: finish("launcher"))
    monkeypatch.setattr(sessions.WindowsPipe, "connect", lambda *args, **kwargs: transport)
    monkeypatch.setattr(InspectorClient, "authenticate", lambda *args, **kwargs: client)
    registry = sessions.SessionRegistry(payload_loader=lambda: payload)
    try:
        with pytest.raises(InspectorUnavailableError) as error:
            registry.attach(IDENTITY, target_hwnd=None, deadline=time.monotonic() + 1)
        assert error.value.code == "attachFailed"
        assert registry.status(IDENTITY).state == "faulted"
        assert transport.closed and client.session.state == "detached"
        assert cleanup == ["launcher", "bootstrap"]
    finally:
        client.close()
        registry.close_all()


@pytest.mark.parametrize("failure", ["processExited", "processReused"])
def test_status_rechecks_identity_after_pipe_closes_before_process_exit(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    registry = sessions.SessionRegistry()
    stale = replace(session(), state="faulted", error="sessionStale")
    entry = sessions._Entry(stale)
    registry._entries[IDENTITY] = entry
    monkeypatch.setattr(probe, "current_identity", lambda pid: IDENTITY)
    assert registry.status(IDENTITY).state == "faulted"

    def terminated(pid: int) -> Any:
        if failure == "processExited":
            raise InspectorUnavailableError("Target exited", code=failure)
        return replace(IDENTITY, creation_time_utc="2026-10-29T00:00:01Z")

    monkeypatch.setattr(probe, "current_identity", terminated)
    assert registry.status(IDENTITY).state == "exited"
    assert registry.status(IDENTITY).error == failure
    assert entry.session.state == "exited"
