"""The Scientific calculator page."""

from pages.calculator import CalculatorModePage
from wintestkit import Button


class ScientificPage(CalculatorModePage):
    pi = Button(automation_id="piButton")
