"""Exercise the Python DTO readers against shared protocol fixtures."""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from wintestkit.inspector.client import _response
from wintestkit.inspector.models import (
    MISSING,
    AttributeInfo,
    AttributeLiteral,
    BindingInfo,
    BootstrapSettings,
    HelloParams,
    ManagedNode,
    Mapping,
    Member,
    ObjectRef,
    Page,
    ProcessIdentity,
    RequestEnvelope,
    Session,
    Value,
    parse_path,
)
from wintestkit.inspector.paths import PathSegment

ROOT = Path(__file__).resolve().parents[3] / "wpf-inspector/protocol/fixtures"
PARSERS: dict[str, Callable[[Any], Any]] = {
    "AttributeInfo": AttributeInfo.from_json,
    "BindingInfo": BindingInfo.from_json,
    "BootstrapSettings": BootstrapSettings.from_json,
    "HelloParams": HelloParams.from_json,
    "Mapping": Mapping.from_json,
    "Member": Member.from_json,
    "MemberPage": lambda value: Page.from_json(value, Member.from_json),
    "ManagedNodePage": lambda value: Page.from_json(value, ManagedNode.from_json),
    "ObjectRef": ObjectRef.from_json,
    "Path": parse_path,
    "PathSegment": PathSegment.from_json,
    "ProcessIdentity": ProcessIdentity.from_json,
    "ResponseEnvelope": _response,
    "RequestEnvelope": RequestEnvelope.from_json,
    "Session": Session.from_json,
    "Value": Value.from_json,
}
FIXTURES = [
    path
    for directory in (ROOT / "valid", ROOT / "invalid")
    for path in sorted(directory.glob("*.json"))
    if json.loads(path.read_text(encoding="utf-8"))["schema"] in PARSERS
]


def test_every_golden_fixture_has_a_python_reader() -> None:
    assert len(FIXTURES) == sum(
        len(list((ROOT / directory).glob("*.json"))) for directory in ("valid", "invalid")
    )


@pytest.mark.parametrize("rules", [None, "account", [""], ["x" * 129], ["x"] * 33, [1], ["\ud800"]])
def test_bootstrap_redaction_rules_are_strict(rules: object) -> None:
    fixture = json.loads((ROOT / "valid/bootstrap.json").read_text(encoding="utf-8"))["instance"]
    with pytest.raises(ValueError, match="redaction"):
        BootstrapSettings.from_json({**fixture, "redactNames": rules})
    del fixture["redactNames"]
    with pytest.raises(ValueError):
        BootstrapSettings.from_json(fixture)


def test_bootstrap_redaction_rules_round_trip_without_repr_leaks() -> None:
    fixture = json.loads((ROOT / "valid/bootstrap.json").read_text(encoding="utf-8"))["instance"]
    fixture["redactNames"] = ["😀" * 128]
    settings = BootstrapSettings.from_json(fixture)
    assert settings.to_json()["redactNames"] == fixture["redactNames"]
    assert fixture["redactNames"][0] not in repr(settings)


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda path: f"{path.parent.name}/{path.name}")
def test_golden_dto(fixture: Path) -> None:
    document = json.loads(fixture.read_text(encoding="utf-8"))
    parser = PARSERS[document["schema"]]
    if fixture.parent.name == "valid":
        parser(document["instance"])
    else:
        with pytest.raises(ValueError):
            parser(document["instance"])


def test_null_and_missing_are_distinct() -> None:
    null = Value.from_json(
        {"status": "ok", "kind": "null", "declaredType": "", "runtimeType": "", "scalar": None}
    )
    unread = Value.from_json(
        {"status": "notRead", "kind": "unavailable", "declaredType": "", "runtimeType": ""}
    )
    assert null.scalar is None and null.to_json()["scalar"] is None
    assert unread.scalar is MISSING and "scalar" not in unread.to_json()


def test_exact_numeric_conversions() -> None:
    large = Value.from_json(
        {
            "status": "ok",
            "kind": "integer",
            "declaredType": "",
            "runtimeType": "",
            "scalar": "9007199254740993",
        }
    )
    decimal = Value.from_json(
        {
            "status": "ok",
            "kind": "number",
            "declaredType": "",
            "runtimeType": "",
            "scalar": "1.00000000000000001",
        }
    )
    assert large.as_python() == 9007199254740993
    assert decimal.as_python() == Decimal("1.00000000000000001")


@pytest.mark.parametrize("kind", ["value", "attribute"])
def test_enormous_numeric_values_are_rejected(kind: str) -> None:
    with pytest.raises(ValueError):
        if kind == "attribute":
            AttributeLiteral.from_json({"kind": "number", "value": 10**400})
        else:
            Value.from_json(
                {
                    "status": "ok",
                    "kind": "number",
                    "declaredType": "",
                    "runtimeType": "",
                    "scalar": 10**400,
                }
            )


def test_creation_time_compares_at_full_windows_precision() -> None:
    first = ProcessIdentity(42, "2026-10-29T01:00:00.1234567+01:00")
    assert first == ProcessIdentity(42, "2026-10-29T00:00:00.1234567Z")
    assert first != ProcessIdentity(42, "2026-10-29T00:00:00.1234568Z")
