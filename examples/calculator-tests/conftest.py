"""Start or attach to Calculator and reset its mode before each test."""

import shutil
from collections.abc import Generator

import pytest
from flows.navigation import open_page
from pages.standard import StandardPage

from wintestkit import App
from wintestkit.errors import AppNotRunningError


@pytest.fixture(scope="session")
def calculator_app() -> Generator[App, None, None]:
    try:
        calculator = App.attach(process="CalculatorApp.exe")
    except AppNotRunningError:
        launcher = shutil.which("calc.exe")
        if launcher is None:
            pytest.fail("Windows Calculator is not installed: calc.exe was not found")
        calculator = App.launch(launcher, process="CalculatorApp.exe")
    try:
        calculator.main_window(timeout=30.0)
        yield calculator
    finally:
        if calculator.launched:
            calculator.close()


@pytest.fixture
def app(calculator_app: App) -> App:
    return calculator_app


@pytest.fixture
def standard(app: App) -> StandardPage:
    calculator = open_page(app, StandardPage)
    calculator.clear()
    return calculator


@pytest.fixture(autouse=True)
def reset_calculator(standard: StandardPage) -> None:
    """Every test starts in Standard mode with a cleared display."""
