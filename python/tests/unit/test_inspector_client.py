"""Authenticated client behavior with an injectable, concurrent byte transport."""

from __future__ import annotations

import json
import struct
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from wintestkit.errors import InspectorError, InspectorUnavailableError
from wintestkit.inspector.client import InspectorClient
from wintestkit.inspector.models import (
    FEATURES,
    HelloResult,
    ProcessFacts,
    ProcessIdentity,
    Session,
)
from wintestkit.inspector.paths import parse_managed_key

IDENTITY = ProcessIdentity(42, "2026-10-29T00:00:00.1234567Z")
FACTS = ProcessFacts(IDENTITY, "app.exe", "x64", "net10", True, 1, "S-1-1", "medium")
TOKEN = "A" * 43 + "="


class ScriptedTransport:
    def __init__(self, handler: Callable[[dict[str, Any]], object | None]) -> None:
        self.handler = handler
        self.condition = threading.Condition()
        self.buffer = bytearray()
        self.requests: list[dict[str, Any]] = []
        self.closed = False

    def feed(self, value: object) -> None:
        data = json.dumps(value).encode()
        with self.condition:
            self.buffer.extend(struct.pack("<I", len(data)) + data)
            self.condition.notify_all()

    def read_exact(self, size: int, deadline: float) -> bytes:
        with self.condition:
            while len(self.buffer) < size:
                if self.closed:
                    raise EOFError("closed")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("deadline")
                self.condition.wait(remaining)
            result = bytes(self.buffer[:size])
            del self.buffer[:size]
            return result

    def write(self, data: bytes, deadline: float) -> None:
        if deadline <= time.monotonic():
            raise TimeoutError("deadline")
        request = json.loads(data[4:])
        with self.condition:
            self.requests.append(request)
        response = self.handler(request)
        if response is not None:
            self.feed(response)

    def close(self) -> None:
        with self.condition:
            self.closed = True
            self.condition.notify_all()


def hello(**changes: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "agentVersion": "1",
        "tfm": "net10.0-windows",
        "architecture": "x64",
        "runtimeVersion": "10.0.11",
        "features": sorted(FEATURES),
        "process": IDENTITY.to_json(),
    }
    result.update(changes)
    return result


def session() -> Session:
    return Session("session", IDENTITY, "ready", 2, 0, tuple(FEATURES), "10.0.11", "x64", "1")


def page() -> dict[str, object]:
    return {"items": [], "complete": True, "snapshotId": "snapshot", "diagnostics": []}


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"agentVersion": "old"}, "agentVersionMismatch"),
        ({"architecture": "x86"}, "unsupportedTarget"),
        ({"tfm": "net8.0-windows"}, "unsupportedTarget"),
        ({"runtimeVersion": "8.0.1"}, "unsupportedTarget"),
        (
            {"process": {"pid": 42, "creationTimeUtc": "2026-10-29T00:00:00.1234568Z"}},
            "processReused",
        ),
        ({"extra": True}, "authenticationFailed"),
    ],
)
def test_hello_rejects_mismatch_without_leaking_token(
    changes: dict[str, object], code: str
) -> None:
    transport = ScriptedTransport(lambda request: {"id": request["id"], "result": hello(**changes)})
    with pytest.raises(InspectorUnavailableError) as error:
        InspectorClient.authenticate(
            transport, FACTS, "session", TOKEN, "1", deadline=time.monotonic() + 1
        )
    assert error.value.code == code and TOKEN not in str(error.value)
    assert transport.closed


def test_hello_requires_correct_id_and_checks_features_per_operation() -> None:
    transport = ScriptedTransport(lambda request: {"id": 9, "result": hello()})
    with pytest.raises(InspectorUnavailableError, match="hello"):
        InspectorClient.authenticate(
            transport, FACTS, "session", TOKEN, "1", deadline=time.monotonic() + 1
        )
    transport = ScriptedTransport(
        lambda request: {"id": request["id"], "result": hello(features=[])}
    )
    client = InspectorClient.authenticate(
        transport, FACTS, "session", TOKEN, "1", deadline=time.monotonic() + 1
    )
    try:
        with pytest.raises(InspectorUnavailableError) as error:
            client.resolve((1,), None, deadline=time.monotonic() + 1)
        assert error.value.code == "unsupportedTarget"
        assert len(transport.requests) == 1
    finally:
        client.close()


