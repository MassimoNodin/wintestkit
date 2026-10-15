# Actions and assertions

## Actions

Every action is a method of a bound element and accepts `timeout=` (seconds) to override how long
it waits for the element.

| Action | What it does |
|---|---|
| `click(mode=None)` | Click. In `pattern` mode (the default) it uses the control's Invoke, Toggle, SelectionItem or ExpandCollapse pattern and falls back to a mouse click; `mode="mouse"` always moves the mouse and clicks |
| `double_click()` / `right_click()` / `hover()` | Mouse input at the center of the element |
| `type(text, clear=True, keys=False)` | Enter text: set through the Value pattern when possible, otherwise typed on the keyboard. `clear=False` appends; `keys=True` always types key by key |
| `clear()` | Remove all text |
| `press(keys)` | Focus the element and press keys: `"Enter"`, `"Ctrl+S"`, `"Ctrl+A Delete"` (combos separated by spaces) |
| `select(item)` | Select an item of a combo box, list, grid, tree or tab control by name, 0-based index or compiled regex |
| `check()` / `uncheck()` | Set a check box or toggle button to a state (no-op if already there) |
| `expand()` / `collapse()` | Expand or collapse a tree item, combo box, menu or expander |
| `focus()` | Give the element keyboard focus |
| `scroll_into_view()` | Scroll a list or grid item into view |
| `highlight(duration_ms=1500)` | Draw a frame around the element (debugging aid) |

Windows have `close()`, `maximize()`, `minimize()` and `restore()`.

Text typed into a `PasswordBox` is never written to logs, reports or events.

```python
# examples/demo-tests/tests/test_guide.py
def test_typing_and_keys(main: MainPage) -> None:
    main.username.type("adm")
    main.username.type("in", clear=False)  # append instead of replacing
    expect(main.username).to_have_value("admin")
    main.username.press("Ctrl+A Delete")  # key combos separated by spaces
    expect(main.username).to_have_value("")
```

### Pattern or mouse input

`pattern` input talks to the control through UI Automation. It works when another window covers
the control, doesn't move the mouse and doesn't depend on screen coordinates, so it is the default. Use `mouse` when the application
reacts to real mouse events (custom controls, drag-sensitive areas) or to reproduce what a user
does exactly. Set it per call, or for the whole project with `input_mode = "mouse"`:

```python
# examples/demo-tests/tests/test_guide.py
def test_mouse_mode_and_nth(main: MainPage) -> None:
    main.sign_in.click(mode="mouse")  # a real mouse click instead of the Invoke pattern
    expect(main.status).to_have_text("Invalid credentials")
    main.all_ok_buttons.nth(1).click()  # 0-based
    expect(main.status).to_have_text("B OK")
```

## Auto-waiting

WinTestKit waits for the application so tests don't need sleeps.

| Call | Waits until | Then |
|---|---|---|
| Actions (`click`, `type`, `select`, …) | the element exists, is **enabled** and is **visible** (items that can be scrolled into view count as visible) | acts; if the element disappears during the action it is found again and the action retried once |
| `scroll_into_view()` | the element exists | scrolls |
| Reads (`text`, `value`, `is_enabled()`, `is_checked()`, `selected_items()`, `row_count()`, …) | the element exists | returns the current value |
| `exists(timeout=0)` | by default, doesn't wait | `True`/`False` |
| `is_visible()` | doesn't wait | `True`/`False` |
| `wait_for(state)` | the state is reached: `attached`, `detached`, `visible`, `hidden`, `enabled`, `disabled` or `stable` | returns the element |
| `expect(...)` | the assertion holds | passes, or fails with the last observed value |

An ambiguous locator never waits; it fails immediately (see
[strict matching](locators-for-wpf.md#strict-matching)).

```python
# examples/demo-tests/tests/test_async.py
def test_continue_waits_until_it_is_enabled(main: MainPage) -> None:
    expect(main.continue_button).to_be_disabled()
    main.load.click()
    expect(main.status).to_have_text("Loading...")
    main.continue_button.click()  # disabled for about two seconds: click() waits
    expect(main.status).to_have_text("Continued")
```

## Reading state

Reads return the current value without asserting anything:

```python
# examples/demo-tests/tests/test_guide.py
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
| `to_have_property(name, expected)` | a UI Automation property has the expected value |

```python
# examples/demo-tests/tests/test_login.py
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

## Timeouts

The time an action or assertion waits is, from highest to lowest precedence:

1. `timeout=` on the call: `click(timeout=5)`, `expect(x, timeout=5)`.
2. `timeout=` on the `Element` definition.
3. `@pytest.mark.wtk(timeout=...)` on the test.
4. The project timeout: `wtk run --timeout`, then the `WTK_TIMEOUT` environment variable, then
   `timeout` in `[tool.wintestkit]`, then the default of **10 seconds**.

```python
# examples/demo-tests/tests/test_guide.py
def test_timeouts(main: MainPage) -> None:
    main.load.click()
    main.continue_button.click(timeout=5)  # per-call: wait up to 5 s for this action
    expect(main.status, timeout=5).to_contain_text("Continued")


@pytest.mark.wtk(timeout=20)  # default auto-wait for this test only
def test_a_slow_test(main: MainPage) -> None:
    main.load.click()
    expect(main.data_loaded).to_be_visible()
```

Application start-up has its own limit, `startup_timeout` in `[tool.wintestkit.app]` (30 seconds
by default).
