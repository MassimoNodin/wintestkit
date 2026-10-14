# 03 — Element Model, `expect`, Config, pytest Plugin (T2.1–T2.9)

## T2.1 — Config loader <a id="t21"></a>

- **Depends on:** T1.0 · **Size:** S
- **Files:** `src/wintestkit/config.py`, `tests/unit/test_config.py`
- **Spec:** config lives in the project's `pyproject.toml` under `[tool.wintestkit]`.
  ```toml
  [tool.wintestkit]
  launch = "per-session"        # "per-test" | "per-session" | "attach"
  timeout = 10.0                # default auto-wait, seconds, > 0
  input_mode = "pattern"        # "pattern" | "mouse"   (default strategy for click())
  screenshots = "on-failure"    # "off" | "on-failure" | "every-step"
  report_dir = "wtk-report"     # relative to project root
  highlight_actions = false     # flash each element before acting (debugging aid)
  slow_mo_ms = 0                # sleep after each action
  python_paths = ["."]          # added to sys.path by `wtk serve` / targets loader (relative to root)

  [tool.wintestkit.app]
  path = "../../demo/DemoApp/bin/Release/net8.0-windows/DemoApp.exe"   # relative to root, or absolute
  args = []
  cwd = "."                     # optional; default: directory of the exe
  env = {}                      # extra env vars
  process = "DemoApp.exe"       # optional; default: file name of path
  startup_timeout = 30.0
  close_timeout = 10.0
  ```
  ```python
  @dataclass(frozen=True)
  class AppConfig:
      path: Path | None; args: tuple[str, ...]; cwd: Path | None; env: Mapping[str, str]
      process: str | None; startup_timeout: float; close_timeout: float
      @property
      def process_name(self) -> str      # process or path.name; ConfigError if neither

  @dataclass(frozen=True)
  class WtkConfig:
      root: Path                         # dir containing the pyproject.toml (cwd if none found)
      found: bool                        # whether a [tool.wintestkit] table existed
      app: AppConfig | None
      launch: Literal["per-test","per-session","attach"]
      timeout: float
      input_mode: Literal["pattern","mouse"]
      screenshots: Literal["off","on-failure","every-step"]
      report_dir: Path                   # absolute
      highlight_actions: bool
      slow_mo_ms: int
      python_paths: tuple[Path, ...]     # absolute

  def find_project_root(start: Path) -> Path | None    # nearest ancestor with pyproject.toml containing [tool.wintestkit]
  def load_config(start: Path | None = None, overrides: Mapping[str, Any] | None = None) -> WtkConfig
  ```
  - Parse with `tomllib`. Unknown keys → `ConfigError(f"unknown key tool.wintestkit.{k}")`
    (with `.key`). Type/enum errors → `ConfigError` naming the key and allowed values.
  - Precedence: defaults < pyproject < environment (`WTK_APP_PATH`, `WTK_LAUNCH`, `WTK_TIMEOUT`,
    `WTK_INPUT_MODE`, `WTK_SCREENSHOTS`) < `overrides` (from CLI/pytest options, keys use the TOML
    names, nested app keys as `"app.path"`).
  - Relative paths resolve against `root`. `app.path` existence is **not** checked here (doctor
    and launch do it).
  - `launch = "attach"` with no `app` table is allowed if `app.process` is set via override; else
    `ConfigError("launch='attach' needs tool.wintestkit.app.process or app.path")`.
- **Done when:** unit tests (tmp_path pyprojects) for defaults, every key, precedence, unknown key,
  bad enum, relative path resolution, no pyproject (found=False, defaults).

---

## T2.2 — Runtime context + step events <a id="t22"></a>

