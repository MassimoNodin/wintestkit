# WinTestKit

The Elements view mirrors discovered screens and nests elements under their
`within` containers. Click an entry to jump to its definition; inline actions
highlight or check elements and check complete screens. Check results update the
tree icons. Multiple project roots appear as separate groups.

UI test automation for Windows WPF applications.

The extension resolves the selected Python interpreter (or `wintestkit.pythonPath`),
starts a per-project Python JSON-RPC server, and displays application state in the
status bar. Launch App, Close App, Restart Server, Check Environment, Install Package,
and Show Output are functional. Python CodeLens provides Highlight, Check, and
Check All Elements actions; checks show gutter results and editor warnings.
Test Explorer and Run Test CodeLens stream pytest progress, output, parameterized
cases, and failure details. Cancellation stops the full test process tree. Runs
queue per project. The Elements tree and Spy panel await their milestones.
Debug Test uses Python Debugger (debugpy), supports normal source breakpoints,
and streams results to the same Test Explorer. Debug waits allow up to one hour.

Initialize Project creates a starter screen and smoke test without overwriting
existing files. If Python's pytest discovery is also enabled, WinTestKit offers
to disable that workspace's duplicate test explorer; keeping both is supported.

Open the examples project folder in a trusted workspace and select an interpreter
with `wintestkit` installed. A missing package produces an installation prompt; the
development repository can install `python/` in editable mode. Server crashes retry
with backoff and stop after three crashes in a minute. Use Restart Server after
installing the package or changing its configuration. Deactivation shuts down
servers without closing your application.

Projects are detected from pyproject.toml files with a tool.wintestkit table,
including nested projects and multi-root workspaces. Discovery refreshes on file
changes and uses unsaved Python document contents after a 400 ms debounce.
Discovery errors appear as editor warnings. Elements Refresh rescans projects.

## Development

Run `npm ci`, then `npm run build`, `npm run typecheck`, `npm run lint`, and `npm test`.
Use the repository's Run Extension launch configuration for an Extension Development Host.
`npm run test:integration` downloads an isolated VS Code host and installs its Python extension.
`npm run package` builds a Windows x64 VSIX in `dist/`.
Protocol generation (`npm run gen:types`) requires the schemas added in T0.5.
