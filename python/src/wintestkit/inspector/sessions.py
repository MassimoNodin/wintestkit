"""Runtime-owned process session registry and secure attach orchestration."""

from __future__ import annotations

import ctypes
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from wintestkit.errors import InspectorError, InspectorUnavailableError
from wintestkit.inspector import bootstrap, launcher, probe
from wintestkit.inspector.client import InspectorClient
from wintestkit.inspector.models import ProcessFacts, ProcessIdentity, Session
from wintestkit.inspector.pipe import WindowsPipe

if TYPE_CHECKING:
    from wintestkit.inspector.payload import Payload


def _load_payload() -> Payload:
    from wintestkit.inspector.payload import load_payload

    return load_payload()


@dataclass
class _Entry:
    session: Session
    done: threading.Event = field(default_factory=threading.Event)
    cancel: threading.Event = field(default_factory=threading.Event)
    client: InspectorClient | None = None
    error: InspectorError | None = None


def _remaining(deadline: float, cancelled: threading.Event) -> None:
    if cancelled.is_set():
        raise InspectorUnavailableError("Inspector attach was cancelled", code="cancelled")
    if time.monotonic() >= deadline:
        raise InspectorUnavailableError("Inspector readiness deadline expired", code="timeout")


def _validate_hwnd(hwnd: int | None, pid: int) -> None:
    if hwnd is None:
        return
    if type(hwnd) is not int or hwnd <= 0:
        raise InspectorUnavailableError("Invalid target window handle", code="invalidParams")
    if os.name != "nt":
        raise InspectorUnavailableError(
            "The WPF inspector requires Windows", code="unsupportedTarget"
        )
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.IsWindow.argtypes = [ctypes.c_void_p]
    user.IsWindow.restype = ctypes.c_int
    user.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    user.GetWindowThreadProcessId.restype = ctypes.c_ulong
    owner = ctypes.c_ulong()
    if (
        not user.IsWindow(hwnd)
        or not user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        or owner.value != pid
    ):
        raise InspectorUnavailableError(
            "Target window does not belong to the selected process", code="invalidParams"
        )


def _validate_facts(facts: ProcessFacts, identity: ProcessIdentity) -> None:
    if facts.identity != identity:
        raise InspectorUnavailableError("Target process identity changed", code="processReused")
    if (
        facts.architecture not in {"x86", "x64"}
        or facts.runtime not in {"net48", "net8", "net10"}
        or not facts.wpf_loaded
    ):
        raise InspectorUnavailableError(
            "Target runtime, architecture, or WPF is unsupported", code="unsupportedTarget"
        )
    user, integrity, session = probe.current_security()
    if (facts.user_sid, facts.integrity, facts.session_id) != (user, integrity, session):
        raise InspectorUnavailableError(
            "Target must have the same user, integrity, and Windows session", code="accessDenied"
        )
    if not probe.controller_supported():
        raise InspectorUnavailableError(
            "Inspector requires a native 64-bit x64 Python controller", code="unsupportedTarget"
        )


def _payload_path(payload: Payload, path: Path) -> Path:
    root = payload.root.resolve(strict=True)
    result = path.resolve(strict=True)
    if not result.is_relative_to(root) or not result.is_file():
        raise InspectorUnavailableError(
            "Inspector payload path is outside its root", code="payloadMismatch"
        )
    relative = result.relative_to(root).as_posix()
    if not any(item.get("path") == relative for item in payload.manifest["files"]):
        raise InspectorUnavailableError(
            "Inspector payload path is not in its manifest", code="payloadMismatch"
        )
    return result


def _disconnected_session(session: Session) -> Session:
    if session.error == "sessionStale":
        try:
            if probe.current_identity(session.process.pid) != session.process:
                return replace(session, state="exited", error="processReused")
        except InspectorUnavailableError as error:
            if error.code == "processExited":
                return replace(session, state="exited", error="processExited")
    return session


