# 07 — Report, CI, Packaging, Release, Docs (T0.4, T7.x, T8.x)

## T0.4 — CI workflow (lint / unit / build) <a id="t04"></a>

- **Depends on:** T0.1, T0.2, T0.3 · **Size:** S
- **File:** `.github/workflows/ci.yml`
- **Spec:** triggers `push` to `main`/`master`, `pull_request`. All jobs `runs-on: windows-latest`.
  - `python`: `astral-sh/setup-uv@v6`, `uv sync --directory python`, then in `python/`:
    `uv run ruff check`, `uv run ruff format --check`, `uv run pyright`,
    `uv run pytest -m "not integration" --junitxml=junit-python.xml`. Upload JUnit as artifact.
  - `extension`: `actions/setup-node@v4` (node 22, npm cache), in `vscode/`: `npm ci`,
    `npm run gen:types && git diff --exit-code src/protocol/generated.ts`, `npm run lint`,
    `npm run typecheck`, `npm test`, `npm run package`. Upload the `.vsix` artifact.
  - `demo`: `actions/setup-dotnet@v4` (8.0.x), `dotnet build demo/DemoApp/DemoApp.csproj -c Release
    -warnaserror`. Upload `demo/DemoApp/bin/Release/net8.0-windows/` as artifact `demo-app`.
- **Done when:** workflow green on a PR.

---

## T7.1 — Results JSON + HTML report <a id="t71"></a>

- **Depends on:** T2.7, T2.8 · **Size:** M
- **Files:** `src/wintestkit/report/__init__.py`, `report/results.py`, `report/html.py`,
  `report/template.html`, `pytest_plugin.py` (extend), `tests/unit/test_report.py`,
  `tests/contract/test_results_contract.py`
- **Spec:**
  - `ResultsCollector` (plugin component): builds `Results` (05-protocol §5) from the same hook data
    as the event stream (share code with `events.py`: one `RunRecorder` that produces events and
    accumulates results — refactor T2.8 if needed). Captured stdout/stderr/log per test from
    `report.capstdout/capstderr/caplog`.
  - At `pytest_sessionfinish`, unless `--wtk-no-report`: write `<report_dir>/results.json` and
    `<report_dir>/index.html`. Clear `<report_dir>` at session start (only files WinTestKit
    created: `index.html`, `results.json`, `artifacts/`), never the whole directory if it contains
    other files.
  - Environment block: `platform.python_version()`, `__version__`, `platform.version()`,
    `platform.node()`, primary screen size + scale (`GetSystemMetrics`, `GetDpiForSystem/96`).
  - **HTML** (`template.html`, single file, no external resources, no CDN, works from `file://`):
    - Data embedded as `<script type="application/json" id="wtk-data">` (JSON with `</` escaped
      as `<\/`); rendering by inline vanilla JS.
    - Header: title "WinTestKit report", start time (local), duration, machine, summary chips
      (total/passed/failed/skipped/errors) that act as filters; text search box filtering by test id.
    - Test list grouped by file; each row: status icon, name, duration. Failed tests expanded by
      default.
    - Test detail: message, location (`file:line`), diagnostic rendered as a table (candidate,
      class, rect, mismatches), steps table (seq, action, target, locator, args, duration, status;
      failed step highlighted; step screenshot thumbnail when present), screenshots as thumbnails
      (click → full-size overlay), link to `tree.txt`, collapsible stdout/stderr/log.
    - Light and dark via `prefers-color-scheme`. Must stay usable with 1000 tests (render rows
      lazily on expand).
    - Paths in the report are relative to the report dir.
  - `wtk report [DIR] [--open]` command: regenerates `index.html` from `results.json` (useful
    after editing the template) and with `--open` opens it in the default browser
    (`os.startfile`).
- **Done when:** unit tests: results built from a pytester run validate against
  `results.schema.json`; HTML contains embedded data and no `http` URLs; manual check of the
  report from `examples/demo-tests` with `WTK_DEMO_FAILURES=1` (screenshots visible, diagnostic
  table readable).

## T7.2 — Report + JUnit wiring in CLI and VS Code <a id="t72"></a>

- **Depends on:** T7.1, T4.4 · **Size:** S
- **Files:** `cli.py` (verify `--report`/`--junit`), `vscode/src/report.ts`
- **Spec:**
  - Python half: `session_end` event includes `reportPath` (absolute path of `index.html`) and
    `junitPath` when produced; `wtk run` prints `Report: <path>` at the end.
  - VS Code half: store last `reportPath` per project; `wintestkit.openReport` opens it with
    `vscode.env.openExternal(Uri.file(path))`; if no run happened this session, look for
    `<project>/<report_dir>/index.html` (report_dir from `initialize` result). After a run with
    failures, show `"N tests failed."` [Open Report] [Show Test Results].
- **Done when:** manual: failing run → notification → report opens in browser.

## T7.3 — Integration CI job <a id="t73"></a>

