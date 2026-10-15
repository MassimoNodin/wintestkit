"""Navigation is ordinary Python; no workflow registration is needed."""

from pages.calculator import CalculatorPage
from pages.programmer import ProgrammerPage
from pages.scientific import ScientificPage
from pages.standard import StandardPage

from wintestkit import App, expect


def open_page[CalculatorMode: CalculatorPage](
    app: App, page_type: type[CalculatorMode]
) -> CalculatorMode:
    modes = {
        StandardPage: ("standard_menu_item", "Standard"),
        ScientificPage: ("scientific_menu_item", "Scientific"),
        ProgrammerPage: ("programmer_menu_item", "Programmer"),
    }
    if page_type not in modes:
        raise ValueError("Choose StandardPage, ScientificPage or ProgrammerPage")
    menu_item, heading = modes[page_type]
    current = CalculatorPage(app)
    current.navigation.click()
    getattr(current, menu_item).click()
    destination = page_type(app)
    expect(destination.heading).to_have_text(heading)
    return destination


def tour_calculator(app: App) -> StandardPage:
    open_page(app, ScientificPage)
    open_page(app, ProgrammerPage)
    return open_page(app, StandardPage)
