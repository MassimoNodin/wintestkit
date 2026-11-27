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
            futures = [
                executor.submit(
                    registry.attach, IDENTITY, target_hwnd=None, deadline=time.monotonic() + 3
                )
                for _ in range(6)
            ]
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
            owner = executor.submit(
                registry.attach, IDENTITY, target_hwnd=None, deadline=time.monotonic() + 3
            )
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
        future = executor.submit(
            registry.attach, IDENTITY, target_hwnd=None, deadline=time.monotonic() + 3
        )
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
    monkeypatch.setattr(
        probe,
        "current_identity",
        lambda pid: (_ for _ in ()).throw(
            InspectorUnavailableError("Target process exited", code="processExited")
        ),
    )
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
        path=tmp_path / "consumed.json",
        session_id="session",
        pipe_name="pipe",
        token="token",
        cleanup=lambda: finish("bootstrap"),
    )
    monkeypatch.setattr(probe, "identify", lambda pid: FACTS)
    monkeypatch.setattr(probe, "current_identity", lambda pid: IDENTITY)
    monkeypatch.setattr(probe, "agent_active", lambda pid: False)
    monkeypatch.setattr(sessions, "_validate_facts", lambda *args: None)
    staged = SimpleNamespace(
        verify=lambda: None,
        inspector_version="1",
        launcher_for=lambda architecture: tmp_path / "staged" / "launcher.exe",
        agent_for=lambda runtime: tmp_path / "staged" / "agent.dll",
    )
    monkeypatch.setattr(sessions, "_stage_payload", lambda original: staged)
    monkeypatch.setattr(sessions, "_payload_path", lambda payload, path: path)
    monkeypatch.setattr(sessions.bootstrap, "create_bootstrap", lambda *args, **kwargs: settings)

    def launch(executable: Path, agent: Path, *args: Any) -> object:
        assert executable == tmp_path / "staged" / "launcher.exe"
        assert agent == tmp_path / "staged" / "agent.dll"
        return object()

    monkeypatch.setattr(sessions.launcher, "launch", launch)
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


@pytest.mark.parametrize("taken", [True, False])
def test_pipe_timeout_reports_agent_taken_by_another_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, taken: bool
) -> None:
    """The agent exits without a pipe when another session won the race for it."""
    payload = SimpleNamespace(
        verify=lambda: None,
        inspector_version="1",
        launcher_for=lambda architecture: tmp_path / "launcher.exe",
        agent_for=lambda runtime: tmp_path / "agent.dll",
    )
    settings = SimpleNamespace(
        path=tmp_path / "consumed.json",
        session_id="session",
        pipe_name="pipe",
        token="token",
        cleanup=lambda: None,
    )
    checks: list[int] = []

    def agent_active(pid: int) -> bool:
        checks.append(pid)
        # Free at the pre-attach check; held by the other session afterwards.
        return taken and len(checks) > 1

    def connect(*args: Any, **kwargs: Any) -> Any:
        raise InspectorUnavailableError("Inspector readiness deadline expired", code="timeout")

    monkeypatch.setattr(probe, "identify", lambda pid: FACTS)
    monkeypatch.setattr(probe, "current_identity", lambda pid: IDENTITY)
    monkeypatch.setattr(probe, "agent_active", agent_active)
    monkeypatch.setattr(sessions, "_validate_facts", lambda *args: None)
    monkeypatch.setattr(sessions, "_stage_payload", lambda payload: payload)
    monkeypatch.setattr(sessions, "_payload_path", lambda payload, path: path)
    monkeypatch.setattr(sessions.bootstrap, "create_bootstrap", lambda *args, **kwargs: settings)
    monkeypatch.setattr(sessions.launcher, "launch", lambda *args: SimpleNamespace(poll=lambda: 0))
    monkeypatch.setattr(sessions.launcher, "close_launcher", lambda process: None)
    monkeypatch.setattr(sessions.launcher, "policy_failure", lambda *args: None)
    monkeypatch.setattr(sessions.WindowsPipe, "connect", connect)
    registry = sessions.SessionRegistry(payload_loader=lambda: payload)
    try:
        with pytest.raises(InspectorUnavailableError) as error:
            registry.attach(IDENTITY, target_hwnd=None, deadline=time.monotonic() + 1)
        assert error.value.code == ("alreadyAttached" if taken else "agentNotStarted")
        assert len(checks) == 2
    finally:
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


def test_a_failing_identity_probe_does_not_end_a_working_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = sessions.SessionRegistry()
    transport = ScriptedTransport(lambda request: {"id": request["id"], "result": {"closed": True}})
    client = InspectorClient(transport, session())
    registry._entries[IDENTITY] = sessions._Entry(session(), client=client)

    def denied(pid: int) -> Any:
        raise InspectorUnavailableError("Cannot open target process", code="accessDenied")

    try:
        monkeypatch.setattr(probe, "current_identity", denied)
        assert registry.get(IDENTITY) is client
        assert client.session.state == "ready"

        def exited(pid: int) -> Any:
            raise InspectorUnavailableError("Target exited", code="processExited")

        monkeypatch.setattr(probe, "current_identity", exited)
        assert registry.get(IDENTITY) is None
        assert client.session.state == "exited"
    finally:
        client.close()


