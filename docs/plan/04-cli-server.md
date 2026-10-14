# 04 — Discovery, CLI, Locator Suggestion, Spy, Doctor, Server (T3.1–T3.8)

## T3.1 — Static discovery <a id="t31"></a>

- **Depends on:** T0.5 · **Size:** M
- **Files:** `src/wintestkit/discovery.py`, `tests/unit/test_discovery.py`,
  `tests/unit/fixtures/discovery/**` (sample project trees), `tests/contract/test_discovery_contract.py`
- **Spec:** pure `ast` analysis — **never imports user code**, never touches UIA.
  ```python
  def discover(root: Path, *, paths: Sequence[Path] | None = None,
               overrides: Mapping[Path, str] | None = None) -> DiscoveryResult
  def discover_file(root: Path, file: Path, source: str) -> tuple[list[TestEntry], list[ScreenEntry], list[DiscoveryError]]
  ```
  (`DiscoveryResult`, `TestEntry`, `ScreenEntry`, `ElementEntry` dataclasses with `to_dict()`
  matching 05-protocol §2.)
  - **Files scanned:** all `*.py` under `root` (or under `paths`), excluding directories named
    `.venv`, `venv`, `env`, `.git`, `node_modules`, `__pycache__`, `build`, `dist`, `.tox`,
    `.pytest_cache`, `site-packages`, and the configured `report_dir`. Read as UTF-8 (BOM ok);
    `overrides` content wins over disk.
  - **Tests** (pytest default rules, overridable by `[tool.pytest.ini_options]` `python_files`,
    `python_classes`, `python_functions` — glob patterns, space-separated or list):
    files matching `test_*.py` or `*_test.py`; module-level `def`/`async def` matching `test*`;
    classes matching `Test*` with no `__init__`, their methods matching `test*`. Respect
    `testpaths` if set (only files under them). nodeid = POSIX relpath from root + `::Class` +
    `::func`. Ranges include decorators (`min(decorator.lineno)`), end from `end_lineno/end_col_offset`.
    `nameRange` = the identifier after `def`/`class` (compute from source line text).
  - **Screens:** two passes over all scanned files.
    1. Collect every `ClassDef` (incl. nested) with its base names (`Name.id` or `Attribute.attr`).
    2. A class is a screen if any base is `Screen` or (transitively) a discovered screen class name.
       Name collisions across files are fine (match by name only).
  - **Elements** in a screen class body: `Assign` (single `Name` target) or `AnnAssign` with value,
    where the value is a `Call` whose func is `Name`/`Attribute` named `Window`, `Element` or
    `Elements` → kind `window`/`element`/`elements`.
    - Literal kwargs → `LocatorData` (snake_case kwarg → camelCase key): `str` constants;
      `int` constants for `index`/`depth`; `re.compile("pat")` or `re.compile("pat", re.I)` /
      `re.IGNORECASE | re.M` → `{"regex": "pat", "flags": "im"}` (flags letters sorted).
    - `within=<Name>` where Name is another attribute of the same class (or a base screen) →
      `withinName`; also nest that element's locator under `locator.within` when resolvable
      statically (recursively, cycle-safe).
    - `window=<Name>`/`window=Window(...)` → `windowName` / inline `locator.window`.
    - Any other non-literal kwarg (variables, f-strings, calls) → `dynamic: true` and the key is
      omitted.
    - The class-level `window = Window(...)` is reported as an element of kind `window` named
      `window`.
  - Syntax errors → `DiscoveryError(file, msg, line0)`; the file contributes nothing else.
  - Results sorted: tests by file then line; screens by file then line.
  - Performance: 500 files < 1 s (cache parsed trees by `(path, mtime, size)` in a module-level LRU
    used by `wtk serve`).
- **Done when:** unit tests over fixture trees cover: function/class/method/async tests, decorators
  in range, custom `python_files`, testpaths, screen inheritance across files, nested `within`
  chain, regex flags, dynamic kwargs, `AnnAssign`, syntax error file, overrides; contract test
  validates output against `discovery.schema.json`.

