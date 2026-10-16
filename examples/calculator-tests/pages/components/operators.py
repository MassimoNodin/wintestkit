"""The arithmetic operator keys."""

from wintestkit import Button, Element, Page


class StandardOperators(Page):
    # Only named, not identified, in Programmer mode: the name works in every mode.
    root = Element(control_type="Group", name="Standard operators")

    divide = Button(automation_id="divideButton")
    multiply = Button(automation_id="multiplyButton")
    minus = Button(automation_id="minusButton")
    plus = Button(automation_id="plusButton")
    equals = Button(automation_id="equalButton")
