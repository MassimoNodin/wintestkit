# API cheat sheet

## Mouse, windows, navigation and typed controls

Clickable typed elements and plain `Element` support `click(mode=None, x=None, y=None,
button="left", modifiers=None)`, `double_click(x=None, y=None, modifiers=None)` and
`right_click(x=None, y=None, modifiers=None)`. All elements support `middle_click` with the same
offset and modifier options, `drag_to(target, source_offset=None, target_offset=None, button="left",
modifiers=None)`, `drag_by(dx, dy, source_offset=None, button="left", modifiers=None)` and
`scroll(clicks, x=None, y=None, horizontal=False)`. Offsets are physical pixels from the top-left;
both coordinates are required, otherwise the center is used, and `-1` on an axis is the centre of
that axis (`click(x=-1, y=-1, modifiers="Shift")`; compute offsets from `el.width`, `el.height`, `el.rect`).
`drag(x, y, dx, dy, button="left", modifiers=None)` drags from a point by a delta. `activate()` and `close()` act on the
window that holds an element; `refresh()` looks an element or window up again. Position, modifiers, or a non-left
button force mouse input. Buttons are left, right or middle; modifiers include `"Ctrl+Shift"`.
Wheel positive is up, or right horizontally. Drag releases input even on failure. Mouse targeting
also accepts the app's owned popups.

Bound windows offer `activate()`, `is_active()`, `rect`, `move(x, y)`, `resize(width, height)`,
`press(keys, secret=False)` and `type(text, secret=False)` as well as close/maximize/minimize/restore.
Window keys activate the window and target its focused control; `finders.send_keys` accepts windows. WPF control typing accepts focus delegated to a descendant; it stops if focus leaves the control and redacts password parts.
`from wintestkit import keyboard` provides `press(keys, secret=False)`, `type(text, secret=False)`
and `hold(modifiers)` as a context manager. They do not activate a window: the app fixture or a
bound page must register the current app, and its window must already own the foreground, otherwise
input is refused. Held modifiers are released on exit, including on error.

`Menu.click_path("File|Recent|Report")` and `element.open_context_menu().click_path("Edit|Copy")`
walk menu levels. Opening a context menu uses right-click or Shift+F10 in pattern mode. `TreeView`
supports `select(path)`, `expand(path)`, `collapse(path)` and `items(path=None)`; expand the target
before listing its children. Paths use `|` by default (`separator=` changes it), or a list of exact
names and compiled regex segments. Empty paths/segments fail; missing segments name siblings.
Failed menu navigation closes open levels with Escape. Tree mouse selection clicks the header and
verifies selection.

`ListBox`, `DataGrid` and plain `Element` support `select(items, add=False)`, `deselect(items)` and
`clear_selection()`. Items may be names, indices or regexes, individually or in a list. Multiple
selection requires control support; mouse mode uses Ctrl+click, pattern mode selection patterns,
and the result is verified. `expect(grid).to_have_rows(expected, columns=None, ordered=True)`
compares list rows or dict rows keyed by header or zero-based index. List rows cover the compared
columns; dict rows can omit cells. Cells are strings or regexes; `columns` chooses a subset and
order, `ordered=False` ignores row order. The limit is 500 rows; failures show tables and the first
difference or unmatched row.

`Slider`, `ScrollBar` and `ProgressBar` expose numeric `value`, `minimum`, `maximum`. Slider and
scrollbar have `set_value(value, mode=None)`; only pattern mode can set a scrollbar. Slider mouse
mode clicks the thumb and uses keys; `increase(steps=1)` and `decrease(steps=1)` use arrow keys,
with at least one step. Range writes reject read-only/out-of-range values and verify within half
a small change. `DatePicker.value` is text, `.date` is a date or None, and `set_date(date, mode=None)`
uses the system short date format and verifies it; month/day names are unsupported. `Expander` has
`expand`, `collapse`, `is_expanded`; `ToggleButton` has click and check/toggle actions. `ToolBar`
has `click_button(name, mode=None)` by name, automation ID or regex; `StatusBar.texts()` returns
item texts. `Hyperlink` actions need UIA for WPF content elements because the WPF inspector lacks
their geometry and automation peer. Menu validates Menu/MenuBar; ContextMenu validates Menu;
range controls, Hyperlink, ToolBar and StatusBar validate their control types. DatePicker checks
its class name contains DatePicker; Expander requires Group and a class ending in Expander;
ToggleButton requires Button plus Toggle pattern.

