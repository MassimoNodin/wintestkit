# 02 — UI Automation Layer and Engine (T1.0–T1.12)

Package areas: `wintestkit/errors.py`, `wintestkit/uia/`, `wintestkit/app.py`,
`wintestkit/engine/`.

Layering rule (enforced in review): `uia/` imports nothing from `engine/`, `app.py` or `model.py`.
`engine/` may import `uia/` and `app.py`. `model.py` (T2.3) imports `engine/`. Nothing below
`model.py` imports pytest.

## Threading model (applies to every task here)

- WinTestKit uses the **COM multithreaded apartment (MTA)** everywhere. `wintestkit/uia/com.py`
  sets `sys.coinit_flags = 0` **before importing comtypes** (comtypes reads it on import), and
  exposes `ensure_com_initialized()` which calls `CoInitializeEx(None, COINIT_MULTITHREADED)` once
  per thread (tracked with `threading.local`). Every public `uia` entry point calls it.
- UIA objects created in the MTA can be used from any MTA thread, so no dedicated engine thread is
  needed. Threads that run Win32 message loops (overlay, spy hooks) never call UIA directly; they
  post work to queues consumed by MTA threads.
- If comtypes was already imported by user code with STA, `ensure_com_initialized` logs a warning
  and continues (UIA still works from the STA thread).

---

## T1.0 — Errors <a id="t10"></a>

- **Depends on:** T0.1 · **Size:** S · **File:** `src/wintestkit/errors.py`, `tests/unit/test_errors.py`
- **Spec:**
  ```python
  class WtkError(Exception):
      """Base class. Every subclass is JSON-serialisable via to_dict() -> ErrorInfo shape."""
      def __init__(self, message: str) -> None: ...
      def to_dict(self) -> dict[str, Any]: ...  # {"type": type(self).__name__, "message": str(self)} (+ "diagnostic")

  class ConfigError(WtkError): ...             # bad [tool.wintestkit] / CLI flag; has .key: str | None
  class EnvironmentNotReadyError(WtkError): ... # locked desktop, non-interactive session, UIA unavailable
  class AppError(WtkError): ...                # launch/attach/close failures
  class AppNotRunningError(AppError): ...
  class LocatorError(WtkError):                # has .diagnostic: Diagnostic (engine/diagnose.py type)
      diagnostic: "Diagnostic"
  class ElementNotFoundError(LocatorError): ...
  class AmbiguousElementError(LocatorError): ...
  class WindowNotFoundError(LocatorError): ...
  class WaitTimeoutError(WtkError): ...        # has .last_error: BaseException | None, .waited: float
  class ActionError(WtkError): ...             # action not possible (e.g. select on a Button)
  class UIAError(WtkError): ...                # wraps COMError from UIA; has .hresult: int | None
  ```
  `LocatorError.__init__(self, diagnostic)` uses `diagnostic.message` as the message and `to_dict()`
  includes `"diagnostic": diagnostic.to_dict()`. To avoid an import cycle, `errors.py` types the
  attribute with a `TYPE_CHECKING` import of `wintestkit.engine.diagnose.Diagnostic` and duck-types
  `to_dict`.
- **Done when:** unit tests cover `to_dict()` for each class, and `str(err)` is the message.

---

## T1.1 — COM bootstrap + UIA constants <a id="t11"></a>

- **Depends on:** T1.0 · **Size:** M
- **Files:** `uia/__init__.py`, `uia/com.py`, `uia/constants.py`, `tests/unit/test_constants.py`,
  `tests/integration/test_com.py`
- **Spec — `uia/com.py`:**
  - `ensure_com_initialized() -> None` (see threading model).
  - `get_uia() -> IUIAutomation` — lazily `comtypes.client.GetModule("UIAutomationCore.dll")`,
    then `CreateObject(CUIAutomation8, interface=IUIAutomation)`, falling back to `CUIAutomation`
    if `CUIAutomation8` fails. Cached in a module global protected by a `threading.Lock`
    (UIA client object is free-threaded in MTA). Raise `EnvironmentNotReadyError` with a clear
    message on failure.
  - `uia_module()` returns the generated `comtypes.gen.UIAutomationClient` module (for constants and
    interface types).
  - `wrap_com_errors` decorator/context manager converting `comtypes.COMError` to `UIAError`
    (keep hresult). Special case `UIA_E_ELEMENTNOTAVAILABLE` (`0x80040201`) → raise
    `UIAError` with `.element_gone = True` (callers treat it as "element disappeared").
  - `create_condition(**props) -> IUIAutomationCondition`: builds `PropertyCondition`s for
    exact-string/int props and combines with `CreateAndConditionFromArray`; no props →
    `CreateTrueCondition()`. Accepts keys `control_type` (int id), `automation_id`, `name`,
    `class_name`, `process_id`, `framework_id`.
