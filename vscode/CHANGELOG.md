# Changelog

All notable changes to WinTestKit (the `wintestkit` Python package and this extension, which are
sharing a version by default for stable releases) are documented here. Formal Python prereleases use
an explicitly selected, distinct numeric extension version and prerelease channel metadata.
Unreleased changes must be moved to a dated candidate section before a release can pass checks.

## [Unreleased]

- Rename the **Highlight actions** setting to **Flash elements during test runs** in the Configuration
  page, so it is not confused with Spy's Highlight. Only the label and description change: the
  `highlight_actions` key, the `--wtk-highlight` option and existing configuration files are unchanged.
- Add a `highlight_color` setting (`#RRGGBB`, default `#FF0000`) for the outline drawn around an
  element by Flash elements during test runs (`highlight_actions`), Spy, `element.highlight()`, `wtk highlight` and the editor's highlight
  commands. In the Configuration page (User Settings, Debugging) it is a row of swatches plus a
  custom colour picker, with a small diagram of a highlighted button. Quote the value in YAML,
  because an unquoted `#` starts a comment. Needs the `wintestkit` package from this version.
- Allow the committed `wintestkit.yaml` to set `app.path` as a path relative to the project folder and to
  share `app.args`, so a repository can point at its own build output (`bin/Debug/App.exe`) and
  launch flags. Absolute, drive and UNC paths are still rejected there, with a message pointing to
  `wintestkit.local.yaml`, and a local value still overrides the shared one. In the Configuration page
  **Browse…** now also works in Repository Settings and stores the path relative to the project
  (refusing files outside it). Needs the `wintestkit` package from this version.
- Redesign the Configuration page: the collapsed **Advanced options** section is gone, so every
  setting is visible at once, with the application executable now the first row of **Application**.
  Settings sit in rounded cards with the control beside the label,
  numbers get a slider next to the exact value, options become a segmented control and booleans a
  switch. Controls are always editable, so changing a value overrides it in place (replacing the per-row
  override checkbox and the Reset button). In **User Settings** a setting whose value differs from what it would be without your file (its
  default, or the repository value) has a short accent bar on its left edge, inset from the top and bottom. A
  value that merely equals the default is not treated as modified, and Repository Settings mark nothing. A setting that the repository's
  `wintestkit.yaml` also sets is greyed out under a blurred **Override Repository Setting** button while the
  repository value is in use; clicking it makes the control editable (starting from the repository
  value) and shows a grey git tab on the card edge that returns to the repository value.
  Settings without a repository value have neither, and **Repository Settings** warns on a
  setting your User Settings override. Small
  illustrations (shown only while a setting is editable) show what Input mode (UI Automation versus mouse), the Replay capture scope (window versus whole screen) and the Report directory do. Every
  change in **User Settings** (the machine-local file, formerly "This machine") and **Repository
  Settings** (formerly "Shared project") is saved immediately, so there is no Save button. In
  Repository Settings every setting starts off (blank and greyed out);
  a blurred **Enable Setting for Repository** button turns each one on separately, writing its
  default to `wintestkit.yaml` or waiting for a value when it has none, and a red git tab on the
  card edge removes it from the file again; clearing a value, or leaving an enabled setting empty,
  switches it off too. While a change is being written a small "Saving" spinner shows at the right of the
  file line (for at least half a second, so it does not flicker), instead of briefly flashing an
  "unsaved changes" banner. The scope switch
  and Open YAML stay in a sticky bar.
- List the desktop's windows for Spy's "show other apps" scope with `EnumWindows` instead of UI
  Automation's desktop root. UI Automation visits every hidden window of every process, so one slow
  provider on the machine made each refresh take around six seconds, queued status checks behind
  it, and let short-lived windows vanish before they were read (reported as an incomplete
  enumeration). The same roots now load in about 0.1 s.
- Merge Spy's Inspection section into **All properties**: one list sorted alphabetically, in which
  nested values (such as `RuntimeId`, `BoundingRectangle` and element lists) show an arrow and a
  count and open in place, several levels deep, with the nested rows indented, tinted and marked
  as belonging to their parent. Properties that hold UI Automation elements or element arrays
  (`ControllerFor`, `DescribedBy`, `SelectionSelection`, ...) are now read into nested rows
  instead of being shown as opaque.
