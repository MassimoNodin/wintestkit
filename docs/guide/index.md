# WinTestKit user guide

WinTestKit automates UI tests for **Windows WPF applications**. You describe your application's
windows and controls as Python classes, write tests with pytest, and run them from the command
line, from CI or from VS Code. Controls are found with Microsoft UI Automation, the same
accessibility API screen readers use, so there is no image matching and nothing to add to the
application under test.

| Page | What it covers |
|---|---|
| [Getting started](getting-started.md) | Install, create a project, write and run the first test |
| [Screens and elements](screens-and-elements.md) | `Screen`, `Window`, `Element`, `Elements`, `within`, organizing screens |
| [Locators for WPF](locators-for-wpf.md) | Strict matching, diagnostics, locator strategies, lists, grids, dialogs |
| [Actions and assertions](actions-and-assertions.md) | Every action, auto-waiting, `expect`, timeouts |
| [Running tests](running-tests.md) | `wtk run`, launch modes, fixtures, reports, JUnit, exit codes |
| [VS Code](vscode.md) | CodeLens, Test Explorer, debugging, Elements view, Spy |
| [CI](ci.md) | Running UI tests on a build agent |
| [Troubleshooting](troubleshooting.md) | `wtk doctor`, common failures, logs |
| [Migrating from TestComplete](migrating-from-testcomplete.md) | Concept mapping |

The [`examples/demo-tests`](../../examples/demo-tests) project tests the small WPF application in
[`demo/`](../../demo) and is the reference for everything in this guide: every Python sample here
is an excerpt of that project, which runs in CI.

## Requirements

- Windows 10 or 11 with an **interactive, unlocked desktop** while tests run.
- Python 3.12 or later.
- The application under test running at the same elevation level (administrator or not) as
  WinTestKit.
