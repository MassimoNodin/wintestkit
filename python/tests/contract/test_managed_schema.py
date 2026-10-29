"""Contract checks for the initial managed protocol definitions."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

SCHEMA = Path(__file__).resolve().parents[3] / "wpf-inspector/protocol/inspector.schema.json"


@pytest.mark.parametrize(
    ("definition", "value", "valid"),
    [
        ("ProcessIdentity", {"pid": 1, "creationTimeUtc": "2026-01-01T00:00:00Z"}, True),
        ("ProcessIdentity", {"pid": 0, "creationTimeUtc": "2026-01-01T00:00:00Z"}, False),
        ("Path", [{"kind": "type", "name": "FullName"}], True),
        ("Path", [{"kind": "type", "name": "FullName"}, {"kind": "field", "name": "x"}], False),
        ("Path", [{"kind": "dependency", "name": "x", "ownerAssembly": "a"}], False),
        ("Path", [{"kind": "property", "name": "x"}] * 9, False),
        ("Path", [{"kind": "unknown", "name": "x"}], False),
        ("HelloParams", {"protocolMajor": 2, "protocolMinor": 0, "sessionId": "s", "token": "t", "process": {"pid": 1, "creationTimeUtc": "2026-01-01T00:00:00Z"}}, False),
    ],
)
def test_initial_managed_contract(definition: str, value: object, valid: bool) -> None:
    document = json.loads(SCHEMA.read_text(encoding="utf-8-sig"))
    Draft202012Validator.check_schema(document)
    registry = Registry().with_resource(document["$id"], Resource.from_contents(document))
    validator = Draft202012Validator({"$ref": f"{document['$id']}#/$defs/{definition}"}, registry=registry)
    assert validator.is_valid(value) is valid
