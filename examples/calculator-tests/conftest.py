"""Reset Calculator to Standard mode before each test.

WinTestKit's own ``app`` fixture decides how Calculator is obtained: attach to the running one or
spawn a new one, according to ``launch`` in the project settings (the Test Target view).
"""

import pytest
from flows.navigation import open_page
from pages.standard import StandardPage

from wintestkit import App


@pytest.fixture
def standard(app: App) -> StandardPage:
    calculator = open_page(app, StandardPage)
    calculator.clear()
    return calculator


@pytest.fixture(autouse=True)
def reset_calculator(standard: StandardPage) -> None:
    """Every test starts in Standard mode with a cleared display."""
