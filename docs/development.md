# Developing WinTestKit

For installation and your first test suite, start with the [README](../README.md).
This page covers working on WinTestKit itself.

## Python backend

Install Python 3.12+ and uv. From the repository root:

```powershell
cd python
uv sync --locked
uv run pytest -m "not integration"
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv build
```

Build output goes to `python/dist/`. From the repository root,
`./scripts/check_wheel.ps1` builds and smoke-tests the wheel in a clean environment.

## VS Code extension

From the repository root:

```powershell
cd vscode
npm ci
npm run build
npm run typecheck
npm run lint
npm test
npm run package
```

Packaging writes the Windows x64 VSIX to `vscode/dist/`. Use the repository's
**Run Extension** launch configuration to open an Extension Development Host.

### Development-only package sources

Use `npm run build:dev` (or `npm run watch:dev`) for a development host, or
`npm run package:dev` to create `vscode/dist/wintestkit-dev-win32-x64-<version>.vsix`.
The development VSIX is labelled **WinTestKit (Development)** and uses the same
extension identity, so installing it replaces the regular extension rather than
running both together. The packaging command builds in an isolated temporary
directory and does not replace `dist/extension.js` with a development bundle.

In a trusted workspace with a selected interpreter, the package strip shows a
**Dev packages** dropdown: **Remote (PyPI)** or **Local wheel**. Selecting Local
opens a file picker for a trusted `wintestkit-*.whl`; use **Choose wheel…** to
select another build, then the existing Install button to install it. The wheel
path is displayed before installation. Choices are saved per workspace in
extension state, not in repository-controlled settings. A missing wheel fails
instead of silently installing a remote package.

Build the Python wheel with `uv build --directory python` from the repository
root; select the resulting file under `python/dist/`. Use a new Python package
version for each update test: pip may skip an already-installed wheel with the
same version. This first increment does not publish a local feed or discover
new local releases automatically.

Switching to Remote and clicking **Install remote package** deliberately
reinstalls from the configured pip index, including resolved dependencies, so
a private local build can be replaced by a published one. Local-wheel installs
can also fetch missing dependencies from that index; they are not offline
installs. Use an isolated test environment and restart the WinTestKit server
after replacing a package used by an existing backend process.

Normal `npm run build` and `npm run package` always compile local installation
support out. They expose no package-source selector and reject source-change
messages, even with saved development state. There is no workspace setting or
environment-variable switch to enable it in a production VSIX; install the
regular VSIX again to remove development functionality. Production no longer
offers editable local installs based on a workspace `pyproject.toml`. This
separates the extension's install paths; it is not a sandbox for Python itself
and cannot protect an interpreter or pip configuration already compromised
outside the extension.

## Retesting the introduction

In the development VSIX, press **Ctrl+Shift+P** and run
**WinTestKit: Development: Reset Repository and Introduction**. Open the test
repository by itself and save any edited files first. The command previews the
cleanup and asks for confirmation before changing anything.

It backs up affected files to a wintestkit-reset-* directory in the system
temporary folder, then removes the entire pages, flows, and tests folders
(including custom code), WinTestKit settings, generated AI skill, reports/results,
and pytest cache. It removes legacy WinTestKit configuration from pyproject.toml
and removes pytest configuration only when it exactly matches the starter template.
Other project configuration, Git history, .gitignore, the selected interpreter,
the installed Python package, and development wheel selection are preserved.
Keep the reported backup path if you need to restore anything; temporary backups
are not permanent storage. Linked cleanup targets are refused.

The command clears WinTestKit workspace state and reloads the window. Click
**Enable for this workspace** to start the introduction again; interpreter and
package checks still reflect what is actually installed. This command and cleanup
implementation are absent from the standard VSIX. Setup instructions point to
the real UI controls; only introduction navigation and cancellation remain in
the guide itself.

## Desktop tests and Calculator example

The Python desktop tests exercise native application error handling, overlay lifecycle and
screenshots without a fixture application:

```powershell
cd python
uv run pytest -m integration
```

Desktop tests require an interactive, unlocked Windows session.

For the extension end-to-end tests, prepare the backend with `uv sync --directory python`,
then run `npm run test:integration` from `vscode/`. The suite opens the
[Calculator project](../examples/calculator-tests) and checks static discovery and CodeLens;
it does not launch Calculator or require a demo executable.

To run the example UI scenarios, follow the [Calculator example instructions](../examples/calculator-tests).
No application source or binaries are bundled.

## Continuous integration

The [CI workflow](../.github/workflows/ci.yml) checks Python lint, formatting, types and
non-desktop tests, smoke-tests the wheel, and checks and packages the extension. It does
not build an example app or run desktop suites.

### Desktop CI runner

