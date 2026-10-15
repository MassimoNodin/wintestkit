# WinTestKit — Implementation Plan (for implementing agents)

> Historical design document: the example application described here has been removed.
> Use the [user guide](../../README.md) for setup and the [development guide](../development.md)
> for current build and test instructions.

This directory is the complete build plan for WinTestKit v1. It is written so that **independent
agents can each pick up one task**, implement it without needing the others' context, and still end
up with parts that fit together.

Background research (why these choices were made): [../research.md](../research.md).

| File | Contents |
|---|---|
| **README.md** (this file) | Product summary, decisions, conventions, repo layout, task index and dependency graph |
| [01-demo-app.md](01-demo-app.md) | The small WPF test target app (exact controls and behaviours) |
| [02-engine.md](02-engine.md) | Python UI Automation layer + engine (resolve, wait, act, highlight) |
| [03-model-pytest.md](03-model-pytest.md) | Screen/Element model, `expect`, config, pytest plugin, examples suite |
| [04-cli-server.md](04-cli-server.md) | Discovery, `wtk` CLI commands, locator suggestion, spy, doctor, JSON-RPC server |
| [05-protocol.md](05-protocol.md) | **Every shared data shape** (JSON schemas in TS notation) — the contract between Python and VS Code |
| [06-vscode.md](06-vscode.md) | The VS Code extension |
| [07-report-ci-release.md](07-report-ci-release.md) | HTML report, CI workflows, packaging, release, user docs |

---

## 1. Product summary

WinTestKit is a replacement for SmartBear TestComplete for automated UI testing of **WPF desktop
applications**. It consists of:

1. **`wintestkit` Python package** (PyPI) — UI Automation engine, element model, pytest plugin,
   `wtk` CLI, JSON-RPC server for the editor.
2. **WinTestKit VS Code extension** — CodeLens actions (**Highlight element** above element
   definitions, **Run test / Debug test** above tests), Test Explorer integration, an Elements tree
   view, a Spy/inspector panel, and report viewing.

Users write:

```python
# screens/login.py
from wintestkit import Screen, Window, Element

class MainScreen(Screen):
    window = Window(title="WTK Demo")

    credentials = Element(control_type="Group", name="Credentials")
    username    = Element(control_type="Edit", class_name="TextBox", within=credentials)
    password    = Element(control_type="Edit", class_name="PasswordBox", within=credentials)
    sign_in     = Element(control_type="Button", name="Sign in")
    status      = Element(automation_id="StatusText")
```

```python
# tests/test_login.py
from wintestkit import expect
from screens.main import MainScreen

def test_valid_login(app):
    main = MainScreen(app)
    main.username.type("admin")
    main.password.type("secret")
    main.sign_in.click()
    expect(main.status).to_have_text("Welcome, admin")
```

and run them with `wtk run` (or from VS Code).

## 2. Fixed decisions (do not revisit without the owner)

| Topic | Decision |
|---|---|
| App under test | WPF, **black box** (no AutomationIds can be added). The real app is **not** available during development — everything is developed and tested against the demo app in `demo/`. |
| Element location | **Microsoft UI Automation only.** No image matching, OCR or AI vision, ever in v1. |
| Language | **Python only** for tests, element definitions and the engine. TypeScript only inside the VS Code extension. |
| Test runner | **pytest** (WinTestKit is a pytest plugin + CLI wrapper). |
| UIA access | Pure Python via **`comtypes`** against `UIAutomationCore.dll` (`CUIAutomation8`). No .NET at runtime, no pywinauto. |
| Win32 calls | `ctypes` only (no pywin32 dependency). |
| Runtime dependencies (Python) | `comtypes` only. Everything else is stdlib. |
| Element definitions | Python classes subclassing `Screen`, with `Window(...)`, `Element(...)`, `Elements(...)` class attributes. |
| Matching | **Strict**: an element locator must match exactly one element (unless `index=` is given). No silent self-healing. Rich diagnostics on failure. |
| v1 scope | engine, model, pytest plugin, CLI, VS Code CodeLens + Test Explorer + Elements tree + Spy + HTML report, JUnit XML. |
| Not in v1 | Recorder, parallel/sharded execution, video, other UI frameworks, non-Windows. |
| License | MIT. |
| Names | Package `wintestkit`, CLI `wtk`, VS Code extension id `wintestkit.wintestkit`, display name "WinTestKit". |

## 3. Repository layout (target)

