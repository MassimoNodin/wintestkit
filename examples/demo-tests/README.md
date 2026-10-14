# demo-tests

A sample WinTestKit project that tests the WPF demo app in [`../../demo`](../../demo). It is
also the reference for how to write screens and tests.

## Run it

Build the demo app once, then run the tests (Windows, interactive unlocked desktop):

```powershell
dotnet build ../../demo/DemoApp/DemoApp.csproj -c Release
uv sync
uv run pytest
```

`launch = "per-session"` starts the app once for the whole run. An autouse fixture in
`conftest.py` resets it with **File > Reset** before every test, so tests stay independent.

## Layout

| Path | What it shows |
|---|---|
| `screens/main.py` | The main window as a `Screen`: locating controls without AutomationIds (`within=`, class names) and the two ids the demo does expose. |
| `screens/dialogs.py` | A modal WPF dialog and a native message box, each on its own `Screen` with its own `Window(...)`. |
| `tests/test_login.py` | Typing, clicking, a parametrized login matrix, check boxes. |
| `tests/test_panels.py` | Duplicate "OK" buttons: `within=`, `Elements`, and the ambiguity diagnostic. |
| `tests/test_async.py` | Auto-waiting: `click()` waits for a disabled button, `expect()` waits for text. |
| `tests/test_choices.py` | Combo boxes: select by name, index or pattern. |
| `tests/test_lists.py` | Virtualized list and grid: far-away items, rows, cells, `find_row()`. |
| `tests/test_dialogs.py` | Dialogs and message boxes. |
| `tests/test_menu.py` | Menu items. |
| `tests/test_expected_failure.py` | A deliberately failing test (skipped unless asked). |

## See a failure

```powershell
$env:WTK_DEMO_FAILURES = "1"
uv run pytest tests/test_expected_failure.py
```

The failure explains what was searched, the closest elements and what differs, and saves a
window screenshot, a desktop screenshot and a UI tree dump under `wtk-report/artifacts/`:

```text
No element matches Button[name="Sign In"] in Window "WTK Demo" (closest: Button "Sign in" — name differs) (waited 1.0s)
```
