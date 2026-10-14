<img src="assets/icon.svg" width="64" height="64" alt="">

# WinTestKit

WinTestKit is UI test automation for Windows WPF applications, built around Microsoft UI
Automation, Python screen and element definitions, and pytest. The planned toolkit includes a
`wtk` command-line interface and a VS Code extension for inspecting elements, running tests,
and viewing reports. The Python package and VS Code extension scaffolds are available;
the UI Automation engine and functional editor integrations are not implemented yet.

See the [implementation plan](docs/plan/README.md) and [background research](docs/research.md).

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

Both CLI entry points currently print `wintestkit 0.1.0`. Unit tests do not need an interactive
desktop. Integration tests require Windows and, when using the demo app fixture, a built demo app
at `demo/DemoApp/bin/Release/net8.0-windows/DemoApp.exe` or the path set in `WTK_DEMO_APP`.
The demo app is developed separately in task T0.3.

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

Open the repository in VS Code and use the Run Extension launch configuration (F5).
The scaffold logs `WinTestKit activated` to the WinTestKit output channel; commands other than
Show Output are placeholders. Packaging writes a Windows x64 VSIX into `vscode/dist/`.

Created in [T3 Code](https://t3.codes).
