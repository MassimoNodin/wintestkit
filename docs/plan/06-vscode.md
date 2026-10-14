# 06 — VS Code Extension (T0.2, T4.1–T6.2)

The extension is a **thin client**: all UI Automation, discovery and test execution happen in the
Python package. The extension finds Python, starts `wtk serve --stdio` per project, renders results.

## Source layout (target)

```
vscode/
├─ package.json
├─ src/
│  ├─ extension.ts               # activate/deactivate, wires services
│  ├─ log.ts                     # OutputChannel "WinTestKit" (LogOutputChannel)
│  ├─ python.ts                  # interpreter resolution (T4.1)
│  ├─ projects.ts                # project root detection, per-project state (T4.2)
│  ├─ server/
│  │  ├─ jsonrpc.ts              # NDJSON JSON-RPC client, pure (no vscode import) (T4.1)
│  │  └─ serverManager.ts        # spawn/restart per project (T4.1)
│  ├─ protocol/generated.ts      # generated from /schemas (T0.5)
│  ├─ discovery/store.ts         # DiscoveryStore (T4.2)
│  ├─ editor/
│  │  ├─ codeLens.ts             # (T4.3)
│  │  ├─ lensModel.ts            # pure: discovery -> lens specs (T4.3)
│  │  ├─ highlightCommands.ts    # (T4.3)
│  │  ├─ diagnostics.ts          # (T4.3)
│  │  └─ decorations.ts          # (T4.3)
│  ├─ testing/
│  │  ├─ controller.ts           # (T4.4)
│  │  ├─ eventServer.ts          # TCP NDJSON listener (T4.4)
│  │  ├─ eventMapper.ts          # pure: RunEvent -> actions (T4.4)
│  │  ├─ runner.ts               # spawn wtk run (T4.4)
│  │  └─ debug.ts                # (T4.5)
│  ├─ views/elementsTree.ts      # (T5.1)
│  ├─ spy/
│  │  ├─ spyView.ts              # WebviewViewProvider (T6.1)
│  │  ├─ messages.ts             # webview message types (T6.1)
│  │  └─ insertElement.ts        # pure text edit computation + command (T6.2)
│  ├─ statusBar.ts               # (T4.1)
│  ├─ init.ts                    # Initialize project command (T4.6)
│  ├─ pytestConflict.ts          # (T4.6)
│  └─ report.ts                  # (T7.2)
├─ media/
│  ├─ icon.png  activity.svg
│  └─ spy/ spy.html  spy.css  spy.js
└─ test/
   ├─ unit/*.test.ts             # vitest
   └─ integration/               # @vscode/test-electron + mocha (T4.7)
```

## `package.json` contributions (complete list — tasks fill in implementations)

