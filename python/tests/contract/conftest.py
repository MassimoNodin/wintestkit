"""Offline JSON Schema validation shared by protocol contract tests."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

SCHEMAS_DIRECTORY = Path(__file__).resolve().parents[3] / "schemas"


@pytest.fixture(scope="session")
def schema_documents() -> dict[str, dict[str, Any]]:
    return {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(SCHEMAS_DIRECTORY.glob("*.schema.json"))
    }


@pytest.fixture(scope="session")
def validate(schema_documents: dict[str, dict[str, Any]]) -> Callable[[str, str, Any], None]:
    registry = Registry().with_resources(
        (document["$id"], Resource.from_contents(document))
        for document in schema_documents.values()
    )

    def validate_definition(schema_file: str, def_name: str, data: Any) -> None:
        document = schema_documents[schema_file]
        if def_name not in document["$defs"]:
            raise KeyError(f"Unknown definition {schema_file}:{def_name}")
        schema = {"$ref": f"{document['$id']}#/$defs/{def_name}"}
        Draft202012Validator(schema, registry=registry).validate(data)

    return validate_definition
