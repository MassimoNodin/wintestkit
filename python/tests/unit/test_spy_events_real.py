"""Live events and resources: who handles a button's events, and one resource read on demand.

The owned fixture's FancyAutomationId button has a Click handler added in code; its StylingButton has
local resources. Only metadata and delegate lists are read and no input is sent to the fixture: no
handler runs, and the one resource that is asked for is the only one created.
"""

import json
import os
from typing import Any

import pytest
from test_spy_properties_real import InProcess, attached, pages, result, select_like_the_host
from test_spy_styling_real import find_by_automation_id

pytest_plugins = ("test_wpf_query_gate_real",)
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.name != "nt" or os.environ.get("WTK_INSPECTOR_REAL") != "1",
        reason="requires owned Windows fixture",
    ),
]


def object_params(session: dict[str, Any], ref: dict[str, Any]) -> dict[str, Any]:
    return {
        "sessionId": session["sessionId"],
        "objectId": ref["objectId"],
        "generation": ref["generation"],
    }


def test_events_of_a_button_with_a_click_handler(owned: Any) -> None:
    scope, path = owned
    rpc = InProcess(path, scope.app)
    with attached(rpc, scope.app.main_window().process_id) as (window, session):
        node = find_by_automation_id(rpc, window, "FancyAutomationId")
        ref = select_like_the_host(rpc, session, node)
        events = pages(rpc, "inspect.managed.events", object_params(session, ref))
        for event in events:
            known = event.get("handlersKnown", event.get("subscribersKnown"))
            count = event.get("handlerCount", event.get("subscriberCount"))
            print(
                f"{event['kind']:6} {event['name']:24} {event['declaringType']} known={known} n={count}"
            )
        print(json.dumps([item for item in events if item["name"] == "Click"], indent=2))

        names = [(item["kind"], item["name"]) for item in events]
        assert len(names) == len(set(names)), "each event is listed once"
        click = next(item for item in events if item["name"] == "Click")
        assert click["kind"] == "routed" and click["strategy"] == "bubble"
        assert click["handlersKnown"] is True and click["handlerCount"] == 1
        [handler] = click["handlers"]
        assert handler["declaringType"] and handler["method"]
        assert handler["handledEventsToo"] is False
        # The Click wrapper is the routed event, not a second CLR event.
        assert not any(item["kind"] == "clr" and item["name"] == "Click" for item in events)
        # Events somebody handles come first.
        counts = [item.get("handlerCount", item.get("subscriberCount")) for item in events]
        assert counts == sorted(counts, key=lambda count: count == 0)
        assert events[0]["name"] == "Click"
        assert next(item for item in events if item["name"] == "MouseDown")["handlerCount"] == 0


def test_resources_are_listed_by_key_and_read_one_at_a_time(owned: Any) -> None:
    scope, path = owned
    rpc = InProcess(path, scope.app)
    with attached(rpc, scope.app.main_window().process_id) as (window, session):
        node = find_by_automation_id(rpc, window, "StylingButton")
        ref = select_like_the_host(rpc, session, node)
        base = object_params(session, ref)
        styling = result(rpc, "inspect.managed.styling", base)
        entries = styling["resources"]["entries"]
        print(json.dumps(entries, indent=2))
        assert {item["key"] for item in entries} >= {"Accent", "StyleTitle"}
        assert all(set(item) == {"key", "keyKind", "index"} for item in entries)
        by_key = {item["key"]: item for item in entries}

        def read(entry: dict[str, Any]) -> dict[str, Any]:
            return dict(
                result(
                    rpc,
                    "inspect.managed.resource",
                    {
                        **base,
                        "scope": "local",
                        "key": entry["key"],
                        "keyKind": entry["keyKind"],
                        "index": entry["index"],
                    },
                )
            )

        title = read(by_key["StyleTitle"])
        print(json.dumps(title, indent=2))
        assert title["found"] is True and title["valueType"] == "System.String"
        assert title["value"]["scalar"] == "Styled"
        accent = read(by_key["Accent"])
        assert accent["found"] is True and accent["value"]["kind"] == "object"
        assert accent["valueType"] == "System.Windows.Media.SolidColorBrush"
        assert accent["value"]["object"]["sessionId"] == session["sessionId"]
        # The object can be expanded through the usual requests.
        members = result(
            rpc, "inspect.managed.members", object_params(session, accent["value"]["object"])
        )
        assert members["items"]
        gone = result(
            rpc,
            "inspect.managed.resource",
            {**base, "scope": "local", "key": "NoSuchKey", "keyKind": "string"},
        )
        assert gone == {"found": False}