```
wintestkit/
├─ README.md
├─ LICENSE                      # MIT
├─ .gitignore  .editorconfig  .gitattributes
├─ .github/workflows/ci.yml  release.yml
├─ docs/
│  ├─ research.md
│  ├─ plan/                     # this plan
│  └─ guide/                    # user documentation (T8.3)
├─ schemas/                     # JSON Schemas generated from 05-protocol.md (T0.5)
├─ demo/
│  └─ DemoApp/                  # WPF .NET 8 demo app (T0.3)
├─ python/                      # the `wintestkit` package (uv project)
│  ├─ pyproject.toml
│  ├─ src/wintestkit/
│  │  ├─ __init__.py  __main__.py  py.typed
│  │  ├─ errors.py              # T1.0
│  │  ├─ uia/                   # T1.1–T1.5
│  │  │  ├─ __init__.py  com.py  constants.py  element.py  patterns.py
│  │  │  ├─ input.py  win32.py  dpi.py  screenshot.py  png.py
│  │  ├─ engine/                # T1.7–T1.12, T3.5, T3.6
│  │  │  ├─ __init__.py  locator.py  resolve.py  diagnose.py  waits.py
│  │  │  ├─ actions.py  overlay.py  suggest.py  spy.py  treedump.py
│  │  ├─ app.py                 # T1.6
│  │  ├─ config.py              # T2.1
│  │  ├─ runtime.py             # T2.2
│  │  ├─ model.py               # T2.3, T2.4
│  │  ├─ expect.py              # T2.5
│  │  ├─ pytest_plugin.py       # T2.6–T2.8
│  │  ├─ events.py              # T2.8
│  │  ├─ discovery.py           # T3.1
│  │  ├─ targets.py             # T3.3
│  │  ├─ doctor.py              # T3.7
│  │  ├─ server.py              # T3.8
│  │  ├─ cli.py                 # T3.2 (+ subcommands added by later tasks)
│  │  ├─ scaffold/              # T4.6 templates for `wtk init`
│  │  └─ report/                # T7.1
│  │     ├─ __init__.py  results.py  html.py  template.html
│  └─ tests/
│     ├─ conftest.py            # shared fixtures incl. demo_app
│     ├─ unit/                  # no desktop needed
│     ├─ integration/           # needs interactive desktop + built demo app
│     └─ contract/              # validates JSON output against /schemas
├─ examples/
│  └─ demo-tests/               # sample WinTestKit project against the demo app (T2.9)
│     ├─ pyproject.toml  screens/  tests/
└─ vscode/                      # the extension (T0.2, T4.x–T7.2)
   ├─ package.json  tsconfig.json  esbuild.mjs  .vscodeignore
   ├─ src/  media/  test/
```

## 4. Conventions (all tasks)

### Python
- Python **3.12+**, managed with **uv** (`uv sync`, `uv run ...` from `python/`).
- Build backend: `hatchling`. Version single-sourced in `src/wintestkit/__init__.py`
  (`__version__ = "0.1.0"`), read by hatch (`[tool.hatch.version] path = ...`).
- Lint/format: **ruff** (`line-length = 100`, rules `E,F,W,I,UP,B,SIM,RUF`), `ruff format`.
- Types: **pyright strict** for `src/`. Files that talk to `comtypes` directly (`uia/com.py`,
  `uia/element.py`, `uia/patterns.py`) and files that declare raw Win32 APIs through `ctypes` (`uia/win32.py`,
  `uia/input.py`, `uia/screenshot.py`, `uia/dpi.py`, `engine/overlay.py`, `engine/spy.py` hooks) may
  start with `# pyright: basic` — nothing else may.
- All public functions/classes have type hints. Use `@dataclass(frozen=True, slots=True)` for value
  objects. No global mutable state except where specified (`runtime.py`).
- Errors: only raise exceptions from `wintestkit.errors` (or built-in `ValueError`/`TypeError` for
  programmer errors at definition time).
- Logging: `logging.getLogger("wintestkit.<module>")`. Never `print` outside `cli.py`.
- JSON produced for other processes uses **camelCase** keys exactly as in `05-protocol.md`;
  Python attributes use snake_case. Each dataclass that crosses the boundary has
  `to_dict() -> dict[str, Any]` (and `from_dict` where it is received).
- Tests: pytest. Markers (declared in `python/pyproject.toml`):
  - `integration` — needs an interactive, unlocked desktop and the built demo app.
  - `slow` — > 5 s.
  - Unit tests must not touch UI Automation (mock at the `uia` boundary).
- Line/column numbers in all JSON are **0-based** (VS Code convention). Human-readable CLI output
  uses 1-based.
- Paths in JSON: absolute, forward slashes, e.g. `C:/work/proj/tests/test_a.py`. Test IDs use pytest
  nodeid format relative to the project root with forward slashes.

