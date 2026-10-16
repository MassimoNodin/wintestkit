# Changelog

All notable changes to WinTestKit (the `wintestkit` Python package and this extension, which are
released together with the same version) are documented here.

## [Unreleased]

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
