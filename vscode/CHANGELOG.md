# Changelog

All notable changes to WinTestKit (the `wintestkit` Python package and this extension, which are
released together with the same version) are documented here.

## [Unreleased]

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

- Switch to a proprietary license for new versions. Earlier releases stay available under MIT.

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