```jsonc
{
  "name": "wintestkit", "publisher": "wintestkit", "displayName": "WinTestKit",
  "description": "UI test automation for Windows WPF apps — highlight elements, run tests, inspect UI.",
  "version": "0.1.0", "license": "MIT", "icon": "media/icon.png",
  "engines": { "vscode": "^1.95.0" },
  "categories": ["Testing"],
  "extensionKind": ["ui"],
  "extensionDependencies": ["ms-python.python"],
  "main": "./dist/extension.js",
  "activationEvents": ["workspaceContains:**/pyproject.toml"],
  "contributes": {
    "commands": [
      { "command": "wintestkit.highlightElement", "title": "Highlight Element", "category": "WinTestKit", "icon": "$(eye)" },
      { "command": "wintestkit.checkElement", "title": "Check Element", "category": "WinTestKit", "icon": "$(check)" },
      { "command": "wintestkit.checkScreen", "title": "Check All Elements", "category": "WinTestKit", "icon": "$(checklist)" },
      { "command": "wintestkit.runTest", "title": "Run Test", "category": "WinTestKit", "icon": "$(play)" },
      { "command": "wintestkit.debugTest", "title": "Debug Test", "category": "WinTestKit", "icon": "$(debug-alt)" },
      { "command": "wintestkit.launchApp", "title": "Launch App", "category": "WinTestKit" },
      { "command": "wintestkit.closeApp", "title": "Close App", "category": "WinTestKit" },
      { "command": "wintestkit.restartServer", "title": "Restart Server", "category": "WinTestKit" },
      { "command": "wintestkit.showOutput", "title": "Show Output", "category": "WinTestKit" },
      { "command": "wintestkit.openReport", "title": "Open Last Report", "category": "WinTestKit" },
      { "command": "wintestkit.runDoctor", "title": "Check Environment (doctor)", "category": "WinTestKit" },
      { "command": "wintestkit.initProject", "title": "Initialize Project", "category": "WinTestKit" },
      { "command": "wintestkit.installPackage", "title": "Install wintestkit Package", "category": "WinTestKit" },
      { "command": "wintestkit.spy.startPick", "title": "Pick Element", "category": "WinTestKit", "icon": "$(inspect)" },
      { "command": "wintestkit.spy.refresh", "title": "Refresh", "category": "WinTestKit", "icon": "$(refresh)" },
      { "command": "wintestkit.elements.refresh", "title": "Refresh", "category": "WinTestKit", "icon": "$(refresh)" },
      { "command": "wintestkit.elements.goTo", "title": "Go to Definition", "category": "WinTestKit" }
    ],
    "viewsContainers": { "activitybar": [ { "id": "wintestkit", "title": "WinTestKit", "icon": "media/activity.svg" } ] },
    "views": {
      "wintestkit": [
        { "id": "wintestkit.elements", "name": "Elements" },
        { "id": "wintestkit.spy", "name": "Spy", "type": "webview" }
      ]
    },
    "viewsWelcome": [
      { "view": "wintestkit.elements", "contents": "No WinTestKit project found.\n[Initialize Project](command:wintestkit.initProject)", "when": "!wintestkit.hasProject" }
    ],
    "menus": {
      "view/title": [
        { "command": "wintestkit.elements.refresh", "when": "view == wintestkit.elements", "group": "navigation" },
        { "command": "wintestkit.spy.startPick", "when": "view == wintestkit.spy", "group": "navigation" },
        { "command": "wintestkit.spy.refresh", "when": "view == wintestkit.spy", "group": "navigation" }
      ],
      "view/item/context": [
        { "command": "wintestkit.highlightElement", "when": "view == wintestkit.elements && viewItem =~ /^(element|window)$/", "group": "inline" },
        { "command": "wintestkit.checkElement", "when": "view == wintestkit.elements && viewItem == element", "group": "inline" },
        { "command": "wintestkit.checkScreen", "when": "view == wintestkit.elements && viewItem == screen", "group": "inline" }
      ],
      "commandPalette": [
        { "command": "wintestkit.highlightElement", "when": "false" },
        { "command": "wintestkit.checkElement", "when": "false" },
        { "command": "wintestkit.runTest", "when": "false" },
        { "command": "wintestkit.debugTest", "when": "false" },
        { "command": "wintestkit.elements.goTo", "when": "false" }
      ]
    },
    "configuration": {
      "title": "WinTestKit",
      "properties": {
        "wintestkit.pythonPath": { "type": "string", "default": "", "description": "Python interpreter to use. Empty = the Python extension's selected interpreter." },
        "wintestkit.codeLens.enabled": { "type": "boolean", "default": true },
        "wintestkit.highlight.durationMs": { "type": "number", "default": 1500, "minimum": 200, "maximum": 10000 },
        "wintestkit.run.extraArgs": { "type": "array", "items": { "type": "string" }, "default": [], "description": "Extra arguments passed to `wtk run`." },
        "wintestkit.run.highlightActions": { "type": "boolean", "default": false, "description": "Flash each element before acting during runs from VS Code." },
        "wintestkit.server.logLevel": { "type": "string", "enum": ["debug", "info", "warning", "error"], "default": "info" },
        "wintestkit.promptDisablePytestExplorer": { "type": "boolean", "default": true }
      }
    }
  }
}
```

Context keys set by the extension: `wintestkit.hasProject`, `wintestkit.appRunning`,
`wintestkit.picking`.

---

## T0.2 — Extension scaffold <a id="t02"></a>

- **Depends on:** — · **Size:** S
- **Files:** `vscode/package.json` (manifest minus implementations: commands may log
  "not implemented"), `tsconfig.json`, `esbuild.mjs`, `.vscodeignore`, `eslint.config.mjs`,
  `vitest.config.ts`, `src/extension.ts`, `src/log.ts`, `test/unit/smoke.test.ts`,
  `test/integration/{runTest.ts,suite/index.ts,suite/activation.test.ts}`, `media/icon.png`
  (export of `assets/icon.svg` at 128×128), `media/activity.svg` (monochrome version).
