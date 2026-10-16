"""Navigation between modes is a flow: it knows the pages, the pages do not know each other."""

from collections.abc import Callable

from pages.calculator import CalculatorModePage, CalculatorWindow
from pages.components.navigation import NavigationPane
from pages.programmer import ProgrammerPage
from pages.scientific import ScientificPage
from pages.standard import StandardPage

from wintestkit import App, expect

# Mode page -> the navigation intent that opens it, and the heading it shows.
_MODES: dict[type[CalculatorModePage], tuple[Callable[[NavigationPane], None], str]] = {
    StandardPage: (NavigationPane.open_standard, "Standard"),
    ScientificPage: (NavigationPane.open_scientific, "Scientific"),
    ProgrammerPage: (NavigationPane.open_programmer, "Programmer"),
}


def open_page[Mode: CalculatorModePage](app: App, page_type: type[Mode]) -> Mode:
    """Switch Calculator to the mode of ``page_type`` and return that page."""
    if page_type not in _MODES:
        raise ValueError("Choose StandardPage, ScientificPage or ProgrammerPage")
    open_mode, heading = _MODES[page_type]
    open_mode(CalculatorWindow(app).navigation)
    destination = page_type(app)
    expect(destination.heading).to_have_text(heading)
    return destination


def tour_calculator(app: App) -> StandardPage:
    open_page(app, ScientificPage)
    open_page(app, ProgrammerPage)
    return open_page(app, StandardPage)
