# WinTestKit

UI test automation for Windows WPF applications using Microsoft UI Automation and pytest.

The package includes a UI Automation engine, screen/element model, pytest integration,
static discovery, environment checks, and target-based highlighting and screen checks.

## Development

From this directory, with Python 3.12+ and uv installed:

```powershell
uv sync
uv run pytest -m "not integration"
uv run wtk --help
uv run python -m wintestkit --version
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

Use `uv run pytest -m integration` with an unlocked Windows desktop and the built demo app
to run desktop tests. See the repository's root README and `docs/plan/` for the full plan.

## Resolve targets

Run from this directory after starting the demo app:

```powershell
uv run wtk --root ../examples/demo-tests highlight screens/main.py::MainScreen.sign_in --json
uv run wtk --root ../examples/demo-tests highlight screens/main.py::MainScreen --launch --duration 1000
uv run wtk --root ../examples/demo-tests check screens/main.py::MainScreen --json
```

`highlight` resolves immediately by default; `--timeout S` enables polling. `--launch` starts
the configured app only if it is not running, and closes only an app launched by that command.
`check` resolves every declared element without waiting. Hidden menu items, collapsed content
and unrealized collection items can legitimately fail until the UI exposes them. Exit codes
are 0 for found/all found, 1 for resolution failures, 2 for invalid targets/configuration,
and 3 for an app that is not running. User modules reload when project Python files change.
