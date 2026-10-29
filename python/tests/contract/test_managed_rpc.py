"""Public managed RPC contracts, including the shared inspector DTOs."""

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[3]
PROCESS = {"pid": 1, "creationTimeUtc": "2026-01-01T00:00:00Z"}
SESSION: dict[str, Any] = {
    "sessionId": "s",
    "process": PROCESS,
    "state": "ready",
    "protocolMajor": 2,
    "protocolMinor": 0,
    "features": [],
}
PAGE: dict[str, Any] = {"items": [], "complete": True, "snapshotId": "snapshot", "diagnostics": []}
OBJECT = {"sessionId": "s", "objectId": "o", "generation": 1}
CASES: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {
    "Identify": (
        {"nodeId": "n"},
        {
            "process": PROCESS,
            "executable": "app.exe",
            "runtime": None,
            "architecture": "x64",
            "wpfLoaded": True,
        },
    ),
    "Attach": ({"process": PROCESS}, SESSION),
    "Status": ({"process": PROCESS}, SESSION),
    "Detach": ({"sessionId": "s"}, {"detached": True}),
    "Resolve": (
        {"sessionId": "s", "nodeId": "n"},
        {"status": "notFound", "process": PROCESS, "runtimeId": [1]},
    ),
    "Roots": ({"sessionId": "s"}, PAGE),
    "Children": ({**OBJECT, "tree": "visual"}, PAGE),
    "Members": (OBJECT, PAGE),
    "Read": (
        {**OBJECT, "paths": [[{"kind": "type", "name": "Name"}]]},
        {"values": [], "readId": "r"},
    ),
    "Bindings": ({**OBJECT, "memberKeys": ["k"]}, {"bindings": []}),
    "Release": ({"sessionId": "s", "objectIds": ["o"]}, {"releasedCount": 1}),
}


@pytest.fixture(scope="module")
def registry() -> Registry[Any]:
    paths = [
        *sorted((ROOT / "schemas").glob("*.schema.json")),
        ROOT / "wpf-inspector/protocol/inspector.schema.json",
    ]
    documents: list[dict[str, Any]] = [
        json.loads(path.read_text(encoding="utf-8-sig")) for path in paths
    ]
    return Registry[Any]().with_resources(
        (doc["$id"], Resource.from_contents(doc)) for doc in documents
    )


@pytest.mark.parametrize("method", CASES)
def test_managed_rpc(method: str, registry: Registry[Any]) -> None:
    document = json.loads((ROOT / "schemas/rpc.schema.json").read_text(encoding="utf-8"))
    params, result = CASES[method]
    for suffix, value in (("Params", params), ("Result", result)):
        name = f"InspectManaged{method}{suffix}"
        assert name in document["$defs"]
        validator = Draft202012Validator(
            {"$ref": f"{document['$id']}#/$defs/{name}"}, registry=registry
        )
        assert validator.is_valid(value)  # pyright: ignore[reportUnknownMemberType]
        if suffix == "Params":
            assert not validator.is_valid({**params, "unexpected": True})  # pyright: ignore[reportUnknownMemberType]


@pytest.mark.parametrize(
    ("method", "field", "value"),
    [
        ("Read", "paths", []),
        ("Read", "paths", [[{"kind": "property", "name": "x"}]] * 33),
        ("Bindings", "memberKeys", []),
        ("Bindings", "memberKeys", ["k"] * 33),
        ("Release", "objectIds", []),
        ("Release", "objectIds", ["o"] * 257),
        ("Children", "tree", "other"),
        ("Attach", "process", {"pid": 1}),
    ],
)
def test_invalid_managed_params(
    method: str, field: str, value: Any, registry: Registry[Any]
) -> None:
    uri = "https://wintestkit.dev/schemas/rpc.schema.json"
    validator = Draft202012Validator(
        {"$ref": f"{uri}#/$defs/InspectManaged{method}Params"}, registry=registry
    )
    assert not validator.is_valid({**CASES[method][0], field: value})  # pyright: ignore[reportUnknownMemberType]