def test_timeout_cancels_and_discards_late_response() -> None:
    cancel = threading.Event()

    def handle(request: dict[str, Any]) -> object | None:
        if request["method"] == "request.cancel":
            cancel.set()
            return {"id": request["id"], "result": {"accepted": True}}
        if request["method"] == "roots" and request["id"] > 2:
            return {"id": request["id"], "result": page()}
        if request["method"] == "session.close":
            return {"id": request["id"], "result": {"closed": True}}
        return None

    transport = ScriptedTransport(handle)
    client = InspectorClient(transport, session(), request_timeout=0.1)
    try:
        with pytest.raises(InspectorError) as error:
            client.roots(deadline=time.monotonic() + 1)
        assert error.value.code == "timeout"
        assert cancel.wait(1)
        transport.feed({"id": 2, "result": page()})
        assert client.roots(deadline=time.monotonic() + 1).complete
        requests = transport.requests
        assert any(
            item["method"] == "request.cancel" and item["params"] == {"requestId": 2}
            for item in requests
        )
        assert [item["id"] for item in requests] == sorted(item["id"] for item in requests)
    finally:
        client.close()


def test_concurrent_out_of_order_responses_are_matched() -> None:
    two = threading.Event()

    def handle(request: dict[str, Any]) -> object | None:
        if request["method"] == "session.close":
            return {"id": request["id"], "result": {"closed": True}}
        if len(transport.requests) == 2:
            two.set()
        return None

    transport = ScriptedTransport(handle)
    client = InspectorClient(transport, session())
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(client.roots, deadline=time.monotonic() + 1) for _ in range(2)
            ]
            assert two.wait(1)
            ids = [request["id"] for request in transport.requests]
            for request_id in reversed(ids):
                transport.feed({"id": request_id, "result": page()})
            assert all(future.result().complete for future in futures)
    finally:
        client.close()


def test_unexpected_id_and_unknown_fields_fault_session() -> None:
    transport = ScriptedTransport(lambda request: {"id": request["id"] + 1, "result": page()})
    client = InspectorClient(transport, session())
    with pytest.raises(InspectorUnavailableError) as error:
        client.roots(deadline=time.monotonic() + 1)
    assert error.value.code == "sessionStale" and transport.closed
    transport = ScriptedTransport(
        lambda request: {"id": request["id"], "result": {**page(), "unknown": 1}}
    )
    client = InspectorClient(transport, session())
    with pytest.raises(InspectorUnavailableError):
        client.roots(deadline=time.monotonic() + 1)
    assert client.session.state == "faulted" and transport.closed


def test_batch_checks_path_features_before_sending() -> None:
    transport = ScriptedTransport(lambda request: {"id": request["id"], "result": {"closed": True}})
    limited = Session("session", IDENTITY, "ready", 2, 0, ("exactUiaMapping", "batchReads"))
    client = InspectorClient(transport, limited)
    try:
        with pytest.raises(InspectorUnavailableError) as error:
            client.read_batch(
                [((1,), None)], [parse_managed_key("clr:Name")], deadline=time.monotonic() + 1
            )
        assert error.value.code == "unsupportedTarget" and not transport.requests
    finally:
        client.close()


def test_unexpected_hello_failure_closes_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = ScriptedTransport(lambda request: {"id": request["id"], "result": hello()})

    def fail(value: object) -> Any:
        raise RuntimeError("unexpected parser failure")

    monkeypatch.setattr(HelloResult, "from_json", fail)
    with pytest.raises(RuntimeError):
        InspectorClient.authenticate(
            transport, FACTS, "session", TOKEN, "1", deadline=time.monotonic() + 1
        )
    assert transport.closed
