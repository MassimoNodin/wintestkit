# WinTestKit — Background Research

Research compiled 2026-10-14 to inform the design of WinTestKit: a TestComplete replacement for
Windows desktop UI testing, delivered as a **VS Code extension + CLI**.

> **Superseded decisions:** this research assumed TypeScript tests and a .NET engine. The final
> decisions are Python-only, a pure-Python UIA engine and WPF only. See [plan/README.md](plan/README.md).

Items marked _(unverified)_ came from general knowledge rather than a fetched source and should be
checked before relying on them.

---

## 1. Why replace TestComplete — what to keep, what to drop

### Top complaints (by evidence strength)
1. **Version control is hostile.** SmartBear's own moderators say most project files must be treated
   as binary; the shared `.mds` project file conflicts constantly in git.
   ([forum](https://community.smartbear.com/discussions/testcomplete-questions/project-merge-fails-due-to-mds-file-conflict/235285))
2. **Steep setup / learning curve.**
3. **Heavy resource use**, slowdowns on large suites.
4. **Cost** — roughly $1.2k–$4.5k per user/year reported, bundles ~$8k; floating license servers.
5. **Stability** — scattered crash/flakiness reports.
6. _(unverified)_ Name-mapping bloat, proprietary script dialects, weak debugging, vendor lock-in.

### Praised — worth keeping
- Object recognition that tolerates UI changes (Name Mapping / Aliases as a central repair point).
- Mix of no-code (record) and scripted testing.
- Object Spy / Object Browser for exploring the app.

### Do NOT copy
- Binary/XML project files and shared mutable project state.
- Multiple proprietary script languages (VBScript, JScript, DelphiScript…). Pick one.
- A separate runtime product (TestExecute) and license server for CI.
- A giant global name-mapping tree that must mirror the app hierarchy.

### The gap
No VS Code-native tool was found that combines a UIA inspector, recorder, Test Explorer
integration, and git-friendly text files. (Marketplace/Open VSX not checked directly — verify.)

---

## 2. Automation engine (Windows UI automation)

### Technology
- **Microsoft UI Automation (UIA)** is the foundation: elements expose `AutomationId`, `Name`,
  `ClassName`, `ControlType`, `FrameworkId`, `ProcessId`, and control patterns (Invoke, Value,
  Toggle, ExpandCollapse, Selection, Scroll, Text, Window).
- Every tree walk / property read is a cross-process COM call → use `CacheRequest` for bulk reads;
  avoid RawView and deep `FindAll` from the desktop root.
- **Prefer patterns over input**: `Invoke`/`Value` don't need focus or coordinates. Use `SendInput`
  only when needed (it's subject to focus rules and UIPI).

### Framework coverage
| Good UIA tree | Partial | Poor / none |
|---|---|---|
| Win32, WinForms, WPF, UWP, WinUI 3 | Qt (accessibility plugin), Delphi/VCL (varies), Java Swing (needs Java Access Bridge) | Custom-drawn / game-style UIs → image/OCR fallback |

Electron/Chromium: accessibility tree is off until an assistive client is detected; force with
`--force-renderer-accessibility` or `app.setAccessibilitySupportEnabled(true)`.

### Libraries
| Library | Status |
|---|---|
| **FlaUI** (.NET, MIT) | Active. v5.0.0 Feb 2025, .NET 8. UIA3 for WPF/modern, UIA2 for WinForms (UIA3 has WinForms bugs). |
| pywinauto (Python, BSD) | 0.6.9 Jan 2025. Slow release cadence. |
| **WinAppDriver** | **Effectively dead** — last real release 2020. Don't build on it. |
| Appium NovaWindows driver | Recommended WinAppDriver replacement in Appium docs; useful reference. |
| node-ffi-napi | Abandoned — avoid. |

### Environment gotchas
- **UIPI:** a non-elevated runner can't drive an elevated app (fails silently).
- **DPI:** the engine must be per-monitor DPI aware, or coordinates are wrong.
- **Locked / disconnected sessions** break UIA and input. Minimized RDP windows stop rendering.
- **CI needs an interactive desktop session**, not a service. Use auto-logon, disable lock/screensaver,
  and `tscon` to disconnect RDP without locking.
  ([MS docs](https://learn.microsoft.com/fi-fi/previous-versions/azure/devops/pipelines/test/ui-testing-considerations?view=tfs-2018))
  Self-hosted runners are the reliable path; GitHub-hosted Windows runners are OK for
  pattern-based tests but flaky for input injection _(partly unverified)_.

### Bridging to TypeScript
| Option | Verdict |
|---|---|
| **.NET sidecar (FlaUI) over JSON-RPC/stdio** | **Recommended.** Mature bindings, process isolation (an engine crash doesn't kill VS Code). Ship self-contained single-file exe. |
| Rust sidecar (windows-rs / `uiautomation` crate) | Viable later: tiny binary, no runtime. Smaller ecosystem. |
| N-API native addon | Fast but per-Node/Electron ABI build pain inside VS Code. |
| koffi FFI | No build step, but hand-rolling COM vtables is painful. |
| edge-js | Not recommended. |

Keep the JSON-RPC protocol language-neutral so the sidecar can be swapped.

---

## 3. Object identification, spy and recorder

### Prior art
- **TestComplete:** Name Mapping + Aliases; hierarchy must mirror the app.
- **Ranorex:** RanoreXPath + repository items; paths can be generalized.
- **Squish:** Object Map — symbolic names in scripts ↔ real-name property sets.
- **UFT Smart Identification** _(best design reference)_: start with base filter properties, then
  narrow with optional properties, **dropping any filter that empties the candidate set**; ordinal
  index is the last resort.
- **Katalon:** multiple locators per element tried in priority order; healed locator proposed for
  approval (self-healing).
- **Playwright:** role + accessible name first, chainable locators, auto-waiting for actionability,
  **strict mode** (ambiguous match = error, not a silent pick).

### Recommended design
1. **Element model:** each element is a *locator bundle* — role/ControlType, Name, AutomationId,
   ClassName, process, ancestor path, bounding-box hint, small thumbnail — stored in human-editable,
   diffable files (one file per screen/window, not one global tree).
2. **Matching:** weighted, UFT-style filter elimination; uniqueness required by default; fallbacks
   tried in order; any "healed" match is logged and offered as a fix, never silently persisted.
3. **API:** Playwright-like chained locators, with a string form for the CLI sharing the same AST:
   ```ts
   app.window({ title: /Invoices/ })
      .find({ role: 'Button', name: 'Save' })
      .click();
   ```
4. **Synchronization:** auto-wait on every action (exists, visible, enabled, bounds stable), default
   ~10s timeout, explicit `waitFor(state)`, no sleeps; errors report the last observed state.
5. **Spy/inspector:** click-through topmost layered-window highlight overlay + tree/properties pane,
   modelled on Accessibility Insights for Windows (Inspect.exe is legacy).
6. **Recorder:** low-level hooks (`WH_MOUSE_LL` / `WH_KEYBOARD_LL`) → `ElementFromPoint` at click →
   coalesce into high-level steps (click / type text / select item) → emit readable code that uses
   named elements. Keep the captured snapshots so users can rename/tune locators afterwards.
7. **Fallback tiers (opt-in, logged):** UIA → OCR → image template matching (OpenCV, DPI-aware) →
   optional vision model (e.g. OmniParser-style). `Windows.Media.Ocr` may need package identity for
   unpackaged apps _(verify)_; Tesseract is the portable alternative.
8. **Checkpoints:** property checkpoints (UIA values) and image checkpoints (masked regions +
   tolerance).

---

## 4. VS Code extension

| Feature | API |
|---|---|
| Test discovery / run / debug / results | **Testing API** — `createTestController`, `resolveHandler`, Run/Debug run profiles, `TestRun` output + `TestMessage` with location/diff |
| Object repository browser | `TreeView` / `TreeDataProvider` |
| Object map visual editor | `CustomTextEditorProvider` (text-backed → free save/undo/git diff) + `jsonValidation` schema |
| Spy panel, recorder panel, screenshot viewer, reports | `WebviewPanel` / `WebviewView` |
| Quick actions | commands, QuickPick, status bar, CodeLens ("Run", "Pick element"), decorations on failed steps |
| IntelliSense for elements | Generate `.d.ts` from object map files → built-in TS server does the rest (no custom LSP for v1) |
| Debugging | Reuse the built-in Node debugger (as Playwright's extension does); no custom DAP for v1 |

Notes:
- `@vscode/webview-ui-toolkit` was **archived Jan 2025**. Use plain HTML/CSS with VS Code theme CSS
  variables + `@vscode/codicons` (or evaluate `@vscode-elements/elements`).
- **Use `extensionKind: ["ui"]`**: the engine must run on the Windows machine with the desktop,
  even if the workspace is remote (WSL/SSH). (The research suggested `workspace`; that would put the
  engine on a machine with no Windows desktop when the workspace is remote.)
- Ship a platform-specific VSIX (`vsce package --target win32-x64`, plus `win32-arm64` later).
- Publish to both the VS Code Marketplace and **Open VSX** (Cursor, VSCodium, Windsurf).
- Bundle with esbuild; use narrow activation events (`workspaceContains:wintestkit.config.*`).
- The extension should **spawn the CLI** and read a machine-readable event stream rather than
  importing the runner into the extension host.

---

## 5. CLI, runner and architecture

### Authoring model
**TypeScript code-first with a readable step DSL** is the recommendation: one language, strong
typing and IntelliSense, native VS Code debugging. Data-driven tests take CSV/XLSX input. A
keyword/table layer could be added later on top of the same core.

**Don't write a runner from scratch.** Build on an existing one for discovery, workers, retries,
tags, sharding and reporters, and supply only fixtures (`app`, `window`, element).
Candidates: **Playwright Test** (proven with custom non-browser fixtures, e.g. Electron suites),
Vitest, or `node:test`. Needs a spike.

### CLI (`wtk`)
| Command | Purpose |
|---|---|
| `wtk run [pattern]` | `--grep/--tag`, `--retries`, `--shard`, `--reporter`, `--env` |
| `wtk list` | discovery as JSON (used by the extension) |
| `wtk spy` | inspect a running app's UIA tree |
| `wtk record` | record a test skeleton |
| `wtk report` | merge shard results, render HTML/JUnit |
| `wtk doctor` | check interactive session, lock state, DPI, resolution, elevation, ffmpeg |

Exit codes: 0 pass, 1 test failures, 2 config/usage, 3 environment not ready, 4 internal error.

Config: `wintestkit.config.ts` (projects, apps to launch/attach, timeouts, retries, reporters,
artifacts, env profiles).

### Parallelism
One desktop session = one input focus, so input-driven tests must be **serial per session**.
Scale out with multiple VMs/agents (most reliable) and shard across them. Multiple RDP sessions on
client Windows are license-restricted.

### Reporting & artifacts
- **CTRF JSON** as canonical format + **JUnit XML** for CI + an HTML report.
- On failure: window and full-desktop screenshots, UIA tree dump, step log; later a trace viewer.
- Video: `ffmpeg -f gdigrab` / `ddagrab` initially; investigate Windows.Graphics.Capture.

### App lifecycle
Launch (path, args, cwd, env) or attach (process name / title / PID); kill the process tree on
teardown only if WinTestKit launched it. Per-test temp dirs.

### Proposed architecture
```
  VS Code extension (TS)            CI pipeline
  Test Explorer, Spy, Recorder      wtk run --shard --reporter=junit
          │ spawn + NDJSON events          │
          ▼                                ▼
  ┌──────────────────────── wtk CLI (Node/TS) ────────────────────────┐
  │ runner adapter (Playwright Test / node:test) · config · reporters │
  └───────────────────────────────┬───────────────────────────────────┘
                                  │ fixtures: app / window / element
                    @wintestkit/core (locators, waits, DSL, types)
                                  │ JSON-RPC over stdio
                    engine sidecar (.NET 8 + FlaUI, input, capture, overlay)
```

```
wintestkit/
  packages/
    core/         # DSL, locator model, waits, JSON-RPC client, types
    runner/       # fixtures + adapter over the chosen test runner
    reporters/    # CTRF, JUnit, HTML
    cli/          # `wtk`
    engine/       # .NET 8 FlaUI sidecar (self-contained exe)
  apps/
    vscode/       # extension — spawns the CLI, never imports the runner
  examples/       # sample tests against Notepad / a WinForms + WPF demo app
  docs/
```

### Licensing / naming
MIT or Apache-2.0 fits the ecosystem (FlaUI is MIT). No existing software product named
"WinTestKit" found, but do a proper trademark check.

---

## 6. Suggested MVP order
1. Engine sidecar + JSON-RPC protocol: launch/attach, find by locator, click/type/invoke/value,
   screenshot. Spike against Notepad + a WinForms + a WPF app (and a Delphi/Electron app if those
   are targets).
2. `@wintestkit/core` locator DSL with auto-wait + strict mode.
3. Runner fixtures + `wtk run` / `wtk list` with CTRF + JUnit output and failure screenshots.
4. VS Code Test Explorer integration (discover/run/debug, failure messages at the right line).
5. Spy: CLI tree dump first, then a VS Code webview with a live highlight overlay and "copy locator".
6. Object map files + generated `.d.ts` for IntelliSense + tree view.
7. Recorder emitting TS code.
8. `wtk doctor`, HTML report, video, image/OCR fallbacks.

## 7. Open decisions
- **Test language:** TypeScript-only (recommended) vs also Python.
- **Runner base:** Playwright Test vs Vitest vs `node:test` (spike needed).
- **Engine:** .NET/FlaUI (recommended) vs Rust.
- **Target apps:** which UI frameworks your apps under test use (WinForms/WPF/Delphi/Qt/Java/Electron)
  decides how much fallback work is needed early.
- **Object maps:** per-screen locator files (recommended) vs locators inline in tests only.

## 8. Verification gaps
- Marketplace / Open VSX not searched directly for competing extensions.
- No Reddit sentiment data; vendor pricing unverified.
- `Windows.Media.Ocr` package-identity requirement; GitHub-hosted runner desktop specifics.
- nut.js, AutoIt, the Rust `uiautomation` crate, and Windows.Graphics.Capture not researched.
