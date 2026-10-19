# API cheat sheet

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
`window`, `timeout`, `validate` (typed elements only), `where`. Windows and `Elements` also accept
`where={"HelpText": "Save", "ItemStatus": re.compile(r"AddressBox$")}`. Entries AND together;
boolean/numeric properties require boolean/numeric values. `property_aliases` in `wintestkit.yaml`
maps alternate names to real UIA properties (for example `ClrFullClassName: ItemStatus`); it does
not expose private .NET properties. Do not duplicate a property via a keyword and `where`.
Strings match exactly; a compiled regex
matches with `re.search`. `window = Window()` with no arguments means the application's main window.

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
| `ListBox` | `BoundListBox` | `select(item)`, `selected`, `selected_items()`, `items()` |
| `ListItem` | `BoundListItem` | `select()`, `is_selected()`, `click()` |
| `DataGrid` | `BoundDataGrid` | `row(i)`, `cell(row, column)`, `row_count()`, `column_count()`, `find_row(column, value)`, `select(row_index)` |
| `TreeView` | `BoundTreeView` | `select(item)`, `selected`, `selected_items()`, `items()` |
| `TabControl` | `BoundTabControl` | `select(tab)`, `selected`, `selected_items()`, `items()` |
| `Text` | `BoundText` | `text` |

Common to every element: `exists()`, `is_visible()`, `is_enabled()`, `text`, `info()`,
`wait_for(state)` (`attached`, `detached`, `visible`, `hidden`, `enabled`, `disabled`, `stable`),
`focus()`, `scroll_into_view()`, `hover()`, `highlight()`, `nth(i)`, `resolve()`. Plain `Element`
offers every action. `select(item)` takes a name, a 0-based index or a compiled regex. There is no
`Menu` type: declare menu items as plain `Element(control_type="MenuItem", name=...)` (popups are
searched too). Items of virtualized lists/grids only exist when realized: ask the container with
`select`, `row`, `cell`, `find_row`. Every action accepts `timeout=`.

`click()` uses the control's UIA pattern (Invoke, Toggle, SelectionItem, ExpandCollapse) and falls
back to the mouse; `click(mode="mouse")` always uses the mouse.

## expect

`expect(target, timeout=None)` takes a bound element, `Elements` collection or bound window.

`to_exist()`, `to_be_visible()`, `to_be_hidden()`, `to_be_enabled()`, `to_be_disabled()`,
`to_be_checked()`, `to_be_selected()`, `to_have_text(str | regex)`, `to_contain_text(str)`,
`to_have_value(str | regex)`, `to_have_count(n)`, `to_have_property(name, expected)`; `.not_`
negates: `expect(x).not_.to_be_checked()`. It retries until the timeout (default 10 s).
Prefer `expect` to `assert` for anything asynchronous. Window targets: `expect(dialog.window).to_exist()`;
windows also have `close()`, `maximize()`, `minimize()`, `restore()`, `title`.

Timeout precedence: call `timeout=` > `Element(timeout=)` > `@pytest.mark.wtk(timeout=...)` >
`wtk run --timeout` > `WTK_TIMEOUT` > `timeout` in `[tool.wintestkit]` > 10 s.

## Application and fixtures

`App.attach(process="X.exe")`, `App.launch(path, process=...)`, `app.close()`, `app.launched`,
`app.main_window(timeout=...)`. The plugin provides the fixtures `app` (launch mode from
`[tool.wintestkit] launch = "attach" | "per-test"`), `page` and `wtk_config`.

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
element to be enabled and visible and calls `act(uia_element)`; `self.step(name, args,
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