Everything importable from `wintestkit`: `App`, `Page` (alias of `PageObject`), `Window`, `Element`,
`Elements`, the typed elements and `expect`. Bound classes (`BoundButton`, ...) are what you get from
an instance (`page.save` is a `BoundButton`; `CustomerPage.save` on the class is the `Button` definition).

## Declarations

```python
from wintestkit import Button, Element, Elements, Page, Window


class P(Page):
    window = Window(title="Customer")  # title, class_name, automation_id, process, index
    save = Button(automation_id="Save")  # typed
    panel = Element(control_type="Group", name="Shipping")
    ok = Element(control_type="Button", name="OK", within=panel)
    rows = Elements(control_type="ListItem", within=panel)  # texts(), count(), nth(i), filter(...)
```

Element options: `automation_id`, `name`, `control_type`, `class_name`, `index`, `depth`, `within`,
`window`, `timeout`, `validate` (typed elements only), `where`, `any_of`, `has`, `tree`. Windows and `Elements` also accept
`where={"HelpText": "Save", "ItemStatus": re.compile(r"AddressBox$")}`. Entries AND together;
boolean/numeric properties require boolean/numeric values. With `backend: auto`, WPF uses its
managed tree; other windows use UIA. Qualified keys such as `type:FullName`, `type:Is`, `clr:`,
`field:` and `dp:` require WPF and fail under `backend: uia`. `property_aliases` can map names
to qualified or UIA keys. Use paths observed in Spy and never put secrets in `where`. Managed
reads execute application code. Do not duplicate a property via a keyword and `where`.
`tree="objects"` (any `Element`, `Elements`, typed element or child) searches the migration object tree of a
WPF window instead: the visual tree without control-template parts and items-panel elements (their visible
descendants move up to the nearest visible ancestor), each popup its own root. `depth`, the first match and
`index` follow it (from an `App`, depth 1 is window nodes labelled `HwndSource: <root x:Name, else type>` and depth 2 the root
visuals; from a window, depth 1 is the root visual). `wpf:Text` (the element's text: `Text` of text blocks and
text boxes, `Title` of windows, `Content` then `Header` of headered content controls, `Header` of headered
items controls, `Content` of other content controls; else `''`) and `wpf:Ordinal` (1-based position among
same-type object-tree siblings) match on it; both work in `where` and `el.get(...)`.
Object labels: `app.WPFObject(cls, text, index)`/`.Window(cls, caption, index)` (also `.wpf_object`/`.window`, `finders.from_label(parent, 'WPFObject("A").Window("B")')`) select direct object-tree children and Win32 child windows as migrated suites write them; `el.parent`, `el.children()`, `el.child_count`, `el.label`, `el.full_name` navigate (see references/migration.md).
Strings match exactly; a compiled regex
matches with `re.search`. Managed values are exactly typed; `AsText("15")` compares a managed value's invariant text instead (15, `True`). Managed paths accept indexers (`clr:Rows[3].Value`) and `type:Name@DataContext` reads the runtime type of a nested value. `window = Window()` with no arguments means the application's main window.

`any_of=[{"automation_id": "Save"}, {"name": "Save"}]` ORs non-empty
property groups (at least two when provided), each merged with the element's properties; conflicts raise at definition time.
Matches form a de-duplicated union in alternative order; strict matching and `index` apply to the
union. Keys other than the four locator fields are `where` properties. `has=Element(...)` or a
`Locator` requires a matching descendant before strict matching and `index`. The child may use
properties, `where`, `any_of` and `depth`, but not `index`, `within`, `window`, item selectors or
nested `has`; it needs a property. Typed elements used as `has` do not add a control type. More
than 200 outer candidates raises `InspectorLimitError`; narrow the locator. If none contains the
child, the diagnostic says `but none contains`. Waits for either form poll.

Direct children only: `ok = panel.Button(name="OK")`, `rows = panel.Elements(control_type="ListItem")`,
`zip_code = panel.Element(name="Address").TextBox(name="Zip")`; any typed element works. It is
`within=panel, depth=1` (no `within`, `depth` or `window` option) and is a normal declaration. A bound
element does the same on the fly (`self.panel.Button(name="OK").click()`), but that child is not a
declared member of the page. A component root can have children too: `street = root.TextBox(...)`.

