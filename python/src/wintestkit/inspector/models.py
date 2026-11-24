"""Explicit, immutable inspector DTOs and strict wire validation."""

from __future__ import annotations

import base64
import binascii
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
        "membersItems",
        "membersStyling",
        "membersEvents",
        "dependencyProperties",
        "bindings",
        "exactUiaMapping",
        "batchReads",
        "query",
        "geometry",
        "treeParent",
        "actions",
        "virtualItems",
        "writes",
        "hitTest",
        "waits",
        "events",
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
        "notFound",
        "actionUnsupported",
        "regexTimeout",
        "valueUnreadable",
        "writeDenied",
        "writeRateExceeded",
    }
)
STATES = frozenset({"detached", "probing", "attaching", "ready", "detaching", "faulted", "exited"})
_INT_PATTERN = re.compile(r"-?(?:0|[1-9][0-9]*)\Z")
_NUMBER_PATTERN = re.compile(
    r"(?:NaN|Infinity|-Infinity|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)\Z"
)
_DECIMAL_PATTERN = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")
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


string_value = _str


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
    if type(value).__name__ == "MemberEvent":
        # The wire names an event's handler list by its kind, so the event writes itself.
        return value.to_json()
    if is_dataclass(value) and not isinstance(value, type):
        result: dict[str, Any] = {}
        for item in fields(value):
            entry = getattr(value, item.name)
            if (
                entry is None
                and (
                    item.name not in {"scalar", "value"}
                    or type(value).__name__ in {"StylingSetter", "ResourceResult"}
                )
                and not (
                    type(value).__name__ in {"ElementState", "PartGeometry"}
                    and item.name in {"bounds", "window_handle", "click_point"}
                )
            ) or entry is MISSING:
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
    winforms_loaded: bool = False


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
            _int(data["protocolMajor"], 2, 2),
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

    @property
    def is_winforms(self) -> bool:
        """True for a WinForms control or tool strip item, false for a WPF object."""
        names = (self.type.full_name, *self.type.base_types)
        return (
            "System.Windows.Forms.Control" in names or "System.Windows.Forms.ToolStripItem" in names
        )

    @property
    def is_winforms_item(self) -> bool:
        """True for a tool strip item, which has no window of its own."""
        return "System.Windows.Forms.ToolStripItem" in (self.type.full_name, *self.type.base_types)

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
class Item(WireModel):
    index: int | None
    key: Value | None
    value: Value

    @classmethod
    def from_json(cls, value: object) -> Item:
        data = _obj(value, "index key value")
        return cls(
            None if data["index"] is None else _int(data["index"], 0, 2**31 - 1),
            None if data["key"] is None else Value.from_json(data["key"]),
            Value.from_json(data["value"]),
        )


@dataclass(frozen=True)
class ItemsError(WireModel):
    type: str
    message: str | None

    @classmethod
    def from_json(cls, value: object) -> ItemsError:
        data = _obj(value, "type message")
        return cls(
            _str(data["type"]),
            None if data["message"] is None else _str(data["message"], 512, empty=True),
        )


@dataclass(frozen=True)
class ItemsResult(WireModel):
    kind: str
    count: int | None
    items: tuple[Item, ...]
    next_page_token: str | None
    complete: bool
    error: ItemsError | None = None

    @classmethod
    def from_json(cls, value: object) -> ItemsResult:
        data = _obj(value, "kind count items nextPageToken complete", "error")
        complete = _bool(data["complete"])
        token = None if data["nextPageToken"] is None else _identifier(data["nextPageToken"])
        if complete and token is not None:
            raise ValueError("Complete page cannot have next token")
        return cls(
            _choice(data["kind"], {"array", "list", "dictionary", "enumerable", "notEnumerable"}),
            None if data["count"] is None else _int(data["count"], 0, 2**31 - 1),
            _array(data["items"], Item.from_json, 200),
            token,
            complete,
            _optional(data, "error", ItemsError.from_json),
        )

    def to_json(self) -> dict[str, Any]:
        result = super().to_json()
        result["count"] = self.count
        result["nextPageToken"] = self.next_page_token
        result["items"] = [
            {
                "index": item.index,
                "key": item.key.to_json() if item.key else None,
                "value": item.value.to_json(),
            }
            for item in self.items
        ]
        if self.error:
            result["error"] = {"type": self.error.type, "message": self.error.message}
        return result


@dataclass(frozen=True)
class MethodParameter(WireModel):
    name: str
    type: str
    is_out: bool

    @classmethod
    def from_json(cls, value: object) -> MethodParameter:
        data = _obj(value, "name type isOut")
        return cls(
            _str(data["name"], 1024, empty=True), _str(data["type"], 1024), _bool(data["isOut"])
        )