- **Spec — `uia/constants.py`:** plain Python (no comtypes import), so it's usable in unit tests:
  - `CONTROL_TYPES: dict[str, int]` — all UIA control types by programmatic name without the
    `ControlType` suffix: `Button=50000, Calendar=50001, CheckBox=50002, ComboBox=50003,
    Edit=50004, Hyperlink=50005, Image=50006, ListItem=50007, List=50008, Menu=50009,
    MenuBar=50010, MenuItem=50011, ProgressBar=50012, RadioButton=50013, ScrollBar=50014,
    Slider=50015, Spinner=50016, StatusBar=50017, Tab=50018, TabItem=50019, Text=50020,
    ToolBar=50021, ToolTip=50022, Tree=50023, TreeItem=50024, Custom=50025, Group=50026,
    Thumb=50027, DataGrid=50028, DataItem=50029, Document=50030, SplitButton=50031,
    Window=50032, Pane=50033, Header=50034, HeaderItem=50035, Table=50036, TitleBar=50037,
    Separator=50038, SemanticZoom=50039, AppBar=50040`.
  - `CONTROL_TYPE_NAMES: dict[int, str]` (inverse).
  - `normalize_control_type(value: str) -> str` — case-insensitive lookup, also accepts a trailing
    `ControlType` suffix (`"buttoncontroltype"` → `"Button"`); raises `ValueError` listing valid
    names (sorted) if unknown.
  - `PROPERTY_IDS: dict[str, int]` for at least: `RuntimeId=30000, BoundingRectangle=30001,
    ProcessId=30002, ControlType=30003, Name=30005, HasKeyboardFocus=30008, IsEnabled=30010,
    AutomationId=30011, ClassName=30012, NativeWindowHandle=30020, IsOffscreen=30022,
    FrameworkId=30024`, plus every other property id from UIAutomationClient.h (used by
    `inspect.properties`).
  - `PATTERN_IDS: dict[str, int]`: `Invoke=10000, Selection=10001, Value=10002, RangeValue=10003,
    Scroll=10004, ExpandCollapse=10005, Grid=10006, GridItem=10007, MultipleView=10008,
    Window=10009, SelectionItem=10010, Dock=10011, Table=10012, TableItem=10013, Text=10014,
    Toggle=10015, Transform=10016, ScrollItem=10017, LegacyIAccessible=10018, ItemContainer=10019,
    VirtualizedItem=10020`.
  - `TreeScope` IntFlag: `Element=1, Children=2, Descendants=4, Subtree=7`.
  - `ToggleState` IntEnum `Off=0, On=1, Indeterminate=2`; `ExpandCollapseState` IntEnum
    `Collapsed=0, Expanded=1, PartiallyExpanded=2, LeafNode=3`.
- **Done when:** unit tests for `normalize_control_type` and the maps; integration test creates
  `get_uia()`, gets the root element, and reads its Name from two threads.

---

## T1.2 — `UIAElement` wrapper + `ElementInfo` <a id="t12"></a>

- **Depends on:** T1.1 · **Size:** M
- **Files:** `uia/element.py`, `tests/unit/test_element_info.py`,
  `tests/integration/test_element.py`
- **Spec:**
  ```python
  @dataclass(frozen=True, slots=True)
  class Rect:
      left: int; top: int; width: int; height: int
      @property
      def right(self) -> int: ...
      @property
      def bottom(self) -> int: ...
      @property
      def center(self) -> tuple[int, int]: ...
      def is_empty(self) -> bool: ...                 # width <= 0 or height <= 0
      def inflate(self, d: int) -> "Rect": ...
      def to_dict(self) -> dict[str, int]: ...

  @dataclass(frozen=True, slots=True)
  class ElementInfo:                                  # mirrors protocol ElementInfo
      automation_id: str; name: str; control_type: str; class_name: str; framework_id: str
      process_id: int; rect: Rect | None; is_enabled: bool; is_offscreen: bool
      has_keyboard_focus: bool; runtime_id: str; patterns: tuple[str, ...] | None = None
      def to_dict(self) -> dict[str, Any]: ...
      @classmethod
      def from_dict(cls, d: Mapping[str, Any]) -> "ElementInfo": ...
      def short(self) -> str: ...   # 'Button "Sign in"' / 'Edit [TextBox]' / 'Text #StatusText "Ready"'

  class UIAElement:
      """Thin wrapper around IUIAutomationElement. Property reads are live (not cached) unless
      the element was obtained through a CacheRequest (see find_all(cached=True))."""
      def __init__(self, raw: Any, cached: bool = False) -> None: ...
      raw: Any
      # live properties
      automation_id: str; name: str; control_type: str; control_type_id: int; class_name: str
      framework_id: str; process_id: int; native_window_handle: int; rect: Rect | None
      is_enabled: bool; is_offscreen: bool; has_keyboard_focus: bool; runtime_id: str
      def get_property(self, name: str) -> Any: ...   # by PROPERTY_IDS name, returns python value
      def supported_patterns(self) -> list[str]: ...  # checks each PATTERN_IDS via GetCurrentPattern != NULL
      def info(self, with_patterns: bool = False) -> ElementInfo: ...
      def parent(self) -> "UIAElement | None": ...    # ControlViewWalker; None at root
      def children(self) -> list["UIAElement"]: ...   # FindAll(TreeScope.Children, ControlView condition)
      def find_all(self, scope: TreeScope, condition: Any | None = None,
                   cached: bool = False) -> list["UIAElement"]: ...
      def find_first(self, scope: TreeScope, condition: Any | None = None) -> "UIAElement | None": ...
      def set_focus(self) -> None: ...
      def same_as(self, other: "UIAElement") -> bool: ...  # IUIAutomation.CompareElements
      def is_alive(self) -> bool: ...                 # reading ProcessId doesn't raise element-gone
      def __repr__(self) -> str: ...                  # "<UIAElement Button 'Sign in'>"

  def root() -> UIAElement: ...                       # desktop root
  def from_point(x: int, y: int) -> UIAElement | None: ...
  def from_handle(hwnd: int) -> UIAElement: ...
  def focused() -> UIAElement | None: ...
  ```
  - All searches use the **control view** (`IUIAutomation.ControlViewCondition` combined with the
    given condition via `CreateAndCondition`), never raw view.
  - `find_all(cached=True)` builds a `CacheRequest` with `AutomationElementMode_Full`, scope
    `Element`, and the properties needed by `info()`; cached elements read via `GetCached*`. Used
    by resolve/diagnose to avoid N×properties cross-process calls.
  - `runtime_id`: `GetRuntimeId()` SAFEARRAY → ints joined by `"."`.
  - `rect`: `CurrentBoundingRectangle` → `Rect`, `None` if empty.
  - All COM calls wrapped with `wrap_com_errors`.