- **Depends on:** T1.0 · **Size:** S
- **Files:** `src/wintestkit/runtime.py`, `tests/unit/test_runtime.py`
- **Spec:** the only module with process-global mutable state.
  ```python
  @dataclass
  class StepRecord:                     # mirrors protocol StepEvent
      seq: int; action: str; target: str; locator: str; args: dict[str, Any]
      start: float; duration: float = 0.0; status: Literal["passed","failed"] = "passed"
      error: dict[str, Any] | None = None; screenshot: str | None = None
      def to_dict(self) -> dict[str, Any]

  StepListener = Callable[[StepRecord], None]

  def get_config() -> WtkConfig            # set by plugin/CLI; default load_config() lazily
  def set_config(cfg: WtkConfig) -> None
  def add_step_listener(fn: StepListener) -> Callable[[], None]   # returns remover
  def begin_test(test_id: str) -> None     # resets seq counter
  def end_test() -> None
  def current_test() -> str | None

  @contextmanager
  def step(action: str, target: str, locator: str, args: Mapping[str, Any] | None = None,
           *, secret: bool = False) -> Iterator[StepRecord]
      # creates record (args redacted per protocol rule; secret=True redacts all args),
      # yields it, on exit sets duration/status/error (from exception .to_dict() or
      # {"type": type(e).__name__, "message": str(e)}), notifies listeners (listener errors logged, never raised),
      # then re-raises any exception. Applies slow_mo_ms after successful steps.
  ```
  - `args` values are made JSON-safe (`re.Pattern` → `/pattern/flags`, other non-JSON → `repr`).
  - Thread-safe listener list (lock).
- **Done when:** unit tests for seq numbering, redaction, error capture, listener isolation,
  slow-mo (with patched sleep).

---

## T2.3 — Screen / Window / Element model <a id="t23"></a>

- **Depends on:** T1.8–T1.12, T2.1, T2.2 · **Size:** L
- **Files:** `src/wintestkit/model.py`, update `src/wintestkit/__init__.py` (public API),
  `tests/unit/test_model.py`, `tests/integration/test_model.py`
- **Public API** (`wintestkit/__init__.py` exports exactly): `Screen, Window, Element, Elements,
  BoundElement, BoundElements, BoundWindow, App, expect, load_config, WtkConfig, errors` (module),
  `__version__`.
