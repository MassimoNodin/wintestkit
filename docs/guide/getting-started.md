# Getting started

The [repository README](../../README.md) is the step-by-step installation and first-test guide.
It covers:

1. Preparing Windows, Python and your application.
2. Installing the Python backend and optional VS Code extension.
3. Creating a test project with `wtk init --app "C:/Apps/Orders.exe"`.
4. Using Spy to find controls and build a page class.
5. Writing a pytest test with the `app` fixture and `expect` assertions.
6. Running the suite and reading its HTML report.

Use your own application's executable, window titles and locators. No example applications
are bundled. The [Calculator example](../../examples/calculator-tests) provides page classes,
navigation flows and tests for Windows Calculator, which must be installed and opened separately.

After your first test, continue with [pages and elements](pages-and-elements.md),
[locator strategies](locators-for-wpf.md), [actions and assertions](actions-and-assertions.md),
and [running tests](running-tests.md).
