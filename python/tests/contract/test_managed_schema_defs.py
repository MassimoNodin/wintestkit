"""Managed pipe schema definitions and representative wire variants."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

SCHEMA = Path(__file__).resolve().parents[3] / "wpf-inspector/protocol/inspector.schema.json"
DOCUMENT = json.loads(SCHEMA.read_text(encoding="utf-8-sig"))
REGISTRY = Registry().with_resource(DOCUMENT["$id"], Resource.from_contents(DOCUMENT))

NAMES = [
    "ProcessIdentity",
    "Session",
    "TypeInfo",
    "ObjectRef",
    "DependencyMetadata",
    "AttributeLiteral",
    "AttributeInfo",
    "Member",
    "DependencySource",
    "Value",
    "Diagnostic",
    "MemberPage",
    "ManagedNodePage",
    "Mapping",
    "ManagedNode",
    "RelativeSource",
    "BindingInfo",
    "PathSegment",
    "PathValue",
    "ReadResult",
    "CandidateRequest",
    "CandidateResult",
    "ReadBatchResult",
    "ErrorInfo",
    "RequestEnvelope",
    "ResponseEnvelope",
    "HelloParams",
    "HelloResult",
    "ResolveParams",
    "ReadBatchParams",
    "RootsParams",
    "ChildrenParams",
    "MembersParams",
    "ReadParams",
    "BindingsParams",
    "BindingsResult",
    "ReleaseParams",
    "ReleaseResult",
    "CancelParams",
    "CancelResult",
    "CloseParams",
    "CloseResult",
    "BootstrapSettings",
]

PROCESS = {"pid": 1, "creationTimeUtc": "2026-01-01T00:00:00Z"}
TYPE = {
    "name": "T",
    "fullName": "T",
    "assemblyName": "A",
    "assemblyQualifiedName": "T, A",
    "baseTypes": [],
}
OBJECT = {"sessionId": "s", "objectId": "o", "generation": 1, "type": TYPE, "dispatcherId": "d"}
VALUE = {
    "status": "ok",
    "kind": "string",
    "declaredType": "String",
    "runtimeType": "String",
    "scalar": "hello",
}
MAPPING = {"status": "exact", "process": PROCESS, "runtimeId": [1], "object": OBJECT}
MEMBER = {
    "memberKey": "k",
    "name": "Name",
    "category": "clrProperty",
    "declaringType": "T",
    "declaredType": "String",
    "visibility": "public",
    "readable": True,
    "attributes": [],
}
BOOTSTRAP = {
    "schemaVersion": 1,
    "protocolMajor": 2,
    "protocolMinor": 0,
    "sessionId": "f1a08a59-e47a-4aec-9afc-7d83a642ec07",
    "process": PROCESS,
    "pipeName": "pipe",
    "token": "A" * 43 + "=",
    "clientSid": "sid",
    "expiresUtc": "2026-01-01T00:00:00Z",
    "requestTimeoutMs": 2000,
    "idleTimeoutMs": 300000,
    "agentVersion": "1",
    "redactNames": [],
    "writeAllowlist": {"properties": [], "methods": []},
}


def test_schema_and_definition_names() -> None:
    Draft202012Validator.check_schema(DOCUMENT)
    assert set(NAMES) <= DOCUMENT["$defs"].keys()


@pytest.mark.parametrize("rules", [None, "account", [""], ["x" * 129], ["x"] * 33, [1], ["\ud800"]])
def test_bootstrap_rejects_invalid_redaction_rules(rules: object) -> None:
    validator = Draft202012Validator(
        {"$ref": f"{DOCUMENT['$id']}#/$defs/BootstrapSettings"}, registry=REGISTRY
    )
    assert not validator.is_valid({**BOOTSTRAP, "redactNames": rules})


def test_bootstrap_requires_bounded_unicode_redaction_rules() -> None:
    validator = Draft202012Validator(
        {"$ref": f"{DOCUMENT['$id']}#/$defs/BootstrapSettings"}, registry=REGISTRY
    )
    missing = dict(BOOTSTRAP)
    del missing["redactNames"]
    assert not validator.is_valid(missing)
    assert validator.is_valid({**BOOTSTRAP, "redactNames": ["😀" * 128]})


@pytest.mark.parametrize(
    ("definition", "instance", "valid"),
    [
        ("Value", VALUE, True),
        ("Value", {**VALUE, "kind": "null", "scalar": None}, True),
        ("Value", {**VALUE, "status": "truncated", "scalar": "a", "truncatedAt": 2}, True),
        ("Value", {**VALUE, "status": "redacted"}, False),
        ("Value", {**VALUE, "kind": "boolean"}, False),
        ("Value", {**VALUE, "status": "exception", "kind": "unavailable", "scalar": None}, False),
        ("Mapping", MAPPING, True),
        ("Mapping", {"status": "notFound", "process": PROCESS, "runtimeId": [1]}, True),
        ("Mapping", {"status": "ambiguous", "process": PROCESS, "runtimeId": [-1]}, True),
        ("Mapping", {**MAPPING, "status": "stale"}, False),
        ("Mapping", {"status": "exact", "process": PROCESS, "runtimeId": [1]}, False),
        ("Mapping", {**MAPPING, "runtimeId": []}, False),
        ("PathSegment", {"kind": "property", "name": "x"}, True),
        (
            "PathSegment",
            {"kind": "dependency", "name": "x", "ownerType": "T", "ownerAssembly": "A"},
            True,
        ),
        ("PathSegment", {"kind": "type", "name": "BaseTypes"}, True),
        ("PathSegment", {"kind": "type", "name": "Unknown"}, False),
        ("PathSegment", {"kind": "field", "name": "x", "ownerType": "T"}, False),
        ("PathSegment", {"kind": "dependency", "name": "x"}, False),
        ("Member", MEMBER, True),
        (
            "Member",
            {**MEMBER, "category": "typeMetadata", "compatibilityAlias": "ClrFullClassName"},
            True,
        ),
        ("Member", {**MEMBER, "readable": False, "reason": "nonPublic"}, True),
        ("Member", {**MEMBER, "category": "method"}, False),
        ("Member", {**MEMBER, "visibility": "unknown"}, False),
        ("Member", {**MEMBER, "extra": 1}, False),
        ("BootstrapSettings", BOOTSTRAP, True),
        ("BootstrapSettings", {**BOOTSTRAP, "requestTimeoutMs": 1}, True),
        ("BootstrapSettings", {**BOOTSTRAP, "protocolMinor": 1}, True),
        ("BootstrapSettings", {**BOOTSTRAP, "token": "short"}, False),
        ("BootstrapSettings", {**BOOTSTRAP, "sessionId": "invalid"}, False),
        ("BootstrapSettings", {**BOOTSTRAP, "idleTimeoutMs": 300001}, False),
    ],
)
def test_variants(definition: str, instance: object, valid: bool) -> None:
    validator = Draft202012Validator(
        {"$ref": f"{DOCUMENT['$id']}#/$defs/{definition}"},
        registry=REGISTRY,
        format_checker=FormatChecker(),
    )
    assert validator.is_valid(instance) is valid
