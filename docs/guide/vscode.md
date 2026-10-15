# VS Code

The **WinTestKit** extension (`wintestkit.wintestkit`) adds editor actions, Test Explorer
integration, separate Pages, Flows and Tests sections, and a Spy. It needs the
[Python extension](https://marketplace.visualstudio.com/items?itemName=ms-python.python) and the
`wintestkit` package in the selected interpreter. When the package is missing, the extension
offers to install it (**WinTestKit: Install wintestkit Package**).

The extension starts one Python server per project in the background. The status bar shows
whether the application is running; click it for **Launch App**, **Close App**, **Restart Server**,
**Open Last Report**, **Check Environment** and **Show Output**.

## CodeLens

- Above every `Element` and `Window`: **Highlight** draws a frame around the control in the running
  application; **Check** resolves it and shows the result in the gutter. A failed check becomes an
  editor warning with the full diagnostic (closest candidates and what differs).
- Above every `Page`: **Check All Elements** checks the whole page.
- Above every test: **Run Test** and **Debug Test**.

If the application isn't running, **Highlight** offers to launch it. Turn the CodeLens off with
`wintestkit.codeLens.enabled`.

## Test Explorer

WinTestKit tests appear in the Testing view, grouped by file, with parameterized cases as
children. Runs stream progress, captured output and failures live; assertion mismatches show an
expected/actual diff. Cancelling a run stops the whole test process tree. Runs of the same project
are queued.

After a run with failures, a notification offers **Open Report** (the HTML report in your browser)
and **Show Test Results**. **WinTestKit: Open Last Report** opens the latest report later.

### Debugging

**Debug Test** (or the Debug profile in the Test Explorer) runs the test under the
[Python Debugger](https://marketplace.visualstudio.com/items?itemName=ms-python.debugpy). Normal
breakpoints work in tests, pages and fixtures. Debug runs raise the default auto-wait to one
hour so a test paused at a breakpoint doesn't time out. Debug runs don't write a
report.

### Duplicate pytest explorer

The Python extension can also discover your tests with pytest, which shows every test twice.
WinTestKit offers to disable the Python extension's pytest discovery for the workspace; keeping
both is supported. Turn the prompt off with `wintestkit.promptDisablePytestExplorer`.

## Pages, Flows and Tests

The WinTestKit activity bar has three independently collapsible sections:

- **Pages** lists page classes, with elements nested under their `within` containers.
  Inline actions highlight/check elements or check a whole page; icons show the last check result.
- **Flows** lists public, module-level Python functions (including async functions) under
  `flows/` directories, grouped by source file. Private helpers and class methods are omitted.
  Flows are ordinary Python helpers, not independently runnable tests.
- **Tests** lists pytest tests by file and class, with inline **Run Tests** and **Debug Tests**
  actions for a test, class, file or project. These use the same runner as the Test Explorer.

Click an entry to open its definition. Each section has its own refresh action and groups
entries by project in multi-project workspaces. Discovery updates while you type without
importing or running your code. The built-in Test Explorer remains available.

## Spy

The **Spy** view explores the live UI Automation tree of the application.

- Expand windows and controls lazily; selecting a control highlights it in the application.
- **Pick Element** (or `wtk spy` in a terminal): hold **Ctrl** and click a control in the
  application. **Esc** cancels.
- The details show the control's properties, supported patterns and a **suggested locator** that
  is marked unique, or not unique with the number of matches.
- **Add to page…** inserts the locator into an existing page or a new page file, adds
  imports, reuses an existing element as `within=` when it matches the container, and reveals the
  new line. The change stays unsaved so you can review it.

## Projects

Every folder with `wintestkit.yaml` or a `pyproject.toml` containing `[tool.wintestkit]` is a project, including
nested folders and multi-root workspaces. Each project has its own server, tests and elements.
**WinTestKit: Initialize Project** creates the starter files described in
[Getting started](getting-started.md).

The inspector loads essential properties first. To read the complete property list and
supported patterns, expand **All properties** and click **Load all properties**. Its loading
state stays inside the inspector, and you can retry if the request fails. Locator generation
does not block the basic property display.

## Project Configuration

**Current Setup**, above Pages, shows the application name and executable icon (with a
generic fallback). Click the row or gear to configure it. In multi-project workspaces,
it follows the active source file.

The custom YAML editor offers **This machine** and **Shared project** tabs. Override
checkboxes control inheritance. Save with the toolbar or Ctrl+S; **Open YAML** switches
to raw text for advanced settings. Comments and other settings are preserved. Saving
reloads the backend and refreshes Current Setup. Invalid settings show actionable errors.

Executable paths, working directories, arguments and viewing preferences are edited in
ignored `wintestkit.local.yaml`; shareable defaults go in `wintestkit.yaml`. Missing files
and ignore rules are created without replacing existing configuration. Files already
tracked by Git are not automatically untracked. Environment and CLI options still override
file settings when running tests. See [configuration](running-tests.md#configuration).

## Extension Settings

| Setting | Default | Description |
|---|---|---|
| `wintestkit.pythonPath` | `""` | Python interpreter to use. Empty uses the Python extension's selection |
| `wintestkit.codeLens.enabled` | `true` | Show the CodeLens actions |
| `wintestkit.highlight.durationMs` | `1500` | How long a highlight stays on screen |
| `wintestkit.run.extraArgs` | `[]` | Extra arguments passed to `wtk run` |
| `wintestkit.run.highlightActions` | `false` | Flash each element before acting during runs from VS Code |
| `wintestkit.server.logLevel` | `"info"` | Log level of the Python server |
| `wintestkit.promptDisablePytestExplorer` | `true` | Offer to disable the Python extension's pytest explorer |

Logs are in the **WinTestKit** output channel (**WinTestKit: Show Output**).
