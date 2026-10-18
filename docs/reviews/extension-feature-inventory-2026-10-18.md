# WinTestKit extension: current feature inventory

Audit date: 18 October 2026. Scope: the actual local working tree, not just the last commit or published version. Manifest version: 0.1.1. This is an implementation-informed product inventory, not a claim that every feature was exercised against a live application during this audit.

## 1. Product purpose and boundaries

WinTestKit is a Python/pytest UI-test toolkit with a VS Code extension for Windows desktop applications, positioned primarily for WPF applications. It finds windows and controls using Microsoft UI Automation rather than image matching. Tests operate against the real application without requiring instrumentation or changes to its source. The extension connects reusable Python page models, a live inspector, locator validation, application lifecycle controls, pytest execution/debugging, and local reports.

The VSIX is the editor frontend; the Python package is a separate required backend. Installing the VSIX alone does not prepare a test environment. The product needs Windows 10/11, Python 3.12+, an interactive unlocked desktop, and matching elevation between VS Code/test processes and the target application. The Python VS Code extension is an extension dependency. Python Debugger/debugpy is required for debugging. Other Windows applications may expose usable UI Automation trees, but this should not be read as a blanket compatibility guarantee for every desktop framework.

The central authoring model is code-first: define Window, Element/typed controls, collections, and reusable Page classes; create pytest tests using the app fixture and expect assertions. It is not currently a full no-code test recorder.

## 2. Main user journey and UI surfaces

A typical journey is: prepare interpreter/package -> initialize a test project -> choose the target application and lifecycle mode -> launch or attach -> inspect controls in Spy -> copy/insert page definitions -> validate locators -> write reusable flows and pytest tests -> run/debug from VS Code Testing -> inspect failures and HTML reports/traces.

The WinTestKit activity-bar container has three sections:

- Test Target: project/application selection, launch mode, status, application actions, configuration gear.
- Explorer: a Page Tree / Flows tab switcher. Tests are deliberately not duplicated here; they live in VS Code's native Testing view.
- Spy: a live UI Automation object browser and inspector.

Python source files have CodeLens actions. The status bar gives backend/application context. Output logs, terminal commands, Problems diagnostics, native Testing UI, a custom YAML editor, quick picks, and an external browser report provide additional surfaces. Some of the product's best features therefore sit outside the main WinTestKit sidebar.

## 3. Project discovery, setup, and workspace support

The extension identifies WinTestKit projects through pyproject.toml containing a tool.wintestkit table. Nested projects and multi-root workspaces are supported. It associates source files with their project and uses the active editor/project selection for commands. The project tile can switch between discovered projects. Discovery watches project/source/configuration changes and refreshes page, element, flow, and test information. Refresh work is coalesced and stale responses are not applied.

Workspace-relative dot-prefixed directories are excluded from project discovery; Python discovery/reload scanning also excludes hidden directories. A workspace living under an ancestor such as .t3 is still valid: that ancestor alone is not grounds to hide the workspace. The previous request to remove an added folder hierarchy is reflected in the current flat file-grouped Flows navigation, rather than a directory browser.

Initialize Project creates starter project/configuration files, a page, a smoke test, and ignore rules without overwriting existing project files. It supports choosing the target executable. The extension uses the selected Python interpreter, supports an explicit interpreter-path override, and offers installation of the Python package when missing. Check Environment runs the doctor CLI in a terminal. It can offer to disable the Python extension's pytest explorer to avoid duplicate tests; that prompt is configurable.

## 4. Test Target: application and lifecycle

The section shows a live status and contextual tiles:

- Application icon/name, executable/process identity, and PID(s) when running.
- Launch mode.
- Workspace/project identity, with project switching when applicable.
- Contextual Launch, Restart, Close, refresh/retry/output actions as appropriate to state and configuration.

Clicking the application tile offers browsing for an executable, attaching to a running application, or opening settings. Selecting an executable saves its path locally, clears an explicit process target, and chooses per-session launch mode. Selecting a running process saves its process name, clears executable configuration, and selects Attach. The process chooser includes identity/PID/window-title information.

The mode quick pick offers Spawn (per-session) first, then Attach. The underlying default is per-session. Important terminology distinction: the UI currently calls this mode Spawn even though the action button says Launch. An existing per-test configuration is honored and displayed as Spawn per test but is not one of the two quick-pick options.

Lifecycle semantics:

- Per-session/Spawn: own the test application's lifecycle; close an already-running copy before starting a fresh one; close the application WinTestKit launched when tests finish.
- Per-test: start a fresh application per test and close it afterward.
- Attach: use an existing application; do not start or close it as part of the test-run lifecycle.