- **Spec:**
  ```python
  class Window:
      def __init__(self, *, title: Matcher | None = None, process: str | None = None,
                   class_name: Matcher | None = None, automation_id: Matcher | None = None,
                   index: int | None = None) -> None
      locator: WindowLocator
      name: str | None                # attribute name (via __set_name__)
      owner: type | None
      source: tuple[str, int] | None  # (file, 1-based line) captured at construction via sys._getframe(1)
      def __set_name__(self, owner, name) -> None
      @overload
      def __get__(self, obj: None, owner) -> "Window": ...
      @overload
      def __get__(self, obj: "Screen", owner) -> "BoundWindow": ...

  class Element:
      def __init__(self, *, automation_id: Matcher | None = None, name: Matcher | None = None,
                   control_type: str | None = None, class_name: Matcher | None = None,
                   index: int | None = None, depth: int | None = None,
                   within: "Element | None" = None, window: Window | None = None,
                   timeout: float | None = None) -> None
      # validation at definition time: control_type normalized (ValueError lists valid names);
      # empty locator without index -> ValueError; within must be an Element (not Elements)
      name: str | None; owner: type | None; source: tuple[str, int] | None
      @property
      def qualname(self) -> str       # f"{owner.__qualname__}.{name}" or "<anonymous>"
      def locator(self) -> Locator    # builds Locator incl. within chain (recursively) and window
      def __set_name__, __get__ (class access -> Element, instance access -> BoundElement)

  class Elements(Element):           # same kwargs except index; __get__ -> BoundElements

  class Screen:
      window: ClassVar[Window | None] = None   # subclasses usually set it; None = app main window
      def __init__(self, app: App) -> None
      app: App
      @classmethod
      def elements(cls) -> dict[str, Element]  # declared Element/Elements in MRO order
      def check(self) -> dict[str, BaseException | None]   # resolve every element once (timeout 0)
  ```
  **BoundElement** (returned by instance attribute access; cheap, holds `screen`, `element`, and
  an optional derived `Locator` override for `nth`/`row`/`cell`):
  ```python
  class BoundElement:
      screen: Screen; definition: Element
      @property
      def locator(self) -> Locator
      @property
      def qualname(self) -> str
      # --- resolution
      def resolve(self, timeout: float | None = None) -> UIAElement   # wait attached (strict)
      def exists(self, timeout: float = 0) -> bool
      def info(self) -> ElementInfo
      # --- actions (all auto-wait, all emit a runtime.step)
      def click(self, *, mode: InputMode | None = None, timeout: float | None = None) -> None
      def double_click(self, *, timeout=None) -> None
      def right_click(self, *, timeout=None) -> None
      def hover(self, *, timeout=None) -> None
      def type(self, text: str, *, clear: bool = True, keys: bool = False, timeout=None) -> None
      def clear(self, *, timeout=None) -> None
      def press(self, keys: str, *, timeout=None) -> None
      def select(self, item: str | int | re.Pattern[str], *, timeout=None) -> None
      def check(self, *, timeout=None) -> None
      def uncheck(self, *, timeout=None) -> None
      def expand(self, *, timeout=None) -> None
      def collapse(self, *, timeout=None) -> None
      def focus(self, *, timeout=None) -> None
      def scroll_into_view(self, *, timeout=None) -> None
      def highlight(self, duration_ms: int = 1500, *, timeout=None) -> None
      def wait_for(self, state: State = "visible", *, timeout=None) -> "BoundElement"
      # --- reads (auto-wait for attached only)
      @property
      def text(self) -> str
      @property
      def value(self) -> str
      def is_enabled(self) -> bool
      def is_visible(self) -> bool       # no wait: False if not attached
      def is_checked(self) -> bool
      def selected_items(self) -> list[str]
      # --- derivation
      def nth(self, i: int) -> "BoundElement"                # locator.with_index(i)
      def row(self, i: int) -> "BoundElement"                # item=row
      def cell(self, row: int, column: int | str) -> "BoundElement"
      def find_row(self, column: int | str, value: Matcher, *, timeout=None) -> "BoundElement"
      def __repr__(self) -> str          # "<BoundElement MainScreen.sign_in Button[name=\"Sign in\"]>"
  ```
  **Auto-wait contract per action** (timeout = per-call > `Element(timeout=)` > config):
  | Action | States waited for (in one `wait_until` loop, re-resolving each poll) |
  |---|---|
  | click/double/right/hover, type, clear, press, select, check/uncheck, expand/collapse, focus | attached + enabled; visible unless the element supports ScrollItem/VirtualizedItem (then `ensure_visible` handles it) |
  | highlight, scroll_into_view | attached |
  | text, value, is_checked, selected_items, info | attached |
  | is_enabled | attached |
  | exists, is_visible | none (single attempt unless `exists(timeout>0)`) |

  Implementation shape for each action:
  ```python
  def click(self, *, mode=None, timeout=None):
      with runtime.step("click", self.qualname, self.locator.describe(), {"mode": mode}) as rec:
          el = self._actionable(timeout)                 # wait_until(resolve + state checks)
          self._maybe_highlight(el)                      # config.highlight_actions
          rec.args["strategy"] = actions.click(el, mode=mode or cfg.input_mode)
  ```
  If an action raises `UIAError(element_gone=True)` mid-way, retry the whole resolve+act once.

  **BoundWindow**: `resolve(timeout)`, `exists`, `wait_for(state)`, `close()`, `maximize()`,
  `minimize()`, `restore()`, `title` property, `is_visible()`, `highlight()`, `info()`. Window
  resolution uses `resolve_window`.

  **Screen.window semantics:** element locators get `scope = Scope(app, type(screen).window
  .locator if set else None)`. An Element with `window=` overrides it.

  **`within=` across classes:** `within` may reference an Element from a base class or another
  Screen; its own `window` (if any) is ignored — the chain lives in the referencing element's
  window.
- **Done when:**
  - Unit tests (no UIA, resolver/actions patched): descriptor behaviour (class access returns
    definition, instance returns bound), qualname, `source` line, locator building incl. within
    chains and window override, validation errors, step emission (action name, target, redaction
    for PasswordBox determined from locator class_name), timeout precedence, `Screen.elements()`
    inheritance order.
  - Integration test file with a `MainScreen`/`NoteDialogScreen` matching the README example runs
    login success, Panel B OK, async Load → Continue (auto-wait on enabled), dialog Save flow,
    MessageBox OK (`window=Window(class_name="#32770")`).

---

## T2.4 — `Elements` collections + grid helpers <a id="t24"></a>

