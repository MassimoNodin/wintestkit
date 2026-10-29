"""Public managed RPC execution, validation, session ownership and schemas (fake agent)."""

import io
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from wintestkit import runtime
from wintestkit.config import load_config
from wintestkit.errors import InspectorUnavailableError
from wintestkit.inspector import payload, probe
from wintestkit.inspector.models import (
    ManagedNode,
    Mapping,
    ObjectRef,
    Page,
    PathValue,
    ProcessFacts,
    ProcessIdentity,
    Session,
    TypeInfo,
    Value,
)
from wintestkit.server import Server
from wintestkit.targets import ModuleLoader

ROOT = Path(__file__).resolve().parents[3]
IDENTITY = ProcessIdentity(42, "2026-01-01T00:00:00Z")
TYPE = TypeInfo("Window", "Test.Window", "Test", "Test.Window, Test", ())
REF = ObjectRef("session", "object", 1, TYPE, "dispatcher")
SESSION = Session("session", IDENTITY, "ready", 1, 0, ("typeMetadata", "clrMembers"))


def _identity(pid: int) -> ProcessIdentity:
    return IDENTITY


def _facts(pid: int) -> ProcessFacts:
    return ProcessFacts(IDENTITY, "app.exe", "x64", "net10", True, 1, "sid", "medium")


def _unexpected_probe(pid: int) -> Any:
    pytest.fail("unexpected probe")


def _element_identity(node: Any) -> tuple[tuple[int, ...], None]:
    return (1, 2), None


def _node(node_id: str) -> Any:
    return SimpleNamespace(process_id=42)


class FakeClient:
    def __init__(self) -> None:
        self.session = SESSION
        self.calls: list[tuple[str, Any]] = []
        self.closed = False

    def resolve(self, runtime_id: Any, hwnd: Any, **kwargs: Any) -> Mapping:
        self.calls.append(("resolve", (runtime_id, hwnd)))
        return Mapping("exact", IDENTITY, runtime_id, REF)

    def roots(self, **kwargs: Any) -> Page[ManagedNode]:
        self.calls.append(("roots", kwargs))
        return Page((ManagedNode(REF, "Window", True, False),), True, "snapshot", ())

    def children(self, object_id: str, generation: int, tree: str, **kwargs: Any) -> Page[Any]:
        self.calls.append(("children", (object_id, generation, tree, kwargs)))
        return Page((), True, "snapshot", ())

    def members(self, object_id: str, generation: int, **kwargs: Any) -> Page[Any]:
        self.calls.append(("members", (object_id, generation, kwargs)))
        return Page((), True, "snapshot", ())

    def read(self, object_id: str, generation: int, paths: Any, **kwargs: Any) -> Any:
        self.calls.append(("read", (object_id, generation, paths)))
        return (
            tuple(
                PathValue(path, Value("ok", "string", "String", "String", "Window"))
                for path in paths
            ),
            "read",
        )

    def bindings(self, object_id: str, generation: int, keys: Any, **kwargs: Any) -> Any:
        self.calls.append(("bindings", (object_id, generation, keys)))
        return ()

    def release(self, object_ids: Any, **kwargs: Any) -> int:
        self.calls.append(("release", list(object_ids)))
        return len(object_ids)

    def close(self) -> None:
        self.closed = True


class FakeRegistry:
    def __init__(self, client: FakeClient) -> None:
        self.client = client

    def get(self, identity: ProcessIdentity) -> Any:
        return self.client if identity == IDENTITY and not self.client.closed else None

    def status(self, identity: ProcessIdentity) -> Session:
        return self.client.session


