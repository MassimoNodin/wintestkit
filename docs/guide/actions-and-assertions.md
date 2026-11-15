# Actions and assertions

## Actions

Every action is a method of a bound element and accepts `timeout=` (seconds) to override how long
it waits for the element.

Which actions exist depends on how the element is declared. A plain `Element` has the common and
generic actions; a
[typed element](pages-and-elements.md#typed-elements) has only the ones that apply to its control
(the *On* column), and a [custom control](pages-and-elements.md#custom-controls) adds its own.

| Action | What it does | On |
|---|---|---|
| `click(mode=None, x=None, y=None, button="left", modifiers=None)` | Click; pattern mode tries an automation pattern and falls back to mouse input | `Button`, `CheckBox`, `RadioButton`, `ListItem`, `ToggleButton`, `Hyperlink` |
| `double_click(x=None, y=None, modifiers=None)` / `right_click(x=None, y=None, modifiers=None)` | Mouse input | `Button`, `CheckBox`, `RadioButton`, `ListItem`, `ToggleButton`, `Hyperlink` |
| `middle_click(x=None, y=None, modifiers=None)` | Middle mouse click | every element |
| `drag_to(target, source_offset=None, target_offset=None, button="left", modifiers=None)` / `drag_by(dx, dy, source_offset=None, button="left", modifiers=None)` | Drag to an element or window / by pixels | every element |
| `scroll(clicks, x=None, y=None, horizontal=False)` | Turn the mouse wheel | every element |
| `open_context_menu(mode=None)` | Open and return a context menu | every element |
| `hover()` | Move the mouse over the element | every element |
| `type(text, clear=True, keys=False)` | Enter text: set through the Value pattern when possible, otherwise typed on the keyboard. `clear=False` appends; `keys=True` always types key by key | `TextBox` |
| `clear()` | Remove all text | `TextBox` |
| `press(keys)` | Focus the element and press keys: `"Enter"`, `"Ctrl+S"`, `"Ctrl+A Delete"` (combos separated by spaces) | `TextBox` |
| `select(item)` | Select by name, 0-based index or compiled regex; combo boxes open and close; trees also accept paths | `ComboBox`, `ListBox`, `DataGrid`, `TreeView`, `TabControl` |
| `select(items, add=False)` / `deselect(item)` / `clear_selection()` | Select several or remove selections | `ListBox`, `DataGrid` |
| `select()` | Select the radio button or list item itself | `RadioButton`, `ListItem` |
| `check()` / `uncheck()` / `toggle()` | Set a check box or toggle button to a state (no-op if already there) / flip it | `CheckBox`, `ToggleButton` |
| `expand()` / `collapse()` | Expand or collapse; trees require a path | `ComboBox`, `TreeView`, `Expander` |
| `click_path(path, separator="\|")` | Open menu levels and click the last item | `Menu`, `ContextMenu` |
| `set_value(value, mode=None)` / `increase(steps=1)` / `decrease(steps=1)` | Set a range or step a slider | `Slider` (all), `ScrollBar` (`set_value` only) |
| `set_date(value, mode=None)` | Set a `datetime.date` | `DatePicker` |
| `click_button(name, mode=None)` | Click a toolbar button by name or automation ID, or regex | `ToolBar` |
| `focus()` | Give the element keyboard focus | every element |
| `scroll_into_view()` | Scroll a list or grid item into view | every element |
| `highlight(duration_ms=1500)` | Bring the owning window forward, then draw a frame around the element. The outline is still drawn if Windows denies foreground | every element |

"every element" means the typed elements and the plain `Element`. A plain `Element` additionally
has generic actions such as `type`, `check`, `expand` and `select`; specialized menu, tree and
widget methods belong to their typed elements.

### Mouse details

Offsets `x` and `y` must be supplied together, in physical pixels from the top-left; otherwise
the center is used. Invalid or out-of-bounds offsets fail. `modifiers` accepts combinations such
as `"Ctrl+Shift"`. `click` accepts `left`, `right` or `middle`; a position, modifier or non-left
button forces mouse input even in pattern mode. Double, right and middle clicks always use mouse input.
Drag offsets are `(x, y)` pairs; drags move in steps across the system drag threshold and release
the button and modifiers even on failure. Wheel clicks are positive for up, or right when horizontal.
Mouse input may target the app's owned popups as well as its window, but rejects unrelated windows.

### Windows

Windows have `close()`, `maximize()`, `minimize()`, `restore()`, `activate()`, `move(x, y)` and
`resize(width, height)`. `rect` reads the screen rectangle and `is_active()` checks foreground.
Move and resize use Transform when available or the native window handle; sizes must be positive.
`window.press(keys, secret=False)` and `window.type(text, secret=False)` activate the window and
send input to its focused control. `wintestkit.finders.send_keys` also accepts a window target and
activates it. Foreground activation can fail; input is refused if the target loses foreground.

### Keyboard outside an element

`from wintestkit import keyboard` exposes `keyboard.press(keys, secret=False)`,
`keyboard.type(text, secret=False)` and `with keyboard.hold("Ctrl+Shift"):`. The context manager
releases modifiers even on error. These calls do not activate a window: they require the foreground
window to belong to the current app. The `app` fixture or a page bound to an `App` registers it;
without one, or when another app is foreground, they raise an error. Use `secret=True` for sensitive input.

### Menus and trees

`menu.click_path("File|Recent|Report.txt")` opens each level and clicks the final item. For a
context menu use `item.open_context_menu().click_path("Edit|Copy")`; opening uses right-click in
mouse mode or Shift+F10 in pattern mode. Tree `select`, `expand`, `collapse` and `items` accept
paths such as `"Root|Child"`; `items()` lists top-level names, while `items(path)` lists children
of that node, which must be expanded first. Ancestors are expanded as needed. Set `separator=`
to change `|`, or pass a list of exact names and compiled regex segments. Empty paths or segments
fail. Missing segments report available siblings; failed menu navigation sends Escape to close opened
levels. Mouse tree selection clicks the header row and verifies that the intended item was selected.

### Selecting several items

On a `ListBox`, `DataGrid` or plain `Element`, `select(["A", "B"], add=False)` replaces the
selection; `add=True` retains it. Items can be names, indices or compiled regexes. `deselect(item)`
and `clear_selection()` remove selections. The control must support multiple selection for multiple
items. Empty lists for `select` or `deselect` raise an error; use `clear_selection()` instead.
Mouse mode uses a plain click for the first replacement and Ctrl+click for additional changes;
pattern mode uses selection patterns. The resulting selection is verified and an error is raised
if it does not match.

### Typed control details

Slider and scrollbar values must be in range and writable; setting verifies the result within half
a small change. Slider mouse mode clicks its thumb and moves by keys; pattern mode uses RangeValue.
`increase` and `decrease` send arrow keys and require at least one step. Scrollbar `set_value`
requires pattern mode. A date picker writes the system short date format, commits and verifies it;
formats using month or day names are unsupported. Expander actions verify the state, using its header
button for UIA mouse mode and the relevant action/pattern on WPF. Hyperlink actions require the UIA
backend when the WPF inspector cannot act on the content element.

Built-in typing, key presses and assertions redact recorded arguments and failure
details for resolved controls reporting UI Automation `IsPassword`, as well as
`PasswordBox` locators. For sensitive controls that do not identify themselves, use
`main.token.type(value, secret=True)`, `main.token.press(keys, secret=True)` or
`expect(main.token, secret=True).to_have_value(value)`. Custom steps accept
`self.step(name, args, secret=True)`. This does not redact your source code,
application output, screenshots or replay pixels: do not hard-code credentials,
and review artifacts before sharing them.

```python
# pseudo-code
def test_typing_and_keys(main: MainPage) -> None:
    main.username.type("adm")
    main.username.type("in", clear=False)  # append instead of replacing
    expect(main.username).to_have_value("admin")
    main.username.press("Ctrl+A Delete")  # key combos separated by spaces
    expect(main.username).to_have_value("")
```

### Pattern or mouse input

`mouse` input is the default on both backends and reproduces real user input. `pattern`
uses automation-peer actions on WPF and UI Automation patterns on UIA; it does not move the
mouse. Opt out with `input_mode: pattern` in YAML or use `mode="pattern"` per call:

Global mouse and keyboard fallbacks refuse input when the owning target window
cannot be activated or no longer owns the foreground. Mouse targets must still
belong to that window; keyboard targets must own keyboard focus. Do not work in
other windows while a UI test runs. These checks reduce misdirected input but do
not make global input atomic against focus changes by Windows or another process.

```python
# pseudo-code
def test_mouse_mode_and_nth(main: MainPage) -> None:
    main.sign_in.click(mode="pattern")  # opt into the Invoke pattern
    expect(main.status).to_have_text("Invalid credentials")
    main.all_ok_buttons.nth(1).click()  # 0-based
    expect(main.status).to_have_text("B OK")
```

### Migrated key strings

Use `wintestkit.finders.send_keys(target, "^a[Del]Hello~1[Enter]")` for mixed text and keys. Prefixes `^`, `!`, and `~` select Ctrl, Alt, and Shift; doubled prefixes or `[[` are literal. `[Hold]` and `[Release]` hold and release prefixed modifiers. `to_keys(text)` converts key-only strings to `press()` syntax, or returns `None` for mixed text. Use `secret=True` for sensitive input.


## Auto-waiting

WinTestKit waits for the application so tests don't need sleeps.
On WPF, supported waits use agent-side events to recheck conditions; other cases can poll.

| Call | Waits until | Then |
|---|---|---|
| Actions (`click`, `type`, `select`, ...) | the element exists by default (`actionability: exists`) | checks enabled and visible, then acts; if it disappears during the action it is found again and the action retried once |
| `scroll_into_view()` | the element exists | scrolls |
| Reads (`text`, `value`, `is_enabled()`, `is_checked()`, `selected_items()`, `row_count()`, …) | the element exists | returns the current value |
| `exists(timeout=0)` | by default, doesn't wait | `True`/`False` |
| `is_visible()` | doesn't wait | `True`/`False` |
| `wait_for_property(name, expected)` | a UIA or managed property matches (including regex) | returns the element |
| `wait_for(state)` | the state is reached: `attached`, `detached`, `visible`, `hidden`, `enabled`, `disabled` or `stable` | returns the element |
| `expect(...)` | the assertion holds | passes, or fails with the last observed value |

With the default `actionability: exists`, a disabled element fails immediately with
`<element> is disabled; actions no longer wait for enabled elements: wait with expect(...).to_be_enabled() or set actionability: strict`.
An off-screen element that cannot be scrolled into view fails immediately with
`<element> is hidden (off-screen and cannot be scrolled into view); actions no longer wait for visible elements: wait with expect(...).to_be_visible() or set actionability: strict`.
Off-screen scrollable items are scrolled into view. Set `actionability: strict` to wait for the
element to be enabled and visible as well. Use `expect(x).to_be_enabled()` for an explicit wait.

An ambiguous locator never waits; it fails immediately (see
[strict matching](locators-for-wpf.md#strict-matching)).

```python
# pseudo-code
def test_continue_waits_until_it_is_enabled(main: MainPage) -> None:
    expect(main.continue_button).to_be_disabled()
    main.load.click()
    expect(main.status).to_have_text("Loading...")
    expect(main.continue_button).to_be_enabled()  # wait for loading to finish
    main.continue_button.click()
    expect(main.status).to_have_text("Continued")
```

## Reading state

Reads return the current value without asserting anything. Like actions, some exist only on
the types they apply to:

| Read | On |
|---|---|
| `text`, `get(name)`, `is_enabled()`, `exists()`, `is_visible()`, `info()` | every element |
| `value` | `TextBox`, `ComboBox`, `DatePicker`, `Slider`, `ScrollBar`, `ProgressBar` |
| `minimum`, `maximum` | `Slider`, `ScrollBar`, `ProgressBar` |
| `date` | `DatePicker` (`datetime.date` or `None` when empty) |
| `texts()` | `StatusBar` (item texts in order) |
| `is_expanded()` | `Expander` |
| `is_checked()` | `CheckBox`, `ToggleButton` |
| `is_selected()` | `RadioButton`, `ListItem` |
| `selected`, `selected_items()` | `ComboBox`, `ListBox`, `TreeView`, `TabControl` (`DataGrid`: `selected_items()` only) |
| `items()` / `items(path)` | `ComboBox` (expands and collapses it), `ListBox`, `TreeView` (also accepts a path), `TabControl` |
| `row_count()`, `column_count()`, `row(i)`, `cell(row, column)`, `find_row(column, value)` | `DataGrid` |


```python
# pseudo-code
def test_reading_state(main: MainPage) -> None:
    assert main.sign_in.exists()
    assert not main.data_loaded.exists()
    assert main.sign_in.is_enabled()
    main.username.type("admin")
    assert main.username.value == "admin"
```

Prefer `expect` over `assert` for anything the application changes asynchronously: `assert` checks
once, `expect` keeps checking until the timeout.

## `expect`

`expect(target)` takes a bound element, collection or window. `.not_` negates the next assertion.

| Assertion | Passes when |
|---|---|
| `to_exist()` | the element exists |
| `to_be_visible()` / `to_be_hidden()` | it is on screen / it is off screen or missing |
| `to_be_enabled()` / `to_be_disabled()` | it is enabled / disabled |
| `to_be_checked()` | a check box or toggle is on |
| `to_be_selected()` | a list item, tab or radio button is selected |
| `to_have_text(expected)` | its text equals `expected` (or matches a compiled regex) |
| `to_contain_text(expected)` | its text contains `expected` |
| `to_have_value(expected)` | its Value pattern value equals `expected` (or matches a regex) |
| `to_have_count(n)` | an `Elements` collection has `n` members |
| `to_have_property(name, expected)` | a UIA or managed property matches the expected value or compiled regex |
| `to_have_rows(expected, columns=None, ordered=True)` | a grid has the expected rows and cells |

```python
# pseudo-code
def test_remember_me_can_be_checked_and_unchecked(main: MainPage) -> None:
    main.remember_me.check()
    expect(main.remember_me).to_be_checked()
    expect(main.status).to_have_text("Remember: True")
    main.remember_me.uncheck()
    expect(main.remember_me).not_.to_be_checked()
    expect(main.status).to_have_text("Remember: False")
```

A failing assertion reports what was expected and the last value it saw; VS Code shows text
mismatches as a diff.

For grids, list rows contain every compared column; dict rows compare only their named columns
(header names or zero-based indices). `columns=` selects and orders columns; without it list rows
compare all columns and dict rows use their named columns. Cells compare as strings or compiled
regexes. `ordered=False` matches rows without regard to order. Comparisons are limited to 500 rows;
failures show expected and actual tables and the first difference (or unmatched row).

```python
# pseudo-code
expect(main.orders).to_have_rows(
    [{"Customer": "Ada", "Status": re.compile(r"^Ready")}, {"Customer": "Lin"}],
    ordered=False,
)
```

## Timeouts

The time an action or assertion waits is, from highest to lowest precedence:

1. `timeout=` on the call: `click(timeout=5)`, `expect(x, timeout=5)`.
2. `timeout=` on the `Element` definition.
3. `@pytest.mark.wtk(timeout=...)` on the test.
4. The project timeout: `wtk run --timeout`, then the `WTK_TIMEOUT` environment variable, then
   `timeout` in `[tool.wintestkit]`, then the default of **10 seconds**.

```python
# pseudo-code
def test_timeouts(main: MainPage) -> None:
    main.load.click()
    expect(main.continue_button, timeout=5).to_be_enabled()
    main.continue_button.click(timeout=5)  # per-call: wait up to 5 s for existence
    expect(main.status, timeout=5).to_contain_text("Continued")


@pytest.mark.wtk(timeout=20)  # default auto-wait for this test only
def test_a_slow_test(main: MainPage) -> None:
    main.load.click()
    expect(main.data_loaded).to_be_visible()
```

Application start-up has its own limit, `startup_timeout` in `[tool.wintestkit.app]` (30 seconds
by default).


## Logging and steps

Use named steps to group actions and messages in the report. Steps can be nested;
exceptions mark each enclosing step as failed. Details named like secrets are
redacted, and `secret=True` redacts every detail.

```python
# pseudo-code
from wintestkit import log, step

with step("Sign in", account="operator"):
    log.message("Opening the sign-in form")
    log.warning("Using a temporary account")
    log.picture(name="Before sign-in")
```

`log.picture()` captures the desktop; pass a bound control or window to capture
its area. Sensitive or unavailable targets are skipped. Warnings do not fail a test.
