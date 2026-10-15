<img src="assets/icon.svg" width="64" height="64" alt="">

# WinTestKit

WinTestKit is UI test automation for Windows WPF applications. Describe your application's windows
and controls as Python classes, write tests with pytest, and run them from the command line, CI or
VS Code. Controls are found with Microsoft UI Automation: no image matching, and nothing to change
in the application under test.

```python
from wintestkit import Element, Screen, Window, expect


class MainScreen(Screen):
    window = Window(title="WTK Demo")

    credentials = Element(control_type="Group", name="Credentials")
    username = Element(control_type="Edit", class_name="TextBox", within=credentials)
    password = Element(control_type="Edit", class_name="PasswordBox", within=credentials)
    sign_in = Element(control_type="Button", name="Sign in", within=credentials)
    status = Element(automation_id="StatusText")


def test_valid_login(app):
    main = MainScreen(app)
    main.username.type("admin")
    main.password.type("secret")
    main.sign_in.click()
    expect(main.status).to_have_text("Welcome, admin")
```

- **`wintestkit` Python package**: UI Automation engine with strict locators and automatic
  waiting, `Screen`/`Element` model, `expect` assertions, pytest plugin, HTML report and JUnit
  XML, and the `wtk` CLI (`run`, `spy`, `inspect`, `highlight`, `check`, `doctor`, `init`,
  `report`).
- **VS Code extension**: Highlight/Check CodeLens above elements, Test Explorer with run and debug,
  an Elements view, a Spy with click-to-insert locators, and report notifications.

**Get started:** read the [user guide](docs/guide/index.md). The
[`examples/demo-tests`](examples/demo-tests) project tests the WPF demo app in [`demo/`](demo).

Design background: the [implementation plan](docs/plan/README.md) and
[research notes](docs/research.md).

## Development

Install Python 3.12+ and uv. From the repository root:

```powershell
cd python
uv sync
uv run pytest
uv run wtk
uv run python -m wintestkit
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

Unit tests (`uv run pytest -m "not integration"`) do not need an interactive desktop.
`uv run pytest -m integration` drives the real demo app: it requires Windows, an unlocked desktop
and a built demo app at `demo/DemoApp/bin/Release/net8.0-windows/DemoApp.exe` or the path set in
`WTK_DEMO_APP`.
See [the demo guide](demo/README.md) for controls and UI Automation observations.

### WPF demo app

On Windows with the .NET 8 SDK installed, run from the repository root:

```powershell
dotnet build demo/DemoApp/DemoApp.csproj -c Release
& ./demo/DemoApp/bin/Release/net8.0-windows/DemoApp.exe
```

The demo has credentials, duplicate buttons, asynchronous loading, virtualized lists and grids,
and modal dialogs. It deliberately exposes very few application-defined AutomationIds.

### VS Code extension

```powershell
cd vscode
npm ci
npm run build
npm run typecheck
npm run lint
npm test
npm run test:integration
npm run package
```

Open the repository in VS Code and use the Run Extension launch configuration (F5). Packaging
writes a Windows x64 VSIX into `vscode/dist/`. `npm run test:integration` opens
`examples/demo-tests` in a test instance of VS Code and drives the demo app.

### Continuous integration

The CI workflow runs on Windows for pushes to `main`/`master` and pull requests. Independent
jobs check Python lint, formatting, types, and unit tests; lint, typecheck, test, and package the
extension; and build the demo with warnings treated as errors. The `python` job also builds the
wheel and smoke-tests it in a fresh environment (`scripts/check_wheel.ps1`). The `integration`
job runs the desktop integration tests, the example project and the extension's end-to-end tests
against the built demo; it is allowed to fail until hosted runners prove reliable.

Shared [JSON schemas](schemas/README.md) define the Python/editor contracts. Run
`npm run gen:types` in `vscode/` after schema changes and commit the generated types. CI checks
generation drift, Python contract validation, and statically checked TypeScript examples.

### Releasing

`python scripts/bump_version.py X.Y.Z` sets the version of the Python package and the extension.
Add a section to `vscode/CHANGELOG.md`, commit, and push a `vX.Y.Z` tag: the release workflow
verifies the versions, builds the wheel, sdist and VSIX files (`win32-x64`, `win32-arm64`) and
creates a GitHub Release. Publishing to PyPI, the Visual Studio Marketplace and Open VSX runs in
the `release` environment and only for the configured credentials: the `PUBLISH_PYPI` variable
(trusted publishing), `AZURE_CLIENT_ID`/`AZURE_TENANT_ID` secrets, and `OVSX_TOKEN`. Run the
workflow manually with `dry_run` to build everything without releasing.

Created in [T3 Code](https://t3.codes).
