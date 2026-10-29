"""Explicit, immutable inspector DTOs and strict wire validation."""

from __future__ import annotations

import json
import math
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, cast

from wintestkit.inspector.paths import PathSegment
from wintestkit.inspector.redaction import validate_redact_names


class _Missing:
    def __repr__(self) -> str:
        return "MISSING"


MISSING = _Missing()
FEATURES = frozenset(
    {
        "typeMetadata",
        "clrMembers",
        "dependencyProperties",
        "bindings",
        "exactUiaMapping",
        "batchReads",
    }
)
ERROR_CODES = frozenset(
    {
        "invalidParams",
        "unsupportedProtocol",
        "unsupportedTarget",
        "accessDenied",
        "authenticationFailed",
        "payloadMissing",
        "payloadMismatch",
        "alreadyAttached",
        "notAttached",
        "attachFailed",
        "blockedByPolicy",
        "agentVersionMismatch",
        "processExited",
        "processReused",
        "sessionStale",
        "objectStale",
        "mappingFailed",
        "memberAmbiguous",
        "memberNotFound",
        "dispatcherUnavailable",
        "timeout",
        "busy",
        "limitExceeded",
        "invalidPageToken",
        "cancelled",
        "internalError",
    }
)
STATES = frozenset({"detached", "probing", "attaching", "ready", "detaching", "faulted", "exited"})
_INT_PATTERN = re.compile(r"-?(?:0|[1-9][0-9]*)\Z")
_NUMBER_PATTERN = re.compile(
    r"(?:NaN|Infinity|-Infinity|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)\Z"
)
_TIMESTAMP = re.compile(
    r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d+))?(Z|[+-]\d\d:\d\d)\Z", re.IGNORECASE
)


def _obj(value: object, required: str, optional: str = "") -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Expected an object")
    raw = cast(dict[object, Any], value)
    if not all(isinstance(key, str) for key in raw):
        raise ValueError("Expected string object keys")
    data = cast(dict[str, Any], raw)
    needed, allowed = set(required.split()), set((required + " " + optional).split())
    if not needed <= data.keys() or not data.keys() <= allowed:
        raise ValueError("Invalid object fields")
    return data


