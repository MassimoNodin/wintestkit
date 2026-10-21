# Changelog

All notable changes to WinTestKit (the `wintestkit` Python package and this extension, which are
released together with the same version) are documented here.

## [Unreleased]

- Restore reloaded optional tutorials paused and resumable; release tutorial UI state before
  saving completion, and ignore picker activity from hidden, cancelled, or superseded sessions.
- Coalesce Spy refresh requests, share root/status snapshots, cache fresh child descriptions,
  queue coverage work, and cache application icons by executable for the extension-host session.
  Surviving objects remain visible with a warning when enumeration is incomplete.
- Save paired last-successful test-time element images with the project: an element crop for
  Selected object and a separate red-outlined owning-window image retained for future use.
  Saved definitions can show their crop offline; image capture has privacy guards and an opt-out.
- Show bounded, expandable external UI Automation inspection values without reflecting opaque
  CLR objects. Remove verified dead helpers, duplicate dispatch paths, and obsolete historical
  documentation while retaining current usage guidance.

- Guide Spy users through eight concise, value-focused steps in visual order, with separate
  selection and Properties explanations, ending on the Testing tab icon. Keep Pick element and its three adjacent controls
  sharp during the toolbar step, and spotlight Highlight with the selection summary.
- Split the selected object inspector into selection details, page definitions and locator
  on the left, with independently scrolling Properties on the right. Narrow inspectors
  stack the sections, and the tutorial highlights the dedicated Properties section.
- Show all desktop applications in the Spy tutorial snapshot while selecting the hosting
  VS Code example. Blur the introduction background and remove Skip tutorial and Cancel
  setup from all Spy tutorial cards, retaining ordinary navigation and Close.
- Keep the first Spy tutorial step available while its snapshot loads; only wait when
  advancing from step two to three. Clear stale object-loading overlays and preserve
  navigation buttons across unchanged tutorial updates.

- Make the optional Spy tutorial read-only while preserving hover effects and scrolling.
  Select the hosting VS Code window's second direct child automatically and keep its
  snapshot fixed. The generated MainPage defines that pane as content, independent of
  workspace titles, for a real match in Defined in pages.
- Enforce the supported Python package range and RPC protocol before connecting. Incompatible
  packages offer direction-specific recovery actions without crash/retry loops; installation
  selects and verifies a compatible package. CI and releases validate the compatibility policy.
- When a test run has failures, the HTML report opens straight away in the main editor area, with the side bar left open. **Open Report**
  and **Open Last Report** use the same preview. Turn it off with `wintestkit.openReportOnFailure`.
- Classified UI Automation environment failures in Test Target offer **Check Environment** for
  the originating project, while ordinary launch errors retain **Show output**.
- Rename the navigation view to **Pages & Flows** and add an **Open Testing** toolbar action.
  Project initialization now offers to open Testing or the generated smoke test.
- Spy distinguishes a stopped app from a project without pages, preserving the page catalogue
  and explaining how to start live definition checks from **Test Target**.
- Align the element check command with the **Check exists** CodeLens and update stale UI guidance.
- Explorer Page Tree and Flows tabs match the Test Target tiles, with rounded borders,
  themed surfaces and orange icons; an accent border identifies the selected tab.
- "Current Setup" is now **Test Target**: tiles for the application (icon, name, process IDs), its
  launch mode, the project and a Launch / Restart / Close action, with the status next to the title.
  The application and mode tiles open quick picks (browse for an executable, attach to a running
  app, Attach or Launch for tests) that save to `wintestkit.local.yaml`, and the project tile
  switches projects. While the app starts it shows each stage (process started, app responding,
  main window shown) with the time against the startup timeout, and a failed launch keeps the
  reason on the section with a way to retry.
- **Launch for tests** mode owns the app's lifecycle: a copy that is already running is closed first,
  and the app WinTestKit started is closed when the tests finish. The Calculator example now uses
  the standard `app` fixture, so the mode in the Test Target view decides whether it attaches or
  starts Calculator.