- **Depends on:** T2.3 · **Size:** M
- **Files:** `model.py` (extend), `tests/integration/test_collections.py`
- **Spec:**
  ```python
  class BoundElements:
      def count(self, *, timeout: float = 0) -> int       # resolve_all
      def nth(self, i: int) -> BoundElement                 # locator.with_index(i)
      def first(self) -> BoundElement; def last(self) -> BoundElement   # last = nth(count()-1) at call time
      def all(self) -> list[BoundElement]                   # [nth(i) for i in range(count())]
      def texts(self) -> list[str]
      def __iter__(self) -> Iterator[BoundElement]
      def __len__(self) -> int
      def filter(self, *, name: Matcher | None = None, class_name: Matcher | None = None,
                 automation_id: Matcher | None = None) -> "BoundElements"   # narrows the locator
  ```
  - `count` on virtualized lists counts only realized items (document this in the docstring and
    the guide). For grids, `BoundElement.row_count()` uses `grid_size` (true count) — add
    `row_count()` and `column_count()` to `BoundElement`.
  - `find_row(column, value)`: for `r in range(row_count)`: read `cell(r, column)` text via
    `grid_item` (which realizes/scrolls); return `row(r)` on first match; uses the action timeout
    only for initial grid resolution. Cap: 10,000 rows → `ActionError`.
- **Done when:** integration: `Elements(control_type="Button", name="OK").count() == 2`;
  `texts()` of the ComboBox items after expand == `["Red","Green","Blue"]`; grid `row_count() ==
  200`; `find_row("Name", "Product 180").click()` → status `Row: Product 180`; `cell(9, "Qty").text
  == "1"` (row index 9 is Product 10, Qty = (10 × 7) mod 23 = 1).

---

## T2.5 — `expect` assertions <a id="t25"></a>

- **Depends on:** T2.3 · **Size:** M
- **Files:** `src/wintestkit/expect.py`, `tests/unit/test_expect.py`, `tests/integration/test_expect.py`
- **Spec:**
  ```python
  def expect(target: BoundElement | BoundElements | BoundWindow, *, timeout: float | None = None) -> Expectation

  class Expectation:
      @property
      def not_(self) -> "Expectation"        # negated copy
      def to_exist(self) -> None             # attached
      def to_be_visible(self) -> None
      def to_be_hidden(self) -> None         # not attached or offscreen
      def to_be_enabled(self) -> None
      def to_be_disabled(self) -> None
      def to_be_checked(self) -> None
      def to_have_text(self, expected: str | re.Pattern[str]) -> None    # str: exact after strip()
      def to_contain_text(self, expected: str) -> None
      def to_have_value(self, expected: str | re.Pattern[str]) -> None
      def to_have_count(self, n: int) -> None                            # BoundElements only
      def to_be_selected(self) -> None                                   # SelectionItem.IsSelected
      def to_have_property(self, name: str, expected: Any) -> None       # any UIA property by PROPERTY_IDS name
  ```
  - Each assertion polls (`wait_until`) until satisfied or timeout (same precedence as actions).
    Negation waits for the opposite.
  - Failure raises `AssertionError` (so pytest shows it as a test failure, not an error) with
    message: `expect(MainScreen.status).to_have_text("Welcome, admin") failed after 10.0s\n
    Expected: "Welcome, admin"\n  Actual: "Invalid credentials"\n  Locator: *[id="StatusText"]`.
    If the element was never found, append the formatted diagnostic.
  - Emits a step `expect.<method>` with args `{expected: ...}`.
- **Done when:** unit tests with patched element reads (pass immediately, pass after delay, fail
  message exact, negation); integration: `to_have_text` waits through the async Load flow;
  `not_.to_exist()` for collapsed `Data loaded` before load.

---

## T2.6 — pytest plugin: options, fixtures, app lifecycle <a id="t26"></a>