- Add a pin button, shown on the row under the pointer, to each property in **All properties** to show it, in a new **Pinned** group,
  for every selected object. The list is the user setting `wintestkit.spy.shownProperties`, so it
  is never saved in a project or its git repository. Needs the `include` parameter of
  `inspect.properties` (the `wintestkit` package from this version).
- Search only the direct children of an element with `panel.Element(...)`, `panel.Button(...)` and the other typed elements, or `panel.Elements(...)` for a group. On a declaration it is `within=panel, depth=1` and shows nested under `panel` in the Page Tree; on a bound element (`self.panel.Button(...)`) it looks the child up on the fly. Needs the `wintestkit` package from this version.
- Allow choosing a different application in the Test App settings while the current one is running. The tile used to be locked until the app was closed. The running application is not closed or touched: it stays open, only the target changes (and the extension restarts its server for the new configuration, which never closes the app).
- Generate Spy's suggested locator only when asked, with a **Generate suggested locator** button (its tooltip, and the progress text, warn that large applications can take 20 seconds or
  more) and a spinner while it runs. It no
  longer holds up the rest of the selected object's details (definitions, preview) on selection.
- Replace the "Last-test preview" in Spy's properties with a **Preview** section: a live capture of
  the selected object, switchable between the element alone (the default) and its window with the
  object outlined in red. Every image is fitted inside the same fixed-size frame. Saved
  definitions show their last-test images in the same section. Needs the new `inspect.preview`
  server method (the `wintestkit` package from this version). Click the image, or the button
  beside the toggle, to open it in VS Code’s built-in image viewer to zoom and pan; the file is
  private, temporary and deleted when its tab closes.
- Stop Spy's objects view from reloading by itself. It no longer reloads when the panel tab is
  shown again (the view now keeps its state while hidden), when a project file changes, or after
  an element has vanished. It reloads on the reload button, with the picker, and when nothing has
  loaded yet.
- Mark the selected application's windows in Spy's objects view with a blue tick, and call a window
  that has no title of its own by the application's name instead of "Window".
- Show elements whose provider returns an empty runtime id (such as TeamViewer's custom-drawn
  content) in Spy instead of reporting an incomplete enumeration. They are keyed by their place
  under the parent, so they can be expanded and inspected like any other node.
- Remove the gutter icons beside page elements, and the inline "✓ found" text on passing ones. Only
  elements that are not found, ambiguous or errored are marked inline, after the code on the
  element's line instead of before it; **Check: Found** stays in the CodeLens.
- Make **All properties** a plain, always-visible section instead of a collapsible one, and stop
  listing `HelpText`, `ItemStatus` and `ItemType` in it before the full list is loaded; it fills in
  when you click **Load all properties**. Properties you pin and properties that your configured
  aliases point at are still read on selection. (`wtk inspect` on the command line still prints
  the three.)
- Keep Spy's selection through a reload, a server restart or a VS Code reload: the tree is opened
  down to the object and it is selected again. It is found by the properties of each object on its
  route from the window, with its place among its siblings, rather than by node ids that change
  on restart. A look-alike is never selected in its place: if the object is gone, ambiguous or
  changed, a VS Code warning says so once and the selection is forgotten.
- Stop the server restarting by itself about once an hour. The extension restarted it on every
  change event for `pyproject.toml`, `wintestkit.yaml` or `wintestkit.local.yaml`, and something
  on the machine (an indexer, scanner or sync client) sends such events for files it merely
  touched. A file now restarts the server only when its content is different.
- Fix **Pick element** doing nothing on such elements: every hover and pick in TeamViewer failed with
  "element has no runtime id". A picked element is now keyed by its place below the nearest
  ancestor that has an id, matching the tree, and its ancestors are revealed as usual. Siblings are
  told apart by their properties because UI Automation cannot compare these elements reliably.
  Hovering skips that lookup, which can take a few hundred milliseconds in a deep tree.

## [0.1.1rc1] - 2026-10-22

First public prerelease. Install the extension's pre-release channel together with
`pip install --pre "wintestkit==0.1.1rc1"`.

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