def request(
    server: Server, output: io.BytesIO, method: str, params: dict[str, Any]
) -> dict[str, Any]:
    output.seek(0)
    output.truncate()
    server.handle({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    return json.loads(output.getvalue())


@pytest.fixture
def managed_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    runtime.reset()
    output = io.BytesIO()
    server = Server(output)
    server.cfg = load_config(
        tmp_path, {"inspector.enabled": True, "inspector.request_timeout": 0.5}
    )
    server.loader = ModuleLoader(server.cfg)
    client = FakeClient()
    registry = FakeRegistry(client)

    def attach(*args: Any, **kwargs: Any) -> FakeClient:
        return client

    monkeypatch.setattr(runtime, "inspector_sessions", lambda: registry)
    monkeypatch.setattr(runtime, "attach_managed", attach)
    monkeypatch.setattr(runtime, "managed_element_identity", _element_identity)
    monkeypatch.setattr(server, "_node", _node)
    monkeypatch.setattr(probe, "current_identity", _identity)
    monkeypatch.setattr(probe, "identify", _facts)
    yield server, output, client
    runtime.reset()


@pytest.fixture(scope="module")
def schema_registry() -> Registry[Any]:
    paths = [
        *sorted((ROOT / "schemas").glob("*.schema.json")),
        ROOT / "wpf-inspector/protocol/inspector.schema.json",
    ]
    documents = [json.loads(path.read_text(encoding="utf-8-sig")) for path in paths]
    return Registry[Any]().with_resources(
        (doc["$id"], Resource.from_contents(doc)) for doc in documents
    )


def test_every_managed_rpc_returns_its_declared_schema(
    managed_server: Any, schema_registry: Registry[Any]
) -> None:
    server, output, client = managed_server
    process = IDENTITY.to_json()
    obj = {"sessionId": "session", "objectId": "object", "generation": 1}
    cases = [
        ("identify", {"nodeId": "n"}),
        ("attach", {"process": process}),
        ("status", {"process": process}),
        ("resolve", {"sessionId": "session", "nodeId": "n"}),
        ("roots", {"sessionId": "session", "pageSize": 3}),
        ("children", {**obj, "tree": "visual", "pageToken": "next"}),
        ("members", obj),
        ("read", {**obj, "paths": [[{"kind": "type", "name": "Name"}]]}),
        ("bindings", {**obj, "memberKeys": ["key"]}),
        ("release", {"sessionId": "session", "objectIds": ["object"]}),
        ("detach", {"sessionId": "session"}),
    ]
    uri = "https://wintestkit.dev/schemas/rpc.schema.json"
    for method, params in cases:
        response = request(server, output, f"inspect.managed.{method}", params)
        assert "result" in response, response
        for suffix, value in (("Params", params), ("Result", response["result"])):
            name = f"InspectManaged{method.title()}{suffix}"
            validator = Draft202012Validator(
                {"$ref": f"{uri}#/$defs/{name}"}, registry=schema_registry
            )
            assert validator.is_valid(value), list(validator.iter_errors(value))  # pyright: ignore[reportUnknownMemberType]
    assert [name for name, _ in client.calls] == [
        "resolve",
        "roots",
        "children",
        "members",
        "read",
        "bindings",
        "release",
    ]
    assert client.closed


@pytest.mark.parametrize(
    ("method", "params"),
    [
        ("identify", {"nodeId": ""}),
        ("attach", {"process": {"pid": 42}}),
        ("status", {"process": {"pid": True, "creationTimeUtc": "2026-01-01T00:00:00Z"}}),
        ("detach", {"sessionId": "x" * 129}),
        ("resolve", {"sessionId": "s", "nodeId": "n", "other": 1}),
        ("roots", {"sessionId": "s", "pageSize": True}),
        ("roots", {"sessionId": "s", "pageSize": 201}),
        ("children", {"sessionId": "s", "objectId": "o", "generation": 0, "tree": "visual"}),
        ("children", {"sessionId": "s", "objectId": "o", "generation": 1, "tree": "bad"}),
        ("members", {"sessionId": "s", "objectId": "o", "generation": True}),
        ("read", {"sessionId": "s", "objectId": "o", "generation": 1, "paths": []}),
        (
            "read",
            {
                "sessionId": "s",
                "objectId": "o",
                "generation": 1,
                "paths": [[{"kind": "type", "name": "bad"}]],
            },
        ),
        ("bindings", {"sessionId": "s", "objectId": "o", "generation": 1, "memberKeys": []}),
        ("release", {"sessionId": "s", "objectIds": ["o"] * 257}),
    ],
)
def test_managed_parameter_validation(
    managed_server: Any, method: str, params: dict[str, Any]
) -> None:
    server, output, _ = managed_server
    assert request(server, output, f"inspect.managed.{method}", params)["error"]["code"] == -32602


def test_unknown_session_cross_session_object_and_generation_are_rejected(
    managed_server: Any,
) -> None:
    server, output, client = managed_server
    assert (
        request(server, output, "inspect.managed.roots", {"sessionId": "wrong"})["error"]["data"][
            "code"
        ]
        == "sessionStale"
    )
    request(server, output, "inspect.managed.attach", {"process": IDENTITY.to_json()})
    request(server, output, "inspect.managed.roots", {"sessionId": "session"})
    for object_id, generation in (("other", 1), ("object", 2)):
        error = request(
            server,
            output,
            "inspect.managed.members",
            {"sessionId": "session", "objectId": object_id, "generation": generation},
        )["error"]
        assert error["data"]["code"] == "objectStale"
    assert all(name != "members" for name, _ in client.calls)


def test_resolve_rejects_process_reuse(
    managed_server: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, output, client = managed_server
    request(server, output, "inspect.managed.attach", {"process": IDENTITY.to_json()})

    def reused(pid: int) -> ProcessIdentity:
        return ProcessIdentity(pid, "2027-01-01T00:00:00Z")

    monkeypatch.setattr(probe, "current_identity", reused)
    error = request(
        server, output, "inspect.managed.resolve", {"sessionId": "session", "nodeId": "n"}
    )["error"]
    assert error["data"]["code"] == "processReused" and not client.calls


@pytest.mark.parametrize(
    ("method", "target", "params"),
    [
        ("identify", "identify", {"nodeId": "n"}),
        ("attach", "attach", {"process": IDENTITY.to_json()}),
        ("status", "status", {"process": IDENTITY.to_json()}),
        ("detach", "close", {"sessionId": "session"}),
        ("resolve", "resolve", {"sessionId": "session", "nodeId": "n"}),
        ("roots", "roots", {"sessionId": "session"}),
        (
            "children",
            "children",
            {"sessionId": "session", "objectId": "object", "generation": 1, "tree": "visual"},
        ),
        ("members", "members", {"sessionId": "session", "objectId": "object", "generation": 1}),
        (
            "read",
            "read",
            {
                "sessionId": "session",
                "objectId": "object",
                "generation": 1,
                "paths": [[{"kind": "type", "name": "Name"}]],
            },
        ),
        (
            "bindings",
            "bindings",
            {"sessionId": "session", "objectId": "object", "generation": 1, "memberKeys": ["k"]},
        ),
        ("release", "release", {"sessionId": "session", "objectIds": ["object"]}),
    ],
)
def test_agent_errors_are_exposed_with_protocol_code(
    managed_server: Any,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    target: str,
    params: dict[str, Any],
) -> None:
    server, output, client = managed_server
    server._managed_clients["session"] = client
    server._managed_objects["session"] = {"object": 1}

    def fail(*args: Any, **kwargs: Any) -> None:
        raise InspectorUnavailableError("Inspector operation failed", code="unsupportedTarget")

    if target == "identify":
        monkeypatch.setattr(probe, "identify", fail)
    elif target == "attach":
        monkeypatch.setattr(runtime, "attach_managed", fail)
    elif target == "status":
        monkeypatch.setattr(runtime.inspector_sessions(), "status", fail)
    else:
        monkeypatch.setattr(client, target, fail)
    error = request(server, output, f"inspect.managed.{method}", params)["error"]
    assert error["data"]["code"] == "unsupportedTarget"
    assert error["message"] == "Inspector operation failed"


def test_unexpected_managed_errors_do_not_expose_target_data(
    managed_server: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    server, output, client = managed_server
    server._managed_clients["session"] = client

    def fail(**kwargs: Any) -> None:
        raise RuntimeError("private target value")

    monkeypatch.setattr(client, "roots", fail)
    error = request(server, output, "inspect.managed.roots", {"sessionId": "session"})["error"]
    assert error == {"code": -32603, "message": "internal error"}
    assert "private target value" not in caplog.text


def test_refresh_releases_leases_but_keeps_session(
    managed_server: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from wintestkit.uia import win32

    server, output, client = managed_server
    request(server, output, "inspect.managed.attach", {"process": IDENTITY.to_json()})
    request(server, output, "inspect.managed.roots", {"sessionId": "session"})
    monkeypatch.setattr(server, "_app", lambda required=False: None)

    def no_windows() -> list[int]:
        return []

    monkeypatch.setattr(win32, "desktop_windows", no_windows)
    assert "result" in request(server, output, "inspect.refresh", {})
    assert ("release", ["object"]) in client.calls and not client.closed
    error = request(
        server,
        output,
        "inspect.managed.members",
        {"sessionId": "session", "objectId": "object", "generation": 1},
    )["error"]
    assert error["data"]["code"] == "objectStale"


def test_disabled_methods_do_not_probe_or_create_registry(
    managed_server: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, output, _ = managed_server
    server.cfg = load_config(server.cfg.root)
    monkeypatch.setattr(probe, "identify", _unexpected_probe)
    monkeypatch.setattr(runtime, "inspector_sessions", lambda: pytest.fail("unexpected registry"))
    for method, params in (
        ("identify", {"nodeId": "n"}),
        ("attach", {"process": IDENTITY.to_json()}),
    ):
        error = request(server, output, f"inspect.managed.{method}", params)["error"]
        assert error["data"]["code"] == "notAttached"


def test_uia_properties_ignore_managed_aliases_without_probing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from rpc_support import make_server
    from rpc_support import request as rpc_request

    server, output, button = make_server(tmp_path, monkeypatch)
    (tmp_path / "wintestkit.yaml").write_text(
        "property_aliases:\n  ClrFullClassName: 'type:FullName'\n", encoding="utf-8"
    )
    rpc_request(server, output, "initialize", {"root": str(tmp_path)})
    fake_button = cast(Any, button)
    server.nodes[fake_button.runtime_id] = fake_button
    monkeypatch.setattr(probe, "identify", _unexpected_probe)
    monkeypatch.setattr(runtime, "inspector_sessions", lambda: pytest.fail("unexpected registry"))
    for full in (False, True):
        response = rpc_request(
            server,
            output,
            "inspect.properties",
            {
                "nodeId": fake_button.runtime_id,
                "full": full,
            },
        )
        assert "result" in response, response


@pytest.mark.parametrize("valid", [True, False])
def test_initialize_capability_requires_successful_payload_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, valid: bool
) -> None:
    def verify() -> None:
        if not valid:
            raise InspectorUnavailableError("bad hash", code="payloadMismatch")

    monkeypatch.setattr(payload, "load_payload", lambda: SimpleNamespace(verify=verify))
    output = io.BytesIO()
    result = request(Server(output), output, "initialize", {"root": str(tmp_path)})["result"]
    assert result["capabilities"]["managedInspector"] is valid
