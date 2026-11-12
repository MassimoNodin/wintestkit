from wintestkit import Button, Element, ListBox, Page, Window


class SuggestionBox(Page):
    root = Element(automation_id="SuggestionLeft")
    suggestion = Button(name="Scoped suggestion")


class FixturePage(Page):
    window = Window(where={"type:FullName": "WinTestKit.Fixture.MainWindow"})
    left = SuggestionBox()
    right = SuggestionBox(root=Element(automation_id="SuggestionRight"))
    fancy = Button(
        automation_id="FancyAutomationId",
        where={"type:Is": "WinTestKit.Fixture.FancyButton", "clr:DataContext.Label": "fixture"},
    )
    effect = Element(automation_id="ActionEffect")
    name_only = Element(automation_id="OnlyXName")

    def run_fancy_action(self) -> None:
        self.fancy.click()


class VirtualItemsPage(Page):
    window = Window(automation_id="VirtualItemsWindow")
    rows = ListBox(automation_id="VirtualItemsList")

    def choose_row(self, label: str) -> None:
        self.rows.select(label)
