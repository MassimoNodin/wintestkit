# Getting started

The [repository README](../../README.md) is the step-by-step installation and first-test guide.
It covers:

1. Preparing Windows, Python and your application.
2. Installing the Python backend and optional VS Code extension.
3. Creating a test project with `wtk init --app "C:/Apps/Orders.exe"`.
4. Using Spy to find controls and build a page class.
5. Writing a pytest test with the `app` fixture and `expect` assertions.
6. Running the suite and reading its HTML report.

Project initialization creates or extends `.gitignore` without replacing existing rules.
It ignores `wintestkit.local.yaml`, `wintestkit.local.toml`, `.venv/`, `__pycache__/`,
`.pytest_cache/`, `.ruff_cache/`, `wtk-report/` and `wtk-results/`.
Rerunning initialization adds missing rules without duplicating them. Shared defaults live
in `wintestkit.yaml`; `--app` writes the executable path to ignored `wintestkit.local.yaml`.
Existing configuration is preserved. In VS Code, use the gear in **Current Setup** to edit
these YAML files with the configuration form.
Ignore rules do not untrack files already committed to Git.

`wtk init` also writes the `wintestkit-tests` agent skill to `.claude/skills/wintestkit-tests/`. It teaches AI
coding tools (such as Claude Code) the page, component, flow and test conventions of these guides,
including migration from TestComplete. The canonical copy is `skills/wintestkit-tests` in the repository;
`wtk init --force` refreshes it.

Use your own application's executable, window titles and locators. No example applications
are bundled. The [Calculator example](../../examples/calculator-tests) provides page classes,
navigation flows and tests for Windows Calculator, which must be installed and opened separately.

After your first test, continue with [pages and elements](pages-and-elements.md),
[locator strategies](locators-for-wpf.md), [actions and assertions](actions-and-assertions.md),
and [running tests](running-tests.md).