### TypeScript (VS Code extension)
- TypeScript 5.x strict, target ES2022, CommonJS output bundled by **esbuild** to `dist/extension.js`.
- `engines.vscode: "^1.95.0"`. Node APIs only from the extension host (no native modules).
- Lint: ESLint (typescript-eslint recommended). Format: Prettier defaults.
- Unit tests: **vitest** for modules that don't import `vscode` (keep logic in pure modules).
- Integration tests: `@vscode/test-electron` + mocha in `vscode/test/integration/`.
- Protocol types are **generated** from `/schemas` into `vscode/src/protocol/generated.ts`
  (`npm run gen:types`, committed). Never hand-edit that file.

### Process
- One task = one branch `task/<id>-<slug>` = one PR. PR title `T1.8: Locator resolver`.
- A task is done when its **Done when** list passes **and** the global definition of done passes:
  1. `uv run ruff check && uv run ruff format --check && uv run pyright && uv run pytest -m "not integration"` (in `python/`)
  2. `npm run lint && npm run typecheck && npm test` (in `vscode/`) — if the task touched `vscode/`
  3. Integration tests listed in the task pass locally on Windows with the demo app built.
  4. No new runtime dependency beyond those listed in §2 (dev dependencies are fine if listed in
     the task).
- If a spec detail turns out to be wrong in practice (e.g. a UIA property differs from what the
  plan expects), implement what actually works, **write the finding into the PR description**, and
  update the relevant plan file in the same PR.

### Environment variables used across tasks

| Var | Meaning |
|---|---|
| `WTK_DEMO_APP` | Path to the built `DemoApp.exe`. Default: `<repo>/demo/DemoApp/bin/Release/net8.0-windows/DemoApp.exe` |
| `WTK_APP_PATH`, `WTK_LAUNCH`, `WTK_TIMEOUT` | Config overrides (T2.1) |
| `WTK_LOG` | Log level for the `wintestkit` logger (`DEBUG`, `INFO`, …). Default `WARNING`. |

## 5. Task index

Size: **S** ≈ < half a day, **M** ≈ 1 day, **L** ≈ 2–3 days.

