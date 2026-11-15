"""UI test automation for Windows WPF applications."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

__version__ = "0.1.1rc2"

if TYPE_CHECKING:
    from wintestkit import errors as errors
    from wintestkit import keyboard as keyboard
    from wintestkit import log as log
    from wintestkit.app import App as App
    from wintestkit.config import WtkConfig as WtkConfig
    from wintestkit.config import load_config as load_config
    from wintestkit.controls import BoundButton as BoundButton
    from wintestkit.controls import BoundCheckBox as BoundCheckBox
    from wintestkit.controls import BoundComboBox as BoundComboBox
    from wintestkit.controls import BoundContextMenu as BoundContextMenu
    from wintestkit.controls import BoundDataGrid as BoundDataGrid
    from wintestkit.controls import BoundDatePicker as BoundDatePicker
    from wintestkit.controls import BoundExpander as BoundExpander
    from wintestkit.controls import BoundHyperlink as BoundHyperlink
    from wintestkit.controls import BoundListBox as BoundListBox
    from wintestkit.controls import BoundListItem as BoundListItem
    from wintestkit.controls import BoundMenu as BoundMenu
    from wintestkit.controls import BoundProgressBar as BoundProgressBar
    from wintestkit.controls import BoundRadioButton as BoundRadioButton
    from wintestkit.controls import BoundScrollBar as BoundScrollBar
    from wintestkit.controls import BoundSlider as BoundSlider
    from wintestkit.controls import BoundStatusBar as BoundStatusBar
    from wintestkit.controls import BoundTabControl as BoundTabControl
    from wintestkit.controls import BoundText as BoundText
    from wintestkit.controls import BoundTextBox as BoundTextBox
    from wintestkit.controls import BoundToggleButton as BoundToggleButton
    from wintestkit.controls import BoundToolBar as BoundToolBar
    from wintestkit.controls import BoundTreeView as BoundTreeView
    from wintestkit.controls import Button as Button
    from wintestkit.controls import CheckBox as CheckBox
    from wintestkit.controls import ComboBox as ComboBox
    from wintestkit.controls import ContextMenu as ContextMenu
    from wintestkit.controls import DataGrid as DataGrid
    from wintestkit.controls import DatePicker as DatePicker
    from wintestkit.controls import Expander as Expander
    from wintestkit.controls import Hyperlink as Hyperlink
    from wintestkit.controls import ListBox as ListBox
    from wintestkit.controls import ListItem as ListItem
    from wintestkit.controls import Menu as Menu
    from wintestkit.controls import ProgressBar as ProgressBar
    from wintestkit.controls import RadioButton as RadioButton
    from wintestkit.controls import ScrollBar as ScrollBar
    from wintestkit.controls import Slider as Slider
    from wintestkit.controls import StatusBar as StatusBar
    from wintestkit.controls import TabControl as TabControl
    from wintestkit.controls import Text as Text
    from wintestkit.controls import TextBox as TextBox
    from wintestkit.controls import ToggleButton as ToggleButton
    from wintestkit.controls import ToolBar as ToolBar
    from wintestkit.controls import TreeView as TreeView
    from wintestkit.expect import expect as expect
    from wintestkit.finders import find as find
    from wintestkit.finders import find_all_children as find_all_children
    from wintestkit.finders import find_child as find_child
    from wintestkit.managed import Decimal as Decimal
    from wintestkit.managed import Double as Double
    from wintestkit.managed import Enum as Enum
    from wintestkit.managed import Int32 as Int32
    from wintestkit.managed import Int64 as Int64
    from wintestkit.managed import Null as Null
    from wintestkit.managed import Single as Single
    from wintestkit.model import BoundControl as BoundControl
    from wintestkit.model import BoundElement as BoundElement
    from wintestkit.model import BoundElements as BoundElements
    from wintestkit.model import BoundWindow as BoundWindow
    from wintestkit.model import Element as Element
    from wintestkit.model import Elements as Elements
    from wintestkit.model import Page as Page
    from wintestkit.model import PageObject as PageObject
    from wintestkit.model import Window as Window
    from wintestkit.runtime import user_step as step

__all__ = [
    "App",
    "BoundButton",
    "BoundCheckBox",
    "BoundComboBox",
    "BoundContextMenu",
    "BoundControl",
    "BoundDataGrid",
    "BoundDatePicker",
    "BoundElement",
    "BoundElements",
    "BoundExpander",
    "BoundHyperlink",
    "BoundListBox",
    "BoundListItem",
    "BoundMenu",
    "BoundProgressBar",
    "BoundRadioButton",
    "BoundScrollBar",
    "BoundSlider",
    "BoundStatusBar",
    "BoundTabControl",
    "BoundText",
    "BoundTextBox",
    "BoundToggleButton",
    "BoundToolBar",
    "BoundTreeView",
    "BoundWindow",
    "Button",
    "CheckBox",
    "ComboBox",
    "ContextMenu",
    "DataGrid",
    "DatePicker",
    "Decimal",
    "Double",
    "Element",
    "Elements",
    "Enum",
    "Expander",
    "Hyperlink",
    "Int32",
    "Int64",
    "ListBox",
    "ListItem",
    "Menu",
    "Null",
    "Page",
    "PageObject",
    "ProgressBar",
    "RadioButton",
    "ScrollBar",
    "Single",
    "Slider",
    "StatusBar",
    "TabControl",
    "Text",
    "TextBox",
    "ToggleButton",
    "ToolBar",
    "TreeView",
    "Window",
    "WtkConfig",
    "__version__",
    "errors",
    "expect",
    "find",
    "find_all_children",
    "find_child",
    "keyboard",
    "load_config",
    "log",
    "step",
]

# Public names are imported lazily so that merely loading the pytest plugin (which happens in
# every pytest run once wintestkit is installed) does not initialise COM or import UI Automation.
_LAZY: dict[str, tuple[str, str]] = {
    "Int32": ("wintestkit.managed", "Int32"),
    "Int64": ("wintestkit.managed", "Int64"),
    "Single": ("wintestkit.managed", "Single"),
    "Double": ("wintestkit.managed", "Double"),
    "Decimal": ("wintestkit.managed", "Decimal"),
    "Enum": ("wintestkit.managed", "Enum"),
    "Null": ("wintestkit.managed", "Null"),
    "step": ("wintestkit.runtime", "user_step"),
    "App": ("wintestkit.app", "App"),
    "BoundButton": ("wintestkit.controls", "BoundButton"),
    "BoundCheckBox": ("wintestkit.controls", "BoundCheckBox"),
    "BoundComboBox": ("wintestkit.controls", "BoundComboBox"),
    "BoundContextMenu": ("wintestkit.controls", "BoundContextMenu"),
    "BoundDataGrid": ("wintestkit.controls", "BoundDataGrid"),
    "BoundDatePicker": ("wintestkit.controls", "BoundDatePicker"),
    "BoundExpander": ("wintestkit.controls", "BoundExpander"),
    "BoundHyperlink": ("wintestkit.controls", "BoundHyperlink"),
    "BoundListBox": ("wintestkit.controls", "BoundListBox"),
    "BoundListItem": ("wintestkit.controls", "BoundListItem"),
    "BoundMenu": ("wintestkit.controls", "BoundMenu"),
    "BoundProgressBar": ("wintestkit.controls", "BoundProgressBar"),
    "BoundRadioButton": ("wintestkit.controls", "BoundRadioButton"),
    "BoundScrollBar": ("wintestkit.controls", "BoundScrollBar"),
    "BoundSlider": ("wintestkit.controls", "BoundSlider"),
    "BoundStatusBar": ("wintestkit.controls", "BoundStatusBar"),
    "BoundTabControl": ("wintestkit.controls", "BoundTabControl"),
    "BoundText": ("wintestkit.controls", "BoundText"),
    "BoundTextBox": ("wintestkit.controls", "BoundTextBox"),
    "BoundToggleButton": ("wintestkit.controls", "BoundToggleButton"),
    "BoundToolBar": ("wintestkit.controls", "BoundToolBar"),
    "BoundTreeView": ("wintestkit.controls", "BoundTreeView"),
    "Button": ("wintestkit.controls", "Button"),
    "CheckBox": ("wintestkit.controls", "CheckBox"),
    "ComboBox": ("wintestkit.controls", "ComboBox"),
    "ContextMenu": ("wintestkit.controls", "ContextMenu"),
    "DataGrid": ("wintestkit.controls", "DataGrid"),
    "DatePicker": ("wintestkit.controls", "DatePicker"),
    "Expander": ("wintestkit.controls", "Expander"),
    "Hyperlink": ("wintestkit.controls", "Hyperlink"),
    "ListBox": ("wintestkit.controls", "ListBox"),
    "ListItem": ("wintestkit.controls", "ListItem"),
    "Menu": ("wintestkit.controls", "Menu"),
    "ProgressBar": ("wintestkit.controls", "ProgressBar"),
    "RadioButton": ("wintestkit.controls", "RadioButton"),
    "ScrollBar": ("wintestkit.controls", "ScrollBar"),
    "Slider": ("wintestkit.controls", "Slider"),
    "StatusBar": ("wintestkit.controls", "StatusBar"),
    "TabControl": ("wintestkit.controls", "TabControl"),
    "Text": ("wintestkit.controls", "Text"),
    "TextBox": ("wintestkit.controls", "TextBox"),
    "ToggleButton": ("wintestkit.controls", "ToggleButton"),
    "ToolBar": ("wintestkit.controls", "ToolBar"),
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
    "find": ("wintestkit.finders", "find"),
    "find_all_children": ("wintestkit.finders", "find_all_children"),
    "find_child": ("wintestkit.finders", "find_child"),
    "load_config": ("wintestkit.config", "load_config"),
}


def __getattr__(name: str) -> Any:
    if name in ("errors", "keyboard", "log"):
        return importlib.import_module("wintestkit." + name)
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module 'wintestkit' has no attribute {name!r}")
    value = getattr(importlib.import_module(target[0]), target[1])
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(__all__)
