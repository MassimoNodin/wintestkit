"""The Programmer mode number system selector."""

from wintestkit import Element, Page, RadioButton


class RadixSelection(Page):
    root = Element(automation_id="ProgrammerOperators")

    hexadecimal = RadioButton(automation_id="hexButton")
    decimal = RadioButton(automation_id="decimalButton")
    octal = RadioButton(automation_id="octolButton")
    binary = RadioButton(automation_id="binaryButton")

    def use_hexadecimal(self) -> None:
        self.hexadecimal.select()

    def use_binary(self) -> None:
        self.binary.select()