---

## T3.2 — CLI skeleton, `run`, `discover` <a id="t32"></a>

- **Depends on:** T2.6, T3.1 · **Size:** M
- **Files:** `src/wintestkit/cli.py`, `tests/unit/test_cli.py`
- **Spec:** `argparse` with subcommands; `main(argv: Sequence[str] | None = None) -> int`.
  Global options: `--root DIR` (default: `find_project_root(cwd)` or cwd), `--log-level LEVEL`,
  `--version`. Each subcommand lives in a function `cmd_<name>(args) -> int`; later tasks add
  subcommands in their own module (`wintestkit/commands/<name>.py`) registered from `cli.py`.

  **Exit codes (all commands):** `0` success · `1` test failures / element not found / check
  failures · `2` usage or config error · `3` environment not ready / app not running · `4`
  internal error (uncaught exception: print `wtk: internal error: <exc>` + hint to rerun with
  `--log-level DEBUG`, traceback at DEBUG) · `5` no tests collected (`run` only).

  **`wtk run [options] [-- pytest args...]`**
  | Option | Effect |
  |---|---|
  | `--launch`, `--timeout`, `--app`, `--input-mode`, `--screenshots`, `--highlight`, `--slowmo` | forwarded as the matching `--wtk-*` pytest options |
  | `--report DIR` / `--no-report` | `--wtk-report` / `--wtk-no-report` (default: report on, config dir) |
  | `--junit PATH` | `--junitxml=PATH` |
  | `--events URL` | `--wtk-events` |
  | `-k EXPR`, `-m EXPR`, `-x`, `--lf` | passed to pytest |
  | positional `TESTS...` | nodeids/paths passed to pytest |

  Implementation: build an argv list and call `pytest.main(argv, plugins=[])` in-process with
  `cwd = root` (`os.chdir`), `-p wintestkit` ensured, `-p no:cacheprovider` **not** added. Map
  pytest exit codes: `0→0, 1→1, 2→4 (interrupted), 3→4, 4→2, 5→5`. Before running, perform the
  quick environment checks from T3.7 (`interactive_session`, `desktop_unlocked`); failing → print
  the doctor message, exit 3 (skip with `--no-env-check`).

  **`wtk discover [PATHS...] [--json] [--pretty]`**: runs `discovery.discover`. Default output is
  JSON (one line); `--pretty` indents; without `--json` and with a TTY prints a human tree:
  ```
  Tests (16)
    tests/test_login.py::test_valid_login           (line 8)
  Screens (2)
    MainScreen  screens/main.py:6
      sign_in     Button[name="Sign in"]
  ```
- **Done when:** unit tests (pytest invoked with a fake via monkeypatch) verify argv building,
  exit-code mapping, env-check skip, discover output modes; integration: `wtk run` in
  `examples/demo-tests` passes and exits 0.

---

## T3.3 — Target loading, `highlight`, `check` <a id="t33"></a>

- **Depends on:** T3.2, T2.3 · **Size:** M
- **Files:** `src/wintestkit/targets.py`, `src/wintestkit/commands/highlight.py`,
  `src/wintestkit/commands/check.py`, `tests/unit/test_targets.py`,
  `tests/integration/test_highlight_cmd.py`
