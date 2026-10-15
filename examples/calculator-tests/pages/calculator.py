"""Shared controls and actions across Calculator modes."""

from wintestkit import Element, Page, Window


class CalculatorPage(Page):
    window = Window()

    navigation = Element(automation_id="TogglePaneButton")
    standard_menu_item = Element(automation_id="Standard")
    scientific_menu_item = Element(automation_id="Scientific")
    programmer_menu_item = Element(automation_id="Programmer")
    heading = Element(automation_id="Header")
    result = Element(automation_id="CalculatorResults")
    clear = Element(automation_id="clearButton")
    one = Element(automation_id="num1Button")
    two = Element(automation_id="num2Button")
    three = Element(automation_id="num3Button")
    plus = Element(automation_id="plusButton")
    equals = Element(automation_id="equalButton")

    def add_one_to(self, number: int) -> None:
        buttons = {1: self.one, 2: self.two, 3: self.three}
        if number not in buttons:
            raise ValueError("This introductory example accepts 1, 2 or 3")
        self.clear.click()
        buttons[number].click()
        self.plus.click()
        self.one.click()
        self.equals.click()
