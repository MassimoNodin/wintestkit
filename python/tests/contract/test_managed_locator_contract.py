"""Qualified locator keys travel through the existing public locator schema unchanged."""

import re

from wintestkit.engine.locator import Locator, WindowLocator


def test_managed_locator_round_trip_matches_public_schema(validate):
    locator = Locator(
        automation_id="fixture",
        where=(
            ("type:FullName", "Example.Control"),
            (r"clr:DataContext.A\.B", re.compile("^Sydney$", re.I)),
            (r"dp:Example|Example.Owner::Value/A\/B", 42),
            ("field:Public.Enabled", True),
        ),
        window=WindowLocator(where=(("type:AssemblyName", "Example"),)),
    )
    data = locator.to_dict()
    validate("common.schema.json", "LocatorData", data)
    assert Locator.from_dict(data) == locator
