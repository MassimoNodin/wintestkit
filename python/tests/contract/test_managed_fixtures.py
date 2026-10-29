"""Validate shared managed fixtures against their named definitions."""

import json
from pathlib import Path
from typing import Any, Protocol, cast

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[3] / "wpf-inspector/protocol"
SCHEMA = json.loads((ROOT / "inspector.schema.json").read_text(encoding="utf-8-sig"))
REGISTRY: Registry[Any] = Registry[Any]().with_resource(
    SCHEMA["$id"], Resource.from_contents(SCHEMA)
)
VALID = sorted((ROOT / "fixtures/valid").glob("*.json"))
INVALID = sorted((ROOT / "fixtures/invalid").glob("*.json"))


class InstanceValidator(Protocol):
    def is_valid(self, instance: object) -> bool: ...


def test_fixture_counts() -> None:
    assert len(VALID) >= 80
    assert len(INVALID) >= 60


@pytest.mark.parametrize("fixture", VALID + INVALID, ids=lambda path: str(path.relative_to(ROOT)))
def test_managed_fixture(fixture: Path) -> None:
    document = json.loads(fixture.read_text(encoding="utf-8"))
    assert set(document) == {"schema", "instance"}
    assert document["schema"] in SCHEMA["$defs"]
    validator = Draft202012Validator(
        {"$ref": f"{SCHEMA['$id']}#/$defs/{document['schema']}"},
        registry=REGISTRY,
        format_checker=FormatChecker(),
    )
    checked = cast(InstanceValidator, validator)
    assert checked.is_valid(document["instance"]) == (fixture.parent.name == "valid")
