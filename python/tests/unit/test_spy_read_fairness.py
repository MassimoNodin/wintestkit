"""The Properties auto-read: batched `spyRead`, per-getter limits and fairness with short requests."""

import io
import json
import queue
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from test_managed_server import (
    IDENTITY,
    ROOT,
    FakeClient,
    FakeRegistry,
    _element_identity,
    _facts,
    _identity,
    _node,
    request,
)

from wintestkit import runtime
from wintestkit import server as server_module
from wintestkit.config import load_config
from wintestkit.errors import InspectorDeadlineError, InspectorError, InspectorUnavailableError
from wintestkit.inspector import probe
from wintestkit.inspector.models import PathSegment, PathValue, Value
from wintestkit.server import Server
from wintestkit.targets import ModuleLoader

URI = "https://wintestkit.dev/schemas/rpc.schema.json"


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


def prop(name: str) -> dict[str, Any]:
    return {"kind": "property", "name": name, "declaringType": "Test.Window"}


def field(name: str) -> dict[str, Any]:
    return {
        "kind": "field",
        "name": name,
        "memberKey": f"clrField|Test.Window|{name}",
        "declaringType": "Test.Window",
    }


def ok(path: tuple[PathSegment, ...]) -> PathValue:
    return PathValue(path, Value("ok", "string", "String", "String", path[0].name))


class ReadClient(FakeClient):
    """A client whose slow getters are named in ``slow``; batches containing one run out of time."""

    def __init__(self) -> None:
        super().__init__()
        self.slow: set[str] = set()
        self.error: InspectorError | None = None
        self.limits: list[float] = []

    def read(self, object_id: str, generation: int, paths: Any, **kwargs: Any) -> Any:
        self.calls.append(("read", [path[0].name for path in paths]))
        self.limits.append(kwargs["deadline"] - time.monotonic())
        if self.error is not None:
            raise self.error
        if any(path[0].name in self.slow for path in paths):
            raise InspectorDeadlineError("Inspector request deadline expired", code="timeout")
        return tuple(ok(path) for path in paths), "read"

    def spy_field_read(self, object_id: str, generation: int, paths: Any, **kwargs: Any) -> Any:
        self.calls.append(("field", [path[0].name for path in paths]))
        return tuple(ok(path) for path in paths), "field"


@pytest.fixture
def reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[Server, io.BytesIO, ReadClient]]:
    runtime.reset()
    output = io.BytesIO()
    server = Server(output)
    server.cfg = load_config(
        tmp_path, {"inspector.enabled": True, "inspector.request_timeout": 0.5}
    )
    server.loader = ModuleLoader(server.cfg)
    client = ReadClient()
    registry = FakeRegistry(client)
    monkeypatch.setattr(runtime, "inspector_sessions", lambda: registry)
    monkeypatch.setattr(runtime, "attach_managed", lambda *args, **kwargs: client)
    monkeypatch.setattr(runtime, "managed_element_identity", _element_identity)
    monkeypatch.setattr(server, "_node", _node)
    monkeypatch.setattr(probe, "current_identity", _identity)
    monkeypatch.setattr(probe, "identify", _facts)
    request(server, output, "inspect.managed.attach", {"process": IDENTITY.to_json()})
    request(server, output, "inspect.managed.roots", {"sessionId": "session"})
    client.calls.clear()
    yield server, output, client
    runtime.reset()


def spy_read(server: Server, output: io.BytesIO, paths: list[dict[str, Any]]) -> dict[str, Any]:
    params = {
        "sessionId": "session",
        "objectId": "object",
        "generation": 1,
        "paths": [[path] for path in paths],
    }
    return request(server, output, "inspect.managed.spyRead", params)


def test_a_batch_is_one_request_and_keeps_the_order(
    reader: Any, schema_registry: Registry[Any]
) -> None:
    server, output, client = reader
    names = [f"P{index}" for index in range(25)]
    response = spy_read(server, output, [prop(name) for name in names])
    assert client.calls == [("read", names)]
    values = response["result"]["values"]
    assert [item["path"][0]["name"] for item in values] == names
    validator = Draft202012Validator(
        {"$ref": f"{URI}#/$defs/InspectManagedReadResult"}, registry=schema_registry
    )
    assert validator.is_valid(response["result"])


def test_each_getter_gets_250_ms_and_a_batch_a_little_more(reader: Any) -> None:
    server, output, client = reader
    spy_read(server, output, [prop("One")])
    assert client.limits[-1] <= server_module.SPY_GETTER_LIMIT
    spy_read(server, output, [prop(f"P{index}") for index in range(25)])
    assert server_module.SPY_GETTER_LIMIT < client.limits[-1] <= 0.25 + 0.02 * 25


def test_fields_are_read_one_by_one_next_to_the_batched_properties(reader: Any) -> None:
    server, output, client = reader
    response = spy_read(server, output, [prop("A"), field("f1"), prop("B"), field("f2")])
    assert client.calls == [("read", ["A", "B"]), ("field", ["f1"]), ("field", ["f2"])]
    assert [item["path"][0]["name"] for item in response["result"]["values"]] == [
        "A",
        "f1",
        "B",
        "f2",
    ]


