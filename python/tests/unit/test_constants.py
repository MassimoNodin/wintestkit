"""Unit tests for the plain-Python UI Automation constants."""

import pytest

from wintestkit.uia.constants import (
    CONTROL_TYPE_NAMES,
    CONTROL_TYPES,
    PATTERN_IDS,
    PROPERTY_IDS,
    ExpandCollapseState,
    ToggleState,
    TreeScope,
    normalize_control_type,
)


def test_control_type_ids() -> None:
    assert CONTROL_TYPES["Button"] == 50000
    assert CONTROL_TYPES["Edit"] == 50004
    assert CONTROL_TYPES["Text"] == 50020
    assert CONTROL_TYPES["Group"] == 50026
    assert CONTROL_TYPES["DataGrid"] == 50028
    assert CONTROL_TYPES["Window"] == 50032
    assert CONTROL_TYPES["Pane"] == 50033
    assert CONTROL_TYPES["AppBar"] == 50040
    assert len(CONTROL_TYPES) == 41


def test_control_type_names_is_inverse() -> None:
    assert CONTROL_TYPE_NAMES[50011] == "MenuItem"
    for name, ident in CONTROL_TYPES.items():
        assert CONTROL_TYPE_NAMES[ident] == name


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Button", "Button"),
        ("button", "Button"),
        ("BUTTON", "Button"),
        ("buttoncontroltype", "Button"),
        ("ButtonControlType", "Button"),
        ("  datagrid ", "DataGrid"),
        ("listitem", "ListItem"),
    ],
)
def test_normalize_control_type(value: str, expected: str) -> None:
    assert normalize_control_type(value) == expected


def test_normalize_control_type_unknown_lists_valid_names() -> None:
    with pytest.raises(ValueError, match="Fooo") as exc:
        normalize_control_type("Fooo")
    message = str(exc.value)
    assert "Button" in message
    assert message.index("AppBar") < message.index("Button")  # sorted


def test_normalize_rejects_bare_suffix() -> None:
    with pytest.raises(ValueError, match="unknown control type"):
        normalize_control_type("ControlType")


def test_property_ids_required_entries() -> None:
    expected = {
        "RuntimeId": 30000,
        "BoundingRectangle": 30001,
        "ProcessId": 30002,
        "ControlType": 30003,
        "Name": 30005,
        "HasKeyboardFocus": 30008,
        "IsEnabled": 30010,
        "AutomationId": 30011,
        "ClassName": 30012,
        "NativeWindowHandle": 30020,
        "IsOffscreen": 30022,
        "FrameworkId": 30024,
    }
    for name, ident in expected.items():
        assert PROPERTY_IDS[name] == ident


def test_property_ids_selected_pattern_properties() -> None:
    assert PROPERTY_IDS["ValueValue"] == 30045
    assert PROPERTY_IDS["ToggleToggleState"] == 30086
    assert PROPERTY_IDS["IsLegacyIAccessiblePatternAvailable"] == 30090
    assert PROPERTY_IDS["IsVirtualizedItemPatternAvailable"] == 30109


def test_pattern_ids() -> None:
    assert PATTERN_IDS["Invoke"] == 10000
    assert PATTERN_IDS["Value"] == 10002
    assert PATTERN_IDS["Toggle"] == 10015
    assert PATTERN_IDS["VirtualizedItem"] == 10020
    assert len(PATTERN_IDS) == 21
    assert len(set(PATTERN_IDS.values())) == 21


def test_enums() -> None:
    assert TreeScope.Subtree == TreeScope.Element | TreeScope.Children | TreeScope.Descendants
    assert ToggleState.Indeterminate == 2
    assert ExpandCollapseState.LeafNode == 3