- **Spec:**
  - Scripts: `build` (esbuild bundle, `--external:vscode`, sourcemaps), `watch`, `typecheck`
    (`tsc --noEmit`), `lint`, `test` (vitest run), `test:integration` (`node
    ./out/test/integration/runTest.js` after `tsc -p test`), `package` (`vsce package --target
    win32-x64 -o dist/`), `gen:types` (T0.5).
  - Dev dependencies: `typescript`, `esbuild`, `@types/vscode@1.95`, `@types/node@20`,
    `eslint`, `typescript-eslint`, `prettier`, `vitest`, `@vscode/test-electron`, `mocha`,
    `@types/mocha`, `@vscode/vsce`, `ovsx`, `json-schema-to-typescript`.
  - Runtime dependency: `@vscode/python-extension` (only runtime dep allowed).
  - `.vscode/launch.json` + `tasks.json` at repo root for "Run Extension" (opens
    `examples/demo-tests` as the dev workspace).
- **Done when:** `npm ci && npm run build && npm run typecheck && npm run lint && npm test`
  pass; F5 launches an Extension Development Host where the extension activates and logs
  `WinTestKit activated` to its output channel; `npm run package` produces a `.vsix`.

---

## T4.1 — Interpreter resolution, server client, status bar <a id="t41"></a>

- **Depends on:** T0.2, T0.5, T3.8 · **Size:** M
- **Files:** `src/python.ts`, `src/server/jsonrpc.ts`, `src/server/serverManager.ts`,
  `src/statusBar.ts`, `test/unit/jsonrpc.test.ts`
- **Spec:**
  - **`python.ts`:** `getInterpreter(folder: Uri): Promise<string | undefined>` — if
    `wintestkit.pythonPath` is set, use it; else `PythonExtension.api()` →
    `environments.getActiveEnvironmentPath(folder)` → `resolveEnvironment` →
    `executable.uri.fsPath`. Event `onDidChangeInterpreter(folder)` from
    `environments.onDidChangeActiveEnvironmentPath`. `checkWintestkit(python): Promise<{ installed:
    boolean; version?: string }>` runs `python -c "import wintestkit,sys;print(wintestkit.__version__)"`
    (10 s timeout).
  - **`jsonrpc.ts`** (pure, unit-tested with fake streams): `class JsonRpcClient { constructor(
    write: (line: string) => void); handleLine(line: string): void; request<R>(method: string,
    params?: unknown, timeoutMs = 30000): Promise<R>; onNotification(method, handler): Disposable;
    dispose(): void }`. Incrementing integer ids; rejects with `RpcError { code, message, data }`;
    timeouts reject with code `-1`; `dispose` rejects all pending with "server stopped". A
    `LineSplitter` handles partial chunks / `\r\n`.
  - **`serverManager.ts`:** `ServerManager.get(project: Project): Promise<ServerConnection>` —
    one server per project root, started lazily: `spawn(python, ["-m", "wintestkit", "serve",
    "--stdio", "--log-level", level], { cwd: root, env: { ...process.env, PYTHONUNBUFFERED: "1",
    PYTHONIOENCODING: "utf-8" } })`. stdout → `handleLine`; stderr → output channel (prefixed with
    project name). After spawn, `initialize { root }`; if `protocolVersion !== 1` show error
    "WinTestKit extension and Python package versions are incompatible" with
    [Install matching version]. Crash handling: restart with backoff (1 s, 2 s, 4 s); after 3
    crashes within 60 s stop and show an error with [Show Output] [Restart]. On interpreter
    change: dispose and restart. `deactivate` sends `shutdown` (1 s grace) then kills.
  - If `wintestkit` isn't installed in the interpreter: status bar shows "WTK: not installed";
    a one-time notification "The wintestkit package isn't installed in <env>." [Install]
    [Select Interpreter]. `wintestkit.installPackage` runs `"<python>" -m pip install -U
    wintestkit` in a new terminal named "WinTestKit" (if the workspace contains
    `python/pyproject.toml` with `name = "wintestkit"` — the dev repo — offer
    `pip install -e <repo>/python` instead).
  - **`statusBar.ts`:** left-aligned item, priority 100: `$(beaker) WTK` + state suffix:
    `$(circle-filled) app running` / `$(circle-outline) app stopped` / `$(error) server error` /
    `$(warning) not installed`. Poll `app.status` every 5 s while the window is focused (and on
    demand). Click → QuickPick: Launch App, Close App, Restart Server, Open Last Report, Check
    Environment, Show Output. Sets context key `wintestkit.appRunning`.
  - Commands implemented here: `launchApp`, `closeApp`, `restartServer`, `showOutput`, `runDoctor`
    (runs `python -m wintestkit doctor` in the "WinTestKit" terminal).
