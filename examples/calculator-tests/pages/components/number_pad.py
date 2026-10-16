"""The digit keys."""

from wintestkit import Button, Element, Page


class NumberPad(Page):
    root = Element(automation_id="NumberPad")

    zero = Button(automation_id="num0Button")
    one = Button(automation_id="num1Button")
    two = Button(automation_id="num2Button")
    three = Button(automation_id="num3Button")
    four = Button(automation_id="num4Button")
    five = Button(automation_id="num5Button")
    six = Button(automation_id="num6Button")
    seven = Button(automation_id="num7Button")
    eight = Button(automation_id="num8Button")
    nine = Button(automation_id="num9Button")

    def enter(self, number: int) -> None:
        """Press the keys of a non-negative whole number, left to right."""
        if number < 0:
            raise ValueError("Enter a non-negative whole number")
        keys = {
            "0": self.zero,
            "1": self.one,
            "2": self.two,
            "3": self.three,
            "4": self.four,
            "5": self.five,
            "6": self.six,
            "7": self.seven,
            "8": self.eight,
            "9": self.nine,
        }
        for digit in str(number):
            keys[digit].click()