- **Depends on:** T2.3 · **Size:** M
- **Files:** `src/wintestkit/pytest_plugin.py`, `tests/unit/test_plugin.py` (uses `pytester`)
- **Spec:**
  - Registered via the `pytest11` entry point (T0.1). Must be a no-op for projects without
    `[tool.wintestkit]` **unless** a `wtk_*` fixture is requested (so installing wintestkit never
    breaks unrelated pytest projects).
  - Command-line options (group "wintestkit"):
    | Option | Maps to config |
    |---|---|
    | `--wtk-launch {per-test,per-session,attach}` | `launch` |
    | `--wtk-timeout SECONDS` | `timeout` |
    | `--wtk-app PATH` | `app.path` |
    | `--wtk-input-mode {pattern,mouse}` | `input_mode` |
    | `--wtk-screenshots {off,on-failure,every-step}` | `screenshots` |
    | `--wtk-highlight` | `highlight_actions = true` |
    | `--wtk-slowmo MS` | `slow_mo_ms` |
    | `--wtk-report DIR` / `--wtk-no-report` | `report_dir` / disable report (T7.1) |
    | `--wtk-events URL` | T2.8 |
  - `pytest_configure`: `load_config(rootdir, overrides)` → `runtime.set_config`; register marker
    `wtk(launch=..., timeout=...)`. Config errors → `pytest.UsageError(str(err))`.
  - Fixtures:
    - `wtk_config` (session): the `WtkConfig`.
    - `app` (function): returns an `App`, according to effective launch mode (marker `wtk(launch=)`
      overrides config for that test):
      - `per-session`: a session-scoped helper (`_wtk_session_app`) launches once on first use and
        closes at session end. Before handing it to a test, if `not app.is_running()` (previous
        test crashed it) relaunch.
      - `per-test`: launch before, `close()` after each test.
      - `attach`: `App.attach(process=config.app.process_name)` per test; never closed.
      - If `config.app is None` and mode isn't attach → `pytest.UsageError`-style error raised as a
        fixture error with a message pointing to `[tool.wintestkit.app]`.
    - `screen` factory fixture: `screen(MainScreen) -> MainScreen(app)`. Convenience.
  - Hooks: `pytest_runtest_setup` → `runtime.begin_test(item.nodeid)`; `pytest_runtest_teardown`
    (trylast) → `runtime.end_test()`. Marker `timeout=` sets a per-test default timeout.
- **Done when:** `pytester` tests: plugin inactive without config; options override config;
  marker override; `app` fixture launches/attaches per mode using a fake `App` class patched in
  (unit), and one integration test running a 2-test file against the demo in per-session mode
  (asserts single launch) and per-test mode (asserts two launches).

---

## T2.7 — Failure artifacts <a id="t27"></a>

- **Depends on:** T2.6, T1.5, T3.4a · **Size:** M
- **Files:** `pytest_plugin.py` (extend), `tests/integration/test_artifacts.py`
- **Spec:**
  - Artifacts directory per test: `<report_dir>/artifacts/<safe_id>/` where `safe_id` = nodeid
    with every char not in `[A-Za-z0-9._-]` replaced by `_`, truncated to 120 chars + 8-char sha1
    suffix.
  - `pytest_runtest_makereport` (hookwrapper): when `call.excinfo` and phase is `call` (or setup
    error) and `screenshots != "off"`:
    - `window.png`: the app main window (if running), `desktop.png`: full virtual screen.
    - `tree.txt`: `treedump.dump(app.main_window(), max_depth=12, max_nodes=3000)` (T3.4a).
    - Store paths on `item.stash[ARTIFACTS_KEY]` for the events/report tasks; attach as
      `report.sections.append(("wintestkit", "screenshots: ..."))`.
  - `every-step` mode: a step listener captures `window.png` after each step into
    `steps/<seq>.png` and sets `StepRecord.screenshot` (relative to report dir).
  - Capturing must never fail the test: wrap in try/except, log a warning.
- **Done when:** a deliberately failing integration test produces the three files; every-step
  produces one PNG per step; artifact capture errors are swallowed.

---

## T2.8 — Event stream <a id="t28"></a>

- **Depends on:** T2.6, T0.5 · **Size:** M
- **Files:** `src/wintestkit/events.py`, `pytest_plugin.py` (extend), `tests/unit/test_events.py`,
  `tests/contract/test_events_contract.py`
