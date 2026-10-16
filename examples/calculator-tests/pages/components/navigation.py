"""The navigation view: the hamburger button and the pane of modes it opens."""

from wintestkit import Button, Element, ListItem, Page


class NavigationPane(Page):
    """The ``NavView`` control. The toggle button and the pane items live inside it."""

    root = Element(automation_id="NavView")

    toggle = Button(automation_id="TogglePaneButton")
    standard = ListItem(automation_id="Standard")
    scientific = ListItem(automation_id="Scientific")
    programmer = ListItem(automation_id="Programmer")

    def open_standard(self) -> None:
        self._open_pane()
        self.standard.select()

    def open_scientific(self) -> None:
        self._open_pane()
        self.scientific.select()

    def open_programmer(self) -> None:
        self._open_pane()
        self.programmer.select()

    def _open_pane(self) -> None:
        """The pane items only exist while the pane is open."""
        if not self.standard.exists():
            self.toggle.click()
