"""Protocol 2 DTOs share the inspector schema fixtures."""

import json
from pathlib import Path

import pytest

from wintestkit.errors import InspectorReadError
from wintestkit.inspector import models
from wintestkit.inspector.client import _response

FIXTURES = Path(__file__).resolve().parents[3] / "wpf-inspector/protocol/fixtures"
MODELS = {
    name: getattr(models, name)
    for name in (
        "Scope",
        "Predicate",
        "Locator",
        "ElementState",
        "QueryFindResult",
        "QueryFindAllResult",
        "ActResult",
        "WaitCondition",
        "WaitResult",
        "WriteAudit",
        "EventsNotification",
    )
}
# Operation result aliases have the same shape as ActResult and WaitResult.
MODELS.update(
    {
        f"Act{verb}Result": models.ActResult
        for verb in (
            "BringIntoView",
            "Collapse",
            "Expand",
            "Focus",
            "Invoke",
            "ScrollIntoView",
            "Scroll",
            "Select",
            "SetRange",
            "SetValue",
            "Toggle",
        )
    }
)
MODELS["WaitUntilResult"] = models.WaitResult
CASES = []
for directory in ("valid", "invalid"):
    for path in sorted((FIXTURES / directory).glob("p2-*.json")):
        fixture = json.loads(path.read_text(encoding="utf-8"))
        if fixture["schema"] in MODELS:
            CASES.append((path.name, directory == "valid", fixture))


@pytest.mark.parametrize("name,valid,fixture", CASES, ids=[case[0] for case in CASES])
def test_protocol2_fixtures(name: str, valid: bool, fixture: dict) -> None:
    model = MODELS[fixture["schema"]]
    if valid:
        model.from_json(fixture["instance"])
    else:
        with pytest.raises(ValueError):
            model.from_json(fixture["instance"])


@pytest.mark.parametrize("pattern", [r"\d", "(?=x)", "a{10001}", "a{3,2}", "[", "\u00e9"])
def test_rejects_unsupported_regex(pattern: str) -> None:
    with pytest.raises(ValueError):
        models.Predicate.from_json(
            {
                "kind": "regex",
                "path": [{"kind": "uia", "name": "name"}],
                "pattern": pattern,
                "flags": [],
            }
        )


def test_nullable_geometry_round_trips_in_nested_result() -> None:
    fixture = json.loads((FIXTURES / "valid/p2-state-geometry.json").read_text(encoding="utf-8"))[
        "instance"
    ]
    fixture["bounds"] = None
    fixture["windowHandle"] = None
    fixture["parts"][0]["bounds"] = None
    state = models.ElementState.from_json(fixture)
    result = models.WaitResult(True, state.handle, state).to_json()
    assert result["state"]["bounds"] is None
    assert result["state"]["windowHandle"] is None
    assert result["state"]["parts"][0]["bounds"] is None


@pytest.mark.parametrize("status", ["redacted", "truncated", None, 7])
def test_unreadable_response_maps_to_read_error(status: object) -> None:
    _, _, error = _response(
        {
            "id": 1,
            "error": {
                "code": "valueUnreadable",
                "message": "unreadable",
                "details": {"status": status},
            },
        }
    )
    assert isinstance(error, InspectorReadError)
    expected = status if isinstance(status, str) else "valueUnreadable"
    assert error.code == expected
    assert expected in str(error)
