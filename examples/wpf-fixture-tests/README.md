# WPF fixture tests

This example uses the published WPF fixture, the managed WPF tree (`backend: auto`), a movable
component mounted twice, typed controls, and TestComplete's `find_child` equivalent. The
`automation_id` locator uses AutomationId, falling back to `x:Name` for WPF controls. Run on an
interactive, unlocked Windows desktop with Python 3.12+, uv, and x64 .NET 10 Core and Windows
Desktop runtimes. Publish the fixture with `scripts/publish_fixtures.ps1` from the repository root. The inspector
payload must also be built; see the repository setup instructions. Set `DOTNET_ROOT_X64` to the x64 .NET 10 installation if it is not in its
standard location; see `python/tests/unit/live_dotnet.py` for runtime discovery.

From this directory, run `uv run pytest`. Each test starts and closes the fixture. Do not interact
with the desktop while it runs. Use `uv run pytest --collect-only` to check collection without UI.
The fixture's test-only controls are examples, not production application selectors.