Component mounts: `address = AddressBox()`, `AddressBox(root=Element(class_name="AddressBox",
within=shipping_panel))`, `AddressBox(window=Window(title="Invoice"))`. `AddressBox(app)` also works
on its own. A page may also declare a `root`: its own elements are then searched inside it, but
mounted components are still searched in the window.

`Page(app)` binds a page; nothing is searched until you act or assert. The `page` fixture is a
shortcut: `page(CustomerPage)`. `Page.check()` returns `{path: error or None}`.

## Typed elements

| Type | Bound class | Actions and reads (besides the common ones) |
|---|---|---|
| `Button` | `BoundButton` | `click()`, `double_click()`, `right_click()` |
| `TextBox` | `BoundTextBox` | `type(text, clear=True, keys=False)`, `clear()`, `press(keys)`, `value` |
| `CheckBox` | `BoundCheckBox` | `check()`, `uncheck()`, `toggle()`, `is_checked()`, `click()` |
| `RadioButton` | `BoundRadioButton` | `select()`, `is_selected()`, `click()` |
| `ComboBox` | `BoundComboBox` | `select(item)`, `selected`, `selected_items()`, `items()`, `expand()`, `collapse()`, `value` |
| `ListBox` | `BoundListBox` | `select(items, add=False)`, `deselect(items)`, `clear_selection()`, `selected`, `selected_items()`, `items()` |
| `ListItem` | `BoundListItem` | `select()`, `is_selected()`, `click()` |
| `DataGrid` | `BoundDataGrid` | `row(i)`, `cell(row, column)`, `row_count()`, `column_count()`, `find_row(column, value)`, `select(items, add=False)`, `deselect(items)`, `clear_selection()`, `selected_items()` |
| `TreeView` | `BoundTreeView` | `select(item or path)`, `expand(path)`, `collapse(path)`, `selected`, `selected_items()`, `items(path=None)` |
| `TabControl` | `BoundTabControl` | `select(tab)`, `selected`, `selected_items()`, `items()` |
| `Text` | `BoundText` | `text` |

Common to every element: `exists()`, `is_visible()`, `is_enabled()`, `text`, `info()`,
`get(name)` reads a UIA property, managed path or pseudo-property; UIA names, configured aliases and qualified keys take precedence; `wait_for_property(name, expected)` waits for a value or regex.
`wait_for(state)` (`attached`, `detached`, `visible`, `hidden`, `enabled`, `disabled`, `stable`),
`focus()`, `scroll_into_view()`, `hover()`, `highlight()`, `nth(i)`, `resolve()`. Plain `Element`
offers generic actions. `select(item)` takes a name, a 0-based index or a compiled regex.
Items of virtualized lists/grids only exist when realized: ask the container with
`select`, `row`, `cell`, `find_row`. Every action accepts `timeout=`.

`click()` uses mouse input by default; `click(mode="pattern")` uses the control's automation
pattern and falls back to the mouse. Actions normally wait only for existence (`actionability: exists`),
then fail immediately if disabled or hidden and not scrollable. Scrollable off-screen items are
scrolled into view. Use `expect(x).to_be_enabled()` or set `actionability: strict` to wait for
enabled and visible. An element disappearing during an action is resolved and retried once.
Configure via YAML/TOML, `WTK_ACTIONABILITY`, `wtk run --actionability`,
`pytest --wtk-actionability`, or `@pytest.mark.wtk(actionability="strict")`; the marker overrides
the project setting for that test.

## expect

`expect(target, timeout=None)` takes a bound element, `Elements` collection or bound window.

