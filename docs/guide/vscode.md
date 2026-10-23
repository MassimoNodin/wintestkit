# VS Code

The **WinTestKit** extension (`wintestkit.wintestkit`) adds editor actions, Test Explorer
integration, an **Explorer** for the Page Tree and Flows, and a **Spy** below it. It needs the
[Python extension](https://marketplace.visualstudio.com/items?itemName=ms-python.python) and the
`wintestkit` package in the selected interpreter. A guided setup in the sidebar walks you through
choosing the interpreter, installing the package and creating a project (see [Guided setup](#guided-setup)).

The extension starts one Python server per project in the background. The status bar shows
whether the application is running; click it for **Launch App**, **Close App**, **Restart Server**,
**Open Last Report**, **Check Environment** and **Show Output**.

## Test Target

### Package compatibility

Extension 0.1.1 requires a stable `wintestkit>=0.1.1,<0.2.0` Python package and RPC
protocol 1. The package version is checked before launching the server and both values
are checked during initialization. Unsupported versions stop the connection rather than
retrying it repeatedly. The message identifies the interpreter, installed version,
supported range, and recommended fix.

Use **Update Extension** for a newer backend, **Install Compatible Package** to repair the
selected environment (this may downgrade a newer package), or **Choose Interpreter** to
keep a different environment untouched. The installer verifies the resulting version and
restarts affected servers. After repairing a package manually, use **Restart Server**.
Development wheels obey the same policy; prerelease and development versions are not supported.

### Application controls

The **Test Target** section at the top of the sidebar is a row of tiles for the application under
test. Its title bar shows the status (**Running**, **Stopped**, **Starting…**, **Failed**) and the gear
that opens the settings.

- **Application** (icon and name, process IDs while running). Click it to browse for an executable
  to launch, attach to a running app that has a window, or open the settings. The choice is saved
  to `wintestkit.local.yaml`.
- **Mode** (**Attach** or **Launch for tests**). **Attach** uses the app that is already running and never
  closes it; **Launch for tests** starts the app for the tests (closing a running copy first) and closes it
  when they finish. Click to switch.
- **Python interpreter** (first tile, with the package strip under it). Click to choose another interpreter.
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

After a run with failures the report opens in an editor panel, or a notification offers **Open Report**
and **Show Test Results**. **WinTestKit: Open Last Report** opens the latest report later. The panel is
drawn straight from the run's `results.json`, so runs from the Testing view write no `index.html`.
Every run started from the Testing view keeps its own report in `<report dir>/runs/<run time>/`, so older
runs in the Test Results panel still have theirs. Hover over a WinTestKit test row and click
**Open Test Report for This Run** to open that run's report with the clicked test selected.
The Testing sidebar also offers **Open in Report** on hover when a stored report contains the test. It opens the newest retained report
containing that test, even when a newer partial run did not include it. On a file or test group,
it selects a failing test in that group, or the first matching test when none failed.
**WinTestKit: Open Report from a Previous Run…** lists stored runs, passing runs included.
A run's report is deleted when VS Code clears that run. **Clear All Results** also deletes retained
reports and their screenshots/replay frames after an editor reload, closes the deleted report's panel,
and removes its report actions and cached totals. Active runs and other workspaces' reports are preserved.
Terminal-generated reports and exported copies outside those run folders are not deleted. The oldest reports are deleted beyond
`wintestkit.keepRunReports` (default 20). (UI tree diffs, which keep their baselines in the report folder,
need a run from the terminal.)
**Export HTML** in the panel's header (or **WinTestKit: Export Last Report as HTML**) saves the report
as one self-contained HTML file, by default into the report folder where its screenshots and replay frames
are found; if you save it elsewhere, keep or copy the `artifacts` folder with it.
The Test Target section shows the last run's time and totals as a notice with a **View the Report**
link. Close it with the **×**; it also goes when VS Code clears that run's results or the window is
reloaded. Runs from the Testing view record a test replay by default (`--replay on`) unless the project,
the `WTK_REPLAY` environment variable or `wintestkit.run.extraArgs` choose a replay mode; set
`replay: off` in the project settings to turn this off. **Run with recording** keeps only the
replays of failed tests. All new report images use lossless WebP, including replay frames,
failure screenshots and step screenshots; existing PNG reports remain readable.
Failed-test reports open with the failed test's evidence, including
the Test Replay when frames were captured. The report follows the VS Code theme until you pick light or
dark with the button in its header; that choice is remembered across reloads and updates.

### Debugging

The **Debug (no report)** profile in the Test Explorer runs the test under the
[Python Debugger](https://marketplace.visualstudio.com/items?itemName=ms-python.debugpy). Normal
breakpoints work in tests, pages and fixtures. Debug runs raise the default auto-wait to one
hour so a test paused at a breakpoint doesn't time out. Debug runs don't write a
report.

### Duplicate pytest explorer

The Python extension can also discover your tests with pytest, which shows every test twice.
WinTestKit offers to disable the Python extension's pytest discovery for the workspace; keeping
both is supported. Turn the prompt off with `wintestkit.promptDisablePytestExplorer`.

## Explorer

**Test Target** and **Pages & Flows** share one WinTestKit sidebar view. Test Target
keeps at least 120px and Pages & Flows at least 160px; each section scrolls its own
content, and the sidebar scrolls when it is too short for both minimums.
**Spy** opens separately in the **WinTestKit Spy** bottom panel.
A **Page Tree | Flows** control switches the list, and the selected tab is remembered.

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

The optional Spy tutorial is a read-only walkthrough. It expands the current VS Code
window and selects its second direct child: the named content pane. Objects and Selected
object stay fixed while the guide is open. Hover effects, tooltips, scrolling, and tutorial
navigation remain available, but clicks and keyboard actions on Spy controls do nothing.
Normal interaction returns when you finish, close, or skip the tutorial.

Reloading the extension during the optional walkthrough restores it paused rather than replaying
blocking UI. Resume it explicitly from the setup guide. Spy never dims itself solely because
another view owns a setup step without a local tutorial callout.

Initialization keeps `pages/main.py` and `MainPage`. Its example window targets the
frontmost `Code.exe` window, and `content = Element(depth=1, index=1)` identifies the second
direct child without using a workspace title. This is a real definition shown under
**Defined in pages**, not tutorial-only display data. Existing page files are not overwritten;
adapt the example locators when testing a different application. If the VS Code window or
its expected content pane cannot be identified, the guide explains why instead of choosing
another object.

The **Spy** view, below Explorer, explores the live UI Automation tree of the application.

- Expand windows and controls lazily. Selecting a control inspects it without highlighting.
  Use the **Highlight** button in the top-right corner to draw its outline above every
  window. The pin button after **Collapse all** (off by default; setting
  `wintestkit.spy.bringWindowToFront`) also brings the control's window to the front, without
  taking keyboard focus from VS Code when using **Highlight**.
- The toolbar starts with **Pick element**, **Refresh objects**, **Collapse all** and the pin button. **Pick
  element** (or `wtk spy` in a terminal): hold **Ctrl** and click a control in the application.
  **Esc** cancels. **Refresh objects** reloads the tree. **Pick element** and **Refresh objects**
  stay in the Spy toolbar.
- While the application is running, a button at the right end of the toolbar switches the tree
  scope. It reads **Show Other Apps** by default, when the tree lists only the current
  application's windows. Click it to append other desktop windows after those; it then reads
  **Show Only Selected App**. The choice is remembered.
- The details show the control's properties and supported patterns. The **suggested locator** is
  made only when you press **Generate suggested locator**, because it searches the whole window
  for each candidate and can take 20 seconds or more in a large application. A spinner shows
  while it runs, during which Spy cannot do anything else. The result is marked unique, or not
  unique with the number of matches. If it fails, the button changes to **Try again**.
- **All properties** is one list, sorted alphabetically by name. A property that holds nested
  values, such as `RuntimeId`, `BoundingRectangle` or an element list like `ControllerFor`,
  shows an arrow and a count; click the arrow to open them in place. Nested rows are indented,
  tinted and marked with an arrow, and hovering a row shows its full path (for example
  `ControllerFor › 0 › BoundingRectangle`). Nesting can go several levels deep: a list of
  elements, each element, and the arrays inside it. Opening is remembered only for the
  selected object. These are external UI Automation values, not arbitrary .NET members: opaque
  CLR properties such as WPF `BorderThickness` or brush internals require application-side
  support and are not reflected.
- To always see a property, click the pin beside it in **All properties**. Pinned properties
  appear in a **Pinned** group for every object you select, in the order you pinned them; click
  the pin again, in either list, to remove one. The list is the user setting
  `wintestkit.spy.shownProperties`: it lives in your VS Code user settings, applies to every
  project, and is never written to a project or its git repository. At most 64 properties can be
  pinned.
- Spy keeps your selection through a reload. After **Refresh objects**, a server restart, or
  reloading VS Code, it expands the tree down to the object you had selected and selects it
  again. It finds the object by what it is, not by an id that changes on restart: the type,
  automation id, name and class of each object on its route from the window, plus its position
  among its siblings. It will not guess: if several objects fit equally well, or the object has
  closed or changed, a VS Code notification says it could not find it, nothing is selected, and
  the selection is forgotten so the message is not repeated. Changing **Show Other Apps** is not
  a reload and clears the selection as before. The remembered selection is kept per workspace in
  VS Code's own storage, never in a project or its git repository.
- The **Preview** section of the properties shows the selected object. By default it shows
  just the element; **In context** switches to its whole window with the object outlined in red.
  Both fit the same fixed-size frame, however large or small the image, and the choice stays
  while you select other objects. It is a live capture taken when you select the object; the
  window is rendered without being brought forward. Click the image, or the button beside the
  toggle, to open the current view in VS Code’s built-in image viewer for zooming and panning;
  it is the only time an image is written to disk (see below). There is no image
  when the object has no on-screen rectangle or its window is minimized or cannot be rendered,
  and the section says why. Opening an image saves it to a private temporary folder, deletes it
  when its editor tab closes and removes the rest when VS Code shuts down; the viewer shows the
  capture at the size sent (at most 1600 px on its longest edge). Live previews need `wintestkit` 0.1.1 or newer in the project's
  environment. Unlike the images saved by tests, a live preview is not screened for sensitive
  controls, so it can show whatever the window shows.
- Selecting a saved single element in **Pages & Flows** shows the same section from the images
  its last test saved: the element crop and the outlined window, with the same toggle. The
  timestamp identifies a saved test lookup, not a live screenshot. This works without the
  application or automation server running. Use Spy's **Refresh objects** button to return to
  live inspection (or the active tutorial). See
  [Last-successful element images](running-tests.md#last-successful-element-images) for
  storage, portability, and privacy controls.
- Refresh keeps direct-child loading lazy and coalesces overlapping requests. If a control
  disappears during enumeration, surviving objects remain visible with an incomplete-result
  warning; refresh again when the application has settled.
- **Add to page…** inserts the locator into an existing page or a new page file, adds
  imports, reuses an existing element as `within=` when it matches the container, and reveals the
  new line. The change stays unsaved so you can review it.

## Projects

Every folder with `wintestkit.yaml` or a `pyproject.toml` containing `[tool.wintestkit]` is a project, including
nested folders and multi-root workspaces. Each project has its own server, tests and elements.
The guided setup creates the starter files described in
[Getting started](getting-started.md).

The inspector loads essential properties first. To read the complete property list and
supported patterns, click **Load all properties** in the **All properties** section. Its loading
state stays inside the inspector, and you can retry if the request fails. Locator generation
does not block the basic property display.

## Project Configuration

The **Test Target** section, above the Explorer, shows the application name and executable icon (with a
generic fallback). Use the gear to edit its settings. In multi-project workspaces,
it follows the active source file.
Its first tile is the **Python interpreter** the tests run with (its environment name, such as `.venv`,
and Python version), with a strip under it that says whether `wintestkit` is installed there: a green
version when it is, a red **Install** button when it is not, and an **Update to …** button when the
installed package is older than the one this extension expects. Click the tile to choose another
interpreter, the strip to install or update. If `wintestkit.pythonPath` is set, the tile offers to stop
overriding it.

### Guided setup

WinTestKit does nothing in a workspace until you enable it there. Until then the WinTestKit sidebar is a
single **Enable for this workspace** button: no projects are read, no server starts and no checks run.
Pressing it starts the guided setup.

The guide is built into the sidebar. Each required step lights the part of Test Target it is about,
dulls everything else (including Pages & Flows and Spy), and shows instructions directly below the
button group. Use the real controls above the instructions rather than duplicate tutorial buttons.
Before a project exists, only the interpreter and **Initialize project** tiles appear. After
initialization, the application, launch mode and launch controls appear. Background check updates
preserve your scroll position:

Your first introduction always visits all seven steps in order, even when an interpreter, package
or project is already configured. A healthy step explains what is already ready; use its **Next**
arrow to continue. An unfinished step must be fixed using the real UI control before **Next** is
available. Checks never advance the introduction on their own, and your place is remembered when
you close the guide or reload VS Code. **Skip tutorial** remains an explicit opt-out.

1. **Choose a Python interpreter**: the interpreter tile.
2. **Install WinTestKit** into it: only the package strip is highlighted. Click **Install** on that
   strip; the callout has no duplicate install button. Installation runs in the background with progress
   on the strip, and the guide checks again when it finishes. If it fails, click **Try again** on the strip.
3. **Check this machine**: explains the environment checks (the same checks as `wtk doctor`) and
   confirms when the machine and installation are ready.
4. **Create the test project**: use **Initialize project** if one does not exist; it adds pages, flows
   and a smoke test without overwriting anything. Existing projects still get an introduction to this step.
5. **Choose the application**: the application tile.
6. **Launch mode**: click the mode tile and select how the application should start.
7. **Start the application**: the launch tile.

After that you can **Continue to extra features**. WinTestKit opens **WinTestKit Spy** in the bottom
panel and moves the optional tutorial there as a short card that floats over the panel beside the
part it explains. That part is lit, the rest of the panel is dulled, and an arrow points at it.
Matching handoff arrows link the original sidebar callout with the tutorial; **Show tutorial in
bottom panel** reveals it again if you switch panel tabs. The sidebar and Spy stay usable throughout
the extras, so you can try the lit control as you read.
The tutorial introduces Spy, picking controls, browsing objects and toolbar tools, inspecting
properties, copying locators and adding them to pages, finding existing definitions, organizing
pages and flows, and running tests and reviewing reports. **Back** and **Next** navigate without
changing the project; the first **Back** returns to the sidebar completion card. **Finish** closes
the tutorial. **Skip tutorial** dismisses it without disabling WinTestKit. Return to the sidebar
after running a test to see its result and report link in Test Target. Alternatively,
**Close introduction**. **‹** goes back one step without undoing anything and **›** returns; **✕**
closes the guide, and while something required is still missing the sidebar shows an interpreter tile and
a **Resume setup** button (also **WinTestKit: Open Setup Guide**).

After the introduction is completed or explicitly skipped, the guide only visits steps that need
repair, skipping healthy steps before and after them. It disappears once those problems are fixed.
WinTestKit keeps checking what it set up, and when a step that worked stops
working (the interpreter is deleted, the package is uninstalled, the project's files are removed, the
application's executable is gone, or the application runs elevated while VS Code does not) the guide
comes back at that step with a red callout saying what is wrong, and a notification names it if the
sidebar is closed. A stopped application is not a problem. **WinTestKit: Check Setup** looks again on
demand.

**Disable for this workspace** (the red button in the callout, **WinTestKit: Disable for This Workspace**,
or the Test Target menu) returns the sidebar to the Enable button. The choice is remembered per workspace.

The custom YAML editor offers **User Settings** (the ignored `wintestkit.local.yaml`) and **Repository
Settings** (the committed `wintestkit.yaml`) tabs. Every setting is shown at once, grouped as
**Application** (starting with **Application executable** and its **Browse…** button; clearing it
removes the override), **Test runs**, **Evidence**, and **Debugging**. Repository Settings accept
the executable only as a path relative to the project folder (**Browse…** stores it that way and
refuses a file outside the project) and share the application arguments; absolute paths, the
working directory and the personal debugging aids (Flash elements during test runs, Slow motion) are
User Settings only. Changing a value overrides it in this file. In **User Settings**, a setting whose value differs from
its default (or from the repository value) has a short accent bar on its left edge, inset from the top and bottom. A value that merely equals
the default is not marked.
In
**User Settings**, a setting that `wintestkit.yaml` also sets is greyed out under a blurred
**Override Repository Setting** button while the repository value is in use (hover it for details). Click the
button to override the value on this machine: the control becomes editable and starts from the
repository value, and a grey git tab appears on the edge of the card. Click that tab to drop your
override and use the repository value again. Settings the repository does not set have neither.
In **Repository Settings**, every setting starts off: blank, greyed out and covered by a blurred **Enable Setting for Repository** button, with no default
shown. Click it to turn the setting on; that writes its default to `wintestkit.yaml` (or, for the
executable and process name, waits for you to enter a value) and makes it editable. A red git tab
then appears on the edge of the card; click it to remove the setting from the file. Leaving a value empty does the same: clearing a
repository value (or an enabled setting you never filled in) switches the setting off again, so
the file never holds an empty value. A setting that
your User Settings override shows a warning with a link to them, because it is not used on your
machine. Small illustrations preview Input mode, the replay capture scope and the report folder; they
appear only while the setting is editable, not under a blurred button. Evidence includes
the screenshot policy, replay recording mode (`replay`), replay FPS (greater than 0 and no more than 30), and capture
scope (**window** or **desktop**). Changes in both files are saved
immediately. **Open YAML** switches to raw text for settings not shown in the form. Comments and
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
| `wintestkit.codeLens.classOnly` | `false` | Show only page class lenses in the editor; element actions remain in Page Tree |
| `wintestkit.highlight.durationMs` | `1500` | How long a highlight stays on screen |
| `wintestkit.run.extraArgs` | `[]` | Extra arguments passed to `wtk run` |
| `wintestkit.run.highlightActions` | `false` | Flash each element before acting during runs from VS Code |
| `wintestkit.server.logLevel` | `"info"` | Log level of the Python server |
| `wintestkit.promptDisablePytestExplorer` | `true` | Offer to disable the Python extension's pytest explorer |

Logs are in the **WinTestKit** output channel (**WinTestKit: Show Output**).

For a page class, **Check after flow…** lets you explicitly associate a navigation flow with that
class. After the flow succeeds, WinTestKit checks the class against the current screen. This is
opt-in because flows can change application state. **Sweep project using remembered reach flows**
reuses those associations, asks for confirmation, and requires Launch for tests (`launch: per-test`). It checks each reached class, reports failures in Problems, and writes the latest summary to
`wtk-report/project-sweep.md`. Cancellation takes effect between flow and check operations. Pages
without a remembered runnable flow, and remembered flows with required parameters, appear in the
skipped-pages section.

Flows with scalar `str`, `int`, `float`, or `bool` parameters can be run from their CodeLens. WinTestKit
prompts for required values, pre-fills defaults, validates input as a scalar, and skips the run if a
prompt is cancelled. Flow source expressions are never evaluated as input.
