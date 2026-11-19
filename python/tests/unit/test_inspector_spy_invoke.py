"""Private capability-gated Spy invocation transport."""

import base64
import json
import time
from dataclasses import replace
from pathlib import Path

import pytest
from test_inspector_client import IDENTITY, ScriptedTransport, session
from test_inspector_writes import REF, audit

from wintestkit.errors import InspectorError, InspectorUnavailableError, WriteDeniedError
from wintestkit.inspector import bootstrap, probe, sessions
from wintestkit.inspector.client import InspectorClient
from wintestkit.inspector.models import BootstrapSettings

CAPABILITY = base64.b64encode(bytes(range(32))).decode("ascii")
RESULT = {
    "status": "ok",
    "kind": "null",
    "declaredType": "System.Void",
    "runtimeType": "",
    "scalar": None,
}


def test_default_denies_without_dispatch():
    transport = ScriptedTransport(lambda req: None)
    client = InspectorClient(transport, session())
    try:
        assert not client._spy_invoke_available
        with pytest.raises(InspectorUnavailableError):
            client._spy_invoke(REF, "M", [], timeout_ms=100, deadline=time.monotonic() + 1)
        assert not transport.requests
    finally:
        client.invalidate(InspectorError("done", code="cancelled"))


def test_authenticated_wire_and_success():
    transport = ScriptedTransport(
        lambda req: {"id": req["id"], "result": {"audit": audit("call"), "result": RESULT}}
    )
    client = InspectorClient(transport, session(), spy_invoke_capability=CAPABILITY)
    args = [
        {"type": "System.String", "value": "hello"},
        {"type": "E", "enum": 1},
        {"type": "T", "null": True},
    ]
    try:
        assert client._spy_invoke_available
        result_audit, result = client._spy_invoke(
            REF, "x" * 8192, args, timeout_ms=500, deadline=time.monotonic() + 1
        )
        assert result_audit.operation == "call" and result.kind == "null"
        req = transport.requests[0]
        assert req["method"] == "spy.invoke"
        assert req["params"] == {
            "capability": CAPABILITY,
            "handle": REF.to_json(),
            "memberKey": "x" * 8192,
            "arguments": args,
            "timeoutMs": req["params"]["timeoutMs"],
        }
        assert 1 <= req["params"]["timeoutMs"] <= 500
        assert CAPABILITY not in repr(client) and CAPABILITY not in repr(client.session)
    finally:
        client.close()


@pytest.mark.parametrize(
    "ref,key,args",
    [
        (replace(REF, session_id="other"), "M", []),
        (REF, "", []),
        (REF, "x" * 8193, []),
        (REF, "M", [{}]),
        (REF, "M", [{"type": "T", "null": False}]),
        (REF, "M", [{"type": "T", "value": None}]),
        (REF, "M", [{"type": "T", "value": float("nan")}]),
        (REF, "M", [{"type": "T", "enum": True}]),
        (REF, "M", [{"type": "T", "value": 1, "enum": 1}]),
        (REF, "M", [{"type": "T", "value": 1}] * 17),
    ],
)
def test_invalid_requests_not_dispatched(ref, key, args):
    transport = ScriptedTransport(lambda req: None)
    client = InspectorClient(transport, session(), spy_invoke_capability=CAPABILITY)
    try:
        with pytest.raises(InspectorError) as error:
            client._spy_invoke(ref, key, args, timeout_ms=100, deadline=time.monotonic() + 1)
        assert error.value.code == "invalidParams" and not transport.requests
    finally:
        client.invalidate(InspectorError("done", code="cancelled"))


def test_failure_is_sanitized_and_preserves_audit():
    transport = ScriptedTransport(
        lambda req: {
            "id": req["id"],
            "error": {
                "code": "writeDenied",
                "message": CAPABILITY,
                "details": {"audit": audit("call", "denied")},
            },
        }
    )
    client = InspectorClient(transport, session(), spy_invoke_capability=CAPABILITY)
    try:
        with pytest.raises(WriteDeniedError) as error:
            client._spy_invoke(REF, "M", [], timeout_ms=100, deadline=time.monotonic() + 1)
        assert error.value.audit.outcome == "denied"
        assert CAPABILITY not in str(error.value)
    finally:
        client.close()


