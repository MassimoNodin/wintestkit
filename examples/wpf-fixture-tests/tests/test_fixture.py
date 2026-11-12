from pages import FixturePage, VirtualItemsPage

from wintestkit import App, expect
from wintestkit.testcomplete import find_child


def test_fancy_action(app: App) -> None:
    page = FixturePage(app)
    page.run_fancy_action()
    expect(page.effect).to_have_text("Clicked 1")


def test_mounted_boxes(app: App) -> None:
    page = FixturePage(app)
    expect(page.left.suggestion).to_exist()
    expect(page.right.suggestion).to_exist()


def test_testcomplete_helper(app: App) -> None:
    page = FixturePage(app)
    expect(find_child(page, "WPFControlName", "FancyAutomationId", depth=20)).to_exist()


def test_virtualized_selection(app: App) -> None:
    page = VirtualItemsPage(app)
    page.choose_row("Item 100")
    assert page.rows.selected_items() == ["Item 100"]
