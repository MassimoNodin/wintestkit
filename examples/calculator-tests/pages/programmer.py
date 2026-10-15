"""The Programmer calculator page."""

from pages.calculator import CalculatorPage
from wintestkit import Element


class ProgrammerPage(CalculatorPage):
    hexadecimal = Element(automation_id="hexButton")
    binary = Element(automation_id="binaryButton")