The UI does not offer impossible launch/restart actions for a process-only/Attach setup lacking an executable. Startup shows real stages such as process creation, responsiveness, and main window visibility, elapsed time/startup budget, and an in-place failure explanation with retry/output access. Application state includes stopped/running/transitional/error conditions, not just backend connectivity. Backend handling includes apps whose visible top-level host window belongs to a different process, such as Calculator.

## 5. Shared and machine-local configuration

A custom editor provides a form for wintestkit.yaml and wintestkit.local.yaml, with access to raw YAML. Shared/team settings are separated from machine-local values. Executable paths and other local values are stored in Git-ignored local configuration; shared settings can be checked into version control. Legacy tool.wintestkit TOML and local TOML remain supported. Config changes trigger UI refresh and backend restart/reload.

The form groups shared/local settings, makes Application executable the primary local setup field with Browse, and collapses advanced settings into Application, Test runs, and Debugging. It validates typed values and preserves YAML editing conventions rather than replacing the whole configuration model with a single opaque form.

Form-exposed settings include:

- app.path, app.process, app.args, app.cwd.
- lifecycle mode; startup timeout (30 seconds), close timeout (10 seconds).
- action/assertion timeout (10 seconds).
- input mode: UI Automation pattern or mouse input.
- screenshot policy: off, on-failure (default), every-step.
- report directory (wtk-report) and Python import paths.
- highlight actions (default false) and slow-motion delay (default zero).

Additional backend configuration includes property aliases and screenshot trace options; not all backend settings have form controls. Trace is one clear example of implemented capability that currently requires YAML/CLI/environment configuration rather than a dedicated extension UI control.

Extension-specific VS Code settings include interpreter override, CodeLens enablement, highlight duration (default 1500 ms; 200-10000 ms range), extra run arguments, action highlighting during extension runs, server log level, duplicate-pytest-explorer prompting, Spy bring-window-to-front (default false), and Spy mark-defined-objects (default true).

## 6. Explorer: Page Tree

Page Tree shows discovered Python page classes with source-file information, nested child pages/components, windows, elements, and element collections. Controls can be nested by within-container relationships. Shared child components can appear beneath each parent that mounts them. Root page trees are visually separated. Rows have type/status icons, indentation/branch guides, expansion, selection, and definition navigation.

Actions include jumping to source definitions, highlighting an individual element/window, checking whether an element/window resolves, and checking all direct definitions in a page/class. Check results feed status icons. The current restored UI again includes individual tick/check controls: do not treat the short-lived removal as current behavior.

The class-wide action's current wording is exactly: Check all elements in this class exist. It checks the class's discovered direct definitions, including Window definitions; it should not be advertised as automatically navigating every application's screen or proving the correctness of an entire nested app model.

The Explorer remembers the selected Page Tree/Flows tab and expansion state. It has refresh and context actions. It is a code-model navigator, distinct from Spy's live runtime UI tree.

## 7. Explorer and editor: reusable Flows

Flows are reusable Python functions discovered by the backend and grouped by source file in the Flows tab. The navigator is flat by file instead of building an arbitrary directory hierarchy. Source navigation is supported.

Flows whose only required parameter is app can be executed directly against the running application, using an inline play action or Run flow CodeLens. Other required arguments make a flow non-runnable from these one-click entry points. Re-running an already running flow is guarded. UI feedback includes running/passed/failed states, elapsed duration, failure notifications, and output access. Editing refreshes stale flow results. The app must already be running; errors explain that it needs to be launched. This is an interactive helper runner, not a replacement for pytest or a graphical flow designer.

## 8. Editor CodeLens, checks, feedback, and diagnostics

Each eligible element/window definition offers Highlight element/window and Check exists. Each page class offers Check all elements in this class exist. Eligible flow definitions offer Run flow. Test Run/Debug CodeLens were deliberately removed; tests run/debug from native VS Code Testing.

Highlight flashes an outline around a matching live control/window. Check resolves the locator and returns structured outcomes such as found, missing, ambiguous/multiple matches, or error. These checks validate locator resolution/existence, not arbitrary business assertions or that every hidden UI state is currently reachable.

Actions show loading/progress and results inline, keep highlight/check feedback independent, include hover diagnostic detail, and remain usable for retry. The default individual label is now Check exists; after an action, the existing dynamic feedback may instead read Check: Found, Check: Not found, an ambiguity message, or Check: Failed. That distinction is intentional in this inventory.