- **Done when:** integration test against the demo app: find main window under root by Name
  `WTK Demo`, list its children, `info()` of the `StatusText` element equals expected values
  (`control_type == "Text"`, `automation_id == "StatusText"`, `name == "Ready"`), cached and live
  reads agree, `from_point(center of Sign in)` returns the Sign in button (or its child text —
  record which in the PR).
- **Findings (implemented):** `from_point(center of Sign in)` returns the button's child
  `Text "Sign in"`, not the `Button`. `FindAll`/`FindFirst` on the **desktop root** can take ~5 s on
  machines with a slow top-level UIA provider (measured: one `GetNextSiblingElement` took 4.6 s), so
  nothing in the engine may enumerate the desktop root's children to find an app's windows — use
  `win32.top_level_windows(pids)` (EnumWindows) plus `from_handle(hwnd)` instead (see T1.6).

---

## T1.3 — Pattern wrappers <a id="t13"></a>

- **Depends on:** T1.2 · **Size:** M
- **Files:** `uia/patterns.py`, `tests/integration/test_patterns.py`
- **Spec:** functions take a `UIAElement` and raise `ActionError(f"{element.info().short()} does
  not support the {name} pattern")` when the pattern is unavailable. Each obtains the pattern with
  `GetCurrentPatternAs(pattern_id, interface)`.
  ```python
  def has_pattern(el: UIAElement, name: str) -> bool
  def invoke(el) -> None
  def get_value(el) -> str                       # ValuePattern.CurrentValue
  def set_value(el, value: str) -> None          # ValuePattern.SetValue
  def is_read_only(el) -> bool                   # ValuePattern.CurrentIsReadOnly
  def toggle(el) -> None
  def toggle_state(el) -> ToggleState
  def select_item(el) -> None                    # SelectionItemPattern.Select
  def add_to_selection(el) -> None
  def is_selected(el) -> bool
  def selection(el) -> list[UIAElement]          # SelectionPattern.GetCurrentSelection
  def expand(el) -> None; def collapse(el) -> None
  def expand_state(el) -> ExpandCollapseState
  def scroll_into_view(el) -> None               # ScrollItemPattern.ScrollIntoView
  def scroll(el, horizontal: str = "none", vertical: str = "none") -> None  # "none"|"small_inc"|"small_dec"|"large_inc"|"large_dec"
  def scroll_percent(el) -> tuple[float, float]  # (-1 when not scrollable, per UIA)
  def set_scroll_percent(el, h: float, v: float) -> None
  def realize(el) -> None                        # VirtualizedItemPattern.Realize
  def find_item_by_property(container, start: UIAElement | None, prop: str | None,
                            value: Any) -> UIAElement | None   # ItemContainerPattern
  def grid_size(el) -> tuple[int, int]           # (RowCount, ColumnCount)
  def grid_item(el, row: int, col: int) -> UIAElement
  def column_headers(el) -> list[UIAElement]     # TablePattern.GetCurrentColumnHeaders
  def window_close(el) -> None
  def window_set_state(el, state: str) -> None   # "normal" | "maximized" | "minimized"
  def window_is_modal(el) -> bool
  def legacy_default_action(el) -> None          # LegacyIAccessible.DoDefaultAction
  ```
- **Done when:** integration tests on the demo app: invoke `Panel A` OK → status `A OK`;
  set/get value on Username box; toggle Remember me; expand ColorCombo, select `Green`, collapse →
  status `Color: Green`; `find_item_by_property(list, None, "Name", "Item 400")` + `realize` +
  `scroll_into_view` + `select_item` → status `Selected: Item 400`; `grid_size` of products grid is
  `(200, 3)`; `grid_item(grid, 150, 1)` returns a cell whose name is `Product 151` (record whether
  GetItem realizes/scrolls the row in the PR); `column_headers` names are `Id, Name, Qty`;
  `window_close` on the NoteDialog closes it.
- **Findings (implemented):** `grid_item(grid, 150, 1)` returns a `Custom`-typed cell named
  `Product 151` that is already on screen — `GetItem` realizes and scrolls the row into view.
  `find_item_by_property(list, None, None, None)` returns the first item (`ListItem "Item 1"`).
  Patterns are obtained with `GetCurrentPattern(id).QueryInterface(IUIAutomation<Name>Pattern)`
  because `GetCurrentPatternAs` takes a raw GUID pointer that comtypes does not marshal well.

---

## T1.4 — Win32 helpers, SendInput, key parser <a id="t14"></a>

- **Depends on:** T1.0 · **Size:** M
- **Files:** `uia/win32.py`, `uia/input.py`, `tests/unit/test_keys.py`,
  `tests/integration/test_input.py`
