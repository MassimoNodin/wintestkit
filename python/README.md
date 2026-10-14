# WinTestKit

UI test automation for Windows WPF applications using Microsoft UI Automation and pytest.

This initial scaffold provides the package version and placeholder CLI and pytest plugin.
The UI Automation engine, screen model, and test runner integration are not implemented yet.

## Development

From this directory, with Python 3.12+ and uv installed:

```powershell
uv sync
uv run pytest
uv run wtk
uv run python -m wintestkit
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

Both CLI entry points print `wintestkit 0.1.0`. See the repository's root README and
`docs/plan/` directory for the full implementation plan.
