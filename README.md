<img src="assets/icon.svg" width="64" height="64" alt="">

# WinTestKit

WinTestKit is UI test automation for Windows WPF applications, built around Microsoft UI
Automation, Python screen and element definitions, and pytest. The planned toolkit includes a
`wtk` command-line interface and a VS Code extension for inspecting elements, running tests,
and viewing reports. The project is currently at the initial Python scaffold stage; UI automation
and the editor extension are not implemented yet.

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
The demo app will be added in task T0.3.

Created in [T3 Code](https://t3.codes).