- **Spec — `uia/win32.py`** (ctypes declarations with explicit `argtypes`/`restype`, `use_last_error=True`):
  - user32: `SendInput`, `GetCursorPos`, `SetCursorPos`, `GetSystemMetrics`, `GetForegroundWindow`,
    `SetForegroundWindow`, `AllowSetForegroundWindow`, `ShowWindow`, `IsWindowVisible`,
    `GetWindow`, `GetWindowThreadProcessId`, `EnumWindows`, `GetClassNameW`,
    `GetWindowTextW`, `IsIconic`, `GetAsyncKeyState`, `MapVirtualKeyW`, `VkKeyScanW`,
    `OpenInputDesktop`, `CloseDesktop`, `GetUserObjectInformationW`, `SetProcessDpiAwarenessContext`,
    `GetDpiForWindow`, `GetDpiForSystem`, `SetWindowsHookExW`, `UnhookWindowsHookEx`,
    `CallNextHookEx`, `GetMessageW`, `PeekMessageW`, `TranslateMessage`, `DispatchMessageW`,
    `PostThreadMessageW`, `CreateWindowExW`, `DestroyWindow`, `RegisterClassExW`, `DefWindowProcW`,
    `SetLayeredWindowAttributes`, `SetWindowPos`, `InvalidateRect`, `BeginPaint`, `EndPaint`,
    `FillRect`, `GetDC`, `ReleaseDC`, `AttachThreadInput`, `BringWindowToTop`.
  - gdi32: `CreateSolidBrush`, `DeleteObject`, `CreateCompatibleDC`, `CreateCompatibleBitmap`,
    `SelectObject`, `BitBlt`, `GetDIBits`, `DeleteDC`.
  - kernel32: `GetCurrentThreadId`, `OpenProcess`, `CloseHandle`, `WaitForSingleObject`,
    `GetExitCodeProcess`, `TerminateProcess`, `CreateToolhelp32Snapshot`, `Process32FirstW`,
    `Process32NextW`, `QueryFullProcessImageNameW`, `ProcessIdToSessionId`, `GetModuleHandleW`.
  - user32 `WaitForInputIdle`; advapi32 `OpenProcessToken`, `GetTokenInformation`.
  - Structures: `POINT`, `RECT`, `MSG`, `INPUT` (union of `MOUSEINPUT`/`KEYBDINPUT`/`HARDWAREINPUT`),
    `MSLLHOOKSTRUCT`, `KBDLLHOOKSTRUCT`, `WNDCLASSEXW`, `PAINTSTRUCT`, `BITMAPINFOHEADER`,
    `PROCESSENTRY32W`. Constants used.
  - Helpers: `list_processes() -> list[tuple[int, str]]` (pid, exe name),
    `pids_by_name(exe: str) -> list[int]` (case-insensitive),
    `top_level_windows(pid_set: set[int] | None = None) -> list[int]` (EnumWindows, visible only
    by default), `window_owner(hwnd) -> int`, `process_is_elevated(pid) -> bool | None` (None if
    access denied), `current_process_is_elevated() -> bool`, `virtual_screen_rect() -> Rect`,
    `bring_to_foreground(hwnd) -> bool` (restore if iconic; `AllowSetForegroundWindow(ASFW_ANY)`;
    the Alt-key trick: send an Alt down/up via SendInput before `SetForegroundWindow` — documented
    technique to satisfy foreground lock rules; verify `GetForegroundWindow() == hwnd`).
- **Spec — `uia/input.py`:**
  ```python
  def move_mouse(x: int, y: int) -> None                 # SendInput MOUSEEVENTF_MOVE|ABSOLUTE|VIRTUALDESK, normalized 0..65535 over virtual screen
  def click(x: int, y: int, button: Literal["left","right","middle"] = "left", count: int = 1) -> None
  def mouse_down(button) -> None; def mouse_up(button) -> None
  def scroll_wheel(x: int, y: int, clicks: int) -> None  # positive = up; 120 per click
  def press(keys: str) -> None                           # see grammar
  def type_text(text: str, interval: float = 0.0) -> None  # KEYEVENTF_UNICODE per UTF-16 code unit; "\n" -> Enter, "\t" -> Tab
  def parse_keys(keys: str) -> list[KeyCombo]            # pure, unit-tested
  @dataclass(frozen=True) class KeyCombo: modifiers: tuple[int, ...]; key: int   # virtual-key codes
  ```
  - Grammar: whitespace-separated combos; each combo is `+`-joined, case-insensitive:
    modifiers `Ctrl|Control`, `Shift`, `Alt`, `Win`; keys `A`–`Z`, `0`–`9`, `F1`–`F24`, `Enter`,
    `Return`, `Tab`, `Esc|Escape`, `Space`, `Backspace`, `Delete|Del`, `Insert|Ins`, `Home`, `End`,
    `PageUp|PgUp`, `PageDown|PgDn`, `Up`, `Down`, `Left`, `Right`, `Plus`, `Minus`, `Comma`,
    `Period`, `Apps`. Examples: `"Ctrl+S"`, `"Ctrl+Shift+Tab"`, `"Alt+F4"`, `"Ctrl+A Delete"`.
    Unknown token → `ValueError` naming the token.
  - `press` sends modifier downs, key down, key up, modifier ups (reverse order) in one `SendInput`
    call per combo. Extended-key flag for arrows/Home/End/PgUp/PgDn/Insert/Delete/Apps.
  - After `click`, `press`, `type_text`: sleep `0.02` s (settle) — constant `INPUT_SETTLE_S`.
  - If `SendInput` returns fewer events than sent → `ActionError("input was blocked (UIPI?) ...")`.
- **Done when:** parser unit tests (≥ 15 cases incl. errors); integration: click into the demo
  Username box via coordinates, `type_text("héllo")`, read back `héllo` via ValuePattern;
  `press("Ctrl+A Delete")` clears it.

---

## T1.5 — DPI awareness, screenshots, PNG encoder <a id="t15"></a>

- **Depends on:** T1.4 · **Size:** M
- **Files:** `uia/dpi.py`, `uia/png.py`, `uia/screenshot.py`, `tests/unit/test_png.py`,
  `tests/integration/test_screenshot.py`
- **Spec:**
  - `dpi.ensure_per_monitor_aware() -> None`: once per process, call
    `SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4)`; ignore
    "access denied" (already set). Called from `uia/__init__.py` import, so every coordinate
    WinTestKit sees is physical pixels. `dpi.scale_for_window(hwnd) -> float` (`GetDpiForWindow/96`).
  - `png.encode_png(width, height, rgb_rows: bytes) -> bytes`: pure Python PNG writer (8-bit RGB,
    filter type 0 per row, `zlib.compress(level=6)`, chunks IHDR/IDAT/IEND with `zlib.crc32`).
  - `screenshot.capture(rect: Rect) -> bytes` (PNG) using `GetDC(0)` + `BitBlt(SRCCOPY|CAPTUREBLT)`
    into a 32-bpp top-down DIB (`biHeight = -h`) + `GetDIBits`, converting BGRA → RGB.
    `capture_screen() -> bytes` captures `virtual_screen_rect()`. `capture_element(el) -> bytes |
    None` (None if rect empty). `save(png: bytes, path: Path) -> Path` creates parent dirs.
  - Must handle negative virtual-screen origins (monitors left of primary).
