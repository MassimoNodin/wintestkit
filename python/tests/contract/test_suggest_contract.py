"""Generated suggestions conform to the editor contract."""

from typing import Any

from wintestkit.engine.locator import Locator, WindowLocator
from wintestkit.engine.suggest import Suggestion


def test_suggestion_contract(validate: Any) -> None:
    helper = Locator(control_type="Group", name="Panel B")
    suggestion = Suggestion(
        Locator(control_type="Button", name="OK", within=helper),
        'Element(control_type="Button", name="OK", within=panel_b)',
        "ok",
        (("panel_b", 'Element(control_type="Group", name="Panel B")', helper),),
        True,
        1,
        "within",
        ('Window(title="Demo")', WindowLocator(title="Demo")),
    )
    validate("rpc.schema.json", "Suggestion", suggestion.to_dict())