Check outcomes also appear as gutter decorations and editor/Problems warnings. Resolution diagnostics can include match counts, candidates/closest matches, and locator context. CodeLens globally respects the extension setting and workspace trust. Highlight duration is configurable. Foreground/focus restoration is best-effort and avoids overriding a user's intervening window switch.

## 9. Spy: live runtime object discovery

Spy shows desktop/target UI Automation objects, not static page source. It supports lazy branch expansion, refresh, selection, type icons, chevrons, branch guides, application executable icons where available, and a loaded-object count. It avoids eagerly querying the entire desktop tree.

Pick element enters a live picker: hold Ctrl and click a control; Esc cancels. Picked nodes can be revealed through their ancestor chain. Refresh objects and Pick element stay in the toolbar. Collapse all closes branches and clears the filter. Filtering searches already-loaded names, control types, classes, and automation IDs while preserving matching ancestors; it does not promise a complete background search of unloaded application controls.

While an application is running, scope can switch between the selected application and other desktop windows using Show Other Apps / Show Only Selected App, with remembered preference. The target-only behavior is the default. Desktop windows may appear when a target is not available; seeing other apps in one screenshot alone is not proof that the scope setting is broken. Transient XAML PopupHost windows are filtered to reduce noise.

The object tree and selected-object inspector use a responsive side-by-side/stacked layout with a draggable, keyboard-resizable divider. It follows VS Code theming. Progress is represented in existing pane headers for connection, refresh, expansion, icon loading, inspection, picking, and launch, avoiding layout jumps or fake progress percentages. Existing content remains visible during refresh. Empty, disconnected, stopped-app, no-match, and failure states have explanations.

## 10. Spy: inspection, highlighting, and code generation

Selection first fetches cheap essential identity/state/geometry properties. Suggested locator generation follows separately so expensive UI Automation calls do not block all inspection. The inspector groups Identity, State, Geometry, and Automation, with an optional All properties / Load all properties path for the complete property list and supported UI Automation patterns.

Selected objects can be highlighted. Bringing their window forward on selection is configurable and defaults off, using the toolbar pin/setting. Highlight can be disabled with an explanation when no visible rectangle is available. Locators are generated for window descendants; selecting a root window instead explains the limitation and shows window/application information. This is not an arbitrary element-action console.

Suggestions include Python code, a proposed attribute name, locator-quality information, and helper/container/window definitions where required. Copy locator copies generated source. Add to page can target an existing page or create a new page/file. Users choose/validate class and attribute names. Insertion handles required imports and helpers, avoids simple name/locator duplication, and places code into page source via editor edits rather than making users manually paste every definition.

Typed suggestions can use Button, CheckBox, ComboBox, DataGrid, ListBox, ListItem, RadioButton, TabControl, Text, TextBox, and TreeView, besides generic Element/Elements/Window definitions.

## 11. Spy: relationship between live objects and page source

Defined in pages identifies existing page-element definitions that resolve to the selected UI Automation object. It shows definition/attribute/locator/file information, supports source navigation, and can indicate reused definitions through nested page paths. Loaded live objects can be marked as already represented in page definitions. Only strict resolution to the exact runtime object counts; this is not just string matching on labels.

The backend uses cached catalogs, property prefilters, bounded work, and resolution caching to keep this feature responsive. Markers can be disabled for applications that answer UI Automation queries slowly. This is definition coverage, not executed test coverage, business-requirement coverage, or proof that every possible UI state is modeled.

## 12. Native Testing integration

WinTestKit registers native VS Code Run and Debug profiles. Test discovery supports pytest structure and parametrized cases. Run selected tests or the project suite through standard Testing controls. Execution streams status, output, durations, and failure information, maps events to native test items, and supports cancellation. Work is coordinated per project to avoid conflicting runs. Extra run arguments and highlight-actions settings can customize extension-triggered execution.

Failures can include traceback/source location, diagnostic details, screenshot links, captured stdout/stderr/logs, and expected/actual diff messages. A failure notification offers Open Report and/or Show Test Results.

Debug starts a debugpy session against the WinTestKit runner with normal Python breakpoints. Debug startup checks for Python Debugger and can offer installation. Debug is intentionally different from an ordinary report-producing run: its launch configuration uses --no-report, --no-env-check, and a long action timeout (3600 seconds) to accommodate breakpoints. Do not imply that ordinary HTML reports are generated identically by the Debug profile.

## 13. Reports and evidence