- **Done when:** unit test decodes the produced PNG with `zlib`+`struct` (or compares against a
  known 2×2 fixture byte string); integration test captures the demo main window, file is a valid
  PNG with expected dimensions (±2 px).

---

## T1.6 — App launch / attach / close <a id="t16"></a>

- **Depends on:** T1.2, T1.4 · **Size:** M
- **Files:** `src/wintestkit/app.py`, `tests/integration/test_app.py`
- **Spec:**
  ```python
  class App:
      """A running application under test: a set of processes sharing an exe name."""
      process_name: str            # e.g. "DemoApp.exe"
      launched: bool               # True if WinTestKit started it
      @classmethod
      def launch(cls, path: str | Path, args: Sequence[str] = (), cwd: str | Path | None = None,
                 env: Mapping[str, str] | None = None, process: str | None = None,
                 startup_timeout: float = 30.0) -> "App": ...
      @classmethod
      def attach(cls, process: str | None = None, pid: int | None = None) -> "App": ...
      @property
      def pids(self) -> list[int]: ...            # live: launched pid + all pids named process_name (if given) that are running
      def is_running(self) -> bool: ...
      def top_level_windows(self) -> list[UIAElement]: ...  # visible top-level windows of pids via win32.top_level_windows (EnumWindows, z-order) + element.from_handle — never FindAll on the UIA root (slow, see T1.2 findings)
      def main_window(self, timeout: float = 0.0) -> UIAElement: ...
      def close(self, timeout: float = 10.0) -> None: ...
      def kill(self) -> None: ...
      def wait_for_exit(self, timeout: float) -> bool: ...
      def __enter__/__exit__   # exit: close() if launched
  ```
  - `launch`: `subprocess.Popen([str(path), *args], cwd=..., env={**os.environ, **env})`
    (`creationflags=0`, no shell). Raise `AppError` if the file doesn't exist. Then
    `WaitForInputIdle(handle, 10000)` (ignore failure for non-GUI launchers), then poll every
    100 ms until `main_window()` exists or `startup_timeout` → `AppError("... did not show a
    window within 30s")` (and kill it). `process` defaults to the exe's file name; windows are
    matched by **all pids with that exe name started at/after launch time** plus the launched pid,
    which handles launcher stubs.
  - `attach`: by pid (must exist) or by exe name (all matching pids; `AppNotRunningError` if none).
    `launched = False`.
  - `main_window`: among `top_level_windows()` that have no owner (`GetWindow(GW_OWNER) == 0`) and
    control type `Window`, return the first (z-order). Poll up to `timeout`. Raise
    `WindowNotFoundError` with a `Diagnostic(kind="window_not_found", …)` listing all top-level
    windows of the app as candidates.
  - `close`: for each top-level window (owned ones first), try `window_close`; wait for exit up to
    `timeout`; then `kill()`. Never closes an app it didn't launch unless called explicitly.
  - `kill`: `taskkill /PID <pid> /T /F` for every pid (subprocess, ignore errors), then wait ≤ 5 s.
- **Done when:** integration tests: launch demo (with `--slow-start 1500`) waits correctly;
  attach by `DemoApp.exe`; `main_window().name == "WTK Demo"`; open NoteDialog → it appears in
  `top_level_windows()` with an owner; MessageBox (`#32770`) appears in `top_level_windows()`;
  `close()` exits; launching a non-existent path raises `AppError`.

---

## T1.7 — Locator data model <a id="t17"></a>

- **Depends on:** T1.0 · **Size:** S
- **Files:** `engine/locator.py`, `tests/unit/test_locator.py`,
  `tests/contract/fixtures/describe_cases.json` (list of `{ "locator": LocatorData, "describe":
  string }` pairs; the VS Code `describeLocator()` port in T4.3 is tested against the same file)
- **Spec:**
  ```python
  Matcher = str | re.Pattern[str]

  def match_value(matcher: Matcher, value: str) -> bool:   # str: equality; Pattern: .search()
  def matcher_to_data(m: Matcher) -> str | dict[str, str]  # {"regex": p.pattern, "flags": "i"...}
  def matcher_from_data(d) -> Matcher
  def describe_matcher(m) -> str                           # '"Sign in"' or '/^Item \d+$/i'

  @dataclass(frozen=True, slots=True)
  class WindowLocator:
      title: Matcher | None = None
      process: str | None = None
      class_name: Matcher | None = None
      automation_id: Matcher | None = None
      index: int | None = None
      def describe(self) -> str            # 'Window[title="WTK Demo"]'
      def to_dict(self) / from_dict(cls, d)
      def is_empty(self) -> bool

  @dataclass(frozen=True, slots=True)
  class ItemSelector:
      kind: Literal["row", "cell"]
      row: int
      column: int | str | None = None
      def describe(self) -> str            # 'row(3)' / 'cell(3, "Name")'

  @dataclass(frozen=True, slots=True)
  class Locator:
      automation_id: Matcher | None = None
      name: Matcher | None = None
      control_type: str | None = None      # normalized via normalize_control_type in __post_init__
      class_name: Matcher | None = None
      index: int | None = None             # >= 0
      depth: int | None = None             # >= 1
      within: "Locator | None" = None
      window: WindowLocator | None = None
      item: ItemSelector | None = None
      def describe(self) -> str
      def chain(self) -> list["Locator"]   # outermost within first, self last
      def to_dict(self) / from_dict(cls, d)
      def with_index(self, i: int) -> "Locator"
      def with_item(self, item: ItemSelector) -> "Locator"
      def exact_props(self) -> dict[str, str | int]   # props usable in a UIA condition (str matchers + control_type id)
      def regex_props(self) -> dict[str, re.Pattern[str]]
      def is_empty(self) -> bool           # no property at all (only allowed with index)
  ```
  - `describe()` format (used in errors, events, reports, UI — keep stable):
    `Button[name="Sign in"]`, `Edit[class="TextBox", index=0]`, `*[id="StatusText"]` (no control
    type → `*`), regex `Text[name=/invalid/i]`, chain joined with ` > ` from outermost:
    `Group[name="Credentials"] > Edit[class="PasswordBox"]`, item suffix `DataGrid > row(3)`,
    window prefix only when explicit: `Window[title="WTK Demo - Dialog"] >> Button[name="Save"]`.
    Property order: id, name, class, then index, depth.
  - Validation in `__post_init__`: negative index/depth → `ValueError`; empty locator without index
    → `ValueError("locator needs at least one property")`.
  - `to_dict()` produces protocol `LocatorData` exactly (camelCase, omitted keys for None).