- **Spec:**
  - `--wtk-events URL` where URL is `tcp://127.0.0.1:<port>` (connect as client) or a file path
    (`file:///C:/x.ndjson` or plain path; append-truncate on session start).
  - `class EventSink: emit(event: dict) -> None; close()` — thread-safe; `TcpSink` (connect with 5 s
    timeout, `TCP_NODELAY`, write `json.dumps(e, separators=(",",":")) + "\n"`, flush per event; if
    the socket breaks, log once and drop further events — never fail the run), `FileSink`.
  - Emit the protocol `RunEvent`s (05-protocol §4):
    - `session_start` in `pytest_sessionstart`.
    - `collected` in `pytest_collection_finish` (all items; `line` = `item.location[1]`
      (0-based already); `parent` = class nodeid or, for parametrized items, the un-parametrized
      function nodeid). Collection errors from `pytest_collectreport` failures.
    - `test_start` in `pytest_runtest_logstart`.
    - `step` from a runtime step listener.
    - `test_output`: captured stdout/stderr/log from reports at test end (one event per non-empty
      stream).
    - `test_end` in `pytest_runtest_logreport`: outcome mapping — call phase passed/failed/skipped;
      setup/teardown failure → `error`; skip in setup → `skipped`. Emit **one** `test_end` per test
      (after teardown), merging phases; duration = sum of phases.
      `message` = for `AssertionError`/`WtkError`: `str(exc)`; else `repr(exc)` short form.
      `location` = deepest traceback frame whose file is under the project root and **not** inside
      the `wintestkit` package or site-packages (0-based line). `error` = `WtkError.to_dict()` when
      the exception is a WtkError (gives VS Code the diagnostic). `screenshots` from T2.7 stash.
    - `session_end` in `pytest_sessionfinish` with summary and exit code.
- **Done when:** unit tests with `pytester` and a FileSink produce a stream that validates against
  `events.schema.json` (contract test) for passing, failing, skipped, error-in-fixture,
  parametrized and collection-error cases; TCP sink tested with a local socket server.

---

## T2.9 — Examples project <a id="t29"></a>

- **Depends on:** T2.4, T2.5, T2.6 · **Size:** M
- **Files:** `examples/demo-tests/pyproject.toml`, `examples/demo-tests/README.md`,
  `screens/__init__.py`, `screens/main.py`, `screens/dialogs.py`, `tests/test_login.py`,
  `tests/test_panels.py`, `tests/test_async.py`, `tests/test_choices.py`, `tests/test_lists.py`,
  `tests/test_dialogs.py`, `tests/test_menu.py`, `tests/test_expected_failure.py`, `conftest.py`
- **Spec:**
  - `pyproject.toml`: a non-package project (`[project] name="demo-tests"`, `requires-python>=3.12`,
    dependency `wintestkit` as a path dependency `{ path = "../../python", editable = true }` via
    `[tool.uv.sources]`), `[tool.pytest.ini_options] pythonpath = ["."]`, `testpaths=["tests"]`,
    `[tool.wintestkit]` with `launch="per-session"`, app path pointing at the demo build.
  - `conftest.py`: autouse function fixture that, before every test, clicks `File > Reset` (via
    `MainScreen`), so tests are independent in per-session mode.
  - `screens/main.py`: `MainScreen` defining every main-window element of the demo (use the
    black-box style: `within=` groups, class names, `automation_id` only for `StatusText` and
    `ColorCombo`), `menu_file`, `menu_reset`, `items = Element(control_type="List")`,
    `products = Element(control_type="DataGrid")`, `list_items = Elements(control_type="ListItem")`.
  - `screens/dialogs.py`: `NoteDialog` (`window = Window(title="WTK Demo - Dialog")`),
    `MessageBox` (`window = Window(class_name="#32770")`, `ok = Element(control_type="Button",
    name="OK")`, `text = Element(control_type="Text", index=0)` — verify).
  - ≥ 15 tests covering every demo behaviour; one parametrized test (login matrix).
  - `tests/test_expected_failure.py`: a test marked `@pytest.mark.skipif(os.environ.get("WTK_DEMO_FAILURES") != "1", ...)`
    that intentionally fails on a misspelled locator — used to demo/diagnose failure output and by
    T4.7/T7.1 tests.
- **Done when:** `cd examples/demo-tests && uv sync && uv run pytest` passes all tests against the
  built demo app (and `WTK_DEMO_FAILURES=1` shows a readable locator diagnostic).