def test_loaded_agent_mismatch_compares_image_content(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    expected = tmp_path / "expected" / "agent.dll"
    loaded = tmp_path / "loaded" / "agent.dll"
    expected.parent.mkdir()
    loaded.parent.mkdir()
    expected.write_bytes(b"expected")
    loaded.write_bytes(b"different")
    monkeypatch.setattr(probe, "loaded_modules", lambda pid: (str(loaded),))
    assert sessions._loaded_agent_mismatch(42, expected)
    loaded.write_bytes(b"expected")
    assert not sessions._loaded_agent_mismatch(42, expected)


def test_detach_then_attach_opens_a_new_session_each_time(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = sessions.SessionRegistry()
    clients: list[InspectorClient] = []

    def attach(identity: Any, hwnd: Any, deadline: float, entry: Any, **kwargs: Any) -> Any:
        transport = ScriptedTransport(
            lambda request: {"id": request["id"], "result": {"closed": True}}
        )
        client = InspectorClient(
            transport,
            replace(session(), session_id=f"session-{len(clients)}"),
            on_closed=lambda closed: registry._client_closed(identity, entry, closed),
        )
        clients.append(client)
        return client

    monkeypatch.setattr(registry, "_attach_owned", attach)
    monkeypatch.setattr(probe, "current_identity", lambda pid: IDENTITY)
    try:
        first = registry.attach(IDENTITY, target_hwnd=None, deadline=time.monotonic() + 1)
        for round_ in range(1, 4):
            registry.detach(clients[-1].session.session_id)
            # The detached client is gone from the registry; nothing hands out a closed session.
            assert registry.get(IDENTITY) is None
            assert clients[-1].session.state == "detached"
            assert registry.status(IDENTITY).state == "detached"
            client = registry.attach(IDENTITY, target_hwnd=None, deadline=time.monotonic() + 1)
            assert client is clients[-1] and client is not first
            assert client.session.state == "ready"
            assert client.session.session_id == f"session-{round_}"
            assert registry.get(IDENTITY) is client
            assert len(registry._entries) == 1
        assert len(clients) == 4
    finally:
        registry.close_all()


@pytest.mark.parametrize(
    ("exit_code", "reason", "expected"),
    [
        (1, "", "injectionFailed"),
        (1260, "", "blockedByPolicy"),
        (None, "", "injectionStalled"),
        (0, "", "agentNotStarted"),
        (0, "Bootstrap expired.", "bootstrapRejected"),
    ],
)
def test_launcher_outcomes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    exit_code: int | None,
    reason: str,
    expected: str,
) -> None:
    from wintestkit.inspector.bootstrap import Bootstrap

    directory = tmp_path / "session"
    directory.mkdir()
    payload = SimpleNamespace(
        verify=lambda: None,
        inspector_version="1",
        launcher_for=lambda architecture: tmp_path / "launcher.exe",
        agent_for=lambda runtime: tmp_path / "agent.dll",
    )
    settings = Bootstrap(
        "session", "pipe", directory / "settings.json", directory, tmp_path, "token"
    )
    error_file = Path(str(settings.path) + ".error")
    if reason:
        error_file.write_text(reason)
    process = SimpleNamespace(poll=lambda: exit_code, returncode=exit_code)
    monkeypatch.setattr(probe, "identify", lambda pid: FACTS)
    monkeypatch.setattr(probe, "current_identity", lambda pid: IDENTITY)
    monkeypatch.setattr(probe, "agent_active", lambda pid: False)
    monkeypatch.setattr(sessions, "_loaded_agent_mismatch", lambda *args: False)
    monkeypatch.setattr(sessions, "_validate_facts", lambda *args: None)
    monkeypatch.setattr(sessions, "_stage_payload", lambda payload: payload)
    monkeypatch.setattr(sessions, "_payload_path", lambda payload, path: path)
    monkeypatch.setattr(sessions.bootstrap, "create_bootstrap", lambda *args, **kwargs: settings)
    monkeypatch.setattr(sessions.bootstrap, "_no_reparse", lambda *args: None)
    monkeypatch.setattr(sessions.launcher, "launch", lambda *args: process)
    monkeypatch.setattr(sessions.launcher, "close_launcher", lambda process: None)

    def connect(*args: Any, **kwargs: Any) -> Any:
        kwargs["check"]()
        raise InspectorUnavailableError("deadline", code="timeout")

    monkeypatch.setattr(sessions.WindowsPipe, "connect", connect)
    start = time.monotonic()
    with pytest.raises(InspectorUnavailableError) as error:
        sessions.SessionRegistry(payload_loader=lambda: payload).attach(
            IDENTITY, target_hwnd=None, deadline=start + 5
        )
    assert error.value.code == expected
    if reason:
        assert str(error.value) == reason
    assert not error_file.exists()
    if exit_code == 1:
        assert time.monotonic() - start < 1


def test_launcher_log_tail(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from wintestkit.inspector.launcher import log_tail

    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert log_tail() == ""
    (tmp_path / "Snoop").mkdir()
    log = tmp_path / "Snoop" / "SnoopLog.txt"
    log.write_text("old\n" + "x" * 70000 + "\nlast line\n\n")
    assert log_tail() == "last line"
    log.write_text("y" * 400)
    assert log_tail() == "y" * 300