- **Done when:** unit tests for describe (≥ 12 cases), round-trip to/from dict incl. regex flags,
  validation errors, `match_value`.

---

## T1.8 — Resolver <a id="t18"></a>

- **Depends on:** T1.2, T1.3, T1.6, T1.7 · **Size:** L
- **Files:** `engine/resolve.py`, `tests/unit/test_resolve.py` (with a fake element tree),
  `tests/integration/test_resolve.py`
- **Spec:**
  ```python
  @dataclass
  class Scope:
      app: App
      window: WindowLocator | None        # Screen.window; None = app.main_window()

  def resolve_window(app: App, wl: WindowLocator | None) -> UIAElement
  def query_all(root: UIAElement, locator: Locator) -> list[UIAElement]   # ignores locator.index/within/window/item
  def resolve(scope: Scope, locator: Locator) -> UIAElement               # strict
  def resolve_all(scope: Scope, locator: Locator) -> list[UIAElement]     # non-strict, for Elements
  ```
  **`resolve_window`:**
  1. `wl is None or wl.is_empty()` → `app.main_window()`.
  2. Candidates = `app.top_level_windows()` (if `wl.process` is set, use windows of that process
     instead — `App.attach(process=wl.process)` semantics without requiring it to be the app).
  3. Filter by `title` (Name), `class_name`, `automation_id` with `match_value`.
  4. `index` given → pick `candidates[index]`; else exactly 1 required. 0 → `WindowNotFoundError`;
     >1 → `AmbiguousElementError` with `kind="ambiguous"`. Diagnostics built by T1.9 (until T1.9
     lands, raise with a minimal `Diagnostic` containing only `message`/`locator`).

  **`query_all(root, locator)`:**
  1. Build a UIA condition from `locator.exact_props()` (`create_condition`).
  2. `root.find_all(TreeScope.Descendants if depth is None or depth > 1 else TreeScope.Children,
     condition, cached=True)`. If `depth > 1`, filter results by computing depth via parent walk
     (cached request includes parent? no — compute with `TreeWalker` on the few results; acceptable).
  3. Filter by `regex_props()` in Python.
  4. Return in document order (UIA FindAll order).

  **`resolve(scope, locator)`:**
  1. `window_root = resolve_window(scope.app, locator.window or scope.window)`.
  2. Walk `locator.chain()`: for each link, `root = _resolve_one(root, link)` where the root for the
     first link is `window_root`. A failure in a non-final link raises `ElementNotFoundError`/
     `AmbiguousElementError` with `kind="within_failed"` wrapping the inner diagnostic.
  3. `_resolve_one(root, link)`: `matches = query_all(root, link)`.
     - `link.index is not None` → `matches[index]` or `index_out_of_range`.
     - else `len == 1` → it; `0` → **popup fallback** (below), then `not_found`; `>1` → `ambiguous`.
  4. **Popup fallback** (only for the first link and only when `locator.window` is None): search
     the app's *other* top-level windows whose `class_name == "Popup"` or control type is `Menu`
     (WPF ContextMenu / ComboBox drop-down / tooltip hosts). If exactly one match across them, use
     it.
  5. If `locator.item` is set: apply to the resolved element:
     - `row`: `grid_item(el, row, 0).parent()` (DataItem row). If `GridPattern` is unsupported →
       `ActionError`.
     - `cell`: column int → `grid_item(el, row, col)`; column str → index of the header whose name
       equals it (`column_headers`) else `ElementNotFoundError` listing header names.
     - Out-of-range row/col → `index_out_of_range` diagnostic.
  6. Never caches results across calls: every action re-resolves (no stale elements).

  `resolve_all` = same as resolve but returns all matches of the final link (index ignored), `[]`
  rather than error when none (window/within errors still raise).
- **Done when:**
  - Unit tests with a fake tree (implement a small `FakeElement` satisfying the `UIAElement`
    interface used by resolve; inject via a module-level `_find_all` hook or protocol) cover:
    unique match, ambiguous, not found, index, regex filter, within chain, within failure, popup
    fallback, depth.
  - Integration against demo: `Button[name="Sign in"]` unique; `Button[name="OK"]` ambiguous with
    2 matches; `Group[name="Panel B"] > Button[name="OK"]` unique; `Edit[class="PasswordBox"]`
    unique; `*[id="StatusText"]` unique; `ListItem[name="Item 1"]` found; DataGrid `row(0)`/
    `cell(5,"Name")` → name `Product 6`; NoteDialog element via
    `window=WindowLocator(title="WTK Demo - Dialog")`; MessageBox OK via
    `window=WindowLocator(class_name="#32770")`; ColorCombo item `Blue` after expand (verify
    whether found via ComboBox children or popup fallback; record in PR).
  - Performance: resolving `Button[name="Sign in"]` takes < 150 ms on the demo (log timings in test
    output; not a hard assertion in CI).