- Spy file rows use the Python logo for `.py` files.
- Spy shows which element definitions in your pages already point at the selected object ("Defined
  in pages": page attribute, locator, file; click to open it) and marks those objects in the tree.
  Only definitions that resolve to exactly that object count. Markers can be turned off with
  `wintestkit.spy.markDefinedObjects`.
- Selecting an object in Spy no longer brings its window forward by default: the outline is drawn above
  every window anyway. A pin button next to Collapse all (setting `wintestkit.spy.bringWindowToFront`)
  turns it on; the window is then raised without taking keyboard focus from VS Code, and left alone
  when the element has no on-screen rectangle (the Highlight button is disabled with an explanation).
- Spy no longer lists the transient `PopupHost` windows that XAML apps create for tooltips and menus.
  Selecting a window explains that only its controls get locators, and shows its application icon.

- After a Highlight from VS Code (CodeLens, Explorer or Spy) the outline fades and focus returns to the
  window that had it, so the right VS Code window is selected again. Focus stays where it is if you
  switched windows meanwhile.

- Fix the Spy failing with "No window matches Window" and Current Setup showing "Status unavailable"
  for apps such as UWP Calculator that have no top-level window in their own process.

- Move the Spy scope toggle to the right of the toolbar and label it **Show Other Apps** /
  **Show Only Selected App**. The page CodeLens now reads **Check all elements in this class**.

- Add **Run flow** to the Flows tab and as a CodeLens above flows whose only required parameter is
  `app`. A new `flow.run` request calls the flow with the running application; discovery reports
  `runnable` for each flow.

- Remove the Run Test / Debug Test CodeLens and their commands; use the Testing view instead.

- Remove the Tests tab from the Explorer; tests are run and debugged from VS Code's Testing view.

- Return to the MIT license for all versions.

- Rename Pages to Page Tree and nest child pages under their parents, with separation
  between root trees. Shared children appear under each parent.

- Windows can now be checked like elements: the Explorer and CodeLens show a Check action for
  them, and Check all elements includes them.

- Highlight and Check show per-element progress, success, missing/ambiguous matches and errors
  inline in their CodeLens actions, with hover details and click-to-retry.

- Move application state and contextual launch, close, restart and refresh actions into the
  Current Setup application row; remove app lifecycle controls from Spy.

- Replace the separate Pages, Flows and Tests views with one **Explorer**. A **Pages | Flows |
  Tests** control remembers the selected tab. **Spy** stays below Explorer.

- Spy shows **Other apps** after **Collapse all** while the application is running. It is off
  by default and remembers the choice. **Pick element** and **Refresh objects** stay in the Spy
  toolbar; the Spy view title no longer repeats them.

- The configuration editor shows only **Application executable** under **Start the application**.
  Other settings are under the collapsed **Advanced options** section.

- Highlight brings the owning window to the foreground before drawing its outline. If Windows
  denies that, the outline is still drawn. This applies to the Highlight CodeLens, Spy selection
  and the Spy **Highlight** button, `wtk highlight`, and `Element.highlight()`.

## [0.1.1]

- Elements, typed controls, collections and windows accept `where={...}` constraints on scalar
  UI Automation properties, with exact values and compiled regular expressions.
- Shared and local configuration support `property_aliases` for TestComplete property names.
  Spy and inspection expose matching properties; editor discovery and locator displays preserve them.
- Add a test-build WPF guide for exposing full .NET type names and update migration skills.
- Checks report every missing declaration as broken/moved, show relocation details when available,
  and share a bounded search budget across a run.
- Spy loads basic properties first, with a **Load all properties** button for the full list
  and supported patterns. Basic details appear before locator generation completes, and normal
  tree selection no longer collects the ancestor hierarchy.
- Breaking: page objects now use `Page`, the `page` fixture, and the `pages/` folder.
  Update imports, class names and project paths; the former screen API is removed.
- Discovery returns `pages` and `PageEntry`; checks use `page.check` with a `page` parameter.
  Update the Python backend and extension together. Spy insertion and editor commands use
  page terminology throughout.

## [0.1.0]

First release.

- Python UI Automation engine with strict locators, waits, actions and resolution diagnostics.
- `Screen`, `Window`, `Element` and `Elements` model, `expect` assertions and a pytest plugin with
  app lifecycle fixtures, failure screenshots and tree dumps.
- `wtk` CLI: `run`, `discover`, `highlight`, `check`, `inspect`, `spy`, `doctor`, `init`,
  `report`, `serve`.
- Self-contained HTML report and `results.json`; JUnit XML via `--junit`.
- VS Code: Highlight/Check CodeLens, Test Explorer with run and debug profiles, Elements view,
  Spy with **Add to screen…**, project initialization and report notifications.
