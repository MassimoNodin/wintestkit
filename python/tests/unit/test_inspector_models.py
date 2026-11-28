"""Exercise the Python DTO readers against shared protocol fixtures."""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator

from wintestkit.inspector.client import _response
from wintestkit.inspector.models import (
    MISSING,
    AttributeInfo,
    AttributeLiteral,
    BindingInfo,
    BootstrapSettings,
    EventHandler,
    HelloParams,
    ItemsResult,
    ManagedNode,
    Mapping,
    Member,
    MemberEvent,
    ObjectRef,
    Page,
    ProcessIdentity,
    ReleaseItem,
    ReleaseParams,
    ReleaseResult,
    RequestEnvelope,
    ResourceResult,
    Session,
    StylingCondition,
    StylingResourceEntry,
    StylingResources,
    StylingResult,
    StylingSetter,
    StylingStyle,
    StylingTemplate,
    StylingTrigger,
    Value,
    parse_path,
)
from wintestkit.inspector.paths import PathSegment

ROOT = Path(__file__).resolve().parents[3] / "wpf-inspector/protocol/fixtures"
ITEMS_SCHEMA = json.loads((ROOT.parent / "inspector.schema.json").read_text(encoding="utf-8"))
ITEMS_PARAMS = {**ITEMS_SCHEMA, "$ref": "#/$defs/ItemsParams"}
STYLING_PARAMS = {**ITEMS_SCHEMA, "$ref": "#/$defs/StylingParams"}
RESOURCE_PARAMS = {**ITEMS_SCHEMA, "$ref": "#/$defs/ResourceParams"}


def _items_params(value: Any) -> None:
    if not Draft202012Validator(ITEMS_PARAMS).is_valid(value):
        raise ValueError("Invalid items parameters")


def _styling_params(value: Any) -> None:
    if not Draft202012Validator(STYLING_PARAMS).is_valid(value):
        raise ValueError("Invalid styling parameters")


def _resource_params(value: Any) -> None:
    if not Draft202012Validator(RESOURCE_PARAMS).is_valid(value):
        raise ValueError("Invalid resource parameters")


def _routed_handler(value: Any) -> EventHandler:
    handler = EventHandler.from_json(value)
    if handler.handled_events_too is None:
        raise ValueError("Routed handlers say whether they take handled events")
    return handler


def _clr_subscriber(value: Any) -> EventHandler:
    handler = EventHandler.from_json(value)
    if handler.handled_events_too is not None:
        raise ValueError("CLR subscribers have no handled-events flag")
    return handler