`to_exist()`, `to_be_visible()`, `to_be_hidden()`, `to_be_enabled()`, `to_be_disabled()`,
`to_be_checked()`, `to_be_selected()`, `to_have_text(str | regex)`, `to_contain_text(str)`,
`to_have_value(str | regex)`, `to_have_count(n)`, `to_have_property(name, expected, op="==")` (UIA, managed or pseudo-property; `op` is `==`, `!=`, `<`,
`<=`, `>`, `>=`, `contains`, `not contains` or a name such as `lessOrEqual`; pseudo-properties are `exists`, `visible_on_screen`,
`enabled`, `checked`, `text`, `name`, `value`, `items`, `item_list`, `item_count`, `child_count`); `expect(x, soft=True)` records a
failure and lets the test continue; `.not_`
negates: `expect(x).not_.to_be_checked()`. It retries until the timeout (default 10 s).
Prefer `expect` to `assert` for anything asynchronous. Window targets: `expect(dialog.window).to_exist()`;
windows also have `close()`, `maximize()`, `minimize()`, `restore()`, `title`.

Timeout precedence: call `timeout=` > `Element(timeout=)` > `@pytest.mark.wtk(timeout=...)` >
`wtk run --timeout` > `WTK_TIMEOUT` > `timeout` in `[tool.wintestkit]` > 10 s.

## Application and fixtures

`App.attach(process="X.exe")`, `App.launch(path, process=...)`, `app.close()`, `app.launched`,
`app.main_window(timeout=...)`. The plugin provides the fixtures `app` (launch mode from
`[tool.wintestkit] launch = "attach" | "per-test"`), `page`, `apps` and `wtk_config`.

Several apps in one test: `apps.launch(path, args=[...], elevated=False)` / `apps.attach("x.exe")` (the `apps` fixture, or
`with Apps() as apps:`) return an `App`; bind a page to each (`ToolPage(tool)`), and the group closes or releases them at the end.
`finders.process("x.exe")` (raises `AppNotRunningError`), `finders.wait_process("x.exe", ms)` (`App` or `None`, `0` checks once) and
`finders.Sys.Process` / `Sys.WaitProcess` find a running process; `"x"` and `"x.exe"` are the same. `App.launch(..., elevated=True)` and
`app.elevated` in `[tool.wintestkit.app]` start it with `runas`; a non-elevated runner cannot drive that app (`ElevationError`).
Closing: `app.request_close("wm_close" | "alt_f4")`, `app.close_gracefully(on_prompt=fn, prompt_timeout=3, exit_timeout=30, kill=False, force=False)`
returns `"exited" | "killed" | "running"`, `app.kill()` (all processes of the exe), `app.wait_for_exit(s)`.
`close()` and `close_gracefully()` refuse an app attached to the Windows shell (`explorer.exe`: they would close every shell window) unless `force=True`.
Clipboard: `from wintestkit import clipboard`; `clipboard.get_text(secret=False, timeout=2)`, `set_text(text)`, `clear()`; report steps,
`ClipboardError` when there is no text or the clipboard stays locked.

## WebView2 content (`pip install "wintestkit[web]"`)

Web pages hosted in the app, through its remote debugging port (Playwright attaches to the running WebView2; no browser download).
Open the port: `App.launch(path, webview_debug_port=9223)` or `webview_debug_port = 9223` in `[tool.wintestkit.app]` (merged into
`WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS`; an app that passes `--remote-debugging-port` itself needs only `port=` below). Loopback only, but any
local process can drive the page while it is open: test machines only.
`page = app.web_page(url="*", *, port=None, timeout=None)` (wildcards `*` `?`, any case, or a compiled regex; first match; waits) and
`app.web_pages(url="*")` (list). `page.playwright_page` is the Playwright `Page`; `page.url`, `page.title`.
`page.find_element(css, first=False, nth=None, timeout=None)` is strict (several matches: `AmbiguousElementError` at once; none: `ElementNotFoundError`
after the wait), `page.find_elements(css)` is a list (no wait), `page.query_selector(css)` is the first match or `None` (no wait). Elements have the same
lookups plus `shadow_root(0)` (0 is the only index; a plain CSS selector pierces open shadow roots too), `click()`, `set_text(text, secret=False)` (clears,
then types), `text`, `get_attribute(name)`, `is_visible()` and `locator` (Playwright). Every lookup and action is a report step (`web.find`, `web.click`, ...);
password inputs are masked. Connections are one per app and port, closed with the app and at the end of the test. Aliases for ported code: `app.Page`, `FindElement`,
`FindElements`, `QuerySelector`, `ShadowRoot`, `Click`, `SetText`. Without the extra the first call raises `WebExtraMissingError`.

## Custom controls

