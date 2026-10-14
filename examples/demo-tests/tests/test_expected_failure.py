"""A deliberately failing test that shows what a locator failure looks like.

Run it with ``WTK_DEMO_FAILURES=1 uv run pytest tests/test_expected_failure.py``. WinTestKit
reports the closest elements and what differs, and saves screenshots and a UI tree dump under
``wtk-report/artifacts``.
"""

import os

import pytest
from screens import MainScreen

from wintestkit import Element


@pytest.mark.skipif(
    os.environ.get("WTK_DEMO_FAILURES") != "1",
    reason="set WTK_DEMO_FAILURES=1 to run the intentionally failing demo test",
)
def test_misspelled_locator(main: MainScreen) -> None:
    class Typo(MainScreen):
        sign_in = Element(control_type="Button", name="Sign In", timeout=1)  # real name: "Sign in"

    Typo(main.app).sign_in.click()
