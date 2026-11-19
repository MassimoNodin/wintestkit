import base64
import io
from typing import Any

import pytest
import test_managed_server
from test_managed_server import IDENTITY, REF, request

from wintestkit import runtime
from wintestkit.inspector.models import Value, WriteAudit
from wintestkit.server import Server

CAPABILITY = base64.b64encode(b"x" * 32).decode()
OTHER = base64.b64encode(b"y" * 32).decode()


def test_invalid_capability_rejected() -> None:
    with pytest.raises(ValueError):
        Server(io.BytesIO(), spy_host_capability="not a capability")


managed_server = test_managed_server.managed_server


def test_gate_lifecycle(managed_server: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    server, output, client = managed_server
    server._spy_host_capability = b"x" * 32
    client._spy_invoke_available = True
    calls: list[Any] = []

    def invoke(ref: Any, key: str, arguments: Any, **kwargs: Any) -> Any:
        calls.append((ref, key, arguments))
        return (
            WriteAudit("call", "Test.Window", key, "performed", "2026-01-01T00:00:00Z"),
            Value("ok", "string", "String", "String", "done"),
        )

    client._spy_invoke = invoke
    attach_calls: list[Any] = []
    monkeypatch.setattr(
        runtime, "attach_managed", lambda *args, **kwargs: attach_calls.append(kwargs) or client
    )
    attach = {"process": IDENTITY.to_json()}
    assert "result" in request(server, output, "inspect.managed.attach", attach)
    assert "spy_invoke" not in attach_calls[-1]
    assert "error" in request(
        server, output, "inspect.managed.attach", {**attach, "hostCapability": OTHER}
    )
    assert len(attach_calls) == 1
    assert "result" in request(
        server, output, "inspect.managed.attach", {**attach, "hostCapability": CAPABILITY}
    )
    assert attach_calls[-1]["spy_invoke"] is True
    select = {"hostCapability": CAPABILITY, "sessionId": "session", "nodeId": "node"}
    prepare = {
        "hostCapability": CAPABILITY,
        "sessionId": "session",
        "objectId": "object",
        "generation": 1,
        "memberKey": "method",
        "arguments": [{"type": "System.Int32", "value": 3}],
    }
    assert "error" in request(server, output, "inspect.managed.spyPrepareInvoke", prepare)
    assert request(server, output, "inspect.managed.spySelect", select)["result"]["canInvoke"]
    assert "error" in request(
        server, output, "inspect.managed.spyPrepareInvoke", {**prepare, "objectId": "other"}
    )
    ticket = request(server, output, "inspect.managed.spyPrepareInvoke", prepare)["result"][
        "ticket"
    ]
    assert "error" in request(
        server, output, "inspect.managed.spyInvoke", {"hostCapability": OTHER, "ticket": ticket}
    )
    assert "result" in request(
        server,
        output,
        "inspect.managed.spyInvoke",
        {"hostCapability": CAPABILITY, "ticket": ticket},
    )
    assert calls == [(REF, "method", prepare["arguments"])]
    assert "error" in request(
        server,
        output,
        "inspect.managed.spyInvoke",
        {"hostCapability": CAPABILITY, "ticket": ticket},
    )
    ticket = request(server, output, "inspect.managed.spyPrepareInvoke", prepare)["result"][
        "ticket"
    ]
    assert "error" in request(server, output, "inspect.managed.spySelect", {**select, "nodeId": ""})
    assert "error" in request(
        server,
        output,
        "inspect.managed.spyInvoke",
        {"hostCapability": CAPABILITY, "ticket": ticket},
    )
    request(server, output, "inspect.managed.spySelect", select)
    assert "error" in request(
        server,
        output,
        "inspect.managed.spyInvoke",
        {"hostCapability": CAPABILITY, "ticket": ticket},
    )
    ticket = request(server, output, "inspect.managed.spyPrepareInvoke", prepare)["result"][
        "ticket"
    ]
    request(
        server, output, "inspect.managed.release", {"sessionId": "session", "objectIds": ["object"]}
    )
    assert "error" in request(
        server,
        output,
        "inspect.managed.spyInvoke",
        {"hostCapability": CAPABILITY, "ticket": ticket},
    )
    assert len(calls) == 1


def test_default_denies_privileged_requests(managed_server: Any) -> None:
    server, output, client = managed_server
    response = request(
        server,
        output,
        "inspect.managed.spySelect",
        {"hostCapability": CAPABILITY, "sessionId": "session", "nodeId": "node"},
    )
    assert "error" in response
    assert client.calls == []


def test_reused_read_only_session(managed_server: Any) -> None:
    server, output, client = managed_server
    server._spy_host_capability = b"x" * 32
    request(server, output, "inspect.managed.attach", {"process": IDENTITY.to_json()})
    request(
        server,
        output,
        "inspect.managed.attach",
        {"process": IDENTITY.to_json(), "hostCapability": CAPABILITY},
    )
    result = request(
        server,
        output,
        "inspect.managed.spySelect",
        {"hostCapability": CAPABILITY, "sessionId": "session", "nodeId": "node"},
    )["result"]
    assert result["canInvoke"] is False
    assert not client.closed
    assert "error" in request(
        server,
        output,
        "inspect.managed.spyPrepareInvoke",
        {
            "hostCapability": CAPABILITY,
            "sessionId": "session",
            "objectId": "object",
            "generation": 1,
            "memberKey": "method",
            "arguments": [],
        },
    )


def test_expiry_failure_and_detach(managed_server: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    server, output, client = managed_server
    server._spy_host_capability = b"x" * 32
    client._spy_invoke_available = True
    calls: list[Any] = []

    def fail(*args: Any, **kwargs: Any) -> Any:
        calls.append(args)
        raise RuntimeError("secret application data")

    client._spy_invoke = fail
    request(server, output, "inspect.managed.attach", {"process": IDENTITY.to_json()})
    select = {"hostCapability": CAPABILITY, "sessionId": "session", "nodeId": "node"}
    prepare = {
        "hostCapability": CAPABILITY,
        "sessionId": "session",
        "objectId": "object",
        "generation": 1,
        "memberKey": "method",
        "arguments": [],
    }
    request(server, output, "inspect.managed.spySelect", select)
    for invalid in ([{"type": "x", "value": 2**63}], [{"type": "x", "null": False}], [{}] * 17):
        assert "error" in request(
            server, output, "inspect.managed.spyPrepareInvoke", {**prepare, "arguments": invalid}
        )
    ticket = request(server, output, "inspect.managed.spyPrepareInvoke", prepare)["result"][
        "ticket"
    ]
    token, _, selected_client, ref, key, arguments = server._spy_ticket
    server._spy_ticket = (token, 0, selected_client, ref, key, arguments)
    assert "error" in request(
        server,
        output,
        "inspect.managed.spyInvoke",
        {"hostCapability": CAPABILITY, "ticket": ticket},
    )
    assert calls == []
    ticket = request(server, output, "inspect.managed.spyPrepareInvoke", prepare)["result"][
        "ticket"
    ]
    response = request(
        server,
        output,
        "inspect.managed.spyInvoke",
        {"hostCapability": CAPABILITY, "ticket": ticket},
    )
    assert "secret" not in str(response)
    assert "error" in request(
        server,
        output,
        "inspect.managed.spyInvoke",
        {"hostCapability": CAPABILITY, "ticket": ticket},
    )
    assert len(calls) == 1
    ticket = request(server, output, "inspect.managed.spyPrepareInvoke", prepare)["result"][
        "ticket"
    ]
    monkeypatch.setattr(
        client,
        "resolve",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("failed resolve")),
    )
    assert "error" in request(server, output, "inspect.managed.spySelect", select)
    assert "error" in request(
        server,
        output,
        "inspect.managed.spyInvoke",
        {"hostCapability": CAPABILITY, "ticket": ticket},
    )
    request(server, output, "inspect.managed.detach", {"sessionId": "session"})
    assert client.closed