@dataclass(frozen=True)
class MethodMetadata(WireModel):
    key: str
    name: str
    declaring_type: str
    return_type: str
    visibility: str
    is_static: bool
    parameters: tuple[MethodParameter, ...]
    unsupported_reason: str | None = None

    @classmethod
    def from_json(cls, value: object) -> MethodMetadata:
        data = _obj(
            value,
            "key name declaringType returnType visibility isStatic parameters",
            "unsupportedReason",
        )
        return cls(
            _str(data["key"], 8192),
            _str(data["name"], 1024),
            _str(data["declaringType"], 1024),
            _str(data["returnType"], 1024),
            _choice(
                data["visibility"],
                {
                    "public",
                    "private",
                    "protected",
                    "internal",
                    "protectedInternal",
                    "privateProtected",
                },
            ),
            _bool(data["isStatic"]),
            _array(data["parameters"], MethodParameter.from_json, 128),
            _optional(data, "unsupportedReason", lambda item: _str(item, 1024)),
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
                    "staticProperty",
                    "staticField",
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
                    {"nonPublic", "writeOnly", "indexer", "unsupportedType", "ambiguous"},
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
    error_message: str | None = None

    @classmethod
    def from_json(cls, value: object) -> Value:
        data = _obj(
            value,
            "status kind declaredType runtimeType",
            "scalar object message truncatedAt cycleTo numericValue typeInfo arrayRank "
            "arrayLength failedSegment redactionRule dependencySource errorMessage",
        )
        status = _choice(
            data["status"],
            {
                "ok",
                "unavailable",
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
        if status != "exception" and "errorMessage" in data:
            raise ValueError("Unexpected error message")
        if (status in {"nullIntermediate", "exception"}) != ("failedSegment" in data):
            raise ValueError("Invalid failed segment")
        if (kind != "array" or status != "ok") and keys & {"arrayRank", "arrayLength"}:
            raise ValueError("Unexpected array shape")
        if (status != "ok" and "numericValue" in data) or (
            status != "redacted" and "redactionRule" in data
        ):
            raise ValueError("Invalid value metadata")
        numeric = _optional(data, "numericValue", _key)
        numeric_pattern = _DECIMAL_PATTERN if kind == "number" else _INT_PATTERN
        if numeric is not None and not numeric_pattern.fullmatch(numeric):
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
            _optional(data, "errorMessage", lambda item: _str(item, 512, empty=True)),
        )

    def as_python(self) -> object:
        if self.status != "ok" or self.scalar is MISSING:
            detail = f": {self.error_message}" if self.error_message else ""
            raise ValueError(f"Value is not a usable scalar{detail}")
        if self.kind == "integer" and isinstance(self.scalar, str):
            return int(self.scalar)
        if self.kind == "number" and isinstance(self.scalar, str):
            return Decimal(self.scalar)
        return self.scalar


def parse_path(value: object) -> tuple[PathSegment, ...]:
    path = _array(value, PathSegment.from_json, 8, 1)
    if len(path) > 1 and any(segment.kind in {"type", "uia"} for segment in path):
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
class NodeIdentity(WireModel):
    x_name: str | None = None
    automation_id: str | None = None

    @classmethod
    def from_json(cls, value: object) -> NodeIdentity:
        data = _obj(value, "", "xName automationId")
        return cls(
            _optional(data, "xName", lambda v: _str(v, 4096, empty=True)),
            _optional(data, "automationId", lambda v: _str(v, 4096, empty=True)),
        )


@dataclass(frozen=True)
class ManagedNode(WireModel):
    object_ref: ObjectRef
    label: str
    has_visual_children: bool
    has_logical_children: bool
    runtime_id: tuple[int, ...] | None = None
    identity: NodeIdentity | None = None

    @classmethod
    def from_json(cls, value: object) -> ManagedNode:
        data = _obj(
            value, "object label hasVisualChildren hasLogicalChildren", "runtimeId identity"
        )
        return cls(
            ObjectRef.from_json(data["object"]),
            _str(data["label"], 1024, empty=True),
            _bool(data["hasVisualChildren"]),
            _bool(data["hasLogicalChildren"]),
            _optional(data, "runtimeId", _runtime_id),
            _optional(data, "identity", NodeIdentity.from_json),
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
    string_format: str | None = None
    fallback_value: Value | None = None
    target_null_value: Value | None = None
    converter_parameter: Value | None = None
    converter_culture: str | None = None
    delay: int | None = None
    binding_group_name: str | None = None
    x_path: str | None = None
    is_async: bool | None = None
    notify_on_source_updated: bool | None = None
    notify_on_target_updated: bool | None = None
    notify_on_validation_error: bool | None = None
    validates_on_data_errors: bool | None = None
    validates_on_exceptions: bool | None = None
    validates_on_notify_data_errors: bool | None = None
    validation_rules: tuple[str, ...] | None = None
    has_update_source_exception_filter: bool | None = None
    active_child_index: int | None = None
    data_item: Value | None = None
    resolved_source: Value | None = None
    resolved_source_property_name: str | None = None
    has_error: bool | None = None
    has_validation_error: bool | None = None

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
                "validationErrors stringFormat fallbackValue targetNullValue converterParameter "
                "converterCulture delay bindingGroupName xPath isAsync notifyOnSourceUpdated "
                "notifyOnTargetUpdated notifyOnValidationError validatesOnDataErrors "
                "validatesOnExceptions validatesOnNotifyDataErrors validationRules "
                "hasUpdateSourceExceptionFilter activeChildIndex dataItem resolvedSource "
                "resolvedSourcePropertyName hasError hasValidationError",
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
                _optional(data, "stringFormat", text),
                _optional(data, "fallbackValue", Value.from_json),
                _optional(data, "targetNullValue", Value.from_json),
                _optional(data, "converterParameter", Value.from_json),
                _optional(data, "converterCulture", lambda entry: _str(entry, 128, empty=True)),
                _optional(data, "delay", lambda entry: _int(entry, 0, 2_147_483_647)),
                _optional(data, "bindingGroupName", text),
                _optional(data, "xPath", text),
                _optional(data, "isAsync", _bool),
                _optional(data, "notifyOnSourceUpdated", _bool),
                _optional(data, "notifyOnTargetUpdated", _bool),
                _optional(data, "notifyOnValidationError", _bool),
                _optional(data, "validatesOnDataErrors", _bool),
                _optional(data, "validatesOnExceptions", _bool),
                _optional(data, "validatesOnNotifyDataErrors", _bool),
                _optional(data, "validationRules", lambda entries: _array(entries, _key, 32)),
                _optional(data, "hasUpdateSourceExceptionFilter", _bool),
                _optional(data, "activeChildIndex", lambda entry: _int(entry, 0, 31)),
                _optional(data, "dataItem", Value.from_json),
                _optional(data, "resolvedSource", Value.from_json),
                _optional(data, "resolvedSourcePropertyName", text),
                _optional(data, "hasError", _bool),
                _optional(data, "hasValidationError", _bool),
            )

        return parse(value, 1)


STYLING_ACTIVITY = frozenset({"active", "inactive", "unknown"})
STYLING_SETTER_KINDS = frozenset(
    {
        "value",
        "dynamicResource",
        "binding",
        "multiBinding",
        "priorityBinding",
        "templateBinding",
        "other",
    }
)
STYLING_TRIGGER_KINDS = frozenset(
    {"trigger", "dataTrigger", "multiTrigger", "multiDataTrigger", "eventTrigger", "other"}
)
STYLING_STYLE_SOURCES = frozenset({"local", "implicit", "typeLookup", "none"})
STYLING_TEMPLATE_KINDS = frozenset(
    {"controlTemplate", "dataTemplate", "hierarchicalDataTemplate", "itemsPanelTemplate", "other"}
)
STYLING_KEY_KINDS = frozenset({"string", "type", "componentResourceKey", "other"})
STYLING_MAX_ENTRIES = 32
STYLING_MAX_BASED_ON = 8
STYLING_MAX_RESOURCES = 200


def _styling_text(value: object) -> str:
    return _str(value, 1024, empty=True)


def _truncation(truncated: bool, total: int, listed: int, maximum: int) -> None:
    if listed > maximum or listed > total or truncated == (listed >= total):
        raise ValueError("Inconsistent list size")


@dataclass(frozen=True)
class StylingCondition(WireModel):
    """A trigger condition: a property or binding path and the value it is compared with."""

    value: Value
    active: str
    property: str | None = None
    binding: str | None = None
    source_name: str | None = None

    @classmethod
    def from_json(cls, value: object) -> StylingCondition:
        data = _obj(value, "value active", "property binding sourceName")
        return cls(
            Value.from_json(data["value"]),
            _choice(data["active"], STYLING_ACTIVITY),
            _optional(data, "property", _styling_text),
            _optional(data, "binding", _styling_text),
            _optional(data, "sourceName", _styling_text),
        )


@dataclass(frozen=True)
class StylingSetter(WireModel):
    """A Setter. Resource and binding markup is named (`expression`), never evaluated."""

    property: str
    owner: str
    kind: str
    target_name: str | None = None
    expression: str | None = None
    value: Value | None = None

    @classmethod
    def from_json(cls, value: object) -> StylingSetter:
        data = _obj(value, "property owner kind", "targetName expression value")
        return cls(
            _styling_text(data["property"]),
            _styling_text(data["owner"]),
            _choice(data["kind"], STYLING_SETTER_KINDS),
            _optional(data, "targetName", _styling_text),
            _optional(data, "expression", _styling_text),
            _optional(data, "value", Value.from_json),
        )


@dataclass(frozen=True)
class StylingTrigger(WireModel):
    kind: str
    active: str
    conditions: tuple[StylingCondition, ...]
    setter_count: int
    setters_truncated: bool
    setters: tuple[StylingSetter, ...]
    enter_actions: int
    exit_actions: int
    routed_event: str | None = None

    @classmethod
    def from_json(cls, value: object) -> StylingTrigger:
        data = _obj(
            value,
            "kind active conditions setterCount settersTruncated setters enterActions exitActions",
            "routedEvent",
        )
        result = cls(
            _choice(data["kind"], STYLING_TRIGGER_KINDS),
            _choice(data["active"], STYLING_ACTIVITY),
            _array(data["conditions"], StylingCondition.from_json, STYLING_MAX_ENTRIES),
            _int(data["setterCount"], 0, 2**31 - 1),
            _bool(data["settersTruncated"]),
            _array(data["setters"], StylingSetter.from_json, STYLING_MAX_ENTRIES),
            _int(data["enterActions"], 0, 2**31 - 1),
            _int(data["exitActions"], 0, 2**31 - 1),
            _optional(data, "routedEvent", _styling_text),
        )
        _truncation(
            result.setters_truncated, result.setter_count, len(result.setters), STYLING_MAX_ENTRIES
        )
        return result


_STYLING_LEVEL_FIELDS = (
    "setterCount settersTruncated setters triggerCount triggersTruncated triggers"
)


def _styling_level_values(data: dict[str, Any]) -> dict[str, Any]:
    """The fields a style level and a style share, checked."""
    setters = _array(data["setters"], StylingSetter.from_json, STYLING_MAX_ENTRIES)
    triggers = _array(data["triggers"], StylingTrigger.from_json, STYLING_MAX_ENTRIES)
    values: dict[str, Any] = {
        "setter_count": _int(data["setterCount"], 0, 2**31 - 1),
        "setters_truncated": _bool(data["settersTruncated"]),
        "setters": setters,
        "trigger_count": _int(data["triggerCount"], 0, 2**31 - 1),
        "triggers_truncated": _bool(data["triggersTruncated"]),
        "triggers": triggers,
        "key": _optional(data, "key", _styling_text),
        "target_type": _optional(data, "targetType", _styling_text),
    }
    _truncation(
        values["setters_truncated"], values["setter_count"], len(setters), STYLING_MAX_ENTRIES
    )
    _truncation(
        values["triggers_truncated"], values["trigger_count"], len(triggers), STYLING_MAX_ENTRIES
    )
    return values


@dataclass(frozen=True)
class StylingLevel(WireModel):
    """One level of a style: its own setters and triggers, without the inherited ones."""

    setter_count: int
    setters_truncated: bool
    setters: tuple[StylingSetter, ...]
    trigger_count: int
    triggers_truncated: bool
    triggers: tuple[StylingTrigger, ...]
    key: str | None = None
    target_type: str | None = None

    @classmethod
    def from_json(cls, value: object) -> StylingLevel:
        data = _obj(value, _STYLING_LEVEL_FIELDS, "key targetType")
        return cls(**_styling_level_values(data))


@dataclass(frozen=True)
class StylingStyle(WireModel):
    """The style an element uses (`source` says how it was found) and the styles it is based on."""

    source: str
    setter_count: int
    setters_truncated: bool
    setters: tuple[StylingSetter, ...]
    trigger_count: int
    triggers_truncated: bool
    triggers: tuple[StylingTrigger, ...]
    based_on: tuple[StylingLevel, ...]
    based_on_truncated: bool
    key: str | None = None
    target_type: str | None = None

    @classmethod
    def from_json(cls, value: object) -> StylingStyle:
        data = _obj(
            value, "source basedOn basedOnTruncated " + _STYLING_LEVEL_FIELDS, "key targetType"
        )
        based_on = _array(data["basedOn"], StylingLevel.from_json, STYLING_MAX_BASED_ON)
        truncated = _bool(data["basedOnTruncated"])
        if truncated and len(based_on) != STYLING_MAX_BASED_ON:
            raise ValueError("Inconsistent BasedOn chain")
        return cls(
            source=_choice(data["source"], STYLING_STYLE_SOURCES),
            based_on=based_on,
            based_on_truncated=truncated,
            **_styling_level_values(data),
        )


@dataclass(frozen=True)
class StylingPart(WireModel):
    name: str
    type: str
    element: Value

    @classmethod
    def from_json(cls, value: object) -> StylingPart:
        data = _obj(value, "name type element")
        return cls(
            _styling_text(data["name"]),
            _styling_text(data["type"]),
            Value.from_json(data["element"]),
        )


@dataclass(frozen=True)
class StylingTemplate(WireModel):
    kind: str
    trigger_count: int
    triggers_truncated: bool
    triggers: tuple[StylingTrigger, ...]
    parts_truncated: bool
    parts: tuple[StylingPart, ...]
    key: str | None = None
    target_type: str | None = None
    data_type: str | None = None
    root_type: str | None = None

    @classmethod
    def from_json(cls, value: object) -> StylingTemplate:
        data = _obj(
            value,
            "kind triggerCount triggersTruncated triggers partsTruncated parts",
            "key targetType dataType rootType",
        )
        result = cls(
            _choice(data["kind"], STYLING_TEMPLATE_KINDS),
            _int(data["triggerCount"], 0, 2**31 - 1),
            _bool(data["triggersTruncated"]),
            _array(data["triggers"], StylingTrigger.from_json, STYLING_MAX_ENTRIES),
            _bool(data["partsTruncated"]),
            _array(data["parts"], StylingPart.from_json, STYLING_MAX_ENTRIES),
            _optional(data, "key", _styling_text),
            _optional(data, "targetType", _styling_text),
            _optional(data, "dataType", _styling_text),
            _optional(data, "rootType", _styling_text),
        )
        _truncation(
            result.triggers_truncated,
            result.trigger_count,
            len(result.triggers),
            STYLING_MAX_ENTRIES,
        )
        if result.parts_truncated and len(result.parts) != STYLING_MAX_ENTRIES:
            raise ValueError("Inconsistent template parts")
        return result


@dataclass(frozen=True)
class StylingTemplates(WireModel):
    control_template: StylingTemplate | None = None
    content_template: StylingTemplate | None = None
    item_template: StylingTemplate | None = None
    item_container_style: StylingStyle | None = None
    items_panel: StylingTemplate | None = None
    templated_parent: Value | None = None

    @classmethod
    def from_json(cls, value: object) -> StylingTemplates:
        data = _obj(
            value,
            "",
            "controlTemplate contentTemplate itemTemplate itemContainerStyle itemsPanel "
            "templatedParent",
        )
        return cls(
            _optional(data, "controlTemplate", StylingTemplate.from_json),
            _optional(data, "contentTemplate", StylingTemplate.from_json),
            _optional(data, "itemTemplate", StylingTemplate.from_json),
            _optional(data, "itemContainerStyle", StylingStyle.from_json),
            _optional(data, "itemsPanel", StylingTemplate.from_json),
            _optional(data, "templatedParent", Value.from_json),
        )


@dataclass(frozen=True)
class StylingResourceEntry(WireModel):
    """A resource's key and its position in the dictionary. The listing never reads a value."""

    key: str
    key_kind: str
    index: int

    @classmethod
    def from_json(cls, value: object) -> StylingResourceEntry:
        data = _obj(value, "key keyKind index")
        return cls(
            _styling_text(data["key"]),
            _choice(data["keyKind"], STYLING_KEY_KINDS),
            _int(data["index"], 0, 2**31 - 1),
        )


@dataclass(frozen=True)
class ResourceResult(WireModel):
    """Result of `members.resource`: one resource value, created on demand."""

    found: bool
    value_type: str | None = None
    value: Value | None = None

    @classmethod
    def from_json(cls, value: object) -> ResourceResult:
        data = _obj(value, "found", "valueType value")
        found = _bool(data["found"])
        if found != ("value" in data and "valueType" in data) or (
            not found and data.keys() != {"found"}
        ):
            raise ValueError("Inconsistent resource result")
        return cls(
            found,
            _optional(data, "valueType", _styling_text),
            _optional(data, "value", Value.from_json),
        )


@dataclass(frozen=True)
class StylingMergedDictionary(WireModel):
    count: int
    source: str | None = None

    @classmethod
    def from_json(cls, value: object) -> StylingMergedDictionary:
        data = _obj(value, "count", "source")
        return cls(_int(data["count"], 0, 2**31 - 1), _optional(data, "source", _styling_text))


@dataclass(frozen=True)
class StylingResources(WireModel):
    """A resource dictionary: size, first page of entries and merged dictionaries."""

    count: int
    truncated: bool
    entries: tuple[StylingResourceEntry, ...]
    merged_truncated: bool
    merged_dictionaries: tuple[StylingMergedDictionary, ...]
    source: str | None = None

    @classmethod
    def from_json(cls, value: object) -> StylingResources:
        data = _obj(value, "count truncated entries mergedTruncated mergedDictionaries", "source")
        result = cls(
            _int(data["count"], 0, 2**31 - 1),
            _bool(data["truncated"]),
            _array(data["entries"], StylingResourceEntry.from_json, STYLING_MAX_RESOURCES),
            _bool(data["mergedTruncated"]),
            _array(
                data["mergedDictionaries"], StylingMergedDictionary.from_json, STYLING_MAX_RESOURCES
            ),
            _optional(data, "source", _styling_text),
        )
        _truncation(result.truncated, result.count, len(result.entries), STYLING_MAX_RESOURCES)
        if result.merged_truncated and len(result.merged_dictionaries) != STYLING_MAX_RESOURCES:
            raise ValueError("Inconsistent merged dictionaries")
        return result


@dataclass(frozen=True)
class StylingResult(WireModel):
    """Result of `members.styling`; empty unless the object is a framework element."""

    applicable: bool
    style: StylingStyle | None = None
    templates: StylingTemplates | None = None
    resources: StylingResources | None = None
    application: StylingResources | None = None

    @classmethod
    def from_json(cls, value: object) -> StylingResult:
        data = _obj(value, "applicable", "style templates resources application")
        result = cls(
            _bool(data["applicable"]),
            _optional(data, "style", StylingStyle.from_json),
            _optional(data, "templates", StylingTemplates.from_json),
            _optional(data, "resources", StylingResources.from_json),
            _optional(data, "application", StylingResources.from_json),
        )
        if not result.applicable and any(
            part is not None
            for part in (result.style, result.templates, result.resources, result.application)
        ):
            raise ValueError("Not applicable result must be empty")
        return result

    def values(self) -> tuple[Value, ...]:
        """Every Value in the result, so the client can check the handles they hold."""
        found: list[Value] = []

        def setters(items: tuple[StylingSetter, ...]) -> None:
            found.extend(item.value for item in items if item.value is not None)

        def triggers(items: tuple[StylingTrigger, ...]) -> None:
            for trigger in items:
                setters(trigger.setters)
                found.extend(condition.value for condition in trigger.conditions)

        def style(item: StylingStyle | None) -> None:
            if item is None:
                return
            for level in (item, *item.based_on):
                setters(level.setters)
                triggers(level.triggers)

        def template(item: StylingTemplate | None) -> None:
            if item is None:
                return
            triggers(item.triggers)
            found.extend(part.element for part in item.parts)

        style(self.style)
        if self.templates is not None:
            template(self.templates.control_template)
            template(self.templates.content_template)
            template(self.templates.item_template)
            style(self.templates.item_container_style)
            template(self.templates.items_panel)
            if self.templates.templated_parent is not None:
                found.append(self.templates.templated_parent)
        return tuple(found)


MEMBER_EVENT_KINDS = frozenset({"routed", "clr"})
MEMBER_EVENT_STRATEGIES = frozenset({"bubble", "tunnel", "direct"})
MEMBER_EVENT_MAX_HANDLERS = 32


@dataclass(frozen=True)
class EventHandler(WireModel):
    """The method a delegate points at: a routed event's handler or a CLR event's subscriber."""

    declaring_type: str
    method: str
    handled_events_too: bool | None = None

    @classmethod
    def from_json(cls, value: object) -> EventHandler:
        data = _obj(value, "declaringType method", "handledEventsToo")
        return cls(
            _styling_text(data["declaringType"]),
            _styling_text(data["method"]),
            _optional(data, "handledEventsToo", _bool),
        )


@dataclass(frozen=True)
class MemberEvent(WireModel):
    """
    An event of an object: a routed event that applies to its type, or a CLR event it declares.

    The wire names the handler list by kind (`handlers*` for a routed event, `subscribers*` for a
    CLR one); here it is one `handlers` list with `known`, `count` and `truncated`.
    """

    kind: str
    name: str
    declaring_type: str
    handler_type: str
    known: bool
    count: int
    truncated: bool
    handlers: tuple[EventHandler, ...]
    strategy: str | None = None
    is_static: bool = False

    @classmethod
    def from_json(cls, value: object) -> MemberEvent:
        if not isinstance(value, dict):
            raise ValueError("Expected an object")
        raw = cast(dict[str, Any], value)
        kind = _choice(raw.get("kind"), MEMBER_EVENT_KINDS)
        routed = kind == "routed"
        names = ("handler", "handlers") if routed else ("subscriber", "subscribers")
        plural, singular = names[1], names[0]
        required = "kind name declaringType handlerType"
        required += f" {plural}Known {singular}Count {plural}Truncated {plural}"
        data = _obj(raw, required + (" strategy" if routed else " isStatic"))
        result = cls(
            kind,
            _styling_text(data["name"]),
            _styling_text(data["declaringType"]),
            _styling_text(data["handlerType"]),
            _bool(data[f"{names[1]}Known"]),
            _int(data[f"{names[0]}Count"], 0, 2**31 - 1),
            _bool(data[f"{names[1]}Truncated"]),
            _array(data[names[1]], EventHandler.from_json, MEMBER_EVENT_MAX_HANDLERS),
            _choice(data["strategy"], MEMBER_EVENT_STRATEGIES) if routed else None,
            False if routed else _bool(data["isStatic"]),
        )
        if not result.known and (result.count or result.truncated or result.handlers):
            raise ValueError("Unknown handlers cannot be listed")
        _truncation(result.truncated, result.count, len(result.handlers), MEMBER_EVENT_MAX_HANDLERS)
        if any((item.handled_events_too is not None) != routed for item in result.handlers):
            raise ValueError("Handler does not match the event kind")
        return result

    def to_json(self) -> dict[str, Any]:
        routed = self.kind == "routed"
        names = ("handler", "handlers") if routed else ("subscriber", "subscribers")
        result: dict[str, Any] = {
            "kind": self.kind,
            "name": self.name,
            "declaringType": self.declaring_type,
            "handlerType": self.handler_type,
        }
        if routed:
            result["strategy"] = self.strategy
        else:
            result["isStatic"] = self.is_static
        result[f"{names[1]}Known"] = self.known
        result[f"{names[0]}Count"] = self.count
        result[f"{names[1]}Truncated"] = self.truncated
        result[names[1]] = [item.to_json() for item in self.handlers]
        return result


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
        return cls(
            _int(data["protocolMajor"], 2, 2),
            _int(data["protocolMinor"]),
            _identifier(data["sessionId"]),
            _identifier(data["token"]),
            ProcessIdentity.from_json(data["process"]),
        )


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
    write_allowlist: WriteAllowlist
    spy_invoke_capability: str | None = field(default=None, repr=False)

    @classmethod
    def from_json(cls, value: object) -> BootstrapSettings:
        data = _obj(
            value,
            "schemaVersion protocolMajor protocolMinor sessionId process pipeName token "
            "clientSid expiresUtc requestTimeoutMs idleTimeoutMs agentVersion "
            "redactNames writeAllowlist",
            "spyInvokeCapability",
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
        capability = data.get("spyInvokeCapability")
        if "spyInvokeCapability" in data:
            try:
                if not isinstance(capability, str):
                    raise ValueError("Invalid capability")
                decoded = base64.b64decode(capability, validate=True)
                if len(decoded) != 32 or base64.b64encode(decoded).decode("ascii") != capability:
                    raise ValueError("Invalid capability")
            except (ValueError, binascii.Error) as error:
                raise ValueError("Invalid capability") from error
        return cls(
            _int(data["schemaVersion"], 1, 1),
            _int(data["protocolMajor"], 2, 2),
            _int(data["protocolMinor"], 0, 2_147_483_647),
            session_id,
            ProcessIdentity.from_json(data["process"]),
            _key(data["pipeName"]),
            token,
            _identifier(data["clientSid"]),
            _timestamp(data["expiresUtc"]),
            _int(data["requestTimeoutMs"], 1, 2000),
            _int(data["idleTimeoutMs"], 1, 300000),
            _identifier(data["agentVersion"]),
            validate_redact_names(cast("list[object]", data["redactNames"])),
            WriteAllowlist.from_json(data["writeAllowlist"]),
            capability,
        )


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
                "session.hello",
                "session.close",
                "request.cancel",
                "element.resolve",
                "element.readBatch",
                "roots",
                "children",
                "tree.parent",
                "members",
                "members.items",
                "read",
                "spy.fieldRead",
                "spy.methods",
                "bindings",
                "release",
            },
        )
        if not isinstance(data["params"], dict):
            raise ValueError("Invalid request parameters")
        return cls(_int(data["id"], 1), method, cast(dict[str, Any], data["params"]))


# Protocol 2.0 query, geometry, action, wait and event DTOs.
@dataclass(frozen=True)
class AllowEntry(WireModel):
    type_full_name: str
    member_key: str

    @classmethod
    def from_json(cls, value: object) -> AllowEntry:
        data = _obj(value, "typeFullName memberKey")
        return cls(_key(data["typeFullName"]), _key(data["memberKey"]))


@dataclass(frozen=True)
class PropertyAllowEntry(WireModel):
    type_full_name: str
    member_name: str

    @classmethod
    def from_json(cls, value: object) -> PropertyAllowEntry:
        data = _obj(value, "typeFullName memberName")
        return cls(_key(data["typeFullName"]), _key(data["memberName"]))


@dataclass(frozen=True)
class WriteAllowlist(WireModel):
    properties: tuple[PropertyAllowEntry, ...]
    methods: tuple[AllowEntry, ...]

    @classmethod
    def from_json(cls, value: object) -> WriteAllowlist:
        data = _obj(value, "properties methods")
        properties = _array(data["properties"], PropertyAllowEntry.from_json, 128)
        methods = _array(data["methods"], AllowEntry.from_json, 128)
        if len(set(properties)) != len(properties) or len(set(methods)) != len(methods):
            raise ValueError("Duplicate allowlist entry")
        return cls(properties, methods)


@dataclass(frozen=True)
class Scope(WireModel):
    kind: str
    handle: ObjectRef | None = None

    @classmethod
    def from_json(cls, value: object) -> Scope:
        data = _obj(value, "kind", "handle")
        kind = _choice(data["kind"], {"allRoots", "window", "object"})
        if (kind == "allRoots") != ("handle" not in data):
            raise ValueError("Invalid scope handle")
        return cls(kind, _optional(data, "handle", ObjectRef.from_json))


def _scalar(value: object) -> str | bool | int | float:
    if isinstance(value, str):
        return _str(value, 4096, empty=True)
    if type(value) is bool:
        return value
    if _finite_number(value):
        return cast(int | float, value)
    raise ValueError("Invalid scalar")


scalar_value = _scalar


def _regex_pattern(value: object) -> str:
    pattern = _str(value, 1024, empty=True)
    index = 0
    in_class = False
    while index < len(pattern):
        char = pattern[index]
        if 0xD800 <= ord(char) <= 0xDFFF or (in_class and ord(char) > 127):
            raise ValueError("Invalid regex literal or non-ASCII character class")
        if char == "\\":
            index += 1
            if (
                index == len(pattern)
                or pattern[index] not in r"\.^$|?*+()[]{}-z"
                or (in_class and pattern[index] == "z")
            ):
                raise ValueError("Unsupported regex escape")
        elif char == "[":
            in_class = True
        elif char == "]":
            in_class = False
        elif char == "(" and pattern[index + 1 : index + 2] == "?":
            if pattern[index + 1 : index + 3] != "?:":
                raise ValueError("Unsupported regex group")
        elif char == "{":
            end = pattern.find("}", index + 1)
            if end < 0:
                raise ValueError("Invalid regex bound")
            match = re.fullmatch(r"([0-9]+)(?:,([0-9]*))?", pattern[index + 1 : end])
            if match is None:
                raise ValueError("Invalid regex bound")
            lower = int(match.group(1))
            upper = match.group(2)
            if lower > 10000 or (upper and (int(upper) > 10000 or int(upper) < lower)):
                raise ValueError("Invalid regex bound")
            index = end
        index += 1
    try:
        re.compile(
            re.sub(r"\\\\.|\\z", lambda m: r"\Z" if m.group() == r"\z" else m.group(), pattern),
            re.ASCII,
        )
    except re.error as error:
        raise ValueError("Invalid regex") from error
    return pattern


@dataclass(frozen=True)
class Predicate(WireModel):
    kind: str
    path: tuple[PathSegment, ...] | None = None
    value: str | bool | int | float | _Missing = MISSING
    pattern: str | None = None
    flags: tuple[str, ...] | None = None
    full_name: str | None = None

    @classmethod
    def from_json(cls, value: object) -> Predicate:
        data = _obj(value, "kind", "path value pattern flags fullName")
        kind = _choice(data["kind"], {"equals", "regex", "assignableTo"})
        if kind == "assignableTo":
            _obj(value, "kind fullName")
            return cls(kind, full_name=_key(data["fullName"]))
        if kind == "equals":
            _obj(value, "kind path value")
            return cls(kind, path=parse_path(data["path"]), value=_scalar(data["value"]))
        _obj(value, "kind path pattern flags")
        flags = _array(
            data["flags"], lambda x: _choice(x, {"ignoreCase", "multiline", "singleline"}), 3
        )
        if len(set(flags)) != len(flags):
            raise ValueError("Duplicate regex flag")
        return cls(
            kind,
            path=parse_path(data["path"]),
            pattern=_regex_pattern(data["pattern"]),
            flags=flags,
        )


@dataclass(frozen=True)
class ItemMatch(WireModel):
    kind: str
    index: int | None = None
    path: tuple[PathSegment, ...] | None = None
    value: str | bool | int | float | _Missing = MISSING
    pattern: str | None = None
    flags: tuple[str, ...] | None = None

    @classmethod
    def from_json(cls, value: object) -> ItemMatch:
        data = _obj(value, "kind", "index path value pattern flags")
        if data["kind"] == "index":
            _obj(value, "kind index")
            return cls("index", index=_int(data["index"], 0, 9999))
        predicate = Predicate.from_json(value)
        if predicate.kind not in {"equals", "regex"}:
            raise ValueError("Invalid item match")
        return cls(
            predicate.kind,
            path=predicate.path,
            value=predicate.value,
            pattern=predicate.pattern,
            flags=predicate.flags,
        )


@dataclass(frozen=True)
class Locator(WireModel):
    scope: Scope
    tree: str
    predicates: tuple[Predicate, ...]
    depth: int
    limit: int
    depth_mode: str
    index: int | None = None

    @classmethod
    def from_json(cls, value: object) -> Locator:
        d = _obj(value, "scope tree predicates depth depthMode limit", "index")
        return cls(
            Scope.from_json(d["scope"]),
            _choice(d["tree"], {"visual", "logical", "combined"}),
            _array(d["predicates"], Predicate.from_json, 32),
            _int(d["depth"], 0, 256),
            _int(d["limit"], 1, 200),
            _choice(d["depthMode"], {"tree", "peers"}),
            _optional(d, "index", lambda x: _int(x, 0, 9999)),
        )


def _number(value: object) -> int | float:
    if not _finite_number(value):
        raise ValueError("Invalid number")
    return cast(int | float, value)


@dataclass(frozen=True)
class Rect(WireModel):
    x: int | float
    y: int | float
    width: int | float
    height: int | float

    @classmethod
    def from_json(cls, value: object) -> Rect:
        d = _obj(value, "x y width height")
        result = cls(*(_number(d[k]) for k in ("x", "y", "width", "height")))
        if result.width < 0 or result.height < 0:
            raise ValueError("Negative rectangle size")
        return result


@dataclass(frozen=True)
class Point(WireModel):
    x: int | float
    y: int | float

    @classmethod
    def from_json(cls, value: object) -> Point:
        d = _obj(value, "x y")
        return cls(_number(d["x"]), _number(d["y"]))


@dataclass(frozen=True)
class Dpi(WireModel):
    x: int | float
    y: int | float

    @classmethod
    def from_json(cls, value: object) -> Dpi:
        d = _obj(value, "x y")
        result = cls(_number(d["x"]), _number(d["y"]))
        if result.x <= 0 or result.y <= 0:
            raise ValueError("Invalid DPI")
        return result


@dataclass(frozen=True)
class PartGeometry(WireModel):
    name: str
    role: str
    bounds: Rect | None

    @classmethod
    def from_json(cls, value: object) -> PartGeometry:
        d = _obj(value, "name role bounds")
        return cls(
            _identifier(d["name"]),
            _choice(
                d["role"],
                {
                    "expanderToggle",
                    "comboDropDown",
                    "scrollThumb",
                    "scrollDecrement",
                    "scrollIncrement",
                    "scrollTrack",
                    "treeItemExpander",
                    "gridColumnHeader",
                    "gridRowHeader",
                    "templatePart",
                },
            ),
            None if d["bounds"] is None else Rect.from_json(d["bounds"]),
        )

    def to_json(self) -> dict[str, Any]:
        return {"name": self.name, "role": self.role, "bounds": _wire(self.bounds)}


@dataclass(frozen=True)
class ElementState(WireModel):
    handle: ObjectRef
    window_handle: int | None
    bounds: Rect | None
    dpi: Dpi
    visible: bool
    clipped: bool
    offscreen: bool
    enabled: bool
    focused: bool
    is_keyboard_focusable: bool
    parts: tuple[PartGeometry, ...]
    uia_runtime_id: tuple[int, ...] | None = None
    click_point: Point | None = None
    visible_bounds: Rect | None = None

    @classmethod
    def from_json(cls, value: object) -> ElementState:
        d = _obj(
            value,
            "handle windowHandle bounds visibleBounds clickPoint dpi visible clipped offscreen "
            "enabled focused isKeyboardFocusable parts",
            "uiaRuntimeId",
        )
        hwnd = d["windowHandle"]
        if hwnd is not None and type(hwnd) is not int:
            raise ValueError("Invalid window handle")
        return cls(
            ObjectRef.from_json(d["handle"]),
            hwnd,
            None if d["bounds"] is None else Rect.from_json(d["bounds"]),
            Dpi.from_json(d["dpi"]),
            _bool(d["visible"]),
            _bool(d["clipped"]),
            _bool(d["offscreen"]),
            _bool(d["enabled"]),
            _bool(d["focused"]),
            _bool(d["isKeyboardFocusable"]),
            _array(d["parts"], PartGeometry.from_json, 1_000_000),
            _optional(d, "uiaRuntimeId", _runtime_id),
            None if d["clickPoint"] is None else Point.from_json(d["clickPoint"]),
            None if d["visibleBounds"] is None else Rect.from_json(d["visibleBounds"]),
        )

    def to_json(self) -> dict[str, Any]:
        result = super().to_json()
        result["windowHandle"] = self.window_handle
        result["bounds"] = _wire(self.bounds)
        result["clickPoint"] = _wire(self.click_point)
        result["visibleBounds"] = _wire(self.visible_bounds)
        result["parts"] = [p.to_json() for p in self.parts]
        return result


@dataclass(frozen=True)
class MatchWarning(WireModel):
    code: str
    count: int

    @classmethod
    def from_json(cls, value: object) -> MatchWarning:
        d = _obj(value, "code count")
        return cls(_choice(d["code"], {"multipleMatches"}), _int(d["count"], 2, 10000))


@dataclass(frozen=True)
class QueryFindResult(WireModel):
    match: ObjectRef
    warning: MatchWarning | None = None

    @classmethod
    def from_json(cls, value: object) -> QueryFindResult:
        d = _obj(value, "match", "warning")
        return cls(ObjectRef.from_json(d["match"]), _optional(d, "warning", MatchWarning.from_json))


@dataclass(frozen=True)
class QueryFindAllResult(WireModel):
    matches: tuple[ObjectRef, ...]
    complete: bool
    count: int | None = None

    @classmethod
    def from_json(cls, value: object) -> QueryFindAllResult:
        d = _obj(value, "matches complete", "count")
        return cls(
            _array(d["matches"], ObjectRef.from_json, 200),
            _bool(d["complete"]),
            _optional(d, "count", lambda x: _int(x, 0, 10000)),
        )


@dataclass(frozen=True)
class ActResult(WireModel):
    outcome: str
    handle: ObjectRef

    @classmethod
    def from_json(cls, value: object) -> ActResult:
        d = _obj(value, "outcome handle")
        return cls(
            _choice(d["outcome"], {"performed", "noChange"}), ObjectRef.from_json(d["handle"])
        )


@dataclass(frozen=True)
class RealizeResult(WireModel):
    outcome: str
    handle: ObjectRef
    warning: MatchWarning | None = None

    @classmethod
    def from_json(cls, value: object) -> RealizeResult:
        data = _obj(value, "outcome handle", "warning")
        return cls(
            _choice(data["outcome"], {"performed", "noChange"}),
            ObjectRef.from_json(data["handle"]),
            _optional(data, "warning", MatchWarning.from_json),
        )


@dataclass(frozen=True)
class WaitCondition(WireModel):
    kind: str
    locator: Locator
    path: tuple[PathSegment, ...] | None = None
    value: str | bool | int | float | _Missing = MISSING

    @classmethod
    def from_json(cls, value: object) -> WaitCondition:
        d = _obj(value, "kind locator", "path value")
        kind = _choice(d["kind"], {"exists", "visible", "enabled", "propertyEquals"})
        if kind == "propertyEquals":
            _obj(value, "kind locator path value")
            return cls(
                kind, Locator.from_json(d["locator"]), parse_path(d["path"]), _scalar(d["value"])
            )
        _obj(value, "kind locator")
        return cls(kind, Locator.from_json(d["locator"]))


@dataclass(frozen=True)
class WaitResult(WireModel):
    satisfied: bool
    handle: ObjectRef | None = None
    state: ElementState | None = None

    @classmethod
    def from_json(cls, value: object) -> WaitResult:
        d = _obj(value, "satisfied", "handle state")
        satisfied = _bool(d["satisfied"])
        if satisfied:
            _obj(value, "satisfied handle state")
        else:
            _obj(value, "satisfied")
        return cls(
            satisfied,
            _optional(d, "handle", ObjectRef.from_json),
            _optional(d, "state", ElementState.from_json),
        )


@dataclass(frozen=True)
class WriteAudit(WireModel):
    operation: str
    type_full_name: str
    member_key: str
    outcome: str
    timestamp_utc: str
    reason: str | None = None
    authorization: str | None = None

    @classmethod
    def from_json(cls, value: object) -> WriteAudit:
        d = _obj(
            value, "operation typeFullName memberKey outcome timestampUtc", "reason authorization"
        )
        if d.get("reason") == "timeout" and d["outcome"] != "failed":
            raise ValueError("Invalid timeout audit")
        return cls(
            _choice(d["operation"], {"setProperty", "call"}),
            _key(d["typeFullName"]),
            _str(d["memberKey"], 8192),
            _choice(d["outcome"], {"performed", "denied", "failed"}),
            _timestamp(d["timestampUtc"]),
            _optional(d, "reason", lambda x: _str(x, 1024, empty=True)),
            _optional(d, "authorization", lambda x: _choice(x, {"allowlist", "pure"})),
        )


@dataclass(frozen=True)
class EventsEventParams(WireModel):
    subscription_id: str
    sequence: int
    kind: str
    handle: ObjectRef | None = None

    @classmethod
    def from_json(cls, value: object) -> EventsEventParams:
        d = _obj(value, "subscriptionId sequence kind", "handle")
        kind = _choice(d["kind"], {"windowOpened", "windowClosed", "treeChanged", "overflow"})
        if kind == "overflow" and "handle" in d:
            raise ValueError("Overflow cannot have a handle")
        return cls(
            _identifier(d["subscriptionId"]),
            _int(d["sequence"], 1),
            kind,
            _optional(d, "handle", ObjectRef.from_json),
        )


@dataclass(frozen=True)
class EventsNotification(WireModel):
    method: str
    params: EventsEventParams

    @classmethod
    def from_json(cls, value: object) -> EventsNotification:
        d = _obj(value, "method params")
        return cls(_choice(d["method"], {"events.event"}), EventsEventParams.from_json(d["params"]))
