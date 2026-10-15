"""The Scientific calculator page."""

from pages.calculator import CalculatorPage
from wintestkit import Element


class ScientificPage(CalculatorPage):
    pi = Element(automation_id="piButton")
