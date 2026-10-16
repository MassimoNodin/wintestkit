"""The Calculator window and the page shared by its calculating modes."""

from pages.components.display_controls import DisplayControls
from pages.components.navigation import NavigationPane
from pages.components.number_pad import NumberPad
from pages.components.operators import StandardOperators
from wintestkit import Page, Text, Window


class CalculatorWindow(Page):
    """The one window; what every mode has in common is declared or mounted here."""

    window = Window()

    navigation = NavigationPane()
    heading = Text(automation_id="Header")
    result = Text(automation_id="CalculatorResults")


class CalculatorModePage(CalculatorWindow):
    """A mode with a keypad: Standard, Scientific and Programmer."""

    number_pad = NumberPad()
    operators = StandardOperators()
    display_controls = DisplayControls()

    def clear(self) -> None:
        self.display_controls.clear.click()

    def add(self, first: int, second: int) -> None:
        """Calculate ``first + second`` from a cleared display; read the answer from ``result``."""
        self.clear()
        self.number_pad.enter(first)
        self.operators.plus.click()
        self.number_pad.enter(second)
        self.operators.equals.click()

    def add_one_to(self, number: int) -> None:
        self.add(number, 1)
