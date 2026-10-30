"""Validate every golden fixture and count protocol 2 additions."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[3] / "wpf-inspector/protocol"
SCHEMA = json.loads((ROOT / "inspector.schema.json").read_text(encoding="utf-8-sig"))
REGISTRY = Registry().with_resource(SCHEMA["$id"], Resource.from_contents(SCHEMA))
VALID = sorted((ROOT / "fixtures/valid").glob("*.json"))
INVALID = sorted((ROOT / "fixtures/invalid").glob("*.json"))


def test_protocol2_fixture_counts() -> None:
    assert len([path for path in VALID if path.name.startswith("p2-")]) >= 60
    assert len([path for path in INVALID if path.name.startswith("p2-")]) >= 50


@pytest.mark.parametrize("fixture", VALID + INVALID, ids=lambda path: str(path.relative_to(ROOT)))
def test_protocol2_fixture(fixture: Path) -> None:
    document = json.loads(fixture.read_text(encoding="utf-8"))
    assert set(document) == {"schema", "instance"}
    assert document["schema"] in SCHEMA["$defs"]
    validator = Draft202012Validator(
        {"$ref": f"{SCHEMA['$id']}#/$defs/{document['schema']}"},
        registry=REGISTRY,
        format_checker=FormatChecker(),
    )
    assert validator.is_valid(document["instance"]) == (fixture.parent.name == "valid")