```python
import datetime

from wintestkit import BoundControl, Element
from wintestkit.engine import actions


class BoundDatePicker(BoundControl):
    required_patterns = ("Value",)  # UIA patterns the match must support; "A|B" accepts either

    def pick(self, day: datetime.date, *, timeout: float | None = None) -> None:
        with self.step("pick", {"day": day.isoformat()}):
            self.perform(timeout, lambda el: actions.type_text(el, day.isoformat()))


class DatePicker(Element[BoundDatePicker]):
    """A date picker."""
```

Use `DatePicker(automation_id="Start")` like any element. `self.perform(timeout, act)` waits for the
element according to actionability and calls `act(uia_element)`; `self.step(name, args,
secret=False)` logs the action. Other type rules: `accepted_control_types`, or override
`check_type(element)` and raise `self.type_mismatch(element, "reason")`. To extend a built-in:
`class BoundMyCombo(BoundComboBox)` with `class MyCombo(Element[BoundMyCombo])`, or subclass the typed
element (`class StateCombo(ComboBox)`). Expose actions of a custom control to tests through
intent methods like any other.

## Commands

`wtk init [DIR] --app PATH`, `wtk doctor`, `wtk spy` (Ctrl+Click picks a locator, Esc exits),
`wtk inspect [--window TITLE|/REGEX/ | --all-windows | --at X,Y] [--depth N] [--json]`,
`wtk check FILE[::Page] [--json]`, `wtk highlight`, `wtk discover [--json]`,
`wtk run [-k EXPR] [-m EXPR] [-x] [--lf] [TESTS ...]`.


## Logging and steps

`from wintestkit import log, step` exposes `with step(name, **details):` for
nested groups, `log.message(text, **details)`, `log.warning(text, **details)`,
`log.error(text, **details)` (records an error: the test continues and fails when it ends, with every error listed),
`log.checkpoint(text)` (a passed check) and `log.picture(target=None, name="picture")`. Warnings do not fail tests.
`from wintestkit import soft`: `soft.continue_on_error()` makes every `expect` in a block soft, `@pytest.mark.wtk(soft=True)` a whole
test or module; `soft.errors()` lists the recorded errors.
Use `secret=True` to redact all step or message details; sensitive picture
targets are skipped.

`wintestkit.finders.send_keys(target, text, secret=False, timeout=None)` sends migrated key strings (`^a[Del]hello[Enter]`, `[Hold]^[Hold]![F8]`); `keyboard.keys(text, secret=False)` sends the same grammar to the foreground window; `parse_keys(text)` parses segments and `to_keys(text)` converts key-only strings to `press()` syntax.

Migration helpers (`wintestkit.finders`): `check_property(el, prop, condition, value, timeout=None, soft=False) -> bool` runs an old property check (`WPFControlText`, `Exists`, `VisibleOnScreen`, `wText`, `wItemList`, `wItemCount`, `ChildCount`, `WndCaption`, `Enabled`, `DataContext.X`... with `equal`, `notEqual`, `contains`, `lessOrEqual`, `greaterOrEqual`) as an `expect` assertion; `wait_property(el, prop, value, timeout_ms=None, condition="equal") -> bool` waits and returns `True`/`False` without raising; `map_property(name, wpf=True)` shows what a name is read as.

Managed calls accept `Int32`, `Int64`, `Single`, `Double`, `Decimal`, `Enum` and `Null` from `wintestkit` to select exact CLR overloads. For example, allowlist `Method(System.Int32)` for `Int32(1)`, `Method(Ns.Choice)` for `Enum("Ns.Choice", "First")`, and ``Method(System.Nullable`1[System.Int32])`` for ``Null("System.Nullable`1[System.Int32]")``. Plain `int`, `float`, `str`, `bool`, and `decimal.Decimal` map to Int64, Double, String, Boolean, and Decimal. Use `Null(type)` instead of `None` and explicit `Enum(...)` instead of Python enum members.

Pure method calls: public instance methods directly marked with an attribute named `PureAttribute` may be called without an allowlist entry. Signature, redaction, deadline and rate limits still apply; property setters always require an allowlist entry. The attribute is the author's claim, not proof: a method can still have side effects. Value-free audits identify authorization as `pure` or `allowlist`; denied attempts omit it.