The separate [desktop workflow](../.github/workflows/desktop.yml) runs on pushes to
`master` and by manual dispatch on `master`; it never runs on pull requests. It wakes and checks the
display, builds the unsigned inspector payload, runs the live tests and six-cell matrix,
and uploads reports. Manual dispatch can optionally enable the stress tests. Hosted CI
does not wait for this runner.

On the Windows runner install Visual Studio C++ build tools, the SDK pinned by
`wpf-inspector/global.json`, .NET 8 and 10 Desktop Runtimes in **both x86 and x64**,
the .NET Framework 4.8 Developer Pack (including its SDK tools), Python 3.12, uv, and
Windows PowerShell 5.1 (`powershell.exe`). Put `uv` and the SDK's `dotnet.exe` on the runner's
PATH. Alternatively set `DOTNET_ROOT` for the runner process to the SDK directory;
it must contain the required x64 runtimes as well. If runtimes are installed elsewhere,
set `WTK_MATRIX_DOTNET_ROOT_X86` and `WTK_MATRIX_DOTNET_ROOT_X64` to their respective
runtime roots before launching the runner. The .NET Framework 4.8 runtime must also be present.
For local live tests, the x64 .NET 10 runtime root is selected from `DOTNET_ROOT`,
the directory of `dotnet.exe` on PATH (the SDK resolver default),
`%LOCALAPPDATA%\wintestkit-dev\dotnet`, then `C:\Program Files\dotnet`.
The first root containing both .NET 10 Core and Windows Desktop runtimes is used.

In the repository's GitHub **Settings → Actions → Runners**, choose **New self-hosted
runner**, select Windows, and follow GitHub's download and `config.cmd` instructions.
Register it for this repository with the custom label `wintestkit-desktop`; GitHub adds
the `self-hosted` and `windows` labels automatically. Log into the Windows desktop and
start `run.cmd` from that session, **not as a Windows service**. Leave the session
logged in and unlocked, prevent screen lock and system/display sleep during runs, keep
the display connected and on, and leave the desktop free for the tests. The preflight
fails if the session is inaccessible or the capture is black. The wake helper is not a
substitute for those Windows power and lock settings. To remove the runner, stop it and
run `config.cmd remove` from its installation directory.

**Security:** A self-hosted runner in a public repository executes workflow code on a
personal machine, with access to that account and its files. This workflow accepts only
trusted pushes to `master` and manual dispatch, never PR code or fork-triggered workflow
runs; protect `master` and restrict who can dispatch workflows. In repository Actions
settings, require approval for all outside collaborators' fork workflows as an additional
precaution. Use a dedicated non-admin Windows account if possible, keep its credentials and
files separate, and review workflow changes before merging. No secrets are used by this job.

Shared [JSON schemas](../schemas/README.md) define the Python/editor contracts. Run
`npm run gen:types` in `vscode/` after changing schemas and commit the generated types.

## WPF inspector (preview)

**Preview:** The inspector is unreleased. `wpf-inspector/src/Protocol` contains the codec,
`src/Agent` the in-process service, `src/Launcher` the loader, `protocol` schemas and fixtures,
`tests` unit/integration tests and owned WPF fixtures, and `third_party` pinned Snoop sources.
`inspector-payload` stages the distributable payload. Use the SDK pinned by
`wpf-inspector/global.json` (10.0.400, latest patch roll-forward). Native loader builds need
the .NET Framework 4.8 Developer Pack as well as the Windows build toolchain.

From the repository root, run `scripts/build_inspector.ps1` and
`scripts/check_inspector.ps1 -Suite Unit` (also `Security`, `Integration`, `Matrix`, `Stress`,
or `Package` as appropriate). Matrix and live integration require suitable runtimes,
architectures and an interactive desktop; packaging alone does not verify them. The owned
fixture supplies controlled WPF targets and a test-only control pipe. Set
`WTK_INSPECTOR_REAL=1` for the Python live inspector tests on a suitable Windows desktop.
CI/non-desktop checks are not a substitute for these live gates. See the
[verification notes](plans/wpf-inspector-implementation-brief.md#s8-managed-locator-verification-2026-10-29)
and [release guide](releasing.md) before claiming compatibility or publishing.

## Releasing

Follow the [release guide](releasing.md) for PyPI trusted-publisher setup, independent
publication switches, local validation, dry runs, version/channel selection and recovery
from partial publication. PyPI, Marketplace, Open VSX and public VSIX uploads are
independent switches; leave a switch off to keep that destination unpublished. Only enabled
targets require publishing credentials.
Packaging success does not establish installed-extension, native WPF or ARM64 acceptance.

## Commit messages

Write commits in the format described in [commit messages](commit-messages.md):
`type(scope): short description`, then a body of one bullet per change.
