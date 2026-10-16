# WinTestKit for VS Code

Write, run and debug UI tests for **Windows WPF applications** in Python. WinTestKit uses
Microsoft UI Automation to find controls, so tests work against the real application without
image matching. This extension is the editor side of the
[`wintestkit`](https://pypi.org/project/wintestkit/) Python package.

```python
from wintestkit import Element, Page, Window, expect

class MainPage(Page):
    window = Window(title="WTK Demo")
    username = Element(control_type="Edit", class_name="TextBox")
    sign_in = Element(control_type="Button", name="Sign in")
    status = Element(automation_id="StatusText")

def test_sign_in(app):
    main = MainPage(app)
    main.username.type("admin")
    main.sign_in.click()
    expect(main.status).to_have_text("Welcome, admin")
```

## Features

- **Current Setup and YAML configuration.** See the current application icon/name above
  the Explorer and use its gear to open a custom settings editor. **This machine** shows
  only **Application executable** under **Start the application**, with **Browse…**. Other
  settings are under collapsed **Advanced options** (**Application**, **Test runs**,
  **Debugging**). Shared defaults live in `wintestkit.yaml`; the executable and other
  machine-specific values stay in Git-ignored `wintestkit.local.yaml`. Save to reload the
  backend, or open raw YAML for settings the form does not show.

- **Highlight and check elements from the editor.** CodeLens actions above every `Element`
  definition flash the matching control on screen or report why it can't be found (no match,
  several matches, closest candidates). **Check All Elements** verifies a whole page at once;
  results appear in the gutter and as editor warnings.
- **Test Explorer.** Tests are discovered from your project and run with live progress,
  captured output, parameterized cases and failure details including expected/actual diffs.
  Run and Debug profiles are in the Testing view; debugging uses the Python Debugger with
  normal breakpoints.
- **Explorer.** One view, with **Spy** below it, and a **Page Tree | Flows** control that
  remembers the selected tab. Browse pages with their child pages and elements nested by `within`
  containers, and reusable flow functions grouped by file. Jump to definitions,
  highlight/check page elements, or run flows that only need `app` inline. Run and debug tests from VS Code's Testing view.
- **Spy.** Explore the live UI Automation tree. **Pick element** and **Refresh objects** stay in
  the Spy toolbar. Hold **Ctrl** and click a control, or press **Esc** to cancel. The Spy shows
  properties, supported patterns and a suggested locator, and **Add to page…** inserts it into a
  page class for you.
- **Reports.** Every run writes a self-contained HTML report with steps, screenshots and failure
  diagnostics. After a failing run, a notification opens it; **WinTestKit: Open Last Report** opens
  it any time.

### Spy object browser

The Spy uses control-type icons, chevrons and dotted branch guides to make the live
hierarchy easier to navigate. A wide view places the object tree beside the inspector;
a narrow sidebar stacks them vertically. Drag the divider, or focus it and use the
arrow keys, to resize the panes. Colours follow your VS Code theme.

Use **Filter loaded objects** to search names, control types, classes and automation
IDs. Filtering retains matching ancestors but only searches controls already loaded;
expand branches to load more. **Collapse all** clears the filter and closes branches.
While the application is running, a button at the right end of the toolbar switches between
**Show Other Apps** (append other desktop windows) and **Show Only Selected App** (the current
application's windows only, the default). The choice is remembered. **Pick element** and **Refresh objects**
stay in this toolbar.

The inspector groups properties into Identity, State, Geometry and Automation, with
raw values under **All properties** and locator quality beside **Suggested locator**.
Selection first reads only the essential identity, state and geometry information and displays
it before locator generation finishes. Open **All properties** and click **Load all properties**
to fetch the complete property list and supported patterns. These expensive reads are not
performed on ordinary selection; ancestor collection is reserved for revealing picked objects.

Root windows show their application's executable icon when Windows permits access
to the process, with control-type icons as a fallback. Icons load separately so the
object tree remains usable while they are retrieved. Loading indicators show the
current phases for connection, refresh, icon loading, expansion, inspection, picking
and application launch inside the existing pane headers, without shifting either
pane. Header bars count completed phases and are indeterminate before the first
phase completes. Expanding controls also show an inline loading indicator. Empty
panes explain missing projects, stopped apps, missing windows, filters with no
matches, unselected objects and loading or inspection failures. Existing content
stays visible during refresh; selecting another object replaces stale properties
with an in-place loading state. No estimated percentages are used for UI Automation calls.

Selecting an object or pressing **Highlight** asks the Python backend to bring the
control's owning application window to the foreground before drawing its outline.
Child controls raise their containing window; minimized windows are restored. This
does not click the control or explicitly change its keyboard focus. Activation is
best-effort: if Windows denies it, highlighting still proceeds. CodeLens **Highlight**,
`wtk highlight` and `Element.highlight()` use the same foreground step. This requires the
updated Python package as well as the extension; after updating, run
**WinTestKit: Restart Server**.

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
2. Run **WinTestKit: Initialize Project** to create `pyproject.toml` settings, a starter page
   and a smoke test. Set `[tool.wintestkit.app] path` to your application's executable.
3. Run **WinTestKit: Launch App**, open the **Spy** view and pick controls to build your pages.
4. Use the **Highlight Element** CodeLens to confirm each locator.
5. Run tests from the Test Explorer or `wtk run` in a terminal.

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
repository's **Run Extension** launch configuration for an Extension Development Host.
No example application is bundled. The end-to-end suite checks static discovery and CodeLens
against the Calculator example without launching an app; see the repository's
[development guide](https://github.com/MassimoNodin/wintestkit/blob/master/docs/development.md).