- **Depends on:** T0.4, T2.9 · **Size:** S
- **File:** `.github/workflows/ci.yml` (add job)
- **Spec:** job `integration` (needs `demo`), `windows-latest`:
  1. Download `demo-app` artifact to `demo/DemoApp/bin/Release/net8.0-windows/`.
  2. Display resolution can't be configured on hosted runners, so log it for debugging with
     `uv run --directory python python -c "import ctypes;u=ctypes.windll.user32;print(u.GetSystemMetrics(0),u.GetSystemMetrics(1))"`.
  3. `uv run --directory python wtk doctor` (continue on warnings; fail on exit 3).
  4. `uv run --directory python pytest -m integration --junitxml=junit-integration.xml`.
  5. `cd examples/demo-tests && uv sync && uv run wtk run --junit junit-examples.xml --report wtk-report`.
  6. (after T4.7) `cd vscode && npm ci && npm run build && npm run test:integration`.
  7. Upload JUnit files and `examples/demo-tests/wtk-report/` as artifacts (always, also on
     failure).
  - Mark the job `continue-on-error: true` until it has been green 10 runs in a row (hosted
    runners' interactive desktop can be flaky); then make it required. Document in
    `docs/guide/ci.md` how to run the same steps on a self-hosted runner.
- **Done when:** job runs and publishes artifacts.

---

## T8.1 — Python packaging <a id="t81"></a>

- **Depends on:** T3.8 · **Size:** S
- **Spec:**
  - `uv build --directory python` produces sdist + wheel (`py3-none-any`); wheel includes
    `report/template.html`, `scaffold/*.tmpl`, `py.typed`.
  - Test: install the wheel into a fresh venv (`uv venv` + `uv pip install dist/*.whl`), run
    `wtk --version`, `wtk doctor --json`, `python -c "import wintestkit"`, and `pytest --help |
    findstr wtk-launch` (plugin registered).
  - Check PyPI name availability for `wintestkit`; if taken, report to the owner before release
    (do not rename silently).
- **Done when:** a `scripts/check_wheel.ps1` script performing the above passes locally and in CI
  (added as a step of the `python` job).

## T8.2 — VSIX packaging + release workflow <a id="t82"></a>

- **Depends on:** T4.7, T8.1 · **Size:** M
- **File:** `.github/workflows/release.yml`, `vscode/CHANGELOG.md`, `vscode/README.md`
- **Spec:**
  - Trigger: tag `v*.*.*`. Verify the tag equals `python/src/wintestkit/__init__.py` version and
    `vscode/package.json` version (fail otherwise). `scripts/bump_version.py X.Y.Z` updates both.
  - Jobs: build wheel/sdist; build VSIX for `win32-x64` and `win32-arm64` (same JS bundle, two
    `vsce package --target` runs); create GitHub Release with all artifacts and changelog section.
  - Publishing steps gated on secrets presence and a manual `environment: release` approval:
    `uv publish` (PyPI trusted publishing), `vsce publish --packagePath ...` (Marketplace; Azure
    credential per current guidance), `ovsx publish` (Open VSX token).
  - `vscode/README.md`: Marketplace page — features with screenshots/GIFs (CodeLens, Test Explorer,
    Spy, report), requirements (Windows, Python 3.12+, `pip install wintestkit`), quick start,
    settings table.
- **Done when:** a dry-run (`workflow_dispatch` with `dry_run: true`) builds all artifacts without
  publishing.

## T8.3 — User guide <a id="t83"></a>

- **Depends on:** all features · **Size:** M
- **Files:** `docs/guide/index.md`, `getting-started.md`, `screens-and-elements.md`,
  `locators-for-wpf.md`, `actions-and-assertions.md`, `running-tests.md`, `vscode.md`, `ci.md`,
  `troubleshooting.md`, `migrating-from-testcomplete.md`
- **Spec (content outline):**
  - **getting-started:** install (`pip install wintestkit` / `uv add --dev wintestkit`), `wtk init`,
    first screen with the Spy, first test, `wtk run`, VS Code extension.
  - **screens-and-elements:** `Screen`, `Window`, `Element`, `Elements`, `within`, `window=`,
    inheritance, organising screens per window/dialog, naming conventions.
  - **locators-for-wpf:** strict matching and why; reading diagnostics; strategy order (id → name →
    class → within → index); regex names; dealing with no AutomationIds; popups/menus/ComboBox;
    virtualized lists/grids (`select`, `row`, `cell`, `find_row`); MessageBoxes (`#32770`).
  - **actions-and-assertions:** every action, pattern vs mouse mode, auto-wait table, `expect`
    reference, timeouts precedence.
  - **running-tests:** `wtk run` options, launch modes, reset fixtures, markers, report, JUnit,
    exit codes, events.
  - **vscode:** CodeLens actions, Test Explorer, debugging, Elements view, Spy, settings,
    multi-project workspaces, pytest explorer conflict.
  - **ci:** self-hosted runner as an interactive process (not a service) with auto-logon, disable
    screen lock/screensaver, fixed resolution and scaling, `tscon %sessionname% /dest:console` to
    disconnect RDP without locking, elevation matching, `wtk doctor` as first step, artifacts;
    sample GitHub Actions and Azure DevOps YAML.
  - **troubleshooting:** doctor checks explained, element not found / ambiguous, elevated apps,
    DPI, locked desktop, comtypes cache, server logs (`WinTestKit` output channel, `WTK_LOG`).
  - **migrating-from-testcomplete:** concept mapping table (NameMapping/Aliases → Screens/Elements,
    Object Spy → Spy, keyword tests → pytest functions, checkpoints → `expect`, TestExecute → `wtk
    run`, project suites → pytest markers/paths, logs → HTML report).
- **Done when:** every code sample in the guide is copied into `examples/` or a doc-test and
  verified to run (or is clearly marked as pseudo-code).
