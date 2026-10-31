"""Typed elements: ``Button``, ``TextBox``, ``ComboBox`` ... and the bound classes behind them.

Declare them exactly like ``Element`` (same locator options). Each binds to a class that offers
only the actions and reads that apply to the control, so autocomplete and the type checker reject
the rest, and each checks after resolving that the matched element really is that kind of control
(by UIA patterns, never by adding a ``control_type`` filter to the search).

Define your own for a custom control by subclassing ``BoundControl`` and ``Element``::

    class BoundDatePicker(BoundControl):
        required_patterns = ("Value",)

        def pick(self, date: datetime.date, *, timeout: float | None = None) -> None:
            with self.step("pick", {"date": date.isoformat()}):
                self.perform(timeout, lambda el: actions.type_text(el, date.isoformat()))

    class DatePicker(Element[BoundDatePicker]):
        pass
"""

# The typed controls assemble the model's private action mixins.
# pyright: reportPrivateUsage=false

from __future__ import annotations

import re

from wintestkit.backends.element import TargetElement
from wintestkit.engine import actions
from wintestkit.model import (
    BoundControl,
    Element,
    _Checkable,
    _Clickable,
    _Expandable,
    _GridControl,
    _Selecting,
    _TextEntry,
    _Valued,
)

__all__ = [
    "BoundButton",
    "BoundCheckBox",
    "BoundComboBox",
    "BoundDataGrid",
    "BoundListBox",
    "BoundListItem",
    "BoundRadioButton",
    "BoundTabControl",
    "BoundText",
    "BoundTextBox",
    "BoundTreeView",
    "Button",
    "CheckBox",
    "ComboBox",
    "DataGrid",
    "ListBox",
    "ListItem",
    "RadioButton",
    "TabControl",
    "Text",
    "TextBox",
    "TreeView",
]


# -- bound classes --------------------------------------------------------------------------------


class BoundButton(_Clickable):
    """A push, toggle or split button: ``click``, ``double_click``, ``right_click``."""

    required_patterns = ("Invoke|Toggle|ExpandCollapse",)


class BoundTextBox(_TextEntry):
    """An editable text control: ``type``, ``clear``, ``press``, ``value`` and ``text``."""

    required_patterns = ("Value|Text",)


class BoundCheckBox(_Clickable, _Checkable):
    """A check box: ``check``, ``uncheck``, ``toggle``, ``is_checked`` and ``click``."""

    required_patterns = ("Toggle",)

    def toggle(self, *, timeout: float | None = None) -> None:
        __tracebackhide__ = True
        with self.step("toggle"):
            self.perform(timeout, actions.toggle)


class BoundRadioButton(_Clickable):
    """A radio button: ``select``, ``is_selected`` and ``click``."""

    required_patterns = ("SelectionItem",)

    def select(self, *, timeout: float | None = None) -> None:
        __tracebackhide__ = True
        with self.step("select"):
            self.perform(timeout, actions.select_self)

    def is_selected(self) -> bool:
        __tracebackhide__ = True
        return actions.is_selected(self.resolve())


class BoundListItem(_Clickable):
    """A selectable list or navigation item: ``select``, ``is_selected`` and ``click``."""

    required_patterns = ("SelectionItem",)

    def select(self, *, timeout: float | None = None) -> None:
        __tracebackhide__ = True
        with self.step("select"):
            self.perform(timeout, actions.select_self)

    def is_selected(self) -> bool:
        __tracebackhide__ = True
        return actions.is_selected(self.resolve())


class _Choice(_Selecting):
    @property
    def selected(self) -> str | None:
        """The name of the selected item, or ``None`` when nothing is selected."""
        __tracebackhide__ = True
        chosen = self.selected_items()
        return chosen[0] if chosen else None


class _Listed(_Choice):
    def items(self) -> list[str]:
        """Names of the items currently realized (a virtualized list yields only those)."""
        __tracebackhide__ = True
        return actions.listed_item_names(self.resolve())


class BoundComboBox(_Valued, _Expandable, _Choice):
    """A combo box: ``select``, ``selected``, ``selected_items``, ``items``, ``expand``,
    ``collapse`` and ``value``."""

    required_patterns = ("ExpandCollapse", "Selection")

    def _choose(self, element: TargetElement, item: str | int | re.Pattern[str]) -> None:
        __tracebackhide__ = True
        actions.select_in_combo(element, item)

    def items(self) -> list[str]:
        """Names of all items: expands the combo box, reads them and collapses it again."""
        __tracebackhide__ = True
        return actions.combo_item_names(self.resolve())


class BoundListBox(_Listed):
    """A list: ``select``, ``selected``, ``selected_items`` and ``items``."""

    required_patterns = ("Selection",)


class BoundDataGrid(_GridControl, _Selecting):
    """A data grid: ``row``, ``cell``, ``row_count``, ``column_count``, ``find_row``, ``select``
    (a row by index) and ``selected_items``."""

    required_patterns = ("Grid",)


class BoundTreeView(_Listed):
    """A tree: ``select``, ``selected``, ``selected_items`` and ``items`` (realized nodes)."""

    accepted_control_types = ("Tree",)


class BoundTabControl(_Listed):
    """A tab control: ``select`` a tab, ``selected``, ``selected_items`` and ``items`` (tabs)."""

    required_patterns = ("Selection",)


class BoundText(BoundControl):
    """A read-only label or text: ``text`` and the common reads."""

    accepted_control_types = ("Text", "Edit", "Document")


# -- elements -------------------------------------------------------------------------------------


class Button(Element[BoundButton]):
    """A button (push, toggle or split)."""


class TextBox(Element[BoundTextBox]):
    """A text box, password box or other editable text control."""


class CheckBox(Element[BoundCheckBox]):
    """A check box."""


class RadioButton(Element[BoundRadioButton]):
    """A radio button."""


class ComboBox(Element[BoundComboBox]):
    """A combo box (drop-down list)."""


class ListBox(Element[BoundListBox]):
    """A list box or list view."""


class ListItem(Element[BoundListItem]):
    """A selectable list item, e.g. an entry of a navigation menu or a list view."""


class DataGrid(Element[BoundDataGrid]):
    """A data grid or table."""


class TreeView(Element[BoundTreeView]):
    """A tree view."""


class TabControl(Element[BoundTabControl]):
    """A tab control."""


class Text(Element[BoundText]):
    """A read-only label or text block."""
