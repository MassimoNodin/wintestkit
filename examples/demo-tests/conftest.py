"""Shared fixtures for the demo tests."""

import pytest
from pages import MainPage

from wintestkit import expect


@pytest.fixture
def main(page) -> MainPage:  # type: ignore[no-untyped-def]
    """The main window page, bound to the application under test."""
    return page(MainPage)


@pytest.fixture(autouse=True)
def reset_demo(main: MainPage) -> None:
    """Start every test from a clean app: the app is shared by the whole session."""
    main.menu_file.click()
    main.menu_reset.click()
    expect(main.status).to_have_text("Ready")
