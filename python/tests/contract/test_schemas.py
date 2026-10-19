"""Positive and negative coverage for the shared data contracts."""

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, ValidationError

FIXTURES_DIRECTORY = Path(__file__).parent / "fixtures"
Validate = Callable[[str, str, Any], None]


def fixture_data(filename: str) -> Any:
    return json.loads((FIXTURES_DIRECTORY / filename).read_text(encoding="utf-8"))


def run_events() -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in (FIXTURES_DIRECTORY / "events.ndjson").read_text(encoding="utf-8").splitlines()
    ]


@pytest.mark.parametrize(
    ("schema_file", "def_name", "filename"),
    [
        ("common.schema.json", "ElementInfo", "element-info.json"),
        ("common.schema.json", "Diagnostic", "diagnostic.json"),
        ("discovery.schema.json", "DiscoveryResult", "discovery.json"),
        ("step.schema.json", "StepEvent", "step.json"),
        ("results.schema.json", "Results", "results.json"),
        ("rpc.schema.json", "Suggestion", "suggestion.json"),
    ],
)
def test_shared_fixtures(
    validate: Validate, schema_file: str, def_name: str, filename: str
) -> None:
    validate(schema_file, def_name, fixture_data(filename))


def test_all_run_event_variants(validate: Validate) -> None:
    events = run_events()
    assert {event["event"] for event in events} == {
        "session_start",
        "collected",
        "test_start",
        "step",
        "test_output",
        "test_end",
        "session_end",
    }
    for event in events:
        validate("events.schema.json", "RunEvent", event)


