"""Live styling read: the Style, templates and resources of the owned fixture's styled button.

The button has a Style based on another Style (a DynamicResource setter, property and data
triggers), a template with named parts and local resources. The request runs no application code and
no input is sent to the fixture.
"""

import json
import os
from typing import Any

import pytest
from test_spy_properties_real import InProcess, attached, result, select_like_the_host

pytest_plugins = ("test_wpf_query_gate_real",)
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.name != "nt" or os.environ.get("WTK_INSPECTOR_REAL") != "1",
        reason="requires owned Windows fixture",
    ),
]


def find_by_automation_id(rpc: Any, window: dict[str, Any], automation_id: str) -> dict[str, Any]:
    pending = [window]
    while pending:
        node = pending.pop(0)
        children = result(rpc, "inspect.children", {"nodeId": node["nodeId"], "tree": "visual"})
        for child in children["nodes"]:
            if child["info"].get("automationId") == automation_id:
                return child
            pending.append(child)
    raise AssertionError(f"{automation_id} not found")


def test_styling_of_the_styled_button(owned: Any) -> None:
    scope, path = owned
    rpc = InProcess(path, scope.app)
    with attached(rpc, scope.app.main_window().process_id) as (window, session):
        node = find_by_automation_id(rpc, window, "StylingButton")
        ref = select_like_the_host(rpc, session, node)
        base = {
            "sessionId": session["sessionId"],
            "objectId": ref["objectId"],
            "generation": ref["generation"],
        }
        styling = result(rpc, "inspect.managed.styling", base)
        print(json.dumps(styling, indent=2))
        assert styling["applicable"] is True

        style = styling["style"]
        assert style["source"] == "local"
        assert style["targetType"] == "System.Windows.Controls.Button"
        assert [item["property"] for item in style["setters"]] == ["FontWeight"]
        [base_level] = style["basedOn"]
        by_property = {item["property"]: item for item in base_level["setters"]}
        assert by_property["Foreground"]["kind"] == "dynamicResource"
        assert by_property["Foreground"]["expression"] == "Accent"
        assert "value" not in by_property["Foreground"]
        assert by_property["Padding"]["kind"] == "value"
        triggers = {item["kind"]: item for item in style["triggers"]}
        assert [item["kind"] for item in style["triggers"]] == ["trigger", "trigger", "dataTrigger"]
        assert style["triggers"][0]["conditions"][0]["property"].endswith("UIElement.IsEnabled")
        # The button is enabled, so the IsEnabled = False trigger is not active; nothing hovers it.
        assert style["triggers"][0]["active"] == "inactive"
        assert style["triggers"][1]["active"] == "inactive"
        assert triggers["dataTrigger"]["active"] == "unknown"
        assert triggers["dataTrigger"]["conditions"][0]["binding"] == "Path=Label"

        control = styling["templates"]["controlTemplate"]
        assert control["kind"] == "controlTemplate"
        assert control["targetType"] == "System.Windows.Controls.Button"
        assert {part["name"] for part in control["parts"]} == {"PART_Frame", "PART_Content"}

        resources = {item["key"]: item for item in styling["resources"]["entries"]}
        assert resources["Accent"]["keyKind"] == "string"
        assert resources["System.Windows.Controls.CheckBox"]["keyKind"] == "type"
        # The listing names keys and positions only; a value is read by `inspect.managed.resource`.
        assert all(set(item) == {"key", "keyKind", "index"} for item in resources.values())
        assert styling["application"]["count"] >= 0

        # A peerless element is described too, and an object that is not an element is not applicable.
        peerless = element_ref(rpc, session, window, "Border")
        border = result(
            rpc,
            "inspect.managed.styling",
            {
                "sessionId": session["sessionId"],
                "objectId": peerless["objectId"],
                "generation": peerless["generation"],
            },
        )
        assert border["applicable"] is True
        assert border["style"]["source"] == "none"


def element_ref(
    rpc: Any, session: dict[str, Any], window: dict[str, Any], name: str
) -> dict[str, Any]:
    pending = [window]
    while pending:
        node = pending.pop(0)
        children = result(rpc, "inspect.children", {"nodeId": node["nodeId"], "tree": "visual"})
        for child in children["nodes"]:
            if child["info"]["className"].rsplit(".", 1)[-1] == name:
                mapping = result(
                    rpc,
                    "inspect.managed.resolve",
                    {"sessionId": session["sessionId"], "nodeId": child["nodeId"]},
                )
                return dict(mapping["object"])
            pending.append(child)
    raise AssertionError(f"{name} not found")
