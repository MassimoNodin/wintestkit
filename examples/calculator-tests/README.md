# Windows Calculator tests

A small WinTestKit project showing page inheritance, reusable navigation flows,
pytest fixtures and parametrized scenarios. No application source or binaries are included.

## Run

Use Windows with an interactive, unlocked desktop, Python 3.12+ and uv.
Install Windows Calculator if necessary and keep at most one Calculator window open.
The project's `launch` setting decides how Calculator is obtained: with `attach` (the default here)
the tests use a Calculator you have already opened; with `per-test` WinTestKit starts it
using the executable from `app.path` (set `C:\Windows\System32\calc.exe` in
`wintestkit.local.yaml`), closes any copy that is already open first, and closes the one it
started when each test finishes. In VS Code, use the **Mode** tile of the Test Target view.
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

The suite is the reference implementation of the agent skill in `.claude/skills/wintestkit-tests`
(canonical copy: `skills/wintestkit-tests` in the repository). Read `SKILL.md` for the rules;
this is how they look here:

```text
pages/
  calculator.py          CalculatorWindow (the one Page, declares the window) and
                         CalculatorModePage (mounts the keypad components, intent methods)
  standard.py            StandardPage, ScientificPage, ProgrammerPage: one page per mode,
  scientific.py          inheriting CalculatorModePage
  programmer.py
  components/
    navigation.py        NavigationPane: root = NavView; open_standard/open_scientific/open_programmer
    number_pad.py        NumberPad: digits and enter(number)
    operators.py         StandardOperators: plus, minus, ..., equals
    display_controls.py  DisplayControls: clear, backspace
    radix.py             RadixSelection: Programmer's hex/decimal/octal/binary selector
flows/navigation.py      open_page(app, ScientificPage), tour_calculator(app)
conftest.py              session app fixture, `standard` fixture, autouse reset
tests/                   intent calls (`standard.add_one_to(n)`, `open_page`) and `expect(...)`
```

- Elements are typed (`Button`, `RadioButton`, `Text`); every box that could move is a component
  with a `root`, mounted once per page (`navigation = NavigationPane()`).
- Tests never act on elements and never use `getattr`; they use intent methods and flows, and reach
  into element paths only inside `expect(...)`.
- Locators were confirmed with `uv run wtk inspect --depth 8` against Windows Calculator. Operator
  and display-control groups have an AutomationId in Standard and Scientific but only a name in
  Programmer, so their roots use `control_type="Group"` plus `name`.
- `uv run wtk check pages/standard.py` (and `scientific.py`, `programmer.py` with that mode
  open) resolves every element; the three navigation items exist only while the navigation pane is
  open; with the pane closed `wtk check` reports them as `✗` (broken/moved, exit 1) because they are
  not visible in that state, so open it first to check them. `uv run wtk discover` lists the pages, components and
  element types without importing the code.
- `[tool.pyright]` in `pyproject.toml` type-checks the suite in strict mode.

The VS Code **Run Extension** configuration opens this project. For normal development,
open this folder in VS Code and select its `.venv` interpreter after running `uv sync`.
