# WinTestKit

UI test automation for Windows WPF applications using Microsoft UI Automation and pytest.

The package includes a UI Automation engine, screen/element model, pytest integration,
static discovery, environment checks, and target-based highlighting and screen checks.

## Initialize a project

Run `wtk init my-tests --app "C:/Apps/My App.exe"` to create a starter screen,
smoke test, pytest configuration, and report ignore entry. Existing metadata,
configuration, and Python files are preserved. `--force` replaces starter Python
files only; it does not overwrite application settings. Review the window title
in `screens/main.py`, then run `wtk doctor` and `wtk run` from the new folder.

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

## Inspect the application

`wtk inspect` dumps the configured app main window. Use `--window TITLE` or
`--window /REGEX/` to select a window, `--all-windows` to inspect all app windows,
and `--depth N` to bound tree expansion (0 to 50, default 12). `--json` emits a
tree object, or a `windows` array for `--all-windows`.

`wtk inspect --at X,Y --json` reports the app element and its nearest-first
ancestor chain, including supported patterns. Coordinates are physical screen
pixels; use `--at=-100,200` for negative coordinates. Button text is normalized
to its containing button. Points outside the configured app fail without
inspecting another process. Window and point selection options are mutually exclusive.

The suggestion engine (`wintestkit.engine.suggest`) verifies generated locators
against the selected element, prioritizing stable IDs, names, classes, scoped
ancestors, and finally positional indices. Helpers precede dependent declarations;
index suggestions are fragile if the UI order changes. In the current demo the
username TextBox is globally unique, so the documented candidate ordering selects
`class_name` rather than the plan example expected `within=credentials`.

## Pick locators

`wtk spy` highlights hovered controls in the configured application. Ctrl+Click
picks a control without activating it and prints its window, required helpers,
and element declaration. Esc or Ctrl+C exits and removes the hooks and overlay.
Use `--all-processes` explicitly to inspect other applications. The command does
not launch an application or change elevation; it requires an unlocked desktop.

## Editor server

`wtk serve --stdio` accepts one JSON-RPC 2.0 object per UTF-8 line. Send
`initialize` with `{ "root": "absolute/project/path" }` first. It supports
discovery, app lifecycle, target checks/highlights, inspector nodes, suggestions,
and Spy notifications, as specified in `docs/plan/05-protocol.md`. Ordinary
requests execute sequentially; Spy stop and shutdown bypass queued work.
Standard output is protocol-only, including when user modules print. Shutdown
and input EOF clean up Spy but leave the application open. Inspector node IDs
are runtime IDs held in a bounded 5,000-entry LRU; stale IDs return `-32005`.
