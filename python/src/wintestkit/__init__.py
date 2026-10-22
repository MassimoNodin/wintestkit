"""UI test automation for Windows WPF applications."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

__version__ = "0.1.1rc1"

if TYPE_CHECKING:
    from wintestkit import errors as errors
    from wintestkit.app import App as App
    from wintestkit.config import WtkConfig as WtkConfig
    from wintestkit.config import load_config as load_config
    from wintestkit.controls import BoundButton as BoundButton
    from wintestkit.controls import BoundCheckBox as BoundCheckBox
    from wintestkit.controls import BoundComboBox as BoundComboBox
    from wintestkit.controls import BoundDataGrid as BoundDataGrid
    from wintestkit.controls import BoundListBox as BoundListBox
    from wintestkit.controls import BoundListItem as BoundListItem
    from wintestkit.controls import BoundRadioButton as BoundRadioButton
    from wintestkit.controls import BoundTabControl as BoundTabControl
    from wintestkit.controls import BoundText as BoundText
    from wintestkit.controls import BoundTextBox as BoundTextBox
    from wintestkit.controls import BoundTreeView as BoundTreeView
    from wintestkit.controls import Button as Button
    from wintestkit.controls import CheckBox as CheckBox
    from wintestkit.controls import ComboBox as ComboBox
    from wintestkit.controls import DataGrid as DataGrid
    from wintestkit.controls import ListBox as ListBox
    from wintestkit.controls import ListItem as ListItem
    from wintestkit.controls import RadioButton as RadioButton
    from wintestkit.controls import TabControl as TabControl
    from wintestkit.controls import Text as Text
    from wintestkit.controls import TextBox as TextBox
    from wintestkit.controls import TreeView as TreeView
    from wintestkit.expect import expect as expect
    from wintestkit.model import BoundControl as BoundControl
    from wintestkit.model import BoundElement as BoundElement
    from wintestkit.model import BoundElements as BoundElements
    from wintestkit.model import BoundWindow as BoundWindow
    from wintestkit.model import Element as Element
    from wintestkit.model import Elements as Elements
    from wintestkit.model import Page as Page
    from wintestkit.model import PageObject as PageObject
    from wintestkit.model import Window as Window

__all__ = [
    "App",
    "BoundButton",
    "BoundCheckBox",
    "BoundComboBox",
    "BoundControl",
    "BoundDataGrid",
    "BoundElement",
    "BoundElements",
    "BoundListBox",
    "BoundListItem",
    "BoundRadioButton",
    "BoundTabControl",
    "BoundText",
    "BoundTextBox",
    "BoundTreeView",
    "BoundWindow",
    "Button",
    "CheckBox",
    "ComboBox",
    "DataGrid",
    "Element",
    "Elements",
    "ListBox",
    "ListItem",
    "Page",
    "PageObject",
    "RadioButton",
    "TabControl",
    "Text",
    "TextBox",
    "TreeView",
    "Window",
    "WtkConfig",
    "__version__",
    "errors",
    "expect",
    "load_config",
]

# Public names are imported lazily so that merely loading the pytest plugin (which happens in
# every pytest run once wintestkit is installed) does not initialise COM or import UI Automation.
_LAZY: dict[str, tuple[str, str]] = {
    "App": ("wintestkit.app", "App"),
    "BoundButton": ("wintestkit.controls", "BoundButton"),
    "BoundCheckBox": ("wintestkit.controls", "BoundCheckBox"),
    "BoundComboBox": ("wintestkit.controls", "BoundComboBox"),
    "BoundDataGrid": ("wintestkit.controls", "BoundDataGrid"),
    "BoundListBox": ("wintestkit.controls", "BoundListBox"),
    "BoundListItem": ("wintestkit.controls", "BoundListItem"),
    "BoundRadioButton": ("wintestkit.controls", "BoundRadioButton"),
    "BoundTabControl": ("wintestkit.controls", "BoundTabControl"),
    "BoundText": ("wintestkit.controls", "BoundText"),
    "BoundTextBox": ("wintestkit.controls", "BoundTextBox"),
    "BoundTreeView": ("wintestkit.controls", "BoundTreeView"),
    "Button": ("wintestkit.controls", "Button"),
    "CheckBox": ("wintestkit.controls", "CheckBox"),
    "ComboBox": ("wintestkit.controls", "ComboBox"),
    "DataGrid": ("wintestkit.controls", "DataGrid"),
    "ListBox": ("wintestkit.controls", "ListBox"),
    "ListItem": ("wintestkit.controls", "ListItem"),
    "RadioButton": ("wintestkit.controls", "RadioButton"),
    "TabControl": ("wintestkit.controls", "TabControl"),
    "Text": ("wintestkit.controls", "Text"),
    "TextBox": ("wintestkit.controls", "TextBox"),
    "TreeView": ("wintestkit.controls", "TreeView"),
    "BoundControl": ("wintestkit.model", "BoundControl"),
    "BoundElement": ("wintestkit.model", "BoundElement"),
    "BoundElements": ("wintestkit.model", "BoundElements"),
    "BoundWindow": ("wintestkit.model", "BoundWindow"),
    "Element": ("wintestkit.model", "Element"),
    "Elements": ("wintestkit.model", "Elements"),
    "Page": ("wintestkit.model", "Page"),
    "PageObject": ("wintestkit.model", "PageObject"),
    "Window": ("wintestkit.model", "Window"),
    "WtkConfig": ("wintestkit.config", "WtkConfig"),
    "expect": ("wintestkit.expect", "expect"),
    "load_config": ("wintestkit.config", "load_config"),
}


def __getattr__(name: str) -> Any:
    if name == "errors":
        return importlib.import_module("wintestkit.errors")
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module 'wintestkit' has no attribute {name!r}")
    value = getattr(importlib.import_module(target[0]), target[1])
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(__all__)