| ID | Task | Size | Depends on | Spec |
|---|---|---|---|---|
| T0.1 | Repo + Python project scaffold | S | — | below §6 |
| T0.2 | VS Code extension scaffold | S | — | [06](06-vscode.md#t02) |
| T0.3 | Demo WPF app | M | — | [01](01-demo-app.md) |
| T0.4 | CI workflow (lint/unit/build) | S | T0.1, T0.2, T0.3 | [07](07-report-ci-release.md#t04) |
| T0.5 | JSON Schemas + TS type generation + contract test harness | M | T0.1, T0.2 | [05](05-protocol.md#t05) |
| T1.0 | Errors module | S | T0.1 | [02](02-engine.md#t10) |
| T1.1 | COM bootstrap + UIA constants | M | T1.0 | [02](02-engine.md#t11) |
| T1.2 | `UIAElement` wrapper + `ElementInfo` | M | T1.1 | [02](02-engine.md#t12) |
| T1.3 | Pattern wrappers | M | T1.2 | [02](02-engine.md#t13) |
| T1.4 | Win32 helpers + SendInput + key parser | M | T1.0 | [02](02-engine.md#t14) |
| T1.5 | DPI awareness + screenshots + PNG encoder | M | T1.4 | [02](02-engine.md#t15) |
| T1.6 | App launch/attach/close | M | T1.2, T1.4 | [02](02-engine.md#t16) |
| T1.7 | Locator data model | S | T1.0 | [02](02-engine.md#t17) |
| T1.8 | Resolver | L | T1.2, T1.3, T1.6, T1.7 | [02](02-engine.md#t18) |
| T1.9 | Resolution diagnostics | M | T1.8 | [02](02-engine.md#t19) |
| T1.10 | Waits | S | T1.8 | [02](02-engine.md#t110) |
| T1.11 | Actions | L | T1.3, T1.4, T1.10 | [02](02-engine.md#t111) |
| T1.12 | Highlight overlay | M | T1.4 | [02](02-engine.md#t112) |
| T2.1 | Config loader | S | T1.0 | [03](03-model-pytest.md#t21) |
| T2.2 | Runtime context + step events | S | T1.0 | [03](03-model-pytest.md#t22) |
| T2.3 | Screen / Window / Element model | L | T1.8–T1.12, T2.1, T2.2 | [03](03-model-pytest.md#t23) |
| T2.4 | `Elements` collections + grid helpers | M | T2.3 | [03](03-model-pytest.md#t24) |
| T2.5 | `expect` assertions | M | T2.3 | [03](03-model-pytest.md#t25) |
| T2.6 | pytest plugin: options, fixtures, app lifecycle | M | T2.3 | [03](03-model-pytest.md#t26) |
| T2.7 | Failure artifacts (screenshots, tree dump) | M | T2.6, T1.5, T3.4a | [03](03-model-pytest.md#t27) |
| T2.8 | Event stream (NDJSON over TCP/file) | M | T2.6, T0.5 | [03](03-model-pytest.md#t28) |
| T2.9 | Examples project against demo app | M | T2.4, T2.5, T2.6 | [03](03-model-pytest.md#t29) |
| T3.1 | Static discovery (ast) | M | T0.5 | [04](04-cli-server.md#t31) |
| T3.2 | CLI skeleton + `run` + `discover` | M | T2.6, T3.1 | [04](04-cli-server.md#t32) |
| T3.3 | Target loading + `highlight` + `check` | M | T3.2, T2.3 | [04](04-cli-server.md#t33) |
| T3.4a | Tree dump module | S | T1.2 | [04](04-cli-server.md#t34a) |
| T3.4 | `inspect` command | S | T3.2, T3.4a | [04](04-cli-server.md#t34) |
| T3.5 | Locator suggestion | M | T1.8 | [04](04-cli-server.md#t35) |
| T3.6 | Spy session (hooks) + `wtk spy` | L | T1.12, T3.5 | [04](04-cli-server.md#t36) |
| T3.7 | `doctor` | M | T3.2, T1.6 | [04](04-cli-server.md#t37) |
| T3.8 | `serve` JSON-RPC server | L | T3.3, T3.4, T3.5, T3.6, T0.5 | [04](04-cli-server.md#t38) |
| T4.1 | Interpreter resolution + server client + status bar | M | T0.2, T0.5, T3.8 | [06](06-vscode.md#t41) |
| T4.2 | Project roots + discovery store | M | T4.1 | [06](06-vscode.md#t42) |
| T4.3 | CodeLens + Highlight/Check commands + diagnostics | M | T4.2 | [06](06-vscode.md#t43) |
| T4.4 | Test controller (run profile) | L | T4.2, T2.8, T3.2 | [06](06-vscode.md#t44) |
| T4.5 | Debug profile | M | T4.4 | [06](06-vscode.md#t45) |
| T4.6 | `wtk init` + Initialize command + pytest-explorer conflict prompt | M | T4.1 | [06](06-vscode.md#t46) |
| T4.7 | Extension integration tests (E2E) | M | T4.3, T4.4, T4.5 | [06](06-vscode.md#t47) |
| T5.1 | Elements tree view | M | T4.3 | [06](06-vscode.md#t51) |
| T6.1 | Spy webview | L | T4.1, T3.8 | [06](06-vscode.md#t61) |
| T6.2 | "Add to screen" code insertion | M | T6.1, T4.2 | [06](06-vscode.md#t62) |
| T7.1 | Results JSON + HTML report | M | T2.7, T2.8 | [07](07-report-ci-release.md#t71) |
| T7.2 | Report + JUnit wiring in CLI and VS Code | S | T7.1, T4.4 | [07](07-report-ci-release.md#t72) |
| T7.3 | Integration CI job | S | T0.4, T2.9 | [07](07-report-ci-release.md#t73) |
| T8.1 | Python packaging | S | T3.8 | [07](07-report-ci-release.md#t81) |
| T8.2 | VSIX packaging + release workflow | M | T4.7, T8.1 | [07](07-report-ci-release.md#t82) |
| T8.3 | User guide | M | all features | [07](07-report-ci-release.md#t83) |

### Parallel waves

Tasks in the same wave can run concurrently once their dependencies are merged.

```
Wave 1:  T0.1  T0.2  T0.3
Wave 2:  T0.4  T0.5  T1.0
Wave 3:  T1.1  T1.4  T1.7  T2.1  T2.2  T3.1
Wave 4:  T1.2  T1.5  T1.12
Wave 5:  T1.3  T1.6  T3.4a
Wave 6:  T1.8
Wave 7:  T1.9  T1.10  T3.5
Wave 8:  T1.11  T3.6
Wave 9:  T2.3
Wave 10: T2.4  T2.5  T2.6
Wave 11: T2.7  T2.8  T2.9  T3.2
Wave 12: T3.3  T3.4  T3.7  T7.1  T7.3
Wave 13: T3.8  T7.2(python half)
Wave 14: T4.1  T8.1
Wave 15: T4.2  T4.6  T6.1
Wave 16: T4.3  T4.4  T6.2
Wave 17: T4.5  T5.1  T7.2(vscode half)
Wave 18: T4.7
Wave 19: T8.2  T8.3
```

Critical path: T0.1 → T1.0 → T1.1 → T1.2 → T1.3 → T1.8 → T1.10 → T1.11 → T2.3 → T2.6 → T3.2 →
T3.3 → T3.8 → T4.1 → T4.2 → T4.4 → T4.5 → T4.7 → T8.2.

---

## 6. T0.1 — Repo + Python project scaffold <a id="t01"></a>

- **Depends on:** —
- **Files:** root `.gitignore`, `.gitattributes`, `.editorconfig`, `LICENSE`, `README.md`;
  `python/pyproject.toml`, `python/src/wintestkit/{__init__.py,__main__.py,py.typed}`,
  `python/tests/{conftest.py,unit/test_smoke.py}`, `python/README.md`, `python/uv.lock`.
- **Spec:**
  - `.gitignore`: Python (`__pycache__/`, `.venv/`, `*.egg-info/`, `dist/`, `.pytest_cache/`,
    `.ruff_cache/`), Node (`node_modules/`, `vscode/dist/`, `*.vsix`), .NET (`demo/**/bin/`,
    `demo/**/obj/`), WinTestKit outputs (`wtk-report/`, `wtk-results/`), `.vscode-test/`.
  - `.gitattributes`: `* text=auto eol=lf`, `*.cs text eol=crlf`, `*.xaml text eol=crlf`,
    `*.png binary`.
  - `.editorconfig`: 4 spaces Python/C#, 2 spaces TS/JSON/YAML/XAML, LF (CRLF for C#/XAML).
  - `LICENSE`: MIT, "Copyright (c) 2026 Massimo Nodin".
  - `README.md`: keep the icon header, one-paragraph description, links to `docs/plan/` and
    `docs/research.md`, "Development" section with the commands below.
  - `python/pyproject.toml`:
    ```toml
    [project]
    name = "wintestkit"
    dynamic = ["version"]
    description = "UI test automation for Windows WPF applications"
    readme = "README.md"
    requires-python = ">=3.12"
    license = "MIT"
    dependencies = ["comtypes>=1.4.8"]
    classifiers = ["Operating System :: Microsoft :: Windows", "Framework :: Pytest"]

    [project.scripts]
    wtk = "wintestkit.cli:main"

    [project.entry-points.pytest11]
    wintestkit = "wintestkit.pytest_plugin"

    [build-system]
    requires = ["hatchling"]
    build-backend = "hatchling.build"

    [tool.hatch.version]
    path = "src/wintestkit/__init__.py"

    [dependency-groups]
    dev = ["pytest>=8.3", "ruff>=0.7", "pyright>=1.1.390", "jsonschema>=4.23"]

    [tool.ruff]
    line-length = 100
    target-version = "py312"
    [tool.ruff.lint]
    select = ["E", "F", "W", "I", "UP", "B", "SIM", "RUF"]

    [tool.pyright]
    include = ["src"]
    typeCheckingMode = "strict"
    pythonVersion = "3.12"

    [tool.pytest.ini_options]
    testpaths = ["tests"]
    markers = [
      "integration: needs an interactive desktop and the built demo app",
      "slow: takes more than 5 seconds",
    ]
    addopts = "-p no:wintestkit"   # don't auto-load our own plugin in our own unit tests
    ```
    Note: tests that exercise the plugin load it explicitly with `pytester` / `-p wintestkit`.
    Hatchling requires the readme to be inside the Python project directory; use
    `python/README.md` for package metadata rather than the root `../README.md`.
  - Until `pytest_plugin.py` / `cli.py` exist (T2.6 / T3.2), create them as stubs so the entry
    points import: `cli.main()` prints the version and returns 0; `pytest_plugin.py` is empty
    apart from a module docstring.
  - `__init__.py`: `__version__ = "0.1.0"` and a docstring. (Public re-exports are added in T2.3.)
  - `__main__.py`: `from wintestkit.cli import main; raise SystemExit(main())`.
  - `tests/conftest.py`: defines `demo_app_path` (session fixture) returning `Path` from
    `WTK_DEMO_APP` or the default path; calls `pytest.skip("demo app not built: run dotnet build
    demo/DemoApp -c Release")` if missing. Also auto-skips `integration` tests when not on Windows.
- **Done when:** `cd python && uv sync && uv run pytest` passes (smoke test asserts
  `wintestkit.__version__`), `uv run wtk` prints `wintestkit 0.1.0`, `uv run python -m wintestkit`
  same, ruff and pyright clean.