def test_schema_documents_are_valid(schema_documents: dict[str, dict[str, Any]]) -> None:
    assert set(schema_documents) == {
        "common.schema.json",
        "discovery.schema.json",
        "step.schema.json",
        "events.schema.json",
        "results.schema.json",
        "rpc.schema.json",
    }
    for document in schema_documents.values():
        assert document["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        Draft202012Validator.check_schema(document)


RELOCATION = {
    "kind": "element",
    "target": "Home.address.street",
    "window": 'Window "Edit Customer"',
    "path": 'Window "Edit Customer" \u203a Group "Address" \u203a Edit "Street"',
}


def definition_examples() -> dict[str, dict[str, Any]]:
    element = fixture_data("element-info.json")
    diagnostic = fixture_data("diagnostic.json")
    discovery = fixture_data("discovery.json")
    results = fixture_data("results.json")
    events = run_events()
    node = {"nodeId": element["runtimeId"], "info": element, "hasChildren": False}
    element_result = {"status": "found", "element": element, "durationMs": 12.5}
    common = {
        "Position": {"line": 0, "character": 0},
        "Range": discovery["tests"][0]["range"],
        "Rect": element["rect"],
        "ElementInfo": element,
        "Matcher": {"regex": "^WTK Demo", "flags": "im"},
        "WindowLocatorData": {"title": "WTK Demo", "process": "DemoApp.exe"},
        "ItemSelectorData": {"kind": "cell", "row": 2, "column": "Name"},
        "LocatorData": discovery["pages"][0]["elements"][0]["locator"],
        "Mismatch": {"property": "name", "expected": "Sign in", "actual": "OK"},
        "Candidate": diagnostic["candidates"][0],
        "Relocation": RELOCATION,
        "Diagnostic": diagnostic,
        "ErrorInfo": {
            "type": "AmbiguousElementError",
            "message": diagnostic["message"],
            "diagnostic": diagnostic,
        },
    }
    rpc = {
        "ElementResult": element_result,
        "CheckResult": {**element_result, "qualname": "MainPage.sign_in"},
        "NodeInfo": node,
        "Suggestion": fixture_data("suggestion.json"),
        "InitializeParams": {"root": discovery["root"]},
        "InitializeResult": {
            "protocolVersion": 1,
            "wintestkitVersion": "0.1.0",
            "python": "3.12.0",
            "config": {
                "found": True,
                "app": {"path": "C:/wtk/DemoApp.exe", "process": "DemoApp.exe"},
                "launch": "per-test",
                "timeout": 10,
                "reportDir": "C:/wtk/wtk-report",
            },
        },
        "ShutdownParams": {},
        "ShutdownResult": None,
        "DiscoverParams": {"overrides": {"C:/wtk/pages/main.py": "class MainPage: pass"}},
        "DiscoverResult": discovery,
        "AppStatusParams": {},
        "AppStatusResult": {"running": True, "pids": [1234], "owned": True, "mainWindowTitle": "WTK Demo"},
        "AppProcessesParams": {},
        "RunningProcess": {
            "name": "CalculatorApp.exe",
            "pids": [38000],
            "windowTitle": "Calculator",
        },
        "AppProcessesResult": {
            "processes": [
                {"name": "CalculatorApp.exe", "pids": [38000], "windowTitle": "Calculator"}
            ]
        },
        "AppLaunchParams": {},
        "AppLaunchResult": {"pids": [1234]},
        "AppCloseParams": {},
        "AppCloseResult": None,
        "ElementHighlightParams": {
            "file": "C:/wtk/pages/main.py",
            "qualname": "MainPage.sign_in",
            "durationMs": 1500,
        },
        "ElementHighlightResult": element_result,
        "PageCheckParams": {"file": "C:/wtk/pages/main.py", "page": "MainPage"},
        "PageCheckResult": {"results": [{**element_result, "qualname": "MainPage.sign_in"}]},
        "FlowRunParams": {"file": "C:/wtk/flows/navigation.py", "name": "tour_calculator"},
        "FlowRunResult": {"status": "failed", "durationMs": 12.5, "message": "AssertionError: x"},
        "InspectRootsParams": {},
        "InspectRootsResult": [node],
        "InspectChildrenParams": {"nodeId": node["nodeId"]},
        "InspectChildrenResult": [node],
        "InspectPropertiesParams": {"nodeId": node["nodeId"]},
        "InspectPropertiesResult": {
            "info": element,
            "properties": {"Name": "Sign in"},
            "ancestors": [node],
        },
        "InspectHighlightParams": {
            "nodeId": node["nodeId"],
            "durationMs": 1500,
            "bringToFront": True,
        },
        "InspectHighlightResult": None,
        "SuggestLocatorParams": {"nodeId": node["nodeId"]},
        "SuggestLocatorResult": fixture_data("suggestion.json"),
        "DefinitionMatch": {
            "id": "pages/main.py::MainPage.sign_in",
            "qualname": "MainPage.sign_in",
            "kind": "element",
            "elementType": "Button",
            "locator": 'Button[name="Sign in"]',
            "file": "C:/wtk/pages/main.py",
            "line": 12,
            "range": common["Range"],
            "pages": ["MainPage.sign_in", "OtherPage.sign_in"],
            "pageCount": 2,
        },
        "DefinitionError": {"file": "C:/wtk/pages/broken.py", "message": "cannot import broken.py"},
        "InspectDefinitionsParams": {"nodeId": node["nodeId"]},
        "InspectDefinitionsResult": {
            "definitions": [
                {
                    "id": "pages/main.py::MainPage.sign_in",
                    "qualname": "MainPage.sign_in",
                    "kind": "element",
                    "elementType": "Button",
                    "locator": 'Button[name="Sign in"]',
                    "file": "C:/wtk/pages/main.py",
                    "line": 12,
                    "range": common["Range"],
                    "pages": ["MainPage.sign_in", "OtherPage.sign_in"],
                    "pageCount": 2,
                }
            ],
            "errors": [{"file": "C:/wtk/pages/broken.py", "message": "cannot import broken.py"}],
            "pageCount": 3,
        },
        "NodeCoverage": {"count": 1, "first": "MainPage.sign_in"},
        "InspectCoverageParams": {"nodeIds": [node["nodeId"]]},
        "InspectCoverageResult": {
            "covered": {node["nodeId"]: {"count": 1, "first": "MainPage.sign_in"}},
            "pending": ["1.2.3"],
        },
        "SpyStartParams": {},
        "SpyStartResult": None,
        "SpyStopParams": {},
        "SpyStopResult": None,
        "AppStartingNotification": {"stage": "window"},
        "SpyHoverNotification": {"node": node},
        "SpyPickedNotification": {"node": node, "suggestion": fixture_data("suggestion.json")},
        "SpyCancelledNotification": {},
        "LogNotification": {"level": "info", "message": "WinTestKit ready"},
    }
    return {
        "common.schema.json": common,
        "discovery.schema.json": {
            "DiscoveryResult": discovery,
            "TestEntry": discovery["tests"][0],
            "FlowEntry": {
                "id": "flows/navigation.py::open_page",
                "file": discovery["root"] + "/flows/navigation.py",
                "name": "open_page",
                "range": common["Range"],
                "nameRange": common["Range"],
                "runnable": True,
            },
            "PageEntry": discovery["pages"][0],
            "ElementEntry": discovery["pages"][0]["elements"][0],
            "ChildPageEntry": {
                "name": "address",
                "pageId": "pages/boxes.py::AddressBox",
                "range": discovery["pages"][0]["range"],
                "nameRange": discovery["pages"][0]["nameRange"],
            },
            "DiscoveryError": discovery["errors"][0],
        },
        "step.schema.json": {"StepEvent": fixture_data("step.json")},
        "events.schema.json": {
            "RunEvent": events[0],
            "TestOutcome": "passed",
            "CollectedTest": events[1]["tests"][0],
            "CollectError": {"file": "C:/wtk/tests/test_broken.py", "message": "invalid syntax"},
            "Summary": results["summary"],
        },
        "results.schema.json": {
            "Results": results,
            "TestResult": results["tests"][0],
            "Trace": {
                "startedAt": 1.0,
                "duration": 0.5,
                "frames": [{"time": 0.1, "path": "trace/0001.png"}],
                "truncated": False,
            },
        },
        "rpc.schema.json": rpc,
    }


@pytest.mark.parametrize("schema_file", sorted(definition_examples()))
def test_every_named_definition(
    validate: Validate, schema_documents: dict[str, dict[str, Any]], schema_file: str
) -> None:
    examples = definition_examples()[schema_file]
    assert set(examples) == set(schema_documents[schema_file]["$defs"])
    for def_name, example in examples.items():
        validate(schema_file, def_name, example)


@pytest.mark.parametrize("schema_file", sorted(definition_examples()))
def test_named_objects_reject_unknown_keys(validate: Validate, schema_file: str) -> None:
    for def_name, example in definition_examples()[schema_file].items():
        if isinstance(example, dict):
            with pytest.raises(ValidationError):
                validate(schema_file, def_name, {**example, "unexpected": True})


@pytest.mark.parametrize("event", run_events(), ids=lambda event: event["event"])
def test_events_reject_unknown_keys(validate: Validate, event: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        validate("events.schema.json", "RunEvent", {**event, "unexpected": True})


@pytest.mark.parametrize(
    "data",
    [
        {"kind": "cell", "row": 0},
        {"kind": "cell", "row": -1, "column": 0},
        {"kind": "cell", "row": 0, "column": -1},
        {"kind": "row", "row": 0.5},
        {"kind": "row", "row": True},
        {"kind": "other", "row": 0},
    ],
)
def test_invalid_item_selectors(validate: Validate, data: Any) -> None:
    with pytest.raises(ValidationError):
        validate("common.schema.json", "ItemSelectorData", data)


@pytest.mark.parametrize(
    ("schema_file", "def_name", "data"),
    [
        ("common.schema.json", "Matcher", {"regex": "test", "flags": "g"}),
        ("common.schema.json", "Position", {"line": -1, "character": 0}),
        ("common.schema.json", "Position", {"line": 0, "character": 1.5}),
        ("common.schema.json", "Rect", {"left": -10, "top": 0, "width": -1, "height": 10}),
        ("common.schema.json", "LocatorData", {"index": -1}),
        ("common.schema.json", "LocatorData", {"within": {"unexpected": True}}),
        ("common.schema.json", "WindowLocatorData", {"title": None}),
        ("events.schema.json", "TestOutcome", "unknown"),
        ("events.schema.json", "RunEvent", {"event": "unknown", "time": 0}),
        ("events.schema.json", "RunEvent", {"event": "test_start", "time": 0}),
        ("rpc.schema.json", "InitializeParams", {}),
        ("rpc.schema.json", "DiscoverParams", {"overrides": {"file.py": 42}}),
        ("rpc.schema.json", "InspectRootsParams", {"includeOtherApps": "yes"}),
        ("rpc.schema.json", "InspectHighlightResult", {}),
        ("rpc.schema.json", "LogNotification", {"level": "trace", "message": "test"}),
    ],
)
def test_invalid_contract_values(
    validate: Validate, schema_file: str, def_name: str, data: Any
) -> None:
    with pytest.raises(ValidationError):
        validate(schema_file, def_name, data)


def test_required_fields_and_nested_objects(validate: Validate) -> None:
    element = fixture_data("element-info.json")
    for required_key in ("name", "rect", "isEnabled", "runtimeId"):
        incomplete = {key: value for key, value in element.items() if key != required_key}
        with pytest.raises(ValidationError):
            validate("common.schema.json", "ElementInfo", incomplete)
    diagnostic = fixture_data("diagnostic.json")
    diagnostic["candidates"][0]["info"]["unexpected"] = True
    with pytest.raises(ValidationError):
        validate("common.schema.json", "Diagnostic", diagnostic)


def test_optional_and_nullable_fields(validate: Validate) -> None:
    element = fixture_data("element-info.json")
    element.pop("patterns")
    element["rect"] = None
    validate("common.schema.json", "ElementInfo", element)
    validate("common.schema.json", "LocatorData", {})
    validate("common.schema.json", "ItemSelectorData", {"kind": "row", "row": 0})
    validate("rpc.schema.json", "DiscoverParams", {})
    validate("rpc.schema.json", "AppStatusResult", {"running": False, "pids": [], "owned": False})
    initialize = definition_examples()["rpc.schema.json"]["InitializeResult"]
    initialize["config"].pop("app")
    validate("rpc.schema.json", "InitializeResult", initialize)


def test_recursive_diagnostic(validate: Validate) -> None:
    diagnostic = fixture_data("diagnostic.json")
    outer = copy.deepcopy(diagnostic)
    outer["kind"] = "within_failed"
    outer["within"] = diagnostic
    validate("common.schema.json", "Diagnostic", outer)
    outer["candidates"] = diagnostic["candidates"] * 3
    with pytest.raises(ValidationError):
        validate("common.schema.json", "Diagnostic", outer)


def test_diagnostic_relocations(validate: Validate) -> None:
    diagnostic = fixture_data("diagnostic.json")
    same = {**RELOCATION, "window": 'Window "Customer"', "sameWindow": True}
    diagnostic["relocations"] = [RELOCATION, {**RELOCATION, "kind": "component_root"}, same]
    diagnostic["hint"] = "the box moved"
    diagnostic["declared"] = "pages/components/address.py:9"
    validate("common.schema.json", "Diagnostic", diagnostic)
    diagnostic["relocations"] = [RELOCATION] * 6
    with pytest.raises(ValidationError):
        validate("common.schema.json", "Diagnostic", diagnostic)
    diagnostic["relocations"] = [{**RELOCATION, "sameWindow": "yes"}]
    with pytest.raises(ValidationError):
        validate("common.schema.json", "Diagnostic", diagnostic)
    diagnostic["relocations"] = [{**RELOCATION, "kind": "window"}]
    with pytest.raises(ValidationError):
        validate("common.schema.json", "Diagnostic", diagnostic)


def test_open_argument_map(validate: Validate) -> None:
    step = fixture_data("step.json")
    step["args"] = {"text": "***", "nested": {"choices": [1, True, None, "test"]}}
    validate("step.schema.json", "StepEvent", step)
    step["seq"] = 0
    with pytest.raises(ValidationError):
        validate("step.schema.json", "StepEvent", step)


def test_report_metadata_fields(validate: Validate) -> None:
    results = fixture_data("results.json")
    results.update(root="C:/project", command="pytest -q")
    results["tests"][0].update(absoluteFile="C:/project/tests/test_login.py", markers=["smoke"])
    validate("results.schema.json", "Results", results)
    events = run_events()
    events[0]["command"] = "pytest -q"
    events[1]["tests"][0]["markers"] = ["smoke"]
    for event in events[:2]:
        validate("events.schema.json", "RunEvent", event)