def test_one_hung_getter_times_out_in_its_own_row_only(
    reader: Any, schema_registry: Registry[Any]
) -> None:
    server, output, client = reader
    client.slow = {"Hung"}
    response = spy_read(server, output, [prop("A"), prop("Hung"), prop("B")])
    statuses = [item["value"]["status"] for item in response["result"]["values"]]
    assert statuses == ["ok", "timeout", "ok"]
    # The batch ran out of time, then every getter was read on its own with its own limit.
    assert client.calls == [
        ("read", ["A", "Hung", "B"]),
        ("read", ["A"]),
        ("read", ["Hung"]),
        ("read", ["B"]),
    ]
    validator = Draft202012Validator(
        {"$ref": f"{URI}#/$defs/InspectManagedReadResult"}, registry=schema_registry
    )
    assert validator.is_valid(response["result"])


def test_a_busy_ui_thread_is_a_timeout_not_a_failed_request(reader: Any) -> None:
    server, output, client = reader
    client.error = InspectorUnavailableError("busy", code="dispatcherUnavailable")
    response = spy_read(server, output, [prop("A"), prop("B")])
    assert [item["value"]["status"] for item in response["result"]["values"]] == [
        "timeout",
        "timeout",
    ]


def test_other_errors_still_fail_the_request(reader: Any) -> None:
    server, output, client = reader
    client.error = InspectorUnavailableError("denied", code="accessDenied")
    response = spy_read(server, output, [prop("A"), prop("B")])
    assert response["error"]["data"]["code"] == "accessDenied"


def test_the_whole_request_has_a_budget(reader: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    server, output, client = reader
    client.slow = {"A", "B", "C"}
    monkeypatch.setattr(server_module, "SPY_READ_BUDGET", 0.0)
    response = spy_read(server, output, [prop("A"), prop("B"), prop("C")])
    assert [item["value"]["status"] for item in response["result"]["values"]] == ["timeout"] * 3
    assert client.calls == []


class Lines:
    """The editor's stdin: lines arrive when the test sends them."""

    def __init__(self) -> None:
        self._lines: queue.Queue[bytes | None] = queue.Queue()

    def send(self, request: dict[str, Any]) -> None:
        self._lines.put((json.dumps(request) + "\n").encode())

    def close(self) -> None:
        self._lines.put(None)

    def __iter__(self) -> Iterator[bytes]:
        return self

    def __next__(self) -> bytes:
        line = self._lines.get()
        if line is None:
            raise StopIteration
        return line


class Serving:
    def __init__(self, server: Server, output: io.BytesIO) -> None:
        self.output, self.lines, self.sequence = output, Lines(), 0
        self.thread = threading.Thread(target=server.serve, args=(self.lines,), daemon=True)
        self.thread.start()

    def send(self, method: str, params: dict[str, Any]) -> int:
        self.sequence += 1
        self.lines.send({"jsonrpc": "2.0", "id": self.sequence, "method": method, "params": params})
        return self.sequence

    def answered(self, request_id: int, within: float) -> bool:
        until = time.monotonic() + within
        while time.monotonic() < until:
            for line in self.output.getvalue().splitlines():
                if json.loads(line).get("id") == request_id:
                    return True
            time.sleep(0.005)
        return False


def test_a_long_read_does_not_hold_up_short_requests(
    reader: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, output, _client = reader
    release = threading.Event()
    started = threading.Semaphore(0)
    original = ReadClient.read

    def slow_read(self: ReadClient, *args: Any, **kwargs: Any) -> Any:
        started.release()
        release.wait(10)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ReadClient, "read", slow_read)
    serving = Serving(server, output)
    try:
        params = {
            "sessionId": "session",
            "objectId": "object",
            "generation": 1,
            "paths": [[prop("A")]],
        }
        # More reads than the pool has workers: the extra ones wait in line.
        reads = [
            serving.send("inspect.managed.read", params)
            for _ in range(server_module._READ_WORKERS + 2)
        ]
        for _ in range(server_module._READ_WORKERS):
            assert started.acquire(timeout=5)
        short = [
            serving.send("inspect.managed.keepalive", {"sessionId": "session"}),
            serving.send("spy.stop", {}),
            serving.send("inspect.managed.resolve", {"sessionId": "session", "nodeId": "n"}),
        ]
        began = time.monotonic()
        assert all(serving.answered(request_id, 1.0) for request_id in short)
        assert time.monotonic() - began < 1.0
        assert not any(serving.answered(request_id, 0) for request_id in reads)
        release.set()
        assert all(serving.answered(request_id, 5.0) for request_id in reads)
    finally:
        release.set()
        serving.send("shutdown", {})
        serving.lines.close()
        serving.thread.join(timeout=10)


def test_reads_do_not_share_the_attach_lock(reader: Any) -> None:
    server, output, _client = reader
    answered = threading.Event()

    def keepalive() -> None:
        request(server, output, "inspect.managed.keepalive", {"sessionId": "session"})
        answered.set()

    # Only the attachment lifecycle takes the lock; a keepalive or a read goes straight through.
    with server._managed_rpc_lock:
        thread = threading.Thread(target=keepalive, daemon=True)
        thread.start()
        assert answered.wait(2), "keepalive waited for the attachment lock"
    thread.join(timeout=2)


@pytest.mark.parametrize("reason", ["workTimeout", "earlierWorkRunning"])
def test_stalled_batch_does_not_retry(reader: Any, reason: str) -> None:
    server, output, client = reader
    client.error = InspectorUnavailableError("stalled", code="dispatcherUnavailable")
    client.error.details = {"reason": reason}
    response = spy_read(server, output, [prop("A"), field("f"), prop("B")])
    assert client.calls == [("read", ["A", "B"])]
    assert [item["value"]["status"] for item in response["result"]["values"]] == [
        "timeout",
        "timeout",
        "timeout",
    ]
