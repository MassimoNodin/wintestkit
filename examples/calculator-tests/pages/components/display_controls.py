"""The keys that clear or correct what is on the display."""

from wintestkit import Button, Element, Page


class DisplayControls(Page):
    root = Element(control_type="Group", name="Display controls")

    clear = Button(automation_id="clearButton")
    backspace = Button(automation_id="backSpaceButton")