- **Spec — `targets.py`** (shared with the server):
  ```python
  @dataclass(frozen=True)
  class Target:
      file: Path; qualname: str        # "MainScreen.sign_in" or "MainScreen"
  def parse_target(text: str, root: Path) -> Target      # "screens/main.py::MainScreen.sign_in"; Windows paths ok
  class ModuleLoader:
      def __init__(self, cfg: WtkConfig) -> None         # inserts cfg.python_paths at front of sys.path
      def load(self, file: Path) -> ModuleType
          # module name from relpath to the first python_path containing it (pkg dirs with __init__.py
          # become dotted names: screens/main.py -> "screens.main"); importlib.import_module;
          # before loading, if any .py under root changed since last load (mtime scan, cached),
          # purge all sys.modules entries whose __file__ is under root so edits take effect.
      def get_screen(self, target: Target) -> type[Screen]
      def get_element(self, target: Target) -> tuple[type[Screen], str]   # screen class + attr name
  def resolve_target(app: App, loader: ModuleLoader, target: Target, timeout: float = 0) -> ElementResult
      # binds Screen(app), gets attr, resolve(timeout) -> ElementResult(status="found", element=info)
      # LocatorError -> status not_found/ambiguous with diagnostic; other WtkError -> status "error"
  ```
  `ElementResult`/`CheckResult` dataclasses mirror the protocol. Import errors raise
  `TargetError(WtkError)` with the exception summary (last traceback line + file:line).

  **`wtk highlight TARGET [--duration MS] [--launch] [--json] [--timeout S]`**
  - Attaches to the configured app (`App.attach(process=config.app.process_name)`); if not running:
    with `--launch` launch it, else exit 3 with `App is not running. Start it or pass --launch.`
  - Resolves (default timeout 0 — immediate), flashes with `overlay.flash(rect, duration,
    block=True)`. Window targets (`MainScreen.window` or bare `MainScreen`) flash the window.
  - Human output: `✓ Found Button "Sign in" at (412,233 80x24)` or the formatted diagnostic.
    `--json`: `ElementResult`. Exit 0 found, 1 not found/ambiguous, 2 bad target.

  **`wtk check TARGET [--json]`** — TARGET is `file.py` (all screens in file) or
  `file.py::Screen`. Resolves every element (timeout 0), prints a table
  `✓ sign_in  Button[name="Sign in"]` / `✗ foo  <message>` / `⚠ ok  2 elements match ...`.
  `--json`: `{ "results": CheckResult[] }`. Exit 0 if all found, else 1.