- **Done when:** jsonrpc unit tests (partial lines, out-of-order responses, errors, timeouts,
  notifications, dispose); manual: in the dev host with examples workspace, status bar shows app
  state, Launch App starts the demo, killing the server process triggers a restart.

---

## T4.2 — Project roots + discovery store <a id="t42"></a>

- **Depends on:** T4.1 · **Size:** M
- **Files:** `src/projects.ts`, `src/discovery/store.ts`, `test/unit/projects.test.ts`
- **Spec:**
  - **Project detection:** `workspace.findFiles("**/pyproject.toml", "**/{node_modules,.venv,venv,.git,site-packages}/**")`;
    a project root is the directory of a `pyproject.toml` whose text matches
    `/^\s*\[tool\.wintestkit(\.app)?\]/m`. Re-scan on create/delete/change of any
    `pyproject.toml` (FileSystemWatcher). Set context `wintestkit.hasProject`.
    `projectFor(uri): Project | undefined` = deepest project root containing the file.
    (Pure helper `pickProject(roots: string[], file: string)` unit-tested; case-insensitive on
    Windows.)
  - **DiscoveryStore:** per project, holds the latest `DiscoveryResult`. Refresh triggers:
    activation, server (re)start, `*.py` saved/created/deleted/renamed in the project (watcher),
    open-document edits (debounced 400 ms; sends `overrides` for all dirty Python documents in
    that project). Exposes `onDidChange(project)`, `get(project)`, lookups
    `elementAt(uri, line)`, `testAt(uri, line)`, `screenById`, `testById`, `elementById`.
    Concurrent refreshes coalesce (latest wins).
  - Discovery errors (`errors[]`) appear as Warning diagnostics in a `wintestkit-discovery`
    DiagnosticCollection.
- **Done when:** unit tests for `pickProject` and debounce/coalescing logic (with fake timers and a
  fake client); manual: editing a screen file updates lookups without saving.

---

## T4.3 — CodeLens, Highlight/Check commands, diagnostics, decorations <a id="t43"></a>

- **Depends on:** T4.2 · **Size:** M
- **Files:** `src/editor/lensModel.ts`, `src/editor/codeLens.ts`,
  `src/editor/highlightCommands.ts`, `src/editor/diagnostics.ts`, `src/editor/decorations.ts`,
  `test/unit/lensModel.test.ts`
