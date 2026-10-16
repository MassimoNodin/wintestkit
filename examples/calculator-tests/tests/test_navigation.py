"""Tests switch modes through flows, then assert the controls specific to each destination."""

import pytest
from flows.navigation import open_page, tour_calculator
from pages.programmer import ProgrammerPage
from pages.scientific import ScientificPage

from wintestkit import App, expect


@pytest.mark.navigation
def test_scientific_page(app: App) -> None:
    scientific = open_page(app, ScientificPage)
    expect(scientific.pi).to_be_visible()


@pytest.mark.navigation
def test_programmer_page(app: App) -> None:
    programmer = open_page(app, ProgrammerPage)
    expect(programmer.radix.hexadecimal).to_be_visible()
    expect(programmer.radix.binary).to_be_visible()


@pytest.mark.navigation
def test_tour_returns_to_standard(app: App) -> None:
    standard = tour_calculator(app)
    expect(standard.heading).to_have_text("Standard")
    expect(standard.operators.plus).to_be_enabled()
