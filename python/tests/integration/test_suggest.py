"""Suggestions round-trip against the live demo."""

import pytest
from support import DemoProcess

from wintestkit.app import App
from wintestkit.engine.locator import Locator
from wintestkit.engine.resolve import Scope, resolve
from wintestkit.engine.suggest import suggest_locator

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "locator,strategy,helper",
    [
        (Locator(control_type="Button", name="Sign in"), "name", None),
        (Locator(automation_id="StatusText"), "automation_id", None),
        (
            Locator(
                control_type="Button",
                name="OK",
                within=Locator(control_type="Group", name="Panel B"),
            ),
            "within",
            "panel_b",
        ),
        (
            Locator(
                control_type="Edit",
                class_name="TextBox",
                within=Locator(control_type="Group", name="Credentials"),
            ),
            "class_name",
            None,
        ),
    ],
)
def test_demo_suggestions(
    demo_process: DemoProcess, locator: Locator, strategy: str, helper: str | None
) -> None:
    app = App.attach(pid=demo_process.pid)
    element = resolve(Scope(app), locator)
    suggestion = suggest_locator(element, app)
    assert suggestion.strategy == strategy
    if helper is not None:
        assert suggestion.helpers[-1][0] == helper
    assert resolve(Scope(app), suggestion.locator).same_as(element)
    assert suggestion.unique