---

## T1.9 — Resolution diagnostics <a id="t19"></a>

- **Depends on:** T1.8 · **Size:** M
- **Files:** `engine/diagnose.py`, `tests/unit/test_diagnose.py`, `tests/integration/test_diagnose.py`
- **Spec:**
  ```python
  @dataclass(frozen=True)
  class Mismatch: property: str; expected: str; actual: str
  @dataclass(frozen=True)
  class Candidate: info: ElementInfo; score: int; mismatches: tuple[Mismatch, ...]
  @dataclass(frozen=True)
  class Diagnostic:
      kind: Literal["not_found","ambiguous","window_not_found","within_failed","index_out_of_range","app_not_running"]
      message: str; locator: str; searched_in: str; match_count: int
      candidates: tuple[Candidate, ...]; within: "Diagnostic | None" = None
      def to_dict(self) -> dict[str, Any]
      @classmethod
      def from_dict(cls, d) -> "Diagnostic"
      def format(self) -> str        # multi-line human text (CLI, pytest failure, VS Code output)

  def diagnose_not_found(root: UIAElement, link: Locator, searched_in: str, full_locator: Locator) -> Diagnostic
  def diagnose_ambiguous(matches: list[UIAElement], link, searched_in, full_locator) -> Diagnostic
  def diagnose_window(app: App, wl: WindowLocator, matches: list[UIAElement]) -> Diagnostic
  ```
  - **not_found algorithm:** relaxed query under the same root: if the link has a `control_type`,
    all descendants of that control type; otherwise all descendants (cap 1000, cached). Score each
    candidate = number of locator properties it satisfies (id, name, class, control type). Keep
    candidates with score ≥ 1, sort by score desc then document order, take 5. Mismatches list
    each unsatisfied property with expected (`describe_matcher`) and actual value.
  - **message formats** (exact, tests assert them):
    - not_found: `No element matches Button[name="Sign In"] in Window "WTK Demo" (closest: Button "Sign in" — name differs)`
      — the parenthetical only when a candidate exists; lists up to 2 mismatching property names.
    - ambiguous: `2 elements match Button[name="OK"] in Window "WTK Demo"; add within= or index= to pick one`
    - window_not_found: `No window matches Window[title="Foo"] for DemoApp.exe (open windows: "WTK Demo")`
    - within_failed: `Could not resolve Group[name="Panel C"] (needed by Group[name="Panel C"] > Button[name="OK"]): <inner message>`
    - index_out_of_range: `index=5 is out of range: 2 elements match Button[name="OK"] in Window "WTK Demo"`
  - `format()`: message, then `Locator: ...`, `Searched in: ...`, then a candidates table:
    `  1. Button "Sign in" [class=Button] at (412,233 80x24) — name: expected "Sign In", got "Sign in"`.
  - `searched_in` text: `Window "WTK Demo"` or `Group "Credentials" in Window "WTK Demo"`.
  - Wire into `resolve.py` (replace minimal diagnostics) and `App.main_window`.
- **Done when:** unit tests on fake trees assert messages exactly; integration test on demo for a
  misspelled `Sign In` finds `Sign in` as top candidate.

---

## T1.10 — Waits <a id="t110"></a>

- **Depends on:** T1.8 · **Size:** S
- **Files:** `engine/waits.py`, `tests/unit/test_waits.py`
- **Spec:**
  ```python
  POLL_INTERVAL = 0.1
  def wait_until(fn: Callable[[], T | None | Literal[False]], timeout: float, *,
                 description: str, interval: float = POLL_INTERVAL,
                 retry_on: tuple[type[BaseException], ...] = (LocatorError, UIAError)) -> T
  ```
  - Calls `fn` immediately, then every `interval` until it returns a truthy value (returned) or the
    timeout elapses. Exceptions in `retry_on` are swallowed and remembered as `last_error`; other
    exceptions propagate. On timeout: if `last_error` is a `LocatorError`, **re-raise that error**
    (so users see the element diagnostic, with ` (waited 10.0s)` appended to the message); else
    raise `WaitTimeoutError(f"Timed out after {timeout:.1f}s waiting for {description}")` with
    `last_error`.
  - `timeout == 0` → exactly one attempt.
  - Uses `time.monotonic()`; injectable clock/sleep for unit tests (module-level `_clock`, `_sleep`).
  ```python
  State = Literal["attached","detached","visible","hidden","enabled","disabled","stable"]
  def element_state_ok(el: UIAElement | None, state: State) -> bool
      # attached: el is not None and alive; detached: el is None or gone
      # visible: attached and not is_offscreen and rect not empty; hidden: not visible
      # enabled / disabled: is_enabled
      # stable: rect equal across two reads 50 ms apart
  def wait_for_state(get: Callable[[], UIAElement | None], state: State, timeout: float,
                     description: str) -> UIAElement | None
  ```
- **Done when:** unit tests with fake clock: immediate success, success after N polls, timeout with
  LocatorError re-raised (message suffix), timeout with WaitTimeoutError, non-retry exception
  propagates, timeout 0.

---

## T1.11 — Actions <a id="t111"></a>

