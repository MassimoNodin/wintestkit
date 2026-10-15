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

Shared [JSON schemas](../schemas/README.md) define the Python/editor contracts. Run
`npm run gen:types` in `vscode/` after changing schemas and commit the generated types.

## Releasing

Run `python scripts/bump_version.py X.Y.Z` to update the Python and extension versions.
Add an entry to `vscode/CHANGELOG.md`. The [release workflow](../.github/workflows/release.yml)
builds the Python distributions and VSIX packages for a version tag and can also be run
manually with `dry_run`. Publishing depends on the credentials configured in that workflow.

The [implementation plan](plan/README.md) and [research notes](research.md) are historical
design context, not installation instructions.
