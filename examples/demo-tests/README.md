# Example test code

This project preserves page models and pytest examples originally written for the
**WTK Demo** application. The application source and binaries are no longer bundled.
These tests are a reference, not an out-of-the-box runnable sample.

## Adapt the examples to your application

Start with the [installation and first-test guide](../../README.md), then copy the patterns
you need from this project. Update the executable path, window titles, element locators,
test data, assertions and reset fixture for your own application. Merely changing the
executable path will not make these app-specific tests work against an unrelated app.

The `main` fixture in `conftest.py` binds the page to the app. Its autouse reset fixture
uses **File > Reset** before each test; replace that with your application's reset flow
or choose a fresh process per test.

## Run against an external legacy fixture

If you already have a compatible WTK Demo executable outside the repository:

```powershell
$env:WTK_APP_PATH = "C:\ExternalFixtures\DemoApp.exe"
uv sync --locked
uv run wtk run
```

Run these commands from this directory on an interactive, unlocked Windows desktop.
The executable must implement the expected WTK Demo controls and behavior.

## Layout

| Path | What it shows |
|---|---|
| `pages/main.py` | The main window as a `Page`: locating controls without AutomationIds (`within=`, class names) and the two ids the demo does expose. |
| `pages/dialogs.py` | A modal WPF dialog and a native message box, each on its own `Page` with its own `Window(...)`. |
| `tests/test_login.py` | Typing, clicking, a parametrized login matrix, check boxes. |
| `tests/test_panels.py` | Duplicate "OK" buttons: `within=`, `Elements`, and the ambiguity diagnostic. |
| `tests/test_async.py` | Auto-waiting: `click()` waits for a disabled button, `expect()` waits for text. |
| `tests/test_choices.py` | Combo boxes: select by name, index or pattern. |
| `tests/test_lists.py` | Virtualized list and grid: far-away items, rows, cells, `find_row()`. |
| `tests/test_dialogs.py` | Dialogs and message boxes. |
| `tests/test_menu.py` | Menu items. |
| `tests/test_expected_failure.py` | A deliberately failing test (skipped unless asked). |

## See a deliberate failure

With the compatible external application configured:

```powershell
$env:WTK_DEMO_FAILURES = "1"
uv run wtk run tests/test_expected_failure.py
```

The report explains what was searched, the closest elements and what differs, and captures
screenshots and a UI tree dump under `wtk-report/artifacts/` when possible.