Ordinary test runs can produce a local HTML report and machine-readable results.json, with per-test outcomes, durations, steps, screenshot artifacts, captured output, failure messages, structured diagnostics, and environment metadata. JUnit XML is supported via the backend CLI/pytest path. Screenshot policy controls on-failure/every-step/off evidence independently of trace recording.

The extension records report paths per project, offers a failure notification to open the report, and provides Open Last Report. A configured report-directory fallback can find an existing report after extension state is lost. Reports open through the external browser/file handler; this is not currently a dedicated native VS Code results-history dashboard.

The HTML viewer provides outcome filters/search, expandable test details, action/step information, screenshot viewing, and diagnostic context. Failed/error cases open their details. Keep the generated report directory/artifacts together when sharing; the HTML uses local evidence paths. Do not assume a hosted report service or server-side history exists.

## 14. Screenshot trace / recording-style playback

The Python backend implements continuous screenshot sampling during tests, distinct from per-action screenshots. HTML reports provide recording-style playback from these frames:

- Play/pause, time display, scrubber, and sampled frame-thumbnail filmstrip.
- Click thumbnails or timestamped steps to seek; playback tracks the current step.
- Filmstrip displays at most 60 representative thumbnails while playback can use all recorded frames.
- Empty recordings, image failures, recording errors, and truncation are explained.
- Playback respects reduced-motion preference instead of forcing automatic animation.

Configuration: trace off (default), on, or retain-on-failure; default 5 FPS, configurable up to 30; window capture by default or desktop scope; default limits of 3000 frames and 104857600 bytes (100 MiB). Limits bound artifact growth and recording is best-effort; missed capture ticks are dropped instead of building an unbounded queue. Failure-retention mode discards successful-test recording frames. Capture does not send UI Automation objects across the screenshot worker boundary.

This is a sequence of timestamped screenshots, not an MP4/video encoder, not exact high-FPS screen recording, and not Playwright's full DOM/network/console replay system. There is no claim of speed control, DOM snapshots, network waterfall, or application-state restoration. It is currently mostly discoverable through configuration/CLI and report output rather than a prominent Record control in the extension.

## 15. Python-backed test authoring capabilities

These belong to the toolkit integrated by the extension, not necessarily separate UI buttons:

- Reusable Page/component composition and Window/Element/Elements descriptors.
- Scoped locators by automation ID, name, control type, class, window, within-container, index/depth, additional property predicates, string/regex matchers, and grid row/cell targeting.
- Strict resolution rather than silently choosing an arbitrary control when multiple controls match; useful diagnostics when no unique match exists.
- Typed controls and their applicable interactions: clicking, text entry/value handling, selecting items/tabs/radio controls, checkbox state/toggle, expanding/collapsing appropriate controls, and grid-specific access. Availability depends on actual UI Automation patterns and control type.
- Retry/wait behavior with configurable budgets; UI Automation pattern input by default and mouse input where configured.
- expect assertions for existence, visibility/hidden state, enabled/disabled state, checked/selected state, text/value matching, text containment, collection counts, arbitrary properties, and negation.
- Standard pytest fixtures/parametrization/markers and reuse of ordinary Python helper functions; failure screenshots, UI tree dumps, steps, logs, and app lifecycle integration.

Do not advertise generic cross-platform browser testing, visual-diff assertions, AI auto-healing, automatic business-test generation, or a visual test designer as already shipped.

## 16. Companion CLI and troubleshooting

Companion commands include wtk init, doctor, spy, inspect, discover, highlight, check, run, report, and serve. They let users initialize/debug/run without relying on every GUI feature. Run supports lifecycle/input/timeout/screenshot overrides, action highlighting/slowmo, report/JUnit output, trace configuration, pytest filters (-k/-m), stop-on-first-failure, last-failed reruns, and forwarding raw pytest arguments.

The extension starts a per-project Python server and provides Restart Server, Show Output, interpreter/package setup, trust checks, and contextual error messages. Backend process exits, interpreter/root/PID details, and protocol/configuration failures are logged. Invalid initialization configuration is not treated as an endlessly restartable crash; actual transport/process failures retain bounded retry/backoff. Workspace/source changes clear or supersede stale asynchronous results. These are resilience features, not proof that backend availability problems cannot occur.

## 17. Current changes and quality context

The latest working tree restores individual Check CodeLens, tick buttons, and context actions after a short-lived removal. Class-wide wording remains Check all elements in this class exist. The individual default CodeLens says Check exists; dynamic result feedback remains. The Launch-first/default and executable-selection behavior is retained. These are present locally even where they are not yet committed. Do not recommend removing Check based on the old removal or presenting its restoration as a new feature.

