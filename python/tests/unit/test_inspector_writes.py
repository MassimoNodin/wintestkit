"""Protocol write requests and safe audit propagation."""

import time
from dataclasses import replace

import pytest
from test_inspector_client import ScriptedTransport, session

from wintestkit.errors import (
    InspectorDeadlineError,
    InspectorError,
    InspectorUnavailableError,
    WriteDeniedError,
)
from wintestkit.inspector.client import InspectorClient
from wintestkit.inspector.models import ObjectRef, TypeInfo, WriteAudit

REF = ObjectRef("session", "object", 1, TypeInfo("T", "T", "App", "T", ()), "dispatcher")


def audit(operation: str, outcome: str = "performed") -> dict:
    return {
        "operation": operation,
        "typeFullName": "T",
        "memberKey": "M",
        "outcome": outcome,
        "timestampUtc": "2026-01-01T00:00:00Z",
    }


@pytest.mark.parametrize(
    "method,operation,argument,field",
    [
        ("write_set_property", "setProperty", "secret", "value"),
        ("write_call", "call", [True, 12, 1.5, "secret"], "arguments"),
    ],
)
def test_write_wire_and_feature(method, operation, argument, field):
    transport = ScriptedTransport(
        lambda req: {"id": req["id"], "result": {"audit": audit(operation)}}
    )
    client = InspectorClient(transport, session())
    try:
        result = getattr(client, method)(
            REF, "M", argument, timeout_ms=500, deadline=time.monotonic() + 1
        )
        assert result == WriteAudit.from_json(audit(operation))
        request = transport.requests[0]
        assert request["method"] == "write." + operation
        assert request["params"][field] == argument
        assert request["params"]["handle"] == REF.to_json()
        assert request["params"]["memberKey"] == "M"
        assert 1 <= request["params"]["timeoutMs"] <= 500
        client.session = replace(client.session, features=())
        with pytest.raises(InspectorUnavailableError):
            getattr(client, method)(
                REF, "M", argument, timeout_ms=500, deadline=time.monotonic() + 1
            )
        assert len(transport.requests) == 1
    finally:
        client.close()


@pytest.mark.parametrize(
    "method,value",
    [
        ("write_set_property", None),
        ("write_set_property", float("nan")),
        ("write_set_property", "x" * 4097),
        ("write_set_property", "\ud800"),
        ("write_call", [None]),
        ("write_call", [float("inf")]),
        ("write_call", [1] * 17),
        ("write_call", "not a sequence of arguments"),
    ],
)
def test_invalid_scalars_are_not_sent(method, value):
    transport = ScriptedTransport(lambda req: None)
    client = InspectorClient(transport, session())
    try:
        with pytest.raises(InspectorError, match="Invalid write") as error:
            getattr(client, method)(REF, "M", value, timeout_ms=100, deadline=time.monotonic() + 1)
        assert error.value.code == "invalidParams"
        assert error.value.audit is None
        assert not transport.requests
    finally:
        client.invalidate(InspectorError("done", code="cancelled"))


@pytest.mark.parametrize(
    "method,operation", [("write_set_property", "setProperty"), ("write_call", "call")]
)
@pytest.mark.parametrize(
    "value,valid", [(-(2**63), True), (2**63 - 1, True), (-(2**63) - 1, False), (2**63, False)]
)
def test_write_integer_boundaries(method, operation, value, valid):
    transport = ScriptedTransport(
        lambda req: {"id": req["id"], "result": {"audit": audit(operation)}}
    )
    client = InspectorClient(transport, session())
    argument = [value] if method == "write_call" else value
    try:
        if valid:
            getattr(client, method)(
                REF, "M", argument, timeout_ms=100, deadline=time.monotonic() + 1
            )
            assert len(transport.requests) == 1
        else:
            with pytest.raises(InspectorError) as error:
                getattr(client, method)(
                    REF, "M", argument, timeout_ms=100, deadline=time.monotonic() + 1
                )
            assert error.value.code == "invalidParams"
            assert not transport.requests
    finally:
        client.close()


@pytest.mark.parametrize(
    "code,outcome",
    [
        ("writeDenied", "denied"),
        ("writeRateExceeded", "denied"),
        ("internalError", "failed"),
        ("timeout", "failed"),
    ],
)
def test_error_audit_is_parsed_without_values(code, outcome, caplog):
    record = audit("call", outcome)
    transport = ScriptedTransport(
        lambda req: {
            "id": req["id"],
            "error": {"code": code, "message": "secret", "details": {"audit": record}},
        }
    )
    client = InspectorClient(transport, session())
    try:
        with pytest.raises(
            InspectorDeadlineError if code == "timeout" else InspectorError
        ) as error:
            client.write_call(REF, "M", ["secret"], timeout_ms=100, deadline=time.monotonic() + 1)
        assert error.value.audit == WriteAudit.from_json(record)
        if code == "writeDenied":
            assert isinstance(error.value, WriteDeniedError)
        assert "secret" not in str(error.value) and "secret" not in caplog.text
        assert len(transport.requests) == 1
    finally:
        client.close()


def test_malformed_error_audit_faults_session():
    record = {**audit("call", "failed"), "value": "secret"}
    transport = ScriptedTransport(
        lambda req: {
            "id": req["id"],
            "error": {"code": "internalError", "message": "secret", "details": {"audit": record}},
        }
    )
    client = InspectorClient(transport, session())
    with pytest.raises(InspectorUnavailableError) as error:
        client.write_call(REF, "M", ["secret"], timeout_ms=100, deadline=time.monotonic() + 1)
    assert error.value.audit is None
    assert "secret" not in str(error.value)


def test_error_constructors_accept_audit():
    record = WriteAudit.from_json(audit("call", "denied"))
    assert WriteDeniedError("denied", code="writeDenied", audit=record).audit is record
    assert InspectorDeadlineError("timeout", code="timeout", audit=record).audit is record
    assert InspectorError("error", code="internalError").audit is None