PARSERS: dict[str, Callable[[Any], Any]] = {
    "AttributeInfo": AttributeInfo.from_json,
    "BindingInfo": BindingInfo.from_json,
    "BootstrapSettings": BootstrapSettings.from_json,
    "HelloParams": HelloParams.from_json,
    "ItemsResult": ItemsResult.from_json,
    "ItemsParams": lambda value: _items_params(value),
    "MemberEvent": MemberEvent.from_json,
    "MemberEventPage": lambda value: Page.from_json(value, MemberEvent.from_json),
    "ResourceParams": lambda value: _resource_params(value),
    "ResourceResult": ResourceResult.from_json,
    "RoutedEventHandler": _routed_handler,
    "ClrEventSubscriber": _clr_subscriber,
    "Mapping": Mapping.from_json,
    "Member": Member.from_json,
    "MemberPage": lambda value: Page.from_json(value, Member.from_json),
    "ManagedNodePage": lambda value: Page.from_json(value, ManagedNode.from_json),
    "ManagedNode": ManagedNode.from_json,
    "ObjectRef": ObjectRef.from_json,
    "Path": parse_path,
    "PathSegment": PathSegment.from_json,
    "ProcessIdentity": ProcessIdentity.from_json,
    "ReleaseItem": ReleaseItem.from_json,
    "ReleaseParams": ReleaseParams.from_json,
    "ReleaseResult": ReleaseResult.from_json,
    "ResponseEnvelope": _response,
    "RequestEnvelope": RequestEnvelope.from_json,
    "Session": Session.from_json,
    "StylingCondition": StylingCondition.from_json,
    "StylingResourceEntry": StylingResourceEntry.from_json,
    "StylingParams": lambda value: _styling_params(value),
    "StylingResources": StylingResources.from_json,
    "StylingResult": StylingResult.from_json,
    "StylingSetter": StylingSetter.from_json,
    "StylingStyle": StylingStyle.from_json,
    "StylingTemplate": StylingTemplate.from_json,
    "StylingTrigger": StylingTrigger.from_json,
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
        sum(not path.name.startswith("p2-") for path in (ROOT / directory).glob("*.json"))
        for directory in ("valid", "invalid")
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


def test_getter_error_message() -> None:
    raw = {
        "status": "exception",
        "kind": "unavailable",
        "declaredType": "",
        "runtimeType": "",
        "failedSegment": 0,
        "message": "System.InvalidOperationException",
        "errorMessage": "broken",
    }
    value = Value.from_json(raw)
    assert value.error_message == "broken"
    with pytest.raises(ValueError, match="broken"):
        value.as_python()
    for bad in (123, "x" * 513):
        with pytest.raises(ValueError):
            Value.from_json({**raw, "errorMessage": bad})


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


@pytest.mark.parametrize(
    ("kind", "scalar", "metadata"),
    [("enum", "Named", "1.5"), ("integer", 1, "1.5"), ("number", "1.5", "NaN")],
)
def test_invalid_exact_numeric_metadata_is_rejected(
    kind: str, scalar: object, metadata: str
) -> None:
    with pytest.raises(ValueError, match="Invalid numeric value"):
        Value.from_json(
            {
                "status": "ok",
                "kind": kind,
                "declaredType": "",
                "runtimeType": "",
                "scalar": scalar,
                "numericValue": metadata,
            }
        )


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


def _binding_fixture(name: str) -> dict[str, Any]:
    document = json.loads((ROOT / "valid" / f"{name}.json").read_text(encoding="utf-8"))
    assert isinstance(document["instance"], dict)
    return document["instance"]


def test_binding_details_round_trip_with_handles() -> None:
    raw = _binding_fixture("binding-details")
    info = BindingInfo.from_json(raw)
    assert info.string_format == "{0:N2}"
    assert info.fallback_value is not None and info.fallback_value.scalar == "fb"
    assert info.target_null_value is not None and info.target_null_value.scalar == 7
    assert info.converter_parameter is not None and info.converter_parameter.object_ref is not None
    assert info.data_item is not None and info.data_item.object_ref is not None
    assert info.data_item.object_ref.object_id == "d1"
    assert info.resolved_source is not None and info.resolved_source.object_ref is not None
    assert info.resolved_source_property_name == "Name"
    assert (info.converter_culture, info.delay, info.binding_group_name, info.x_path) == (
        "fr-FR",
        250,
        "group",
        "item",
    )
    assert info.is_async is True and info.notify_on_target_updated is False
    assert info.validates_on_notify_data_errors is True
    assert info.validation_rules == ("App.NonEmptyRule",)
    assert info.has_update_source_exception_filter is True
    assert info.has_error is False and info.has_validation_error is False
    assert info.to_json() == raw


def test_binding_details_nested_children_and_active_child() -> None:
    multi = BindingInfo.from_json(_binding_fixture("binding-details-multi"))
    assert multi.converter_parameter is not None and multi.converter_parameter.scalar == "-"
    assert multi.children is not None and len(multi.children) == 2
    assert multi.children[0].data_item is not None
    priority = BindingInfo.from_json(_binding_fixture("binding-details-priority"))
    assert priority.active_child_index == 1
    assert priority.fallback_value is not None and priority.fallback_value.scalar == "pfb"


def test_binding_without_details_leaves_them_unset() -> None:
    info = BindingInfo.from_json(
        {
            "memberKey": "k",
            "kind": "binding",
            "status": "Active",
            "mode": "OneWay",
            "updateSourceTrigger": "Default",
        }
    )
    assert info.string_format is None and info.data_item is None and info.has_error is None
    assert "dataItem" not in info.to_json()


@pytest.mark.parametrize(
    "extra",
    [
        {"delay": -1},
        {"delay": 2_147_483_648},
        {"hasError": "yes"},
        {"isAsync": 1},
        {"activeChildIndex": 32},
        {"validationRules": [1]},
        {"validationRules": [f"R{index}" for index in range(33)]},
        {"fallbackValue": {"status": "ok"}},
        {"dataItem": "object"},
        {"stringFormat": "x" * 1025},
        {"converterCulture": "x" * 129},
        {"resolvedSourceType": "T"},
    ],
)
def test_binding_details_reject_invalid_fields(extra: dict[str, Any]) -> None:
    base = {
        "memberKey": "k",
        "kind": "binding",
        "status": "Active",
        "mode": "OneWay",
        "updateSourceTrigger": "Default",
    }
    with pytest.raises(ValueError):
        BindingInfo.from_json({**base, **extra})


def _styling_fixture(name: str) -> dict[str, Any]:
    document = json.loads((ROOT / "valid" / f"{name}.json").read_text(encoding="utf-8"))
    assert document["schema"].startswith("Styling")
    return cast(dict[str, Any], document["instance"])


@pytest.mark.parametrize(
    "name",
    [
        "styling-result-empty",
        "styling-result-style",
        "styling-result-style-implicit",
        "styling-result-style-none",
        "styling-result-templates",
        "styling-result-resources",
    ],
)
def test_styling_result_round_trips_the_golden_fixtures(name: str) -> None:
    raw = _styling_fixture(name)
    assert StylingResult.from_json(raw).to_json() == raw


def test_styling_style_describes_setters_triggers_and_based_on() -> None:
    style = StylingResult.from_json(_styling_fixture("styling-result-style")).style
    assert style is not None
    assert (style.source, style.key, style.target_type) == (
        "local",
        "Fancy",
        "System.Windows.Controls.Button",
    )
    assert [trigger.kind for trigger in style.triggers] == [
        "trigger",
        "dataTrigger",
        "multiTrigger",
        "eventTrigger",
    ]
    assert [trigger.active for trigger in style.triggers] == [
        "active",
        "unknown",
        "inactive",
        "unknown",
    ]
    assert style.triggers[1].conditions[0].binding == "Path=Ready"
    assert style.triggers[3].routed_event == "System.Windows.Controls.Primitives.ButtonBase.Click"
    base = style.based_on[0]
    assert base.key == "Base" and style.based_on[1].key is None
    dynamic, hidden, event_setter = base.setters
    assert (dynamic.kind, dynamic.expression, dynamic.value) == ("dynamicResource", "Accent", None)
    assert hidden.value is not None and hidden.value.status == "redacted"
    assert event_setter.kind == "other"
    assert "value" not in dynamic.to_json()


def test_styling_templates_and_resources_describe_parts_and_keys() -> None:
    result = StylingResult.from_json(_styling_fixture("styling-result-templates"))
    assert result.templates is not None
    control = result.templates.control_template
    assert control is not None and control.root_type == "System.Windows.Controls.Border"
    assert [part.name for part in control.parts] == ["PART_Border"]
    assert control.triggers[0].conditions[0].source_name == "PART_Border"
    assert result.templates.item_template is not None
    assert result.templates.item_template.kind == "hierarchicalDataTemplate"
    assert result.templates.items_panel is not None
    assert result.templates.items_panel.root_type == "System.Windows.Controls.WrapPanel"
    assert result.templates.templated_parent is not None
    assert len(result.values()) == 4
    resources = StylingResult.from_json(_styling_fixture("styling-result-resources"))
    assert resources.resources is not None and resources.application is not None
    assert [entry.key_kind for entry in resources.resources.entries] == [
        "string",
        "type",
        "componentResourceKey",
        "other",
    ]
    assert [item.source for item in resources.resources.merged_dictionaries] == [
        "Themes/Dark.xaml",
        None,
    ]
    assert resources.application.truncated and resources.application.count == 250


def test_styling_result_must_be_empty_when_not_applicable() -> None:
    assert StylingResult.from_json({"applicable": False}).style is None
    with pytest.raises(ValueError):
        StylingResult.from_json(
            {"applicable": False, "style": _styling_fixture("styling-result-style-none")["style"]}
        )
    with pytest.raises(ValueError, match="Inconsistent"):
        raw = _styling_fixture("styling-result-resources")["application"]
        StylingResources.from_json({**raw, "truncated": False})


def _valid_fixture(name: str) -> dict[str, Any]:
    document = json.loads((ROOT / "valid" / f"{name}.json").read_text(encoding="utf-8"))
    return cast(dict[str, Any], document["instance"])


@pytest.mark.parametrize(
    "name",
    [
        "member-event-routed",
        "member-event-routed-no-handlers",
        "member-event-routed-unknown",
        "member-event-clr",
        "member-event-clr-static",
        "member-event-clr-unknown",
        "member-event-clr-truncated",
    ],
)
def test_member_events_round_trip_the_golden_fixtures(name: str) -> None:
    raw = _valid_fixture(name)
    assert MemberEvent.from_json(raw).to_json() == raw


def test_member_events_name_their_handler_fields_by_kind() -> None:
    routed = MemberEvent.from_json(_valid_fixture("member-event-routed"))
    assert (routed.kind, routed.strategy, routed.known, routed.count) == (
        "routed",
        "bubble",
        True,
        2,
    )
    assert [item.handled_events_too for item in routed.handlers] == [False, True]
    assert routed.handlers[0].declaring_type == "Demo.MainWindow"
    assert "subscribers" not in routed.to_json() and "isStatic" not in routed.to_json()
    clr = MemberEvent.from_json(_valid_fixture("member-event-clr-static"))
    assert (clr.kind, clr.is_static, clr.strategy, clr.known, clr.count) == (
        "clr",
        True,
        None,
        True,
        1,
    )
    assert clr.handlers[0].handled_events_too is None
    assert "handledEventsToo" not in clr.handlers[0].to_json()
    assert "handlers" not in clr.to_json() and "strategy" not in clr.to_json()
    unknown = MemberEvent.from_json(_valid_fixture("member-event-clr-unknown"))
    assert not unknown.known and unknown.handlers == ()


def test_member_event_lists_are_capped_and_consistent() -> None:
    truncated = MemberEvent.from_json(_valid_fixture("member-event-clr-truncated"))
    assert (truncated.count, len(truncated.handlers), truncated.truncated) == (40, 32, True)
    raw = _valid_fixture("member-event-clr-truncated")
    with pytest.raises(ValueError, match="Inconsistent"):
        MemberEvent.from_json({**raw, "subscribersTruncated": False})
    with pytest.raises(ValueError):
        MemberEvent.from_json({**raw, "subscribers": raw["subscribers"] + raw["subscribers"][:1]})
    routed = _valid_fixture("member-event-routed")
    with pytest.raises(ValueError, match="Unknown"):
        MemberEvent.from_json({**routed, "handlersKnown": False})
    with pytest.raises(ValueError):
        MemberEvent.from_json({**routed, "subscribers": []})
    with pytest.raises(ValueError):
        MemberEvent.from_json({**routed, "strategy": "sideways"})
    with pytest.raises(ValueError, match="kind"):
        MemberEvent.from_json({**routed, "handlers": [{"declaringType": "T", "method": "M"}] * 2})
    with pytest.raises(ValueError):
        MemberEvent.from_json({**routed, "kind": "delegate"})


def test_resource_listing_carries_keys_and_positions_never_values() -> None:
    result = StylingResult.from_json(_valid_fixture("styling-result-resources"))
    assert result.resources is not None
    assert [entry.index for entry in result.resources.entries] == [0, 1, 2, 3]
    assert result.resources.entries[1].to_json() == {
        "key": "System.Windows.Controls.Button",
        "keyKind": "type",
        "index": 1,
    }
    assert result.values() == ()
    with pytest.raises(ValueError):
        StylingResourceEntry.from_json({"key": "k", "keyKind": "string", "index": 0, "value": {}})
    with pytest.raises(ValueError):
        StylingResourceEntry.from_json({"key": "k", "keyKind": "string"})


def test_resource_result_round_trips_and_is_empty_when_not_found() -> None:
    found = _valid_fixture("resource-result-found")
    parsed = ResourceResult.from_json(found)
    assert parsed.found and parsed.value_type == "System.String" and parsed.value is not None
    assert parsed.to_json() == found
    assert ResourceResult.from_json({"found": False}).to_json() == {"found": False}
    assert ResourceResult.from_json(_valid_fixture("resource-result-redacted")).value is not None
    for bad in (
        {"found": True, "valueType": "System.String"},
        {"found": True, "value": found["value"]},
        {"found": False, "valueType": "System.String"},
        {"found": False, "value": found["value"], "valueType": "System.String"},
        {"found": "yes"},
        {},
    ):
        with pytest.raises(ValueError):
            ResourceResult.from_json(bad)


def test_equals_text_predicate_and_nested_type_paths() -> None:
    from wintestkit.inspector.models import Predicate

    path = [{"kind": "property", "name": "DataContext"}, {"kind": "type", "name": "Name"}]
    parsed = Predicate.from_json({"kind": "equalsText", "path": path, "value": "15"})
    assert parsed.kind == "equalsText" and parsed.value == "15"
    assert Predicate.from_json(parsed.to_json()) == parsed
    for bad in (
        {"kind": "equalsText", "path": path, "value": 15},
        {"kind": "equalsText", "path": path, "value": True},
        {"kind": "equalsText", "path": path},
    ):
        with pytest.raises(ValueError):
            Predicate.from_json(bad)
    # Type metadata ends a path; it cannot lead one, and UIA segments stay alone.
    with pytest.raises(ValueError):
        Predicate.from_json({"kind": "equals", "path": path[::-1], "value": "x"})
    with pytest.raises(ValueError):
        Predicate.from_json(
            {
                "kind": "equals",
                "path": [{"kind": "uia", "name": "name"}, {"kind": "property", "name": "A"}],
                "value": "x",
            }
        )
    indexed = [{"kind": "property", "name": "Items[0]"}, {"kind": "property", "name": "Name"}]
    assert Predicate.from_json({"kind": "equals", "path": indexed, "value": "x"}).path


def test_find_all_result_continuation() -> None:
    from wintestkit.inspector.models import QueryFindAllResult

    parsed = QueryFindAllResult.from_json({"matches": [], "complete": False, "continuation": "abc"})
    assert parsed.continuation == "abc" and not parsed.complete
    assert QueryFindAllResult.from_json({"matches": [], "complete": True}).continuation is None
    for bad in (
        {"matches": [], "complete": True, "continuation": "abc"},
        {"matches": [], "complete": False, "continuation": ""},
        {"matches": [], "complete": False, "continuation": "x" * 129},
    ):
        with pytest.raises(ValueError):
            QueryFindAllResult.from_json(bad)


@pytest.mark.parametrize(
    "path", [p for p in FIXTURES if p.parent.name == "valid"], ids=lambda p: p.name
)
def test_python_owns_exactly_the_handles_the_agent_counts(path: Path) -> None:
    """Every handle on the wire is one ``ObjectRef`` the client owns, so release counts agree."""
    from wintestkit.inspector.handouts import object_refs, wire_refs

    fixture = json.loads(path.read_text(encoding="utf-8"))
    parsed = PARSERS[fixture["schema"]](fixture["instance"])
    if parsed is None or (isinstance(parsed, tuple) and not parsed):
        return
    owned = sum(1 for _ in object_refs(parsed))
    if fixture["schema"] in {"RequestEnvelope", "ResponseEnvelope"}:
        return  # envelopes are parsed in two steps; their results are covered by their own schemas
    assert wire_refs(fixture["instance"]) == owned, path.name