- **Spec:**
  - **Lens model** (pure): `buildLenses(discovery: DiscoveryResult, file: string, lastResults:
    Map<string, TestOutcome>): LensSpec[]` where `LensSpec = { line: number; title: string;
    command: string; args: unknown[]; tooltip: string }`. Lenses at the entry's `range.start.line`
    (the decorator line for decorated tests):
    | Entry | Lenses (in order) |
    |---|---|
    | element (kind `element`/`elements`) | `$(eye) Highlight element` → `wintestkit.highlightElement {file, qualname}` · `$(check) Check` → `wintestkit.checkElement {file, qualname}` |
    | window | `$(eye) Highlight window` → `wintestkit.highlightElement {file, qualname}` |
    | screen class | `$(checklist) Check all elements` → `wintestkit.checkScreen {file, screen}` |
    | test function / method | `$(play) Run test` → `wintestkit.runTest {id}` · `$(debug-alt) Debug test` → `wintestkit.debugTest {id}` · last result if known: `$(pass-filled) Passed` / `$(error) Failed` / `$(debug-step-over) Skipped` (no command; tooltip shows duration) |
    | test class | `$(play) Run tests` · `$(debug-alt) Debug tests` |
    Elements marked `dynamic: true` still get lenses (resolution happens in Python).
    Tooltip for element lenses: the locator description (render `LocatorData` → same format as
    Python `describe()`; implement `describeLocator()` in TS and unit-test it against fixture
    pairs shared with Python tests in `python/tests/contract/fixtures/describe_cases.json` — T1.7
    adds that file).
  - **CodeLensProvider** for `{ language: "python", scheme: "file" }`, files inside a project only;
    `onDidChangeCodeLenses` fires on store change; disabled when `wintestkit.codeLens.enabled` is
    false.
  - **highlightElement** command: `server.request("element.highlight", {file, qualname,
    durationMs: setting})` with a progress notification only if it takes > 500 ms.
    - `found` → status bar message (5 s): `$(eye) Found Button "Sign in"`; clear any diagnostic on
      that element.
    - `not_found`/`ambiguous` → `showWarningMessage(diagnostic.message, "Show Details", "Open Spy")`;
      "Show Details" writes `formatDiagnostic()` (TS port of Python `Diagnostic.format()`) to the
      output channel and reveals it; also set a Warning `Diagnostic` on the element's `nameRange`
      (source `WinTestKit`, message = `diagnostic.message`, `relatedInformation` none).
    - RPC error -32002 (app not running) → `showInformationMessage("The app isn't running.",
      "Launch App")` → on Launch: `app.launch` then retry the highlight once.
    - -32003 (target/import error) → error message with the server-provided text + "Show Output".
  - **checkElement**: same as highlight but calls `screen.check` for the single element (filter
    results) — no flashing; shows the result inline via decorations only.
  - **checkScreen**: `screen.check`; applies decorations to all elements of that screen and
    updates the Elements tree (T5.1 subscribes to a `CheckResultsStore` defined here:
    `Map<elementId, CheckResult>` + `onDidChange`). Summary message: `Checked 12 elements: 11 found,
    1 missing.`
  - **Decorations:** three `TextEditorDecorationType`s with gutter icons (codicon-style SVGs in
    `media/`: green check, red cross, yellow warning) and an `after` text (`  ✓ found`,
    `  ✗ not found`, `  ⚠ 2 matches`) in the theme's `editorCodeLens.foreground` colour. Cleared
    for an element when its line range is edited (`onDidChangeTextDocument` intersecting the
    element's range) or a new result arrives.
- **Done when:** lensModel unit tests (each entry type, decorated test line, last-result lens,
  describeLocator cases); manual in dev host: Highlight element flashes Sign in in the demo, a
  misspelled element shows the warning + diagnostic, app-not-running prompt launches the app.

---

## T4.4 — Test controller (run profile) <a id="t44"></a>

- **Depends on:** T4.2, T2.8, T3.2 · **Size:** L
- **Files:** `src/testing/controller.ts`, `src/testing/eventServer.ts`,
  `src/testing/eventMapper.ts`, `src/testing/runner.ts`, `test/unit/eventMapper.test.ts`
- **Spec:**
  - `vscode.tests.createTestController("wintestkit", "WinTestKit")`. One root `TestItem` per
    project (label = folder name relative to workspace) when there are multiple projects; else
    files are top-level. Hierarchy: file → class → function (from discovery `tests`, using
    `parent`). `TestItem.id` = nodeid prefixed with the project root path + `|` to keep ids unique
    across projects; `uri` + `range` from discovery. Parametrized children are created dynamically
    when `collected`/`test_start` events reference `id[...]` (parent = un-parametrized id).
    `refreshHandler` → store refresh. Item tags: none in v1.
  - **Run profile** "Run" (`TestRunProfileKind.Run`, default):
    1. Map `request.include` (or all) minus `request.exclude` to nodeids (a file item → file
       path, class → class nodeid).
    2. `EventServer.listen()` on `127.0.0.1:0` (Node `net`), accepts one connection, splits lines,
       `JSON.parse`, emits `RunEvent`.
    3. `runner.ts`: `spawn(python, ["-m", "wintestkit", "run", "--events", "tcp://127.0.0.1:<port>",
       ...(highlightActions ? ["--highlight"] : []), ...extraArgs, "--", ...nodeids], { cwd:
       root })`. stdout/stderr → `run.appendOutput` (convert `\n` → `\r\n`).
    4. `eventMapper.ts` (pure): consumes events and emits abstract actions `{ kind: "enqueue" |
       "started" | "passed" | "failed" | "skipped" | "errored" | "output" | "createChild";
       id; ... }`, which `controller.ts` applies to the `TestRun`. On `test_start`: `run.started`.
       On `step`: append `"  ▸ click MainScreen.sign_in (0.12s)\r\n"` to output with the test item.
       On `test_end`: passed → `run.passed(item, duration*1000)`; failed → `run.failed(item,
       messages, duration)`; error → `run.errored`; skipped → `run.skipped`.
    5. **Failure message:** `TestMessage` with `MarkdownString`: first line `message`; if `error.diagnostic`
       present, a fenced block with the formatted diagnostic; screenshot links
       `[window.png](file:///...)`; `location` from event (`file`, 0-based `line`) → `new
       Location(Uri.file(file), new Position(line, 0))`. For `expect` failures that include
       `Expected:`/`Actual:` lines, also set `expectedOutput`/`actualOutput` on a second plain
       `TestMessage` so the diff view works.
    6. Cancellation token → `taskkill /PID <pid> /T /F`; items still running → `run.skipped`.
    7. Process exit without `session_end` → all unfinished items `errored` with message "Test
       process exited unexpectedly (code N). See output.".
    8. `session_end.reportPath` stored for `openReport` (T7.2). Results feed the "last result"
       CodeLens map.
  - `wintestkit.runTest {id}` command → look up the TestItem, create
    `new TestRunRequest([item], undefined, runProfile)` and call the profile's `runHandler`
    directly (don't use `testing.runAtCursor`; it depends on cursor position).
  - Only one run at a time per project; a second request while running → queue it (FIFO).
- **Done when:** eventMapper unit tests replaying `python/tests/contract/fixtures/events.ndjson`
  plus generated cases (parametrized, error in setup, unexpected exit); manual: Run test from
  CodeLens and Test Explorer shows live results, failure message with diagnostic and clickable
  screenshot, cancel kills the run.

---

## T4.5 — Debug profile <a id="t45"></a>

- **Depends on:** T4.4 · **Size:** M
- **Files:** `src/testing/debug.ts`
- **Spec:**
  - Profile "Debug" (`TestRunProfileKind.Debug`). Starts the `EventServer` as in T4.4, then:
    ```ts
    vscode.debug.startDebugging(workspaceFolder, {
      type: "debugpy", request: "launch", name: "WinTestKit: Debug tests",
      module: "wintestkit",
      args: ["run", "--events", url, "--no-report", "--no-env-check", "--timeout", "3600", "--", ...nodeids],
      cwd: projectRoot, python: interpreterPath, console: "internalConsole",
      justMyCode: true, env: { PYTHONUNBUFFERED: "1" }
    }, { testRun: run })
    ```
    Timeout is raised to 3600 s so auto-waits don't fail while stopped at breakpoints.
  - Map events exactly like T4.4 (reuse `eventMapper`). The run ends when the debug session
    terminates (`onDidTerminateDebugSession` for that session) or `session_end` arrives.
  - If `ms-python.debugpy` isn't installed → error message with [Install Python Debugger].
  - `wintestkit.debugTest {id}` → `runHandler` of the Debug profile.
- **Done when:** manual: a breakpoint in a test and in a screen helper method is hit; stepping
  works; results appear in Test Explorer.

---

## T4.6 — `wtk init`, Initialize command, pytest explorer conflict <a id="t46"></a>

- **Depends on:** T4.1 · **Size:** M
- **Files:** `python/src/wintestkit/commands/init.py`, `python/src/wintestkit/scaffold/*.tmpl`,
  `python/tests/unit/test_init.py`, `vscode/src/init.ts`, `vscode/src/pytestConflict.ts`
- **Spec — `wtk init [DIR] [--app PATH] [--force]`** (Python):
  - Creates (never overwrites without `--force`; skips existing files with a notice):
    - `pyproject.toml` — if absent, a minimal project with `[tool.pytest.ini_options]
      pythonpath=["."] testpaths=["tests"]` and `[tool.wintestkit]` + `[tool.wintestkit.app]`
      (path from `--app` or a placeholder `"C:/path/to/YourApp.exe"`). If present without
      `[tool.wintestkit]`, append those tables (and pytest options if missing).
    - `screens/__init__.py` (empty), `screens/main.py` (a `MainScreen` with
      `window = Window(title="<exe stem>")` and a commented example element),
      `tests/__init__.py` (empty), `tests/test_smoke.py` (a test asserting the main window is
      visible via `expect(MainScreen(app).window).to_be_visible()`).
    - `.gitignore` entry `wtk-report/` (append if file exists).
  - Prints next steps.
- **Spec — `init.ts`:** `wintestkit.initProject` → pick a workspace folder (if several) → optional
  file picker "Select the application .exe" (can skip) → run `python -m wintestkit init <folder>
  --app <exe>` (requires the package; if missing, offer install first) → open
  `screens/main.py`, refresh projects.
- **Spec — `pytestConflict.ts`:** when a project is active and
  `python.testing.pytestEnabled` is `true` for that folder, and `wintestkit.promptDisablePytestExplorer`
  is true, show once per workspace: "WinTestKit shows your tests in Test Explorer. Turn off the
  Python extension's pytest discovery for this workspace to avoid duplicate tests?" [Turn Off]
  [Keep Both] [Don't Ask Again]. Turn Off → update `python.testing.pytestEnabled=false` at
  `WorkspaceFolder` target. Don't Ask Again → set the setting false globally.
- **Done when:** Python unit tests for scaffold (fresh dir, existing pyproject, `--force`); manual
  checks for the VS Code side.

---

## T4.7 — Extension integration tests (E2E) <a id="t47"></a>

- **Depends on:** T4.3, T4.4, T4.5 · **Size:** M
- **Files:** `vscode/test/integration/suite/*.test.ts`, `vscode/test/integration/runTest.ts`
- **Spec:** `@vscode/test-electron` launches VS Code (stable) with `examples/demo-tests` as
  workspace, the built extension, and `ms-python.python` + `ms-python.debugpy` installed via
  `--install-extension` (runTest.ts uses `resolveCliArgsFromVSCodeExecutablePath`). The test
  sets `wintestkit.pythonPath` to `examples/demo-tests/.venv/Scripts/python.exe` (created by
  `uv sync` beforehand). Tests (mocha, 60 s timeout each):
  1. Activation: `wintestkit.hasProject` true; server initializes.
  2. CodeLens: `vscode.executeCodeLensProvider` on `screens/main.py` returns a lens titled
     `$(eye) Highlight element` on the `sign_in` line and `$(play) Run test` on a test.
  3. Highlight: execute `wintestkit.highlightElement` for `MainScreen.sign_in` → resolves (check via
     a test-only command `wintestkit._lastHighlightResult` registered when
     `process.env.WTK_TEST === "1"`) with status `found`.
  4. Run: run `tests/test_login.py::test_valid_login` via `wintestkit.runTest`; wait for a test-only
     `wintestkit._lastRunResults` to report `passed`.
  5. Failure: with `WTK_DEMO_FAILURES=1`, run the expected-failure test; result `failed` with a
     diagnostic message containing `No element matches`.
- **Done when:** `npm run test:integration` passes locally on Windows with the demo built; added
  to the integration CI job (T7.3).

---

## T5.1 — Elements tree view <a id="t51"></a>

- **Depends on:** T4.3 · **Size:** M
- **Files:** `src/views/elementsTree.ts`, `test/unit/elementsTreeModel.test.ts`
- **Spec:**
  - `TreeDataProvider` for `wintestkit.elements`. Pure model builder `buildTree(discoveries:
    DiscoveryResult[]): Node[]`:
    - Level 0 (only when > 1 project): project nodes.
    - Screen nodes (label = class name, description = relative file path, icon
      `symbol-class`, contextValue `screen`), sorted by name.
    - Under a screen: its `window` entry first (icon `window`, contextValue `window`), then
      elements **nested by `withinName`** (an element whose `withinName` refers to another element
      of the same screen is shown as its child), in source order. Icon `symbol-field` (element),
      `list-flat` (elements). Description = locator description (`describeLocator`, last link
      only). Tooltip = full description + `file:line`.
  - Status icons: if a `CheckResult` exists for the element, icon becomes `pass` (green,
    `testing.iconPassed` ThemeColor), `error` (red, `testing.iconFailed`), or `warning`
    (`testing.iconQueued`/`list.warningForeground`).
  - Clicking a node → `wintestkit.elements.goTo` → open file and reveal `nameRange`.
  - Inline actions per contributions (highlight, check, check all).
  - Refreshes on DiscoveryStore and CheckResultsStore changes.
- **Done when:** model unit tests (nesting by within, multi-project, ordering); manual: tree
  mirrors the examples' screens, inline Highlight works.

---

## T6.1 — Spy webview <a id="t61"></a>

- **Depends on:** T4.1, T3.8 · **Size:** L
- **Files:** `src/spy/spyView.ts`, `src/spy/messages.ts`, `media/spy/spy.html`,
  `media/spy/spy.css`, `media/spy/spy.js`
- **Spec:**
  - `WebviewViewProvider` for `wintestkit.spy`; `enableScripts: true`, `localResourceRoots` =
    `media/spy` + `@vscode/codicons` dist (copy `codicon.css`/`codicon.ttf` into
    `media/codicons/` at build time). Strict CSP: `default-src 'none'; style-src
    ${webview.cspSource}; font-src ${webview.cspSource}; script-src 'nonce-${nonce}'`.
    No frameworks; plain DOM in `spy.js`. Styling uses VS Code CSS variables only
    (`--vscode-foreground`, `--vscode-list-activeSelectionBackground`, `--vscode-button-*`,
    `--vscode-textCodeBlock-background`, etc.).
  - **Layout** (top to bottom):
    1. Toolbar: `Pick` button (codicon `inspect`; toggles to `Stop` while picking), `Refresh`,
       app state label, `Launch app` button when the app isn't running.
    2. Hint line while picking: "Hover over the app. Ctrl+Click to pick, Esc to cancel."
    3. **Tree** (≈ 50% height, resizable splitter): lazy-expanding nodes `ControlType "Name"`
       with dimmed `[class] #id`. Single-click selects (→ properties + suggestion + highlight in
       app). Keyboard: Up/Down/Left/Right/Enter.
    4. **Properties** table: Name, ControlType, AutomationId, ClassName, FrameworkId, IsEnabled,
       IsOffscreen, BoundingRectangle, ProcessId, supported patterns, then "All properties"
       collapsible section (from `inspect.properties`).
    5. **Suggested locator**: code block showing helpers + `attribute = Element(...)`; badges:
       strategy and "unique" / "fragile (index)" / "not unique (N matches)"; buttons **Copy**,
       **Add to screen…** (T6.2), **Highlight**.
  - **Messages** (`messages.ts`, discriminated unions, shared by extension and `spy.js` via JSDoc
    typedef comments):
    - webview → extension: `{type:"ready"}`, `{type:"pick"}`, `{type:"stopPick"}`,
      `{type:"refresh"}`, `{type:"expand", nodeId}`, `{type:"select", nodeId}`,
      `{type:"highlight", nodeId}`, `{type:"copy", text}`, `{type:"addToScreen", suggestion}`,
      `{type:"launchApp"}`.
    - extension → webview: `{type:"state", picking, appRunning, hasProject}`,
      `{type:"roots", nodes}`, `{type:"children", nodeId, nodes}`,
      `{type:"selected", nodeId, properties, suggestion}` (properties = `inspect.properties`
      result), `{type:"hover", node}`, `{type:"picked", node, suggestion, ancestors}`,
      `{type:"error", message}`.
  - **Picking:** `pick` → `spy.start`; set context `wintestkit.picking`. `spy.hover` → forward
    `hover` (webview shows the hovered element's summary in the hint line). `spy.picked` →
    `spy.stop`, then expand the tree along `ancestors` (from `inspect.properties`) and select the
    node; bring VS Code back to the foreground isn't possible from the extension — instead show a
    notification "Picked Button "Sign in"" (clicking focuses the Spy view). Esc → `spy.cancelled`
    → state update.
  - Command `wintestkit.spy.startPick` focuses the view and starts picking.
  - Node errors -32005 (stale) → refresh roots and show "The element is gone; refreshed."
- **Done when:** manual: pick Sign in in the demo → tree reveals it, suggestion is
  `sign_in = Element(control_type="Button", name="Sign in")`, Copy works, selecting tree nodes
  highlights them in the app; works in light/dark/high-contrast themes.

---

## T6.2 — "Add to screen" insertion <a id="t62"></a>

- **Depends on:** T6.1, T4.2 · **Size:** M
- **Files:** `src/spy/insertElement.ts`, `test/unit/insertElement.test.ts`
- **Spec:**
  - Flow: QuickPick of screens from all projects (`MainScreen — screens/main.py`) plus
    "$(add) New screen…" → for new: InputBox class name (PascalCase validated) + file (QuickPick of
    `screens/*.py` or new file name) → InputBox attribute name prefilled with
    `suggestion.attributeName` (validate Python identifier, not a keyword, not already defined in
    the class — check discovery) → apply edit → open file and reveal the new line.
  - Pure function `computeInsertion(source: string, screen: ScreenEntry | null, newScreen?:
    {className: string; window?: string}, suggestion, attributeName: string): { edits: {
    range: Range; text: string }[] }`:
    - Indentation: detect from the first element line of the class, else class body, else 4 spaces.
    - Insert after the last element entry of the class (its `range.end.line`), or after the class
      docstring / `window` line if no elements.
    - Helpers (`suggestion.helpers`) are inserted first, skipping any helper whose locator equals an
      existing element's locator in that class (reuse its attribute name, rewriting `within=` in
      the element code).
    - If the class has no `window` attribute and the suggestion has a `window`, insert
      `window = Window(...)` as the first body line.
    - Imports: ensure `from wintestkit import ...` contains every name used (`Screen`, `Window`,
      `Element`, `Elements`); extend an existing `from wintestkit import` line or add one after the
      last top-of-file import; add `import re` if the code uses `re.compile`.
    - New screen: append a `class <Name>(Screen):` block (two blank lines before) with window line
      and the element.
- **Done when:** unit tests with fixture sources: append to existing class, empty class, class with
  docstring, helper reuse, import extension, `import re` addition, new screen in existing file and
  new file; manual end-to-end from the Spy.