@pytest.mark.parametrize(
    "result",
    [
        {"audit": audit("call", "denied"), "result": RESULT},
        {"audit": audit("setProperty"), "result": RESULT},
        {"audit": audit("call"), "result": {"status": "ok"}},
        {"audit": audit("call"), "result": RESULT, "extra": True},
    ],
)
def test_invalid_success_is_rejected(result):
    transport = ScriptedTransport(lambda req: {"id": req["id"], "result": result})
    client = InspectorClient(transport, session(), spy_invoke_capability=CAPABILITY)
    try:
        with pytest.raises(InspectorError):
            client._spy_invoke(REF, "M", [], timeout_ms=100, deadline=time.monotonic() + 1)
    finally:
        client.close()


def test_bootstrap_capabilities_are_independent(monkeypatch, tmp_path):
    monkeypatch.setattr(bootstrap, "_local_app_data", lambda: tmp_path)
    sid, _, _ = probe.current_security()
    first = bootstrap.create_bootstrap(IDENTITY, sid, "1", spy_invoke=True)
    second = bootstrap.create_bootstrap(IDENTITY, sid, "1", spy_invoke=True)
    try:
        documents = [json.loads(item.path.read_text(encoding="utf-8")) for item in (first, second)]
        for item, document in zip((first, second), documents, strict=True):
            capability = document["spyInvokeCapability"]
            assert capability == item.spy_invoke_capability and capability != document["token"]
            assert len(base64.b64decode(capability, validate=True)) == 32
            parsed = BootstrapSettings.from_json(document)
            assert (
                parsed.to_json()["spyInvokeCapability"] == capability
                and capability not in repr(parsed)
                and capability not in repr(item)
            )
        assert first.spy_invoke_capability != second.spy_invoke_capability
    finally:
        first.cleanup()
        second.cleanup()


@pytest.mark.parametrize("capability", [None, "A" * 43 + "=", "bad", "A" * 44])
def test_invalid_capability_rejected(capability):
    path = (
        Path(__file__).resolve().parents[3] / "wpf-inspector/protocol/fixtures/valid/bootstrap.json"
    )
    document = json.loads(path.read_text(encoding="utf-8"))["instance"]
    if capability == "A" * 43 + "=":
        capability = "A" * 42 + "B="
    with pytest.raises(ValueError):
        BootstrapSettings.from_json({**document, "spyInvokeCapability": capability})


def test_opt_in_does_not_upgrade_existing(monkeypatch):
    registry = sessions.SessionRegistry()
    client = InspectorClient(
        ScriptedTransport(lambda req: {"id": req["id"], "result": {"closed": True}}), session()
    )
    monkeypatch.setattr(registry, "_attach_owned", lambda *args: client)
    monkeypatch.setattr(probe, "current_identity", lambda pid: IDENTITY)
    try:
        assert registry.attach(IDENTITY, target_hwnd=None, deadline=time.monotonic() + 1) is client
        assert (
            registry.attach(
                IDENTITY, target_hwnd=None, deadline=time.monotonic() + 1, spy_invoke=True
            )
            is client
        )
        assert not client._spy_invoke_available
    finally:
        registry.detach("session")


def test_new_opted_in_registry_attach_passes_flag(monkeypatch):
    registry = sessions.SessionRegistry()
    client = InspectorClient(
        ScriptedTransport(lambda req: {"id": req["id"], "result": {"closed": True}}),
        session(),
        spy_invoke_capability=CAPABILITY,
    )
    options = []

    def attach(*args, **kwargs):
        options.append(kwargs)
        return client

    monkeypatch.setattr(registry, "_attach_owned", attach)
    try:
        assert (
            registry.attach(
                IDENTITY, target_hwnd=None, deadline=time.monotonic() + 1, spy_invoke=True
            )
            is client
        )
        assert options == [{"spy_invoke": True}]
        assert client._spy_invoke_available
    finally:
        registry.detach("session")
