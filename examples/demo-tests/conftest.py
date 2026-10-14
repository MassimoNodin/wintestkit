"""Shared fixtures for the demo tests."""

import pytest
from screens import MainScreen

from wintestkit import expect


@pytest.fixture
def main(screen) -> MainScreen:  # type: ignore[no-untyped-def]
    """The main window screen, bound to the application under test."""
    return screen(MainScreen)


@pytest.fixture(autouse=True)
def reset_demo(main: MainScreen) -> None:
    """Start every test from a clean app: the app is shared by the whole session."""
    main.menu_file.click()
    main.menu_reset.click()
    expect(main.status).to_have_text("Ready")