def _str(value: object, maximum: int = 128, *, empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > maximum or (not value and not empty):
        raise ValueError("Invalid string")
    if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise ValueError("Invalid Unicode string")
    return value


def _int(value: object, minimum: int = 0, maximum: int = 9_223_372_036_854_775_807) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("Invalid integer")
    return value


def _bool(value: object) -> bool:
    if type(value) is not bool:
        raise ValueError("Invalid boolean")
    return value


def _finite_number(value: object) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(cast(float, value))
    except OverflowError:
        return False


def _choice(value: object, choices: frozenset[str] | set[str]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise ValueError("Invalid enum value")
    return value


def _array[T](
    value: object, reader: Callable[[Any], T], maximum: int, minimum: int = 0
) -> tuple[T, ...]:
    if not isinstance(value, list):
        raise ValueError("Invalid array")
    items = cast(list[Any], value)
    if not minimum <= len(items) <= maximum:
        raise ValueError("Invalid array")
    return tuple(reader(item) for item in items)


def _optional[T](data: dict[str, Any], key: str, reader: Callable[[Any], T]) -> T | None:
    return reader(data[key]) if key in data else None


def _identifier(value: object) -> str:
    return _str(value)


def _key(value: object) -> str:
    return _str(value, 1024)


def _type_name(value: object) -> str:
    return _str(value, 1024, empty=True)


def _runtime_id(value: object) -> tuple[int, ...]:
    return _array(value, lambda item: _int(item, -2_147_483_648, 2_147_483_647), 1024, 1)


array_value = _array
bool_value = _bool
choice_value = _choice
identifier_value = _identifier
integer_value = _int
key_value = _key
object_value = _obj
runtime_id_value = _runtime_id


def _timestamp(value: object) -> str:
    text = _str(value)
    match = _TIMESTAMP.fullmatch(text)
    if not match:
        raise ValueError("Invalid process timestamp")
    fraction = match.group(2) or ""
    if len(fraction) > 7 and any(char != "0" for char in fraction[7:]):
        raise ValueError("Process timestamp exceeds Windows clock precision")
    ticks = int((fraction + "0000000")[:7])
    zone = match.group(3).upper().replace("Z", "+00:00")
    moment = datetime.fromisoformat(match.group(1) + zone).astimezone(UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%S") + f".{ticks:07d}Z"


def timestamp_from_filetime(ticks: int) -> str:
    seconds, fraction = divmod(ticks, 10_000_000)
    moment = datetime(1601, 1, 1, tzinfo=UTC) + timedelta(seconds=seconds)
    return moment.strftime("%Y-%m-%dT%H:%M:%S") + f".{fraction:07d}Z"


def _camel(name: str) -> str:
    first, *rest = name.split("_")
    return first + "".join(word.title() for word in rest)


def _wire(value: Any) -> Any:
    if isinstance(value, PathSegment):
        return value.to_json()
    if is_dataclass(value) and not isinstance(value, type):
        result: dict[str, Any] = {}
        for item in fields(value):
            entry = getattr(value, item.name)
            if (entry is None and item.name not in {"scalar", "value"}) or entry is MISSING:
                continue
            name = {"object_ref": "object", "type_info": "typeInfo"}.get(
                item.name, _camel(item.name)
            )
            result[name] = _wire(entry)
        return result
    if isinstance(value, (tuple, list)):
        return [_wire(entry) for entry in cast(tuple[Any, ...] | list[Any], value)]
    if isinstance(value, dict):
        return {key: _wire(entry) for key, entry in cast(dict[str, Any], value).items()}
    return value


class WireModel:
    def to_json(self) -> dict[str, Any]:
        return cast(dict[str, Any], _wire(self))


@dataclass(frozen=True)
class ProcessIdentity(WireModel):
    pid: int
    creation_time_utc: str

    def __post_init__(self) -> None:
        _int(self.pid, 1, 4_294_967_295)
        object.__setattr__(self, "creation_time_utc", _timestamp(self.creation_time_utc))

    @classmethod
    def from_json(cls, value: object) -> ProcessIdentity:
        data = _obj(value, "pid creationTimeUtc")
        return cls(_int(data["pid"], 1, 4_294_967_295), _timestamp(data["creationTimeUtc"]))


@dataclass(frozen=True)
class ProcessFacts:
    identity: ProcessIdentity
    executable: str
    architecture: Literal["x86", "x64", "arm64", "unknown"]
    runtime: Literal["net48", "net8", "net10"] | None
    wpf_loaded: bool
    session_id: int
    user_sid: str
    integrity: str


@dataclass(frozen=True)
class Session(WireModel):
    session_id: str
    process: ProcessIdentity
    state: str
    protocol_major: int
    protocol_minor: int
    features: tuple[str, ...]
    runtime_version: str | None = None
    architecture: str | None = None
    agent_version: str | None = None
    error: str | None = None

    @classmethod
    def from_json(cls, value: object) -> Session:
        data = _obj(
            value,
            "sessionId process state protocolMajor protocolMinor features",
            "runtimeVersion architecture agentVersion error",
        )
        return cls(
            _identifier(data["sessionId"]),
            ProcessIdentity.from_json(data["process"]),
            _choice(data["state"], STATES),
            _int(data["protocolMajor"]),
            _int(data["protocolMinor"]),
            _array(data["features"], lambda item: _choice(item, FEATURES), 200),
            _optional(data, "runtimeVersion", _identifier),
            _optional(data, "architecture", _identifier),
            _optional(data, "agentVersion", _identifier),
            _optional(data, "error", _key),
        )


@dataclass(frozen=True)
class TypeInfo(WireModel):
    name: str
    full_name: str
    assembly_name: str
    assembly_qualified_name: str
    base_types: tuple[str, ...]

    @classmethod
    def from_json(cls, value: object) -> TypeInfo:
        data = _obj(value, "name fullName assemblyName assemblyQualifiedName baseTypes")
        return cls(
            _type_name(data["name"]),
            _type_name(data["fullName"]),
            _type_name(data["assemblyName"]),
            _type_name(data["assemblyQualifiedName"]),
            _array(data["baseTypes"], _type_name, 1024),
        )


@dataclass(frozen=True)
class ObjectRef(WireModel):
    session_id: str
    object_id: str
    generation: int
    type: TypeInfo
    dispatcher_id: str

    @classmethod
    def from_json(cls, value: object) -> ObjectRef:
        data = _obj(value, "sessionId objectId generation type dispatcherId")
        return cls(
            _identifier(data["sessionId"]),
            _identifier(data["objectId"]),
            _int(data["generation"], 1),
            TypeInfo.from_json(data["type"]),
            _identifier(data["dispatcherId"]),
        )


@dataclass(frozen=True)
class AttributeLiteral(WireModel):
    kind: str
    value: object

    @classmethod
    def from_json(cls, value: object, *, nested: bool = False) -> AttributeLiteral:
        data = _obj(value, "kind value")
        kind = _choice(
            data["kind"],
            {"string", "enum", "type", "boolean", "integer", "number", "null", "array"},
        )
        item = data["value"]
        if kind == "string":
            item = _str(item, 4096, empty=True)
        elif kind in {"enum", "type"}:
            item = _key(item)
        elif kind == "boolean":
            item = _bool(item)
        elif kind == "integer":
            item = _int(item, -9_223_372_036_854_775_808)
        elif kind == "number":
            if not _finite_number(item):
                raise ValueError("Invalid attribute number")
        elif kind == "null":
            if item is not None:
                raise ValueError("Invalid attribute null")
        else:
            if nested:
                raise ValueError("Nested attribute arrays are not supported")
            item = _array(item, lambda entry: cls.from_json(entry, nested=True), 32)
        return cls(kind, item)


@dataclass(frozen=True)
class AttributeInfo(WireModel):
    type_name: str
    constructor_arguments: tuple[AttributeLiteral, ...]
    named_arguments: dict[str, AttributeLiteral]

    @classmethod
    def from_json(cls, value: object) -> AttributeInfo:
        data = _obj(value, "typeName constructorArguments namedArguments")
        named_value: object = data["namedArguments"]
        if not isinstance(named_value, dict):
            raise ValueError("Invalid named arguments")
        named = cast(dict[str, Any], named_value)
        if len(named) > 32:
            raise ValueError("Invalid named arguments")
        return cls(
            _key(data["typeName"]),
            _array(data["constructorArguments"], AttributeLiteral.from_json, 32),
            {_identifier(key): AttributeLiteral.from_json(item) for key, item in named.items()},
        )


@dataclass(frozen=True)
class DependencyMetadata(WireModel):
    owner_type: str
    owner_assembly: str
    property_type: str
    read_only: bool
    is_attached: str
    has_local_value: bool
    metadata_flags: tuple[str, ...]

    @classmethod
    def from_json(cls, value: object) -> DependencyMetadata:
        data = _obj(
            value,
            "ownerType ownerAssembly propertyType readOnly isAttached hasLocalValue metadataFlags",
        )
        flags = {
            "None",
            "AffectsMeasure",
            "AffectsArrange",
            "AffectsParentMeasure",
            "AffectsParentArrange",
            "AffectsRender",
            "Inherits",
            "OverridesInheritanceBehavior",
            "NotDataBindable",
            "BindsTwoWayByDefault",
            "Journal",
            "SubPropertiesDoNotAffectRender",
        }
        return cls(
            _key(data["ownerType"]),
            _key(data["ownerAssembly"]),
            _key(data["propertyType"]),
            _bool(data["readOnly"]),
            _choice(data["isAttached"], {"true", "false", "unknown"}),
            _bool(data["hasLocalValue"]),
            _array(data["metadataFlags"], lambda item: _choice(item, flags), 32),
        )


@dataclass(frozen=True)
class Member(WireModel):
    member_key: str
    name: str
    category: str
    declaring_type: str
    declared_type: str
    visibility: str
    readable: bool
    attributes: tuple[AttributeInfo, ...]
    path_segment: PathSegment | None = None
    dependency: DependencyMetadata | None = None
    reason: str | None = None
    wrapper_key: str | None = None
    compatibility_alias: str | None = None

    @classmethod
    def from_json(cls, value: object) -> Member:
        data = _obj(
            value,
            "memberKey name category declaringType declaredType visibility readable attributes",
            "pathSegment dependency reason wrapperKey compatibilityAlias",
        )
        return cls(
            _key(data["memberKey"]),
            _key(data["name"]),
            _choice(
                data["category"],
                {
                    "typeMetadata",
                    "clrProperty",
                    "clrField",
                    "dependencyProperty",
                    "attachedProperty",
                },
            ),
            _type_name(data["declaringType"]),
            _type_name(data["declaredType"]),
            _choice(
                data["visibility"],
                {
                    "public",
                    "protected",
                    "internal",
                    "private",
                    "protectedInternal",
                    "privateProtected",
                },
            ),
            _bool(data["readable"]),
            _array(data["attributes"], AttributeInfo.from_json, 32),
            _optional(data, "pathSegment", PathSegment.from_json),
            _optional(data, "dependency", DependencyMetadata.from_json),
            _optional(
                data,
                "reason",
                lambda item: _choice(
                    item,
                    {"nonPublic", "writeOnly", "indexer", "static", "unsupportedType", "ambiguous"},
                ),
            ),
            _optional(data, "wrapperKey", _key),
            _optional(data, "compatibilityAlias", _identifier),
        )


@dataclass(frozen=True)
class Diagnostic(WireModel):
    code: str
    message: str
    category: str | None = None

    @classmethod
    def from_json(cls, value: object) -> Diagnostic:
        data = _obj(value, "code message", "category")
        return cls(
            _identifier(data["code"]),
            _str(data["message"], 1024, empty=True),
            _optional(data, "category", _identifier),
        )


@dataclass(frozen=True)
class DependencySource(WireModel):
    base_value_source: str
    is_expression: bool
    is_animated: bool
    is_coerced: bool
    is_current: bool

    @classmethod
    def from_json(cls, value: object) -> DependencySource:
        data = _obj(value, "baseValueSource isExpression isAnimated isCoerced isCurrent")
        sources = {
            "Unknown",
            "Default",
            "Inherited",
            "DefaultStyle",
            "DefaultStyleTrigger",
            "Style",
            "TemplateTrigger",
            "StyleTrigger",
            "ImplicitStyleReference",
            "ParentTemplate",
            "ParentTemplateTrigger",
            "Local",
        }
        return cls(
            _choice(data["baseValueSource"], sources),
            *(_bool(data[key]) for key in ("isExpression", "isAnimated", "isCoerced", "isCurrent")),
        )


@dataclass(frozen=True)
class Value(WireModel):
    status: str
    kind: str
    declared_type: str
    runtime_type: str
    scalar: object = MISSING
    object_ref: ObjectRef | None = None
    message: str | None = None
    truncated_at: int | None = None
    cycle_to: ObjectRef | None = None
    numeric_value: str | None = None
    type_info: TypeInfo | None = None
    array_rank: int | None = None
    array_length: int | None = None
    failed_segment: int | None = None
    redaction_rule: str | None = None
    dependency_source: DependencySource | None = None

    @classmethod
    def from_json(cls, value: object) -> Value:
        data = _obj(
            value,
            "status kind declaredType runtimeType",
            "scalar object message truncatedAt cycleTo numericValue typeInfo arrayRank "
            "arrayLength failedSegment redactionRule dependencySource",
        )
        status = _choice(
            data["status"],
            {
                "ok",
                "notRead",
                "notReadable",
                "nullIntermediate",
                "exception",
                "stale",
                "redacted",
                "truncated",
                "cycle",
                "timeout",
                "unsupported",
            },
        )
        kind = _choice(
            data["kind"],
            {
                "null",
                "string",
                "boolean",
                "integer",
                "number",
                "enum",
                "object",
                "array",
                "type",
                "unavailable",
            },
        )
        scalar = data.get("scalar", MISSING)
        keys = data.keys()
        if status == "ok":
            if kind == "unavailable" or keys & {"cycleTo", "truncatedAt", "failedSegment"}:
                raise ValueError("Invalid ok value")
            if kind in {"null", "string", "boolean", "integer", "number", "enum"}:
                if "scalar" not in data or "object" in data:
                    raise ValueError("Missing scalar")
            elif kind in {"object", "array"}:
                if "object" not in data or "scalar" in data:
                    raise ValueError("Missing object")
            elif kind == "type" and ("typeInfo" not in data or keys & {"object", "scalar"}):
                raise ValueError("Invalid type value")
            if kind == "null" and scalar is not None:
                raise ValueError("Invalid null")
            if kind in {"string", "enum"}:
                _str(scalar, 4096, empty=True)
            if kind == "boolean":
                _bool(scalar)
            if kind == "integer" and not (
                (type(scalar) is int and abs(scalar) <= 9_007_199_254_740_991)
                or (
                    isinstance(scalar, str)
                    and len(scalar) <= 4096
                    and _INT_PATTERN.fullmatch(scalar)
                )
            ):
                raise ValueError("Invalid integer scalar")
            if kind == "number" and not (
                _finite_number(scalar)
                or (
                    isinstance(scalar, str)
                    and len(scalar) <= 4096
                    and _NUMBER_PATTERN.fullmatch(scalar)
                )
            ):
                raise ValueError("Invalid number scalar")
            if kind == "enum" and "numericValue" not in data:
                raise ValueError("Missing enum numeric value")
            if kind == "array" and not {"arrayRank", "arrayLength"} <= keys:
                raise ValueError("Missing array shape")
        elif status == "truncated":
            if (
                kind != "string"
                or not {"scalar", "truncatedAt"} <= keys
                or keys & {"object", "cycleTo", "failedSegment"}
            ):
                raise ValueError("Invalid truncated value")
            if _int(data["truncatedAt"], 1) <= len(_str(scalar, 4096, empty=True)):
                raise ValueError("Invalid truncation length")
        elif status == "cycle":
            if "cycleTo" not in data or keys & {"scalar", "object", "truncatedAt", "failedSegment"}:
                raise ValueError("Invalid cycle")
        elif kind != "unavailable" or keys & {
            "scalar",
            "object",
            "cycleTo",
            "truncatedAt",
            "dependencySource",
        }:
            raise ValueError("Invalid unavailable value")
        if (status in {"nullIntermediate", "exception"}) != ("failedSegment" in data):
            raise ValueError("Invalid failed segment")
        if (kind != "array" or status != "ok") and keys & {"arrayRank", "arrayLength"}:
            raise ValueError("Unexpected array shape")
        if (status != "ok" and "numericValue" in data) or (
            status != "redacted" and "redactionRule" in data
        ):
            raise ValueError("Invalid value metadata")
        numeric = _optional(data, "numericValue", _key)
        if numeric is not None and not _INT_PATTERN.fullmatch(numeric):
            raise ValueError("Invalid numeric value")
        return cls(
            status,
            kind,
            _type_name(data["declaredType"]),
            _type_name(data["runtimeType"]),
            scalar,
            _optional(data, "object", ObjectRef.from_json),
            _optional(data, "message", lambda item: _str(item, 1024, empty=True)),
            _optional(data, "truncatedAt", lambda item: _int(item, 1)),
            _optional(data, "cycleTo", ObjectRef.from_json),
            numeric,
            _optional(data, "typeInfo", TypeInfo.from_json),
            _optional(data, "arrayRank", lambda item: _int(item, 1)),
            _optional(data, "arrayLength", _int),
            _optional(data, "failedSegment", lambda item: _int(item, 0, 7)),
            _optional(data, "redactionRule", _key),
            _optional(data, "dependencySource", DependencySource.from_json),
        )

    def as_python(self) -> object:
        if self.status != "ok" or self.scalar is MISSING:
            raise ValueError("Value is not a usable scalar")
        if self.kind == "integer" and isinstance(self.scalar, str):
            return int(self.scalar)
        if self.kind == "number" and isinstance(self.scalar, str):
            return Decimal(self.scalar)
        return self.scalar


def parse_path(value: object) -> tuple[PathSegment, ...]:
    path = _array(value, PathSegment.from_json, 8, 1)
    if len(path) > 1 and any(segment.kind == "type" for segment in path):
        raise ValueError("Type metadata must be the only segment")
    if (
        len(
            json.dumps(
                [segment.to_json() for segment in path], ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        )
        > 1024
    ):
        raise ValueError("Serialized path exceeds 1024 bytes")
    return path


@dataclass(frozen=True)
class PathValue(WireModel):
    path: tuple[PathSegment, ...]
    value: Value

    @classmethod
    def from_json(cls, value: object) -> PathValue:
        data = _obj(value, "path value")
        return cls(parse_path(data["path"]), Value.from_json(data["value"]))


@dataclass(frozen=True)
class Mapping(WireModel):
    status: str
    process: ProcessIdentity
    runtime_id: tuple[int, ...]
    object_ref: ObjectRef | None = None

    @classmethod
    def from_json(cls, value: object) -> Mapping:
        data = _obj(value, "status process runtimeId", "object")
        status = _choice(
            data["status"],
            {"exact", "notFound", "ambiguous", "unsupportedPeer", "stale", "limitExceeded"},
        )
        if (status == "exact") != ("object" in data):
            raise ValueError("Invalid mapping variant")
        return cls(
            status,
            ProcessIdentity.from_json(data["process"]),
            _runtime_id(data["runtimeId"]),
            _optional(data, "object", ObjectRef.from_json),
        )


@dataclass(frozen=True)
class ManagedNode(WireModel):
    object_ref: ObjectRef
    label: str
    has_visual_children: bool
    has_logical_children: bool
    runtime_id: tuple[int, ...] | None = None

    @classmethod
    def from_json(cls, value: object) -> ManagedNode:
        data = _obj(value, "object label hasVisualChildren hasLogicalChildren", "runtimeId")
        return cls(
            ObjectRef.from_json(data["object"]),
            _str(data["label"], 1024, empty=True),
            _bool(data["hasVisualChildren"]),
            _bool(data["hasLogicalChildren"]),
            _optional(data, "runtimeId", _runtime_id),
        )


@dataclass(frozen=True)
class Page[T](WireModel):
    items: tuple[T, ...]
    complete: bool
    snapshot_id: str
    diagnostics: tuple[Diagnostic, ...]
    next_token: str | None = None

    @classmethod
    def from_json(cls, value: object, reader: Callable[[Any], T]) -> Page[T]:
        data = _obj(value, "items complete snapshotId diagnostics", "nextToken")
        complete = _bool(data["complete"])
        if complete and "nextToken" in data:
            raise ValueError("Complete page has a continuation")
        return cls(
            _array(data["items"], reader, 200),
            complete,
            _identifier(data["snapshotId"]),
            _array(data["diagnostics"], Diagnostic.from_json, 200),
            _optional(data, "nextToken", _identifier),
        )


@dataclass(frozen=True)
class RelativeSource(WireModel):
    mode: str
    ancestor_type: str | None = None
    ancestor_level: int | None = None

    @classmethod
    def from_json(cls, value: object) -> RelativeSource:
        data = _obj(value, "mode", "ancestorType ancestorLevel")
        return cls(
            _choice(data["mode"], {"FindAncestor", "PreviousData", "TemplatedParent", "Self"}),
            _optional(data, "ancestorType", _key),
            _optional(data, "ancestorLevel", lambda item: _int(item, 1, 2_147_483_647)),
        )


@dataclass(frozen=True)
class BindingInfo(WireModel):
    member_key: str
    kind: str
    status: str
    mode: str
    update_source_trigger: str
    path: str | None = None
    element_name: str | None = None
    relative_source: RelativeSource | None = None
    source_type: str | None = None
    converter_type: str | None = None
    children: tuple[BindingInfo, ...] | None = None
    validation_errors: tuple[str, ...] | None = None

    @classmethod
    def from_json(cls, value: object) -> BindingInfo:
        count = [0]

        def parse(item: object, depth: int) -> BindingInfo:
            count[0] += 1
            if count[0] > 32 or depth > 8:
                raise ValueError("Binding tree exceeds limits")
            data = _obj(
                item,
                "memberKey kind status mode updateSourceTrigger",
                "path elementName relativeSource sourceType converterType children "
                "validationErrors",
            )
            kind = _choice(data["kind"], {"none", "binding", "multiBinding", "priorityBinding"})
            status, mode, trigger = (
                _str(data[key], 128, empty=True)
                for key in ("status", "mode", "updateSourceTrigger")
            )
            if kind == "none" and any((status, mode, trigger)):
                raise ValueError("Invalid empty binding")
            def text(entry: object) -> str:
                return _str(entry, 1024, empty=True)
            return cls(
                _key(data["memberKey"]),
                kind,
                status,
                mode,
                trigger,
                _optional(data, "path", text),
                _optional(data, "elementName", text),
                _optional(data, "relativeSource", RelativeSource.from_json),
                _optional(data, "sourceType", _key),
                _optional(data, "converterType", _key),
                _optional(
                    data,
                    "children",
                    lambda entries: _array(entries, lambda child: parse(child, depth + 1), 32),
                ),
                _optional(data, "validationErrors", lambda entries: _array(entries, _key, 32)),
            )

        return parse(value, 1)


@dataclass(frozen=True)
class CandidateResult(WireModel):
    runtime_id: tuple[int, ...]
    mapping: Mapping
    values: tuple[PathValue, ...]

    @classmethod
    def from_json(cls, value: object) -> CandidateResult:
        data = _obj(value, "runtimeId mapping values")
        mapping = Mapping.from_json(data["mapping"])
        values = _array(data["values"], PathValue.from_json, 32)
        if mapping.status != "exact" and values:
            raise ValueError("Values for an inexact mapping")
        return cls(_runtime_id(data["runtimeId"]), mapping, values)


@dataclass(frozen=True)
class HelloResult(WireModel):
    agent_version: str
    tfm: str
    architecture: str
    runtime_version: str
    features: tuple[str, ...]
    process: ProcessIdentity

    @classmethod
    def from_json(cls, value: object) -> HelloResult:
        data = _obj(value, "agentVersion tfm architecture runtimeVersion features process")
        return cls(
            _identifier(data["agentVersion"]),
            _choice(data["tfm"], {"net48", "net8.0-windows", "net10.0-windows"}),
            _choice(data["architecture"], {"x86", "x64"}),
            _identifier(data["runtimeVersion"]),
            _array(data["features"], lambda item: _choice(item, FEATURES), 200),
            ProcessIdentity.from_json(data["process"]),
        )


@dataclass(frozen=True)
class HelloParams(WireModel):
    protocol_major: int
    protocol_minor: int
    session_id: str
    token: str = field(repr=False)
    process: ProcessIdentity

    @classmethod
    def from_json(cls, value: object) -> HelloParams:
        data = _obj(value, "protocolMajor protocolMinor sessionId token process")
        return cls(_int(data["protocolMajor"], 1, 1), _int(data["protocolMinor"]),
                   _identifier(data["sessionId"]), _identifier(data["token"]),
                   ProcessIdentity.from_json(data["process"]))


@dataclass(frozen=True)
class BootstrapSettings(WireModel):
    schema_version: int
    protocol_major: int
    protocol_minor: int
    session_id: str
    process: ProcessIdentity
    pipe_name: str
    token: str = field(repr=False)
    client_sid: str
    expires_utc: str
    request_timeout_ms: int
    idle_timeout_ms: int
    agent_version: str
    redact_names: tuple[str, ...] = field(repr=False)

    @classmethod
    def from_json(cls, value: object) -> BootstrapSettings:
        data = _obj(
            value,
            "schemaVersion protocolMajor protocolMinor sessionId process pipeName token "
            "clientSid expiresUtc requestTimeoutMs idleTimeoutMs agentVersion redactNames",
        )
        session_id = _identifier(data["sessionId"])
        try:
            uuid.UUID(session_id)
        except ValueError as error:
            raise ValueError("Invalid bootstrap session UUID") from error
        token = _identifier(data["token"])
        if not re.fullmatch(r"[A-Za-z0-9+/]{43}=", token):
            raise ValueError("Invalid bootstrap token")
        if not isinstance(data["redactNames"], list):
            raise ValueError("Invalid redaction names")
        return cls(_int(data["schemaVersion"], 1, 1), _int(data["protocolMajor"], 0, 2_147_483_647),
                   _int(data["protocolMinor"], 0, 2_147_483_647), session_id,
                   ProcessIdentity.from_json(data["process"]), _key(data["pipeName"]), token,
                   _identifier(data["clientSid"]), _timestamp(data["expiresUtc"]),
                   _int(data["requestTimeoutMs"], 1, 2000), _int(data["idleTimeoutMs"], 1, 300000),
                   _identifier(data["agentVersion"]),
                   validate_redact_names(cast("list[object]", data["redactNames"])))


@dataclass(frozen=True)
class RequestEnvelope:
    id: int
    method: str
    params: dict[str, Any]

    @classmethod
    def from_json(cls, value: object) -> RequestEnvelope:
        data = _obj(value, "id method params")
        method = _choice(
            data["method"],
            {
                "session.hello", "session.close", "request.cancel", "element.resolve",
                "element.readBatch", "roots", "children", "members", "read", "bindings", "release",
            },
        )
        if not isinstance(data["params"], dict):
            raise ValueError("Invalid request parameters")
        return cls(_int(data["id"], 1), method, cast(dict[str, Any], data["params"]))
