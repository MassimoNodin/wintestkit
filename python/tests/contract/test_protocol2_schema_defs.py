import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

DOCUMENT = json.loads((Path(__file__).parents[3] / "wpf-inspector/protocol/inspector.schema.json").read_text(encoding="utf-8"))
REGISTRY = Registry().with_resource(DOCUMENT["$id"], Resource.from_contents(DOCUMENT))
TYPE = {"name": "T", "fullName": "T", "assemblyName": "A", "assemblyQualifiedName": "T, A", "baseTypes": []}
HANDLE = {"sessionId": "s", "objectId": "o", "generation": 1, "type": TYPE, "dispatcherId": "d"}
PATH = [{"kind": "uia", "name": "name"}]
PRED = {"kind": "equals", "path": PATH, "value": "x"}
LOCATOR = {"scope": {"kind": "allRoots"}, "tree": "combined", "predicates": [PRED], "depth": 256, "limit": 100}
STATE = {"handle": HANDLE, "windowHandle": None, "bounds": None, "dpi": {"x": 96, "y": 96}, "visible": True, "clipped": False, "offscreen": False, "enabled": True, "focused": False, "isKeyboardFocusable": True, "parts": []}
SEARCH = {"container": HANDLE, "match": {"kind": "index", "index": 0}, "maxItems": 10000}
AUDIT = {"operation": "call", "typeFullName": "T", "memberKey": "Reset()", "outcome": "performed", "timestampUtc": "2026-01-01T00:00:00Z"}
EVENT = {"method": "events.event", "params": {"subscriptionId": "s", "sequence": 1, "kind": "overflow"}}


def valid(name, value):
    return Draft202012Validator({"$ref": f"{DOCUMENT['$id']}#/$defs/{name}"}, registry=REGISTRY, format_checker=FormatChecker()).is_valid(value)


def test_schema_definitions_and_version():
    Draft202012Validator.check_schema(DOCUMENT)
    names = ["Scope", "Locator", "Predicate", "ElementState", "ActResult", "WaitCondition", "WaitResult", "ItemSearch", "ItemMatch", "MatchWarning", "WriteAudit", "AllowEntry", "EventsNotification"]
    methods = ["QueryFind", "QueryFindAll", "StateGet", "ActFocus", "ActBringIntoView", "ActInvoke", "ActToggle", "ActExpand", "ActCollapse", "ActSelect", "ActScrollIntoView", "ActSetValue", "ActSetRange", "ActScroll", "ActRealizeItem", "WaitUntil", "HitTest", "WriteSetProperty", "WriteCall", "EventsSubscribe", "EventsUnsubscribe"]
    assert set(names + [method + suffix for method in methods for suffix in ("Params", "Result")]) <= DOCUMENT["$defs"].keys()
    for name in ("Session", "HelloParams", "BootstrapSettings"):
        version = DOCUMENT["$defs"][name]["properties"]["protocolMajor"]
        assert Draft202012Validator(version).is_valid(2)
        assert not Draft202012Validator(version).is_valid(1)


@pytest.mark.parametrize(("name", "good", "bad"), [
    ("Locator", [LOCATOR, {**LOCATOR, "index": 9999, "predicates": []}], [{**LOCATOR, "depth": 257}, {**LOCATOR, "extra": 1}]),
    ("Predicate", [PRED, {"kind": "regex", "path": PATH, "pattern": "a", "flags": ["ignoreCase"]}], [{**PRED, "value": None}, {"kind": "regex", "path": PATH, "pattern": "a", "flags": ["ignoreCase", "ignoreCase"]}]),
    ("ElementState", [STATE, {**STATE, "windowHandle": 42, "parts": [{"name": "part", "role": "templatePart", "bounds": None}]}], [{**STATE, "dpi": {"x": 0, "y": 96}}, {**STATE, "bounds": {"x": 0, "y": 0, "width": -1, "height": 1}}]),
    ("ItemSearch", [SEARCH, {**SEARCH, "match": PRED}], [{**SEARCH, "maxItems": 10001}, {**SEARCH, "match": {"kind": "index", "index": -1}}]),
    ("WriteAudit", [AUDIT, {**AUDIT, "outcome": "failed", "reason": "timeout"}], [{**AUDIT, "outcome": "unknown"}, {**AUDIT, "value": "secret"}]),
    ("EventsNotification", [EVENT, {"method": "events.event", "params": {"subscriptionId": "s", "sequence": 2, "kind": "treeChanged", "handle": HANDLE}}], [{**EVENT, "id": 1}, {"method": "events.event", "params": {"subscriptionId": "s", "sequence": 1, "kind": "overflow", "handle": HANDLE}}]),
])
def test_instances(name, good, bad):
    assert all(valid(name, instance) for instance in good)
    assert all(not valid(name, instance) for instance in bad)