Most recent full extension suite in the thread: 271 tests passed. Latest label-only change: 31 focused tests passed; typecheck/lint passed; VSIX rebuilt. These are automated validation results, not live usability evidence. No new implementation changes are requested in this review task.

## 18. Screenshot supplied for product review

Original image: C:/Users/massi/.t3/userdata/attachments/fab1f2f2-e4c3-4d0f-bb14-5bcb26891dcb-734b64fa-3e8a-43f5-85b5-ae8d40bb394f.png

The screenshot shows a wide VS Code window with the WinTestKit sidebar: Test Target at the top (calc, Spawn, project tile, Launch, stopped state), Page Tree/Flows below, and Spy below that. The editor is navigation.py with page definitions, Highlight element and Check exists CodeLens, and the class-wide existence-check label. The terminal occupies the lower editor region and shows extension installation/environment output. Spy shows multiple desktop windows and the selected object is the VS Code window rather than Calculator; the target application is stopped. The inspector has a Defined in pages section with a no-pages message despite visible page models elsewhere in the UI. That is a screenshot-visible context discrepancy to investigate, not a proven root-cause bug. Some text is necessarily small in this full-screen overview; distinguish screenshot scaling from actual UI font sizes.

Questions for the reviewer: How can a new user understand what Target, Page Tree, Spy, Check, Flows, and native Testing each mean? What should happen when the target is stopped? How can current powerful-but-hidden features be made discoverable without clutter? What new features would solve real user problems rather than reproduce capabilities already implemented?

## 19. Evidence map / source of truth

Primary inspected implementation locations:

- vscode/package.json: commands, views, menus, extension settings.
- vscode/src/extension.ts, projects.ts, python.ts, init.ts, pytestConflict.ts: orchestration/setup/project behavior.
- vscode/src/settings/testApp.ts, testAppModel.ts, model.ts, files.ts, editor.ts: Test Target/configuration.
- vscode/src/views/elementsTree.ts, elementsTreeModel.ts, navigationModel.ts, navigationDocument.ts: code navigation/actions.
- vscode/src/editor/lensModel.ts, highlightCommands.ts, checkStatus.ts, diagnostics.ts, decorations.ts, flowRuns.ts: CodeLens/checks/flows.
- vscode/src/spy/spyView.ts, messages.ts, insertElement.ts, insertionModel.ts and media/spy: live inspection and insertion.
- vscode/src/testing/controller.ts, runner.ts, debug.ts and report.ts: test execution/debug/failure/report UI.
- python/src/wintestkit/config.py, model.py, controls.py, expect.py, coverage.py, trace.py, pytest_plugin.py, commands/run.py, report/results.py and report/template.html: backend-backed capabilities and actual limits.
- README.md, vscode/README.md, vscode/CHANGELOG.md: supporting documentation. Some older quick-start/settings text still describes removed test CodeLens or legacy setup paths; source takes precedence over those stale sentences.

## 20. Post-review clarifications (verified by the parent)

The inventory above is the brief originally sent to Opus 5.5. Its source review added the following important details; these clarify the original rather than replacing its record.

- Attach does not automatically own the application's test-run lifecycle, but explicit manual Close is still offered for a running attached application. The app.close backend request calls close regardless of launch mode. Consequently the mode's absolute description that it never closes the app overstates the actual safety guarantee. This is an important distinction between automatic teardown and a deliberate manual action, not proof that tests automatically close attached applications.
- The screenshot's false-looking no-pages message has a concrete code path: inspect.definitions returns empty definitions and pageCount 0 when no application is available; Spy renders that as This project has no pages. This confirms a misleading unavailable-state presentation, not missing project discovery.
- Resolution diagnostics already include found in the same window under a different container, found in another window, and relocated component-root hints. They appear in diagnostic text; clickable reveal/repair workflows would enhance an existing capability rather than invent relocation detection.
- Whole-class Check emits a found versus broken/moved status-bar summary. Like every existence check, the result depends on current UI state; controls behind a closed pane can be missing without their locators being structurally broken.
- Editor Highlight/Check can offer to launch a stopped target and retry. Run flow currently gives a launch-first message instead. The lifecycle progress entry points are not fully unified.
- Some stopped-Spy copy still names Current Setup instead of Test Target, and the generic check command/context-menu label still says Check Element even though the default CodeLens says Check exists.

Review boundary: the Opus review also referenced local project-memory assumptions about suite size and TestComplete migration goals. Those assumptions are not established by the screenshot or this audit and should be confirmed with the user before prioritizing migration-specific work. Its recommendations are product hypotheses, not measured user-research outcomes.
