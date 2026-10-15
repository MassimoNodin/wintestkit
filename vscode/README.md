# WinTestKit for VS Code

Write, run and debug UI tests for **Windows WPF applications** in Python. WinTestKit uses
Microsoft UI Automation to find controls, so tests work against the real application without
image matching. This extension is the editor side of the
[`wintestkit`](https://pypi.org/project/wintestkit/) Python package.

```python
from wintestkit import Element, Screen, Window, expect

class MainScreen(Screen):
    window = Window(title="WTK Demo")
    username = Element(control_type="Edit", class_name="TextBox")
    sign_in = Element(control_type="Button", name="Sign in")
    status = Element(automation_id="StatusText")

def test_sign_in(app):
    main = MainScreen(app)
    main.username.type("admin")
    main.sign_in.click()
    expect(main.status).to_have_text("Welcome, admin")
```

## Features

- **Highlight and check elements from the editor.** CodeLens actions above every `Element`
  definition flash the matching control on screen or report why it can't be found (no match,
  several matches, closest candidates). **Check All Elements** verifies a whole screen at once;
  results appear in the gutter and as editor warnings.
- **Test Explorer.** Tests are discovered from your project and run with live progress,
  captured output, parameterized cases and failure details including expected/actual diffs.
  **Run Test** and **Debug Test** CodeLens appear above each test. Debugging uses the Python
  Debugger with normal breakpoints.
- **Elements view.** Browse every screen and its elements, nested by `within` containers. Jump to
  definitions, highlight or check entries inline, and see the last check result as an icon.
- **Spy.** Explore the live UI Automation tree, or press **Pick Element** and Ctrl+Click a control
  in your application. The Spy shows properties, supported patterns and a suggested locator, and
  **Add to screen…** inserts it into a screen class for you.
- **Reports.** Every run writes a self-contained HTML report with steps, screenshots and failure
  diagnostics. After a failing run, a notification opens it; **WinTestKit: Open Last Report** opens
  it any time.

## Requirements

- Windows 10 or 11 with an interactive, unlocked desktop while tests run.
- Python 3.12 or later, selected through the
  [Python extension](https://marketplace.visualstudio.com/items?itemName=ms-python.python)
  (installed automatically as a dependency).
- The `wintestkit` package in that interpreter: `pip install wintestkit` or
  `uv add --dev wintestkit`. The extension offers to install it when it is missing.
- The application under test must run at the same elevation level as VS Code.

## Quick start

1. Open a folder and select a Python interpreter.
2. Run **WinTestKit: Initialize Project** to create `pyproject.toml` settings, a starter screen
   and a smoke test. Set `[tool.wintestkit.app] path` to your application's executable.
3. Run **WinTestKit: Launch App**, open the **Spy** view and pick controls to build your screens.
4. Use the **Highlight Element** CodeLens to confirm each locator.
5. Run tests from the Test Explorer, the **Run Test** CodeLens or `wtk run` in a terminal.

WinTestKit detects every `pyproject.toml` that contains a `[tool.wintestkit]` table, including
nested projects and multi-root workspaces.

## Commands

| Command | Description |
|---|---|
| WinTestKit: Launch App / Close App | Start or close the configured application |
| WinTestKit: Open Last Report | Open the HTML report of the last run |
| WinTestKit: Check Environment (doctor) | Run `wtk doctor` in a terminal |
| WinTestKit: Initialize Project | Create a starter project without overwriting files |
| WinTestKit: Install wintestkit Package | Install the package into the selected interpreter |
| WinTestKit: Restart Server | Restart the per-project Python server |
| WinTestKit: Show Output | Show the WinTestKit log |

## Settings

| Setting | Default | Description |
|---|---|---|
| `wintestkit.pythonPath` | `""` | Python interpreter to use. Empty uses the Python extension's selection. |
| `wintestkit.codeLens.enabled` | `true` | Show Highlight/Check and Run/Debug CodeLens. |
| `wintestkit.highlight.durationMs` | `1500` | How long a highlight stays on screen (200–10000 ms). |
| `wintestkit.run.extraArgs` | `[]` | Extra arguments passed to `wtk run`. |
| `wintestkit.run.highlightActions` | `false` | Flash each element before acting during runs from VS Code. |
| `wintestkit.server.logLevel` | `"info"` | Log level of the Python server (shown in **Show Output**). |
| `wintestkit.promptDisablePytestExplorer` | `true` | Offer to disable the Python extension's pytest explorer for WinTestKit projects. |

## Troubleshooting

- **Elements are not found while tests run from CI or RDP:** UI Automation needs an unlocked,
  interactive desktop. Run **Check Environment (doctor)** for a full list of checks.
- **Tests appear twice:** the Python extension's own pytest explorer is also enabled; accept the
  prompt to disable it for this workspace, or keep both.
- **Nothing happens after installing the package:** run **Restart Server**.

See the [user guide](https://github.com/MassimoNodin/wintestkit/tree/master/docs/guide) for
locator strategies, CI setup and migrating from TestComplete.

## Development

Run `npm ci`, then `npm run build`, `npm run typecheck`, `npm run lint` and `npm test`. Use the
repository's **Run Extension** launch configuration for an Extension Development Host;
`npm run test:integration` runs the end-to-end tests against the demo application.
