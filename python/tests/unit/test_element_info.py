"""Unit tests for Rect and ElementInfo (no UI Automation calls)."""

import json
from pathlib import Path

from wintestkit.uia.element import ElementInfo, Rect

FIXTURE = Path(__file__).parents[1] / "contract" / "fixtures" / "element-info.json"


def make_info(**overrides: object) -> ElementInfo:
    values: dict[str, object] = {
        "automation_id": "",
        "name": "Sign in",
        "control_type": "Button",
        "class_name": "Button",
        "framework_id": "WPF",
        "process_id": 1234,
        "rect": Rect(10, 20, 80, 30),
        "is_enabled": True,
        "is_offscreen": False,
        "has_keyboard_focus": False,
        "runtime_id": "42.1234.4.17",
    }
    values.update(overrides)
    return ElementInfo(**values)  # type: ignore[arg-type]


def test_rect_geometry() -> None:
    rect = Rect(10, 20, 80, 30)
    assert (rect.right, rect.bottom) == (90, 50)
    assert rect.center == (50, 35)
    assert not rect.is_empty()
    assert rect.inflate(3) == Rect(7, 17, 86, 36)
    assert rect.to_dict() == {"left": 10, "top": 20, "width": 80, "height": 30}


def test_rect_empty() -> None:
    assert Rect(0, 0, 0, 10).is_empty()
    assert Rect(0, 0, 10, -1).is_empty()


def test_fixture_round_trip() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    info = ElementInfo.from_dict(data)
    assert info.to_dict() == data
    assert info.patterns == ("Invoke",)


def test_patterns_omitted_unless_requested() -> None:
    assert "patterns" not in make_info().to_dict()
    assert make_info(patterns=("Invoke", "Value")).to_dict()["patterns"] == ["Invoke", "Value"]


def test_null_rect_round_trip() -> None:
    info = make_info(rect=None)
    data = info.to_dict()
    assert data["rect"] is None
    assert ElementInfo.from_dict(data) == info


def test_short_forms() -> None:
    assert make_info().short() == 'Button "Sign in"'
    assert make_info(name="", control_type="Edit", class_name="TextBox").short() == "Edit [TextBox]"
    assert (
        make_info(automation_id="StatusText", name="Ready", control_type="Text").short()
        == 'Text #StatusText "Ready"'
    )
    assert make_info(automation_id="Color", name="", control_type="ComboBox").short() == (
        "ComboBox #Color"
    )
    assert make_info(name="", class_name="", control_type="Pane").short() == "Pane"