- **Depends on:** T1.3, T1.4, T1.10 · **Size:** L
- **Files:** `engine/actions.py`, `tests/integration/test_actions.py`
- **Spec:** all functions take an already-resolved `UIAElement` (the model layer re-resolves and
  waits before calling them). Each returns `None` unless stated.
  ```python
  InputMode = Literal["pattern", "mouse"]

  def ensure_visible(el) -> None
      # if is_offscreen: realize() if VirtualizedItem supported; scroll_into_view() if ScrollItem supported;
      # if still offscreen -> ActionError("element is off-screen and cannot be scrolled into view")
  def click(el, *, mode: InputMode = "pattern", button="left") -> str   # returns strategy used (logged in step args)
  def double_click(el) -> None        # always mouse
  def right_click(el) -> None         # always mouse
  def hover(el) -> None               # mouse move to centre
  def type_text(el, text: str, *, clear: bool = True, keys: bool = False) -> str   # returns strategy
  def clear(el) -> None
  def press(el, keys: str) -> None    # focus el then input.press
  def select(el, item: str | int | re.Pattern[str]) -> None
  def set_checked(el, checked: bool) -> None
  def expand(el) -> None; def collapse(el) -> None
  def focus(el) -> None
  def get_text(el) -> str
  def get_value(el) -> str
  def is_checked(el) -> bool
  def selected_items(el) -> list[str]
  ```
  **click strategy (mode="pattern"):** in order, first supported wins:
  1. `Invoke` → `invoke` (strategy `"invoke"`)
  2. `Toggle` → `toggle` (`"toggle"`)
  3. `SelectionItem` → `select_item` (`"select"`)
  4. `ExpandCollapse` → expand if collapsed else collapse (`"expand_collapse"`)
  5. otherwise mouse (`"mouse"`).
  `button != "left"` or `mode="mouse"` → mouse. **Mouse click:** `ensure_visible`; bring the
  element's top-level window to foreground (`win32.bring_to_foreground(native handle of top-level
  ancestor)`); wait `stable`; `input.click(*rect.center)`.

  **type_text strategy:** if not `keys` and `Value` supported and not read-only: `set_value(text if
  clear else get_value + text)` (for `PasswordBox` get_value isn't readable → if `clear=False`,
  fall back to keys). Strategy `"value"`. If `set_value` raises `UIAError` → fall back to keys.
  Keys strategy (`"keys"`): `focus`, if `clear`: `press("Ctrl+A Delete")`, then
  `input.type_text(text)`.

  **select(item):**
  - ComboBox (`control_type == "ComboBox"`): `expand`; find a child `ListItem` (str → name equals;
    Pattern → search; int → index among ListItems) via `query_all` on the combo, then if 0 found
    try popup windows (same rule as resolver fallback); `select_item`; `collapse` if still expanded.
  - List / DataGrid / Tree / Tab (`Selection` pattern on el): str/Pattern → first try direct
    descendants of type ListItem/DataItem/TreeItem/TabItem; if not found and `ItemContainer`
    supported → `find_item_by_property(el, None, "Name", item)` (str only) → `realize` →
    `select_item`. int → for DataGrid `grid_item(el, i, 0).parent()`, for List iterate
    `find_item_by_property(el, prev, None, None)` i+1 times. Then `scroll_into_view` + `select_item`.
  - Otherwise `ActionError(f"select() is not supported on {short}")`.
  - Not found → `ElementNotFoundError` with a diagnostic listing up to 5 available item names.

  **set_checked:** Toggle until `toggle_state` matches (max 3 toggles; Indeterminate skipped).
  **get_text:** if `Value` supported and class isn't `PasswordBox` → value; elif `Text` pattern →
  `DocumentRange.GetText(-1)`; else `name`.
  **focus:** `set_focus`; for elements whose window isn't foreground, bring window to foreground
  first.
- **Done when:** integration tests (each starts from `File > Reset`): login success and failure
  through `type_text` + `click` (both modes); Panel A/B OK via within; Remember me via
  `set_checked(True/False)`; ColorCombo `select("Blue")` and `select(0)`; ListBox
  `select("Item 450")` (virtualized); DataGrid `select(120)` → status `Row: Product 121`; menu
  `File > Reset` via click on `File` then `Reset`; `press("Alt+F4")` on NoteDialog closes it;
  `double_click`/`right_click` don't raise; `get_text(status)` returns status text.

---

## T1.12 — Highlight overlay <a id="t112"></a>

- **Depends on:** T1.4 · **Size:** M
- **Files:** `engine/overlay.py`, `tests/integration/test_overlay.py`
- **Spec:**
  ```python
  class Overlay:
      """A click-through, topmost rectangle outline running on its own thread with a message loop."""
      # color is a COLORREF (0x00BBGGRR), so 0x000000FF is red
      def __init__(self, color: int = 0x000000FF, thickness: int = 3) -> None
      def show(self, rect: Rect) -> None        # thread-safe; repositions if visible
      def hide(self) -> None
      def close(self) -> None                   # destroys window, joins thread
      def __enter__/__exit__

  def flash(rect: Rect, duration_ms: int = 1500, *, color: int = 0x000000FF, thickness: int = 3,
            blink: bool = True, block: bool = False) -> None
      # shows outline for duration (blinking 3x if blink); block=False returns immediately (daemon thread)
  ```
  - Window: `CreateWindowExW(WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_TOOLWINDOW
    | WS_EX_NOACTIVATE, cls, None, WS_POPUP, ...)`. `SetLayeredWindowAttributes(hwnd, MAGENTA
    (0x00FF00FF), 0, LWA_COLORKEY)`. `WM_PAINT`: fill client with magenta brush, then four
    filled rects of the outline colour of width `thickness`. Window rect = target rect inflated
    by `thickness`. Show with `SetWindowPos(HWND_TOPMOST, ..., SWP_NOACTIVATE | SWP_SHOWWINDOW)`.
  - The thread owns the window and runs `GetMessageW`; cross-thread requests go through
    `PostThreadMessageW` with custom `WM_APP+n` messages carrying a request id; rect data passed via a
    thread-safe dict.
  - The overlay must never take focus or intercept clicks (verified in test by clicking through it).
  - Overlay windows are owned by the Python process; resolvers and spy ignore elements whose
    `process_id == os.getpid()`.
- **Done when:** integration test: `flash(rect of Sign in, 800, block=True)` returns after ~0.8 s;
  while an `Overlay` is shown over the Sign in button, `input.click` on its centre still triggers
  the button (status changes) and the demo window keeps foreground; `close()` leaves no thread
  running.
