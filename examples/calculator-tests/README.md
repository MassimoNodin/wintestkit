# Windows Calculator tests

A small WinTestKit project showing page inheritance, reusable navigation flows,
pytest fixtures and parametrized scenarios. No application source or binaries are included.

## Run

Use Windows with an interactive, unlocked desktop, Python 3.12+ and uv.
Install Windows Calculator if necessary and keep at most one Calculator window open.
The fixtures attach to `CalculatorApp.exe` if it is already running; otherwise they
start it using `calc.exe` and close that instance at the end of the test session.
Use an English-language Calculator because navigation headings and result text are asserted
in English. Control identifiers may need adapting for other Calculator versions.

From the repository root:

```powershell
cd examples/calculator-tests
uv sync --locked
uv run wtk doctor
uv run wtk run
```

Each test switches to Standard mode and clears the display before running.
Do not interact with Calculator while tests run. To collect tests without opening Calculator:

```powershell
uv run pytest --collect-only
```

## Structure

- `pages/calculator.py`: shared window, navigation controls and arithmetic actions.
- `pages/standard.py`, `pages/scientific.py`, `pages/programmer.py`: mode-specific pages.
- `flows/navigation.py`: ordinary Python helpers that switch pages or tour all three modes.
- `conftest.py`: fixtures that establish a known starting state.
- `tests/`: arithmetic and navigation scenarios.

The VS Code **Run Extension** configuration opens this project. For normal development,
open this folder in VS Code and select its `.venv` interpreter after running `uv sync`.
