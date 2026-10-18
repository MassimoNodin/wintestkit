# VS Code

The **WinTestKit** extension (`wintestkit.wintestkit`) adds editor actions, Test Explorer
integration, an **Explorer** for the Page Tree and Flows, and a **Spy** below it. It needs the
[Python extension](https://marketplace.visualstudio.com/items?itemName=ms-python.python) and the
`wintestkit` package in the selected interpreter. When the package is missing, the extension
offers to install it (**WinTestKit: Install wintestkit Package**).

The extension starts one Python server per project in the background. The status bar shows
whether the application is running; click it for **Launch App**, **Close App**, **Restart Server**,
**Open Last Report**, **Check Environment** and **Show Output**.

## Test Target

The **Test Target** section at the top of the sidebar is a row of tiles for the application under
test. Its title bar shows the status (**Running**, **Stopped**, **Starting…**, **Failed**) and the gear
that opens the settings.

- **Application** (icon and name, process IDs while running). Click it to browse for an executable
  to launch, attach to a running app that has a window, or open the settings. The choice is saved
  to `wintestkit.local.yaml`.
- **Mode** (**Attach** or **Spawn**). **Attach** uses the app that is already running and never
  closes it; **Spawn** starts the app for the tests (closing a running copy first) and closes it
  when they finish. Click to switch.
- **Project**. The workspace folder and project name; with several WinTestKit projects, click to
  switch between them.
- **Launch**, or **Restart** and **Close** while it runs. For a process-only attach setup the section
  says it is waiting for the app: start it yourself, then **Check again**.

While the app starts, a panel shows each stage (process started, app responding, main window shown)
and how long it has taken against the startup timeout. If the launch fails, the reason stays under
the tiles with **Try again** and a **Show output** link. The state updates automatically while VS Code
is focused, and app actions refresh the visible Spy.

## CodeLens

- Above every `Element` and `Window`: **Highlight** brings the control's owning window to the
  foreground, then draws a frame around it. If Windows denies that, the outline is still drawn.
  When the frame disappears, focus goes back to the window that had it (the VS Code window you
  clicked in), unless you switched to another window meanwhile. `wtk highlight` and
  `Element.highlight()` use the same foreground step but leave focus on the highlighted window. **Check** resolves
  the control and shows the result in the gutter. A failed check becomes an editor warning with
  the full diagnostic (closest candidates and what differs).
- Above every `Page`: **Check all elements in this class** checks the whole page.
- Above every runnable flow (one whose only required parameter is `app`): **Run flow** runs it
  against the running application and shows **Running flow…**, **Flow passed** or **Flow failed**.
  If the application isn't running, you get an error instead of a launch prompt. Flows can take
  minutes; the request waits up to ten minutes.

Highlight and Check show progress and their latest result directly in the CodeLens: **Highlighting…** /
**Checking…**, then **Highlighted** / **Check: Found**, **Not found**, **multiple matches**, or **Failed**.
Hover over a result for details; click it again to retry the same action. Highlight and Check keep
separate results, and Check All Elements updates each element's Check result. Results describe the
last attempt, not live app state; editing the declaration or refreshing discovery clears them.

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

The Debug profile in the Test Explorer runs the test under the
[Python Debugger](https://marketplace.visualstudio.com/items?itemName=ms-python.debugpy). Normal
breakpoints work in tests, pages and fixtures. Debug runs raise the default auto-wait to one
hour so a test paused at a breakpoint doesn't time out. Debug runs don't write a
report.

### Duplicate pytest explorer

The Python extension can also discover your tests with pytest, which shows every test twice.
WinTestKit offers to disable the Python extension's pytest discovery for the workspace; keeping
both is supported. Turn the prompt off with `wintestkit.promptDisablePytestExplorer`.

## Explorer

**Test Target**, **Explorer** and **Spy** stack in the WinTestKit activity bar, with Spy
below Explorer. Explorer is a single view. A **Page Tree | Flows** control at the top
switches the list, and the selected tab is remembered.

- **Page Tree** shows only pages that are not children of another page at the root,
  with spacing and dividers between root trees. Expand a page to reveal its elements
  and child pages; shared child pages appear under each parent, not again at the root.
  Elements remain nested under their `within` containers.
  Inline actions highlight/check elements or check a whole page; icons show the last check result.
- **Flows** lists public, module-level Python functions (including async functions) under
  `flows/` directories, grouped by source file. Private helpers and class methods are omitted.
  Flows are ordinary Python helpers, not tests. A flow whose only required parameter is `app`
  (such as `tour_calculator(app)`) has a **Run Flow** button. It calls the flow with the running
  application, shows a spinner while it runs and a pass or fail icon afterwards, and reports an
  exception as a failed run. Flows that need other arguments have no Run button.

Click an entry to open its definition. **Refresh** on the Explorer title reloads discovery.
Entries are grouped by project in multi-project workspaces. Discovery updates while you type
without importing or running your code. Run and debug tests from VS Code's Testing view (Test Explorer).

## Spy

The **Spy** view, below Explorer, explores the live UI Automation tree of the application.

- Expand windows and controls lazily. Selecting a control draws an outline around it, above every
  window. The pin button after **Collapse all** (off by default; setting
  `wintestkit.spy.bringWindowToFront`) also brings the control's window to the front, without
  taking keyboard focus from VS Code. The same switch applies to the **Highlight** button.
- The toolbar starts with **Pick element**, **Refresh objects**, **Collapse all** and the pin button. **Pick
  element** (or `wtk spy` in a terminal): hold **Ctrl** and click a control in the application.
  **Esc** cancels. **Refresh objects** reloads the tree. **Pick element** and **Refresh objects**
  stay in the Spy toolbar.
- While the application is running, a button at the right end of the toolbar switches the tree
  scope. It reads **Show Other Apps** by default, when the tree lists only the current
  application's windows. Click it to append other desktop windows after those; it then reads
  **Show Only Selected App**. The choice is remembered.
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

The **Test Target** section, above the Explorer, shows the application name and executable icon (with a
generic fallback). Use the gear to edit its settings. In multi-project workspaces,
it follows the active source file.

The custom YAML editor offers **This machine** and **Shared project** tabs. On **This
machine**, **Start the application** shows only **Application executable**, with **Browse…**;
clearing it removes the override. On **Shared project**, that section explains the executable
lives in the ignored local file. Everything else (process name, arguments, working directory,
lifecycle, timeouts, input mode, screenshots, reports, import paths and debugging aids)
sits under the collapsed **Advanced options** section, grouped as **Application**, **Test runs**
and **Debugging**, where override checkboxes control inheritance. Save with the toolbar or
Ctrl+S; **Open YAML** switches to raw text for settings not shown in the form. Comments and
other settings are preserved. Saving reloads the backend and refreshes the Test Target section. Invalid
settings show actionable errors.

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
