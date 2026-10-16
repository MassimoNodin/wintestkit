"""The Programmer calculator page."""

from pages.calculator import CalculatorModePage
from pages.components.radix import RadixSelection


class ProgrammerPage(CalculatorModePage):
    radix = RadixSelection()