class SessionRegistry:
    def __init__(
        self,
        payload_loader: Callable[[], Payload] = _load_payload,
        *,
        request_timeout: float = 2.0,
        redact_names: tuple[str, ...] = (),
    ) -> None:
        if not 0 < request_timeout <= 2:
            raise ValueError("Request timeout must be between zero and two seconds")
        self._payload_loader = payload_loader
        self._request_timeout = request_timeout
        from wintestkit.inspector.redaction import validate_redact_names

        self._redact_names = validate_redact_names(redact_names)
        self._lock = threading.RLock()
        self._entries: dict[ProcessIdentity, _Entry] = {}

    def attach(
        self, identity: ProcessIdentity, *, target_hwnd: int | None, deadline: float
    ) -> InspectorClient:
        deadline = min(deadline, time.monotonic() + 10.0)
        if time.monotonic() >= deadline:
            raise InspectorUnavailableError("Inspector readiness deadline expired", code="timeout")
        while True:
            with self._lock:
                entry = self._entries.get(identity)
                ready = (
                    entry is not None
                    and entry.client is not None
                    and entry.client.session.state == "ready"
                )
                if not ready:
                    owner = entry is None or entry.done.is_set()
                    if owner:
                        entry = _Entry(Session("pending", identity, "probing", 1, 0, ()))
                        self._entries[identity] = entry
                    break
            existing = self.get(identity)
            if existing is not None:
                return existing
        assert entry is not None
        if not owner:
            if not entry.done.wait(max(0, deadline - time.monotonic())):
                raise InspectorUnavailableError(
                    "Inspector readiness deadline expired", code="timeout"
                )
            if entry.client is not None and entry.client.session.state == "ready":
                return entry.client
            raise entry.error or InspectorUnavailableError(
                "Inspector attach failed", code="attachFailed"
            )
        try:
            client = self._attach_owned(identity, target_hwnd, deadline, entry)
            with self._lock:
                if entry.cancel.is_set():
                    client.close()
                    raise InspectorUnavailableError(
                        "Inspector attach was cancelled", code="cancelled"
                    )
                entry.client = client
                entry.session = client.session
            return client
        except InspectorError as error:
            with self._lock:
                entry.error = error
                state = "exited" if error.code == "processExited" else "faulted"
                entry.session = replace(entry.session, state=state, error=error.code)
            raise
        except (OSError, ValueError) as error:
            failure = InspectorUnavailableError("Inspector attachment failed", code="attachFailed")
            with self._lock:
                entry.error = failure
                entry.session = replace(entry.session, state="faulted", error=failure.code)
            raise failure from error
        except BaseException:
            with self._lock:
                entry.error = InspectorUnavailableError(
                    "Inspector attachment failed", code="attachFailed"
                )
                entry.session = replace(entry.session, state="faulted", error=entry.error.code)
            raise
        finally:
            entry.done.set()

    def _attach_owned(
        self, identity: ProcessIdentity, target_hwnd: int | None, deadline: float, entry: _Entry
    ) -> InspectorClient:
        _remaining(deadline, entry.cancel)
        facts = probe.identify(identity.pid)
        _validate_facts(facts, identity)
        _validate_hwnd(target_hwnd, identity.pid)
        _remaining(deadline, entry.cancel)
        if probe.agent_active(identity.pid):
            raise InspectorUnavailableError(
                "An inspector is already attached to this process", code="alreadyAttached"
            )
        payload = self._payload_loader()
        payload.verify()
        executable = _payload_path(payload, payload.launcher_for(cast(Any, facts.architecture)))
        agent = _payload_path(payload, payload.agent_for(cast(Any, facts.runtime)))
        _remaining(deadline, entry.cancel)
        settings = bootstrap.create_bootstrap(
            identity,
            facts.user_sid,
            payload.inspector_version,
            request_timeout_ms=max(1, int(self._request_timeout * 1000)),
            redact_names=self._redact_names,
        )
        process = None
        client = None
        pipe = None
        try:
            with self._lock:
                entry.session = replace(
                    entry.session, session_id=settings.session_id, state="attaching"
                )
            _remaining(deadline, entry.cancel)
            if probe.current_identity(identity.pid) != identity:
                raise InspectorUnavailableError(
                    "Target process identity changed", code="processReused"
                )
            process = launcher.launch(executable, agent, identity, settings.path)

            def check() -> None:
                _remaining(deadline, entry.cancel)
                assert process is not None
                launcher.policy_failure(process, executable)

            pipe = WindowsPipe.connect(settings.pipe_name, identity, deadline, check=check)
            client = InspectorClient.authenticate(
                pipe,
                facts,
                settings.session_id,
                settings.token,
                payload.inspector_version,
                deadline=deadline,
                request_timeout=self._request_timeout,
                on_closed=lambda closed: self._client_closed(identity, entry, closed),
            )
            _remaining(deadline, entry.cancel)
            if settings.path.exists():
                raise InspectorUnavailableError(
                    "Inspector did not consume its bootstrap file", code="authenticationFailed"
                )
            if probe.current_identity(identity.pid) != identity:
                raise InspectorUnavailableError(
                    "Target process identity changed", code="processReused"
                )
            return client
        except BaseException:
            if client is not None:
                client.close()
            elif pipe is not None:
                pipe.close()
            if process is not None:
                launcher.policy_failure(process, executable)
            raise
        finally:
            try:
                try:
                    if process is not None:
                        launcher.close_launcher(process)
                finally:
                    settings.cleanup()
            except BaseException:
                if client is not None:
                    client.close()
                raise

    def _client_closed(
        self, identity: ProcessIdentity, entry: _Entry, client: InspectorClient
    ) -> None:
        client.session = _disconnected_session(client.session)
        with self._lock:
            if self._entries.get(identity) is entry:
                entry.session = client.session
                entry.client = None

    def get(self, identity: ProcessIdentity) -> InspectorClient | None:
        with self._lock:
            entry = self._entries.get(identity)
            client = entry.client if entry is not None else None
        if client is None or client.session.state != "ready":
            return None
        try:
            if probe.current_identity(identity.pid) != identity:
                client.invalidate(
                    InspectorUnavailableError(
                        "Target process identity changed", code="processReused"
                    ),
                    "exited",
                )
                return None
        except InspectorUnavailableError as error:
            client.invalidate(error, "exited" if error.code == "processExited" else "faulted")
            return None
        return client

    def status(self, identity: ProcessIdentity) -> Session:
        self.get(identity)
        with self._lock:
            entry = self._entries.get(identity)
            session = (
                entry.client.session
                if entry is not None and entry.client is not None
                else (
                    entry.session
                    if entry is not None
                    else Session("detached", identity, "detached", 1, 0, ())
                )
            )
        refreshed = _disconnected_session(session)
        if refreshed is not session:
            with self._lock:
                if entry is not None and self._entries.get(identity) is entry:
                    if entry.client is not None and entry.client.session is session:
                        entry.client.session = refreshed
                    if entry.session is session:
                        entry.session = refreshed
        return refreshed

    def detach(self, session_id: str) -> None:
        with self._lock:
            entry = next(
                (item for item in self._entries.values() if item.session.session_id == session_id),
                None,
            )
            if entry is None:
                return
            entry.cancel.set()
            client = entry.client
            if client is not None:
                entry.session = replace(client.session, state="detaching")
        if client is not None:
            client.close()
        elif not entry.done.is_set():
            entry.done.wait(10.0)

    def close_all(self) -> None:
        with self._lock:
            entries = tuple(self._entries.values())
            for entry in entries:
                entry.cancel.set()
        for entry in entries:
            if entry.client is not None:
                entry.client.close()
            elif not entry.done.is_set():
                entry.done.wait(10.0)
