"""UI Automation constants as plain Python (no comtypes import, usable in unit tests)."""

from __future__ import annotations

from enum import IntEnum, IntFlag

_CONTROL_TYPE_NAMES_IN_ORDER = (
    "Button",
    "Calendar",
    "CheckBox",
    "ComboBox",
    "Edit",
    "Hyperlink",
    "Image",
    "ListItem",
    "List",
    "Menu",
    "MenuBar",
    "MenuItem",
    "ProgressBar",
    "RadioButton",
    "ScrollBar",
    "Slider",
    "Spinner",
    "StatusBar",
    "Tab",
    "TabItem",
    "Text",
    "ToolBar",
    "ToolTip",
    "Tree",
    "TreeItem",
    "Custom",
    "Group",
    "Thumb",
    "DataGrid",
    "DataItem",
    "Document",
    "SplitButton",
    "Window",
    "Pane",
    "Header",
    "HeaderItem",
    "Table",
    "TitleBar",
    "Separator",
    "SemanticZoom",
    "AppBar",
)

CONTROL_TYPES: dict[str, int] = {
    name: 50000 + i for i, name in enumerate(_CONTROL_TYPE_NAMES_IN_ORDER)
}
CONTROL_TYPE_NAMES: dict[int, str] = {v: k for k, v in CONTROL_TYPES.items()}

_CONTROL_TYPES_LOWER: dict[str, str] = {name.lower(): name for name in CONTROL_TYPES}
_CONTROL_TYPE_SUFFIX = "controltype"


def normalize_control_type(value: str) -> str:
    """Return the canonical control type name for ``value``.

    Lookup is case-insensitive and accepts a trailing ``ControlType`` suffix.
    """
    key = value.strip().lower()
    if key.endswith(_CONTROL_TYPE_SUFFIX) and key != _CONTROL_TYPE_SUFFIX:
        key = key[: -len(_CONTROL_TYPE_SUFFIX)]
    try:
        return _CONTROL_TYPES_LOWER[key]
    except KeyError:
        valid = ", ".join(sorted(CONTROL_TYPES))
        raise ValueError(f"unknown control type {value!r}; valid names: {valid}") from None


_PROPERTY_NAMES_IN_ORDER = (
    "RuntimeId",
    "BoundingRectangle",
    "ProcessId",
    "ControlType",
    "LocalizedControlType",
    "Name",
    "AcceleratorKey",
    "AccessKey",
    "HasKeyboardFocus",
    "IsKeyboardFocusable",
    "IsEnabled",
    "AutomationId",
    "ClassName",
    "HelpText",
    "ClickablePoint",
    "Culture",
    "IsControlElement",
    "IsContentElement",
    "LabeledBy",
    "IsPassword",
    "NativeWindowHandle",
    "ItemType",
    "IsOffscreen",
    "Orientation",
    "FrameworkId",
    "IsRequiredForForm",
    "ItemStatus",
    "IsDockPatternAvailable",
    "IsExpandCollapsePatternAvailable",
    "IsGridItemPatternAvailable",
    "IsGridPatternAvailable",
    "IsInvokePatternAvailable",
    "IsMultipleViewPatternAvailable",
    "IsRangeValuePatternAvailable",
    "IsScrollPatternAvailable",
    "IsScrollItemPatternAvailable",
    "IsSelectionItemPatternAvailable",
    "IsSelectionPatternAvailable",
    "IsTablePatternAvailable",
    "IsTableItemPatternAvailable",
    "IsTextPatternAvailable",
    "IsTogglePatternAvailable",
    "IsTransformPatternAvailable",
    "IsValuePatternAvailable",
    "IsWindowPatternAvailable",
    "ValueValue",
    "ValueIsReadOnly",
    "RangeValueValue",
    "RangeValueIsReadOnly",
    "RangeValueMinimum",
    "RangeValueMaximum",
    "RangeValueLargeChange",
    "RangeValueSmallChange",
    "ScrollHorizontalScrollPercent",
    "ScrollHorizontalViewSize",
    "ScrollVerticalScrollPercent",
    "ScrollVerticalViewSize",
    "ScrollHorizontallyScrollable",
    "ScrollVerticallyScrollable",
    "SelectionSelection",
    "SelectionCanSelectMultiple",
    "SelectionIsSelectionRequired",
    "GridRowCount",
    "GridColumnCount",
    "GridItemRow",
    "GridItemColumn",
    "GridItemRowSpan",
    "GridItemColumnSpan",
    "GridItemContainingGrid",
    "DockDockPosition",
    "ExpandCollapseExpandCollapseState",
    "MultipleViewCurrentView",
    "MultipleViewSupportedViews",
    "WindowCanMaximize",
    "WindowCanMinimize",
    "WindowWindowVisualState",
    "WindowWindowInteractionState",
    "WindowIsModal",
    "WindowIsTopmost",
    "SelectionItemIsSelected",
    "SelectionItemSelectionContainer",
    "TableRowHeaders",
    "TableColumnHeaders",
    "TableRowOrColumnMajor",
    "TableItemRowHeaderItems",
    "TableItemColumnHeaderItems",
    "ToggleToggleState",
    "TransformCanMove",
    "TransformCanResize",
    "TransformCanRotate",
    "IsLegacyIAccessiblePatternAvailable",
    "LegacyIAccessibleChildId",
    "LegacyIAccessibleName",
    "LegacyIAccessibleValue",
    "LegacyIAccessibleDescription",
    "LegacyIAccessibleRole",
    "LegacyIAccessibleState",
    "LegacyIAccessibleHelp",
    "LegacyIAccessibleKeyboardShortcut",
    "LegacyIAccessibleSelection",
    "LegacyIAccessibleDefaultAction",
    "AriaRole",
    "AriaProperties",
    "IsDataValidForForm",
    "ControllerFor",
    "DescribedBy",
    "FlowsTo",
    "ProviderDescription",
    "IsItemContainerPatternAvailable",
    "IsVirtualizedItemPatternAvailable",
    "IsSynchronizedInputPatternAvailable",
    "OptimizeForVisualContent",
    "IsObjectModelPatternAvailable",
)

PROPERTY_IDS: dict[str, int] = {name: 30000 + i for i, name in enumerate(_PROPERTY_NAMES_IN_ORDER)}
PROPERTY_NAMES: dict[int, str] = {v: k for k, v in PROPERTY_IDS.items()}

PATTERN_IDS: dict[str, int] = {
    "Invoke": 10000,
    "Selection": 10001,
    "Value": 10002,
    "RangeValue": 10003,
    "Scroll": 10004,
    "ExpandCollapse": 10005,
    "Grid": 10006,
    "GridItem": 10007,
    "MultipleView": 10008,
    "Window": 10009,
    "SelectionItem": 10010,
    "Dock": 10011,
    "Table": 10012,
    "TableItem": 10013,
    "Text": 10014,
    "Toggle": 10015,
    "Transform": 10016,
    "ScrollItem": 10017,
    "LegacyIAccessible": 10018,
    "ItemContainer": 10019,
    "VirtualizedItem": 10020,
}


class TreeScope(IntFlag):
    """``TreeScope`` flags used by ``FindAll`` / ``FindFirst``."""

    Element = 1
    Children = 2
    Descendants = 4
    Subtree = 7


class ToggleState(IntEnum):
    """``ToggleState`` values of the Toggle pattern."""

    Off = 0
    On = 1
    Indeterminate = 2


class ExpandCollapseState(IntEnum):
    """``ExpandCollapseState`` values of the ExpandCollapse pattern."""

    Collapsed = 0
    Expanded = 1
    PartiallyExpanded = 2
    LeafNode = 3
