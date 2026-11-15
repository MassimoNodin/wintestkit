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
from collections.abc import Sequence

from wintestkit import runtime
from wintestkit.backends.element import TargetElement, WpfElement
from wintestkit.engine import actions, navigate
from wintestkit.model import (
    BoundControl,
    Element,
    _Checkable,
    _Clickable,
    _Expandable,
    _GridControl,
    _MultiSelecting,
    _Selecting,
    _TextEntry,
    _Valued,
)

__all__ = [
    "BoundButton",
    "BoundCheckBox",
    "BoundComboBox",
    "BoundContextMenu",
    "BoundDataGrid",
    "BoundListBox",
    "BoundListItem",
    "BoundMenu",
    "BoundRadioButton",
    "BoundTabControl",
    "BoundText",
    "BoundTextBox",
    "BoundTreeView",
    "Button",
    "CheckBox",
    "ComboBox",
    "ContextMenu",
    "DataGrid",
    "ListBox",
    "ListItem",
    "Menu",
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
        if isinstance(element, WpfElement):
            actions.select_in_combo(element, item, mode=runtime.get_config().input_mode)
        else:
            actions.select_in_combo(element, item)

    def items(self) -> list[str]:
        """Names of all items: expands the combo box, reads them and collapses it again."""
        __tracebackhide__ = True
        return actions.combo_item_names(self.resolve())


class BoundListBox(_MultiSelecting, _Listed):
    """A list: ``select`` (one item or several), ``deselect``, ``clear_selection``, ``selected``,
    ``selected_items`` and ``items``."""

    required_patterns = ("Selection",)


class BoundDataGrid(_GridControl, _MultiSelecting):
    """A data grid: ``row``, ``cell``, ``row_count``, ``column_count``, ``find_row``, ``select``
    (rows by index, one or several), ``deselect``, ``clear_selection`` and ``selected_items``."""

    required_patterns = ("Grid",)


class BoundTreeView(_Choice):
    """A tree: ``select``, ``selected``, ``selected_items``, ``items``, ``expand`` and ``collapse``.

    ``select``, ``expand``, ``collapse`` and ``items`` also take a path through the tree, such as
    ``"Root|Child A|Leaf 1"`` (or a list of names or compiled regexes): every ancestor is expanded
    on the way. ``separator`` changes the character that splits a string path.
    """

    accepted_control_types = ("Tree",)

    def select(
        self,
        items: str | int | re.Pattern[str] | Sequence[navigate.Segment],
        *,
        timeout: float | None = None,
        separator: str = navigate.DEFAULT_SEPARATOR,
    ) -> None:
        __tracebackhide__ = True
        if isinstance(items, int | re.Pattern) or (
            isinstance(items, str) and not navigate.is_path(items, separator)
        ):
            super().select(items, timeout=timeout)
            return
        segments = navigate.split_path(items, separator)
        mode = runtime.get_config().input_mode
        budget = self._timeout(timeout)
        with self.step("select", {"item": navigate.path_text(items, separator)}):
            self.perform(
                timeout,
                lambda el: navigate.select_tree_path(el, segments, mode=mode, timeout=budget),
            )

    def expand(
        self,
        path: navigate.PathSpec,
        *,
        timeout: float | None = None,
        separator: str = navigate.DEFAULT_SEPARATOR,
    ) -> None:
        """Expand the node at ``path`` and every node on the way to it."""
        __tracebackhide__ = True
        segments = navigate.split_path(path, separator)
        budget = self._timeout(timeout)
        with self.step("expand", {"path": navigate.path_text(path, separator)}):
            self.perform(
                timeout, lambda el: navigate.expand_tree_path(el, segments, timeout=budget)
            )

    def collapse(
        self,
        path: navigate.PathSpec,
        *,
        timeout: float | None = None,
        separator: str = navigate.DEFAULT_SEPARATOR,
    ) -> None:
        """Collapse the node at ``path`` (its ancestors are expanded to reach it)."""
        __tracebackhide__ = True
        segments = navigate.split_path(path, separator)
        budget = self._timeout(timeout)
        with self.step("collapse", {"path": navigate.path_text(path, separator)}):
            self.perform(
                timeout, lambda el: navigate.collapse_tree_path(el, segments, timeout=budget)
            )

    def items(
        self,
        path: navigate.PathSpec | None = None,
        *,
        separator: str = navigate.DEFAULT_SEPARATOR,
    ) -> list[str]:
        """Names of the children of the node at ``path`` (the top level without a path).

        A node's children exist only while it is expanded, so ``expand`` it first.
        """
        __tracebackhide__ = True
        segments = None if path is None else navigate.split_path(path, separator)
        budget = self._timeout(None)
        return navigate.tree_item_names(self.resolve(), segments, timeout=budget)


class BoundTabControl(_Listed):
    """A tab control: ``select`` a tab, ``selected``, ``selected_items`` and ``items`` (tabs)."""

    required_patterns = ("Selection",)


class BoundMenu(BoundControl):
    """A menu bar: ``click_path`` opens each level in turn and clicks the last item."""

    accepted_control_types = ("Menu", "MenuBar")
    #: Menus already open when the path starts; a failure presses Escape for them as well.
    _base_open = 0

    def click_path(
        self,
        path: navigate.PathSpec,
        *,
        timeout: float | None = None,
        separator: str = navigate.DEFAULT_SEPARATOR,
    ) -> None:
        """Click the item at ``path``, e.g. ``"File|Recent|Report.txt"``.

        Each segment is an item name, or a compiled regex when the path is a list. A failure
        names the missing segment, lists the items of that level and closes the open menus.
        """
        __tracebackhide__ = True
        segments = navigate.split_path(path, separator)
        mode = runtime.get_config().input_mode
        budget = self._timeout(timeout)
        base = self._base_open
        with self.step("click_path", {"path": navigate.path_text(path, separator)}):
            self.perform(
                timeout,
                lambda el: navigate.click_menu_path(
                    el, segments, mode=mode, timeout=budget, base_open=base
                ),
            )


class BoundContextMenu(BoundMenu):
    """A context menu: ``click_path``. ``open_context_menu()`` on any element returns one."""

    accepted_control_types = ("Menu",)
    _base_open = 1
    _of_owner = False

    @classmethod
    def _for_owner(cls, owner: BoundControl) -> BoundContextMenu:
        """The context menu just opened on ``owner`` (its items are found in the popup windows)."""
        __tracebackhide__ = True
        menu = cls(owner.page, owner.definition, owner.locator)
        menu._of_owner = True
        return menu

    def check_type(self, element: TargetElement) -> None:
        __tracebackhide__ = True
        if not self._of_owner:
            super().check_type(element)


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


class Menu(Element[BoundMenu]):
    """A menu bar."""


class ContextMenu(Element[BoundContextMenu]):
    """A context menu (a popup, so it exists only while open)."""
