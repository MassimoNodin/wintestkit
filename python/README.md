# WinTestKit

UI test automation for Windows WPF applications using Microsoft UI Automation and pytest.

The package includes a UI Automation engine, page/element model, pytest integration,
static discovery, environment checks, and target-based highlighting and page checks.

## Installation

Requires Windows and Python 3.12 or later:

```powershell
python -m pip install wintestkit
wtk --version
```

pytest is installed automatically. For the editor tools, install the WinTestKit VS Code
extension and select the Python environment containing this package. See the
[user guide](https://github.com/MassimoNodin/wintestkit/blob/master/docs/guide/index.md).

## Initialize a project

Run `wtk init my-tests --app "C:/Apps/My App.exe"` to create a starter page,
smoke test, pytest configuration, and report ignore entry. Existing metadata,
configuration, and Python files are preserved. `--force` replaces starter Python
files only; it does not overwrite application settings. The generated `MainPage` in
`pages/main.py` is a VS Code walkthrough example: it targets the frontmost `Code.exe`
window and its second direct UI Automation child, without relying on the workspace title.
The smoke test and starter flow check both. For your own application, replace these example
locators with its window and controls before running `wtk doctor` and `wtk run`.

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

No example app is bundled. Native desktop tests require an interactive, unlocked Windows
session, but no external demo executable. See the
[development guide](https://github.com/MassimoNodin/wintestkit/blob/master/docs/development.md)
for desktop tests and packaging, and the
[Calculator example](https://github.com/MassimoNodin/wintestkit/tree/master/examples/calculator-tests)
for application-level scenarios.

## Resolve targets

Open Windows Calculator in Standard mode before running these commands from this directory.
For your own application, replace the project root and page targets:

```powershell
uv run wtk --root ../examples/calculator-tests highlight pages/calculator.py::CalculatorPage.one --json
uv run wtk --root ../examples/calculator-tests highlight pages/standard.py::StandardPage --duration 1000
uv run wtk --root ../examples/calculator-tests check pages/standard.py::StandardPage --json
```

`highlight` resolves immediately by default; `--timeout S` enables polling. It brings the
owning window to the foreground before drawing the outline. If Windows denies that, the
outline is still drawn. `--launch` starts
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
ancestor chain, including supported patterns. Coordinates are physical page
pixels; use `--at=-100,200` for negative coordinates. Button text is normalized
to its containing button. Points outside the configured app fail without
inspecting another process. Window and point selection options are mutually exclusive.

The suggestion engine (`wintestkit.engine.suggest`) verifies generated locators
against the selected element, prioritizing stable IDs, names, classes, scoped
ancestors, and finally positional indices. Helpers precede dependent declarations;
index suggestions are fragile if the UI order changes. When an element is globally
unique, candidate ordering selects simpler properties such as `class_name` rather
than nested container scopes.

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
and Spy notifications, as specified in `schemas/rpc.schema.json`. Ordinary
requests execute sequentially; Spy stop and shutdown bypass queued work.
Standard output is protocol-only, including when user modules print. Shutdown
and input EOF clean up Spy but leave the application open. Inspector node IDs
are runtime IDs held in a bounded 5,000-entry LRU; stale IDs return `-32005`.