- **Done when:** unit tests for `parse_target` (incl. `C:\` paths, missing `::`), module naming,
  reload-on-change (tmp project, edit file, reload picks it up); integration: highlight found /
  ambiguous / not-found against demo via the examples project; `check screens/main.py` all ✓.

---

## T3.4a — Tree dump module <a id="t34a"></a>

- **Depends on:** T1.2 · **Size:** S
- **Files:** `engine/treedump.py`, `tests/integration/test_treedump.py`
- **Spec:**
  ```python
  def walk(root: UIAElement, max_depth: int = 50, max_nodes: int = 5000) -> Iterator[tuple[int, ElementInfo]]
  def dump(root: UIAElement, max_depth: int = 12, max_nodes: int = 3000) -> str
  def dump_json(root: UIAElement, max_depth: int, max_nodes: int) -> dict[str, Any]   # {"info": ElementInfo, "children": [...]}
  ```
  Text format, two spaces per level, one line per node:
  `Button "Sign in" [class=Button] (412,233 80x24)` — add ` id=StatusText` when automation id is
  set, ` disabled` when not enabled, ` offscreen` when offscreen. Uses cached `find_all(Children)`
  per node. Truncation appends `… (truncated at 3000 nodes)`.
- **Done when:** dump of the demo main window contains `Group "Credentials"` and indented
  `Button "Sign in"`; respects limits.

## T3.4 — `inspect` command <a id="t34"></a>

- **Depends on:** T3.2, T3.4a · **Size:** S
- **Files:** `src/wintestkit/commands/inspect.py`, `tests/integration/test_inspect_cmd.py`
- **Spec:** `wtk inspect [--window TITLE|/REGEX/] [--depth N] [--at X,Y] [--json] [--all-windows]`
  - Default root: app main window (attach via config). `--window` picks a top-level window of the
    app by title. `--all-windows`: dump every top-level window of the app. `--at X,Y`: print
    `ElementInfo` (with patterns) of the element at that physical point plus its ancestor chain.
  - `--json` uses `dump_json`/`ElementInfo.to_dict()`.
- **Done when:** commands work against the demo; `--at` on Sign in centre reports the button.

---

## T3.5 — Locator suggestion <a id="t35"></a>

- **Depends on:** T1.8 · **Size:** M
- **Files:** `engine/suggest.py`, `tests/unit/test_suggest.py`, `tests/integration/test_suggest.py`
- **Spec:**
  ```python
  @dataclass(frozen=True)
  class Suggestion:                 # mirrors protocol Suggestion
      locator: Locator; code: str; attribute_name: str
      helpers: tuple[tuple[str, str, Locator], ...]     # (attribute_name, code, locator)
      unique: bool; match_count: int; strategy: str
      window: tuple[str, WindowLocator] | None
      def to_dict(self) -> dict[str, Any]

  def suggest_locator(el: UIAElement, app: App | None = None) -> Suggestion
  def render_element_code(loc: Locator, within_attr: str | None = None, kind: str = "Element") -> str
  def render_window_code(wl: WindowLocator) -> str
  def attribute_name_for(info: ElementInfo) -> str
  ```
  - Find `top` = the element's top-level window (walk parents until parent is root). Window
    suggestion: `Window(title="<name>")`; if another top-level window of the same app has the same
    title → add `class_name`; Win32 dialogs (`#32770`) → `Window(class_name="#32770")` plus title.
  - Candidates tried in order, each verified with `query_all(top, candidate)` — accept the first
    with exactly 1 match **that is the same element** (`same_as`):
    1. `automation_id` (if non-empty and not purely numeric) + `control_type`. Strategy
       `automation_id`.
    2. `control_type` + `name` (if name non-empty, ≤ 60 chars, and doesn't look volatile: no
       digits run ≥ 4, no date/time pattern `\d{1,2}[:/]\d{2}`). Strategy `name`.
    3. `control_type` + `class_name` (+ `name` if usable). Strategy `class_name`.
    4. **within**: walk ancestors (nearest first, max 5 levels, skipping `Pane`/`Custom` with no
       name/id); for the first ancestor that itself gets a unique suggestion by rules 1–3, try
       rules 1–3 for the element scoped to that ancestor. Strategy `within`; the ancestor becomes
       a helper. Max helper depth 2 (helper of helper).
    5. **index**: `control_type` (+ `class_name`) scoped to the nearest named ancestor (or `top`)
       with `index = position among matches`. Strategy `index`, `unique` true but flagged in UI as
       fragile.
  - `attribute_name_for`: snake_case of name (`"Sign in"` → `sign_in`), else automation id
    (`StatusText` → `status_text`), else `<control_type>_<n>` (`edit_1`); strip non-identifier
    chars, prefix `_` if starting with a digit, avoid Python keywords (`class` → `class_`).
  - `render_element_code`: kwargs order `automation_id, control_type, name, class_name, index,
    within`; strings with `repr`-style escaping using double quotes; regexes as
    `re.compile("...")`. Example: `Element(control_type="Edit", class_name="PasswordBox",
    within=credentials)`.
- **Done when:** unit tests for naming, volatility heuristic, code rendering; integration on demo:
  Sign in → strategy `name`; StatusText → `automation_id`; Panel B OK → `within` with helper
  `panel_b = Element(control_type="Group", name="Panel B")`; Username box → `within` Credentials +
  `class_name`; each suggested locator resolves back to the same element.

---

## T3.6 — Spy session + `wtk spy` <a id="t36"></a>

- **Depends on:** T1.12, T3.5 · **Size:** L
- **Files:** `engine/spy.py`, `src/wintestkit/commands/spy.py`, `tests/integration/test_spy.py`
- **Spec:**
  ```python
  class SpySession:
      def __init__(self, on_hover: Callable[[UIAElement], None],
                   on_pick: Callable[[UIAElement], None],
                   on_cancel: Callable[[], None],
                   process_filter: Callable[[int], bool] | None = None,
                   throttle_ms: int = 60) -> None
      def start(self) -> None
      def stop(self) -> None          # idempotent, joins threads, removes hooks and overlay
      @property
      def running(self) -> bool
  ```
  - **Hook thread:** installs `WH_MOUSE_LL` and `WH_KEYBOARD_LL` (`SetWindowsHookExW(id, proc,
    GetModuleHandleW(None), 0)`) and runs `GetMessageW`. Hook procs must return within a few ms:
    they only push `(kind, x, y, time)` into a `queue.SimpleQueue` and decide swallowing:
    - `WM_LBUTTONDOWN` with Ctrl held (`GetAsyncKeyState(VK_CONTROL) & 0x8000`) → push `pick`,
      **return 1** (swallow) and remember to also swallow the matching `WM_LBUTTONUP`.
    - `WM_KEYDOWN` `VK_ESCAPE` → push `cancel` (do not swallow).
    - everything else → `CallNextHookEx`.
    - Keep a reference to the `HOOKPROC` ctypes callbacks (avoid GC). Stop: `PostThreadMessageW(
      tid, WM_QUIT)`, unhook.
  - **Worker thread (MTA):** drains the queue; coalesces mouse moves to at most one per
    `throttle_ms`; `from_point(x, y)`; ignore elements whose `process_id == os.getpid()` (our
    overlay) or rejected by `process_filter`; if the element differs from the last one (runtime
    id), move the `Overlay` to its rect and call `on_hover`. On `pick` → resolve element at point,
    `on_pick(el)`, keep running (caller decides to stop). On `cancel` → `on_cancel()`.
  - Callback exceptions are logged, never kill the session.
  - **`wtk spy [--all-processes]`** (terminal): process filter = app pids (unless
    `--all-processes`). Prints a live single line (`\r`-rewritten) with `info.short()`; on
    Ctrl+Click prints a block:
    ```
    Picked: Button "Sign in" [class=Button]
      window = Window(title="WTK Demo")
      sign_in = Element(control_type="Button", name="Sign in")
    ```
    (helpers printed before the element). Esc or Ctrl+C exits 0.
- **Done when:** integration test drives the hook with real `SendInput` moves over Sign in (hover
  callback receives it), a synthesized Ctrl+Click picks it **without** clicking the button (status
  unchanged), Esc cancels, `stop()` cleans up (no hooks left — verify a second session can start).

---

## T3.7 — Doctor <a id="t37"></a>

- **Depends on:** T3.2, T1.6 · **Size:** M
- **Files:** `src/wintestkit/doctor.py`, `src/wintestkit/commands/doctor.py`,
  `tests/unit/test_doctor.py`
- **Spec:**
  ```python
  @dataclass(frozen=True)
  class Check:
      id: str; title: str; status: Literal["ok","warn","fail","skip"]; detail: str; hint: str | None = None
  def run_checks(cfg: WtkConfig, *, quick: bool = False) -> list[Check]
  ```
  Checks (id — rule):
  | id | ok / warn / fail |
  |---|---|
  | `platform` | fail if not Windows 10 1809+ |
  | `python` | fail if < 3.12 |
  | `interactive_session` | fail if `ProcessIdToSessionId(pid) == 0` (service session) |
  | `desktop_unlocked` | fail if `OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)` returns NULL or the desktop name (`GetUserObjectInformationW(UOI_NAME)`) isn't `Default` (locked / UAC secure desktop) |
  | `remote_session` | warn if `GetSystemMetrics(SM_REMOTESESSION)`: "Minimizing or disconnecting RDP will break UI tests; use tscon to disconnect" |
  | `uia` | fail if `get_uia().GetRootElement()` fails |
  | `dpi` | ok with detail `"<scale>% on primary monitor"`; warn if monitors have different scales |
  | `config` | warn if no `[tool.wintestkit]`; fail on ConfigError |
  | `app_path` | fail if `app.path` set and missing; skip if no app config |
  | `app_running` | ok/warn (not running is just informational) |
  | `elevation` | fail if the app is running elevated and wtk isn't (`process_is_elevated` true / access denied) — "run your terminal/VS Code as administrator" |
  | `comtypes_cache` | warn if comtypes gen dir isn't writable (first run will be slower / fail) |
  `quick=True` runs only `interactive_session`, `desktop_unlocked`, `uia` (used by `wtk run`).
  **`wtk doctor [--json]`**: table with ✓ / ! / ✗ / - icons, details and hints; `--json` list of
  checks. Exit 3 if any `fail`, else 0.
- **Done when:** unit tests with patched win32 functions for each status; running `wtk doctor` on
  the dev machine passes.

---

## T3.8 — `wtk serve --stdio` JSON-RPC server <a id="t38"></a>

- **Depends on:** T3.3, T3.4, T3.5, T3.6, T0.5 · **Size:** L
- **Files:** `src/wintestkit/server.py`, `src/wintestkit/commands/serve.py`,
  `tests/unit/test_server.py`, `tests/integration/test_server.py`,
  `tests/contract/test_rpc_contract.py`
- **Spec:** implements every method in 05-protocol §6.
  - **Transport:** read stdin as UTF-8 lines (`sys.stdin.buffer.readline`); write responses as
    single-line JSON + `\n` to `sys.stdout.buffer`, guarded by a lock, flushed per message. Before
    serving, redirect Python's `sys.stdout` to `sys.stderr` so stray prints from user modules can't
    corrupt the protocol.
  - **Threads:** reader (main thread) → `queue.Queue` → single **worker** thread (MTA) executing
    requests in order. `spy.stop`, `shutdown` and notifications are handled on the reader thread
    immediately. Spy callbacks run on the spy worker thread and only send notifications.
  - **State:** `cfg` (loaded at `initialize` from `root`), `loader: ModuleLoader`, `app: App |
    None` (attached lazily on first need via `App.attach(process=cfg.app.process_name)`; re-attach
    if `not app.is_running()`), `nodes: LRU[str, UIAElement]` (5000), `spy: SpySession | None`.
  - Any method other than `initialize`/`shutdown` before `initialize` → error `-32600` with
    message `"not initialized"`.
  - Method mapping:
    - `discover` → `discovery.discover(cfg.root, overrides=...)` (uses parse cache).
    - `app.status` → never launches; `running` false if no process.
    - `app.launch` → `App.launch(**cfg.app)`; keeps the handle; `launched=True` (but the server
      never closes it on shutdown — users keep their app open).
    - `element.highlight` → `targets.resolve_target(timeout=0)`; on found, `overlay.flash(rect,
      durationMs or 1500, block=False)`; ElementResult with `durationMs` of the resolution. App not
      running → JSON-RPC error -32002. Bad target → -32003 with `data: {message}`.
    - `screen.check` → resolve every element of the screen (in definition order), no flashing.
    - `inspect.roots` → app top-level windows (if app configured and running), else all top-level
      windows on the desktop (control view children of root). Each registered in `nodes`.
    - `inspect.children` → cached children; `hasChildren` computed with `find_first(Children)`.
    - `inspect.properties` → `info(with_patterns=True)`, all `PROPERTY_IDS` read with errors
      skipped (value stringified; arrays joined), ancestors root-first.
    - `inspect.highlight` → flash node rect.
    - `suggest.locator` → `suggest_locator(node, app)`.
    - `spy.start` → creates `SpySession` with process filter = app pids if app running else none;
      hover → register node → notify `spy.hover`; pick → notify `spy.picked` with suggestion;
      cancel → `spy.cancelled` and stop.
    - `shutdown` → stop spy, respond `null`, exit 0. EOF on stdin → same.
  - Errors: `WtkError` subclasses map to codes per the protocol table, `data = err.to_dict()`;
    unexpected exceptions → -32603 with `data.message` and traceback logged to stderr.
  - Log notifications: forward `wintestkit` logger records ≥ configured level as `log`
    notifications (in addition to stderr).
- **Done when:** unit tests drive the server through in-memory pipes (requests → responses) with
  patched engine functions for every method incl. error paths and ordering; contract test
  validates every result payload against `rpc.schema.json`; integration test starts `python -m
  wintestkit serve --stdio` as a subprocess against the examples project and exercises
  `initialize`, `discover`, `app.status`, `element.highlight` (found + not found),
  `inspect.roots/children/properties`, `suggest.locator`, `shutdown`.
