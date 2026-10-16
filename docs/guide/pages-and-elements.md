# Pages and elements

A **page** is a Python class that describes one window, dialog or page of your application: which
window it lives in and how to find each control. Tests use pages instead of raw locators, so a
changed control is fixed in one place.

```python
# pseudo-code
class NoteDialog(Page):
    """The modal dialog opened by "Open dialog" (an owned WPF window)."""

    window = Window(title="WTK Demo - Dialog")

    note = Element(control_type="Edit")
    save = Element(control_type="Button", name="Save")
    cancel = Element(control_type="Button", name="Cancel")
```

## `Page`

Subclass `Page` and declare `Window`, `Element` and `Elements` attributes. Bind it to the
running application by creating an instance: `NoteDialog(app)`. Accessing an attribute on the
**class** returns the definition (`NoteDialog.save`); accessing it on an **instance** returns a
bound element you can act on (`NoteDialog(app).save.click()`). Nothing is searched until you act
or assert, so creating a page is free.

The `page` fixture is a shortcut: `page(MainPage)` is `MainPage(app)`.

## `Window`

`window = Window(...)` says which top-level window the page's elements are searched in. Its
options are `title`, `class_name`, `automation_id`, `process` and `index`. Without a `window`,
elements are searched in the application's main window.

A page for a native message box matches the Win32 dialog class:

```python
# pseudo-code
class MessageBox(Page):
    """A native Win32 message box (window class ``#32770``)."""

    window = Window(class_name="#32770")

    ok = Element(control_type="Button", name="OK")
    text = Element(control_type="Text", index=0)
```

Bound windows support `close()`, `maximize()`, `minimize()`, `restore()` and the `title` property,
and can be passed to `expect` (`expect(dialog.window).not_.to_exist()`).

## `Element`

An element is found by its UI Automation properties (a plain `Element` offers every action; see
[Typed elements](#typed-elements) for declarations that offer only what a control supports):

| Option | Matches |
|---|---|
| `automation_id` | `AutomationId` (WPF `x:Name` or `AutomationProperties.AutomationId`) |
| `name` | `Name`: the label, content or text |
| `control_type` | `ControlType`: `Button`, `Edit`, `CheckBox`, `ComboBox`, `List`, `DataGrid`, … |
| `class_name` | `ClassName`: the WPF type, e.g. `TextBox`, `PasswordBox` |
| `index` | the n-th match (0-based) when several elements match |
| `depth` | maximum search depth below the container |
| `within` | another `Element` to search inside instead of the whole window |
| `window` | a `Window` overriding the page's window for this element |
| `timeout` | default auto-wait for this element, in seconds |
| `validate` | typed elements only: `False` skips the check that the match fits the type (default `True`) |

`name`, `class_name`, `automation_id` (and `Window` `title`) accept a string for an exact match or
a compiled regular expression, which matches with `re.search`:

```python
# pseudo-code
class AnyDemoWindow(Page):
    # Regular expressions match with re.search; plain strings must match exactly.
    window = Window(title=re.compile(r"^WTK Demo$"))

    sign_in = Element(control_type="Button", name=re.compile(r"^Sign\s+in$"))
```

A locator must match **exactly one** element. See [Locators for WPF](locators-for-wpf.md) for why
and how to choose properties.

## `within`

`within=` searches inside another element. It is the main tool for applications without
AutomationIds: find a uniquely named container, then the control inside it.

```python
# pseudo-code
    # two groups that each contain an "OK" button
    panel_a = Element(control_type="Group", name="Panel A")
    panel_b = Element(control_type="Group", name="Panel B")
    ok_a = Element(control_type="Button", name="OK", within=panel_a)
    ok_b = Element(control_type="Button", name="OK", within=panel_b)
    all_ok_buttons = Elements(control_type="Button", name="OK")
```

`within` chains can be as deep as needed; each link must itself be unique.

## `Elements`

`Elements(...)` describes a group of elements matching one locator. It takes the same options as
`Element` except `index`. A bound collection supports `count()`, `nth(i)`, `first()`, `last()`,
`all()`, `texts()`, `filter(name=..., class_name=..., automation_id=...)`, iteration and `len()`.

```python
# pseudo-code
def test_the_dropdown_items(main: MainPage) -> None:
    main.color.expand()
    assert main.color_items.texts() == ["Red", "Green", "Blue"]
    main.color_items.filter(name="Green").first().click()
    expect(main.status).to_have_text("Color: Green")
```

## Typed elements

`Element` is the generic declaration: its bound element offers every action (`click`, `type`,
`select`, `check`, `expand`, `row`, ...) whatever the control. When you know what the control is,
declare it with a **typed element**. It takes the same options as `Element`, but the bound element
offers only the actions and reads that apply, so autocomplete and the type checker reject the rest
(`save.type("x")` on a button is an error before the test ever runs).

```python
# pseudo-code
from wintestkit import Button, CheckBox, ComboBox, DataGrid, Page, TextBox, Window


class CustomerPage(Page):
    window = Window(title="Customer")

    name = TextBox(automation_id="Name")
    vip = CheckBox(automation_id="Vip")
    country = ComboBox(automation_id="Country")
    orders = DataGrid(automation_id="Orders")
    save = Button(name="Save")


def test_create_a_customer(customer: CustomerPage) -> None:
    customer.name.type("Ada")
    customer.vip.check()
    customer.country.select("Norway")
    customer.save.click()
    assert customer.orders.row_count() == 1
    customer.save.type("x")  # type checker: "type" is not an attribute of BoundButton
```

| Type | Bound class | Actions and reads (besides the common ones) |
|---|---|---|
| `Button` | `BoundButton` | `click()`, `double_click()`, `right_click()` |
| `TextBox` | `BoundTextBox` | `type(text, clear=True, keys=False)`, `clear()`, `press(keys)`, `value` |
| `CheckBox` | `BoundCheckBox` | `check()`, `uncheck()`, `toggle()`, `is_checked()`, `click()`, `double_click()`, `right_click()` |
| `RadioButton` | `BoundRadioButton` | `select()`, `is_selected()`, `click()`, `double_click()`, `right_click()` |
| `ComboBox` | `BoundComboBox` | `select(item)`, `selected`, `selected_items()`, `items()` (expands, reads, collapses), `expand()`, `collapse()`, `value` |
| `ListBox` | `BoundListBox` | `select(item)`, `selected`, `selected_items()`, `items()` |
| `ListItem` | `BoundListItem` | `select()`, `is_selected()`, `click()`, `double_click()`, `right_click()` |
| `DataGrid` | `BoundDataGrid` | `row(i)`, `cell(row, column)`, `row_count()`, `column_count()`, `find_row(column, value)`, `select(row_index)`, `selected_items()` |
| `TreeView` | `BoundTreeView` | `select(item)`, `selected`, `selected_items()`, `items()` |
| `TabControl` | `BoundTabControl` | `select(tab)`, `selected`, `selected_items()`, `items()` (the tabs) |
| `Text` | `BoundText` | nothing extra: a read-only label, read with `text` |

Every typed element, and the plain `Element`, also has the **common** members: `resolve()`,
`exists()`, `is_visible()`, `info()`, `wait_for(state)`, `highlight()`, `text`, `is_enabled()`,
`focus()`, `scroll_into_view()`, `hover()`, `nth(i)`, `locator`, `qualname`, and works with
`expect(...)`. `items()` of a list, tree or tab control returns the items that are currently
realized (a virtualized list yields only those on screen). `row()`, `cell()` and `find_row()` return
a plain bound element. There is deliberately no `Menu` type: menus are usually components or
plain elements with your own naming.

`Element(...)` is unchanged and stays the generic fallback for controls without a fitting type.
There are no typed `Elements(...)` collections; those keep returning plain bound elements.

In an editor, `page.save` is the bound class (`BoundButton`), and `CustomerPage.save` on the class
is the definition (`Button`). The `within=` and `root=` options accept any element, typed or not.

### Type validation

A typed element does **not** add a `control_type` filter to its locator: custom WPF controls
often report `Custom`, and a filter would hide them. The locator finds the element exactly as
`Element` would. Afterwards, whenever the element is resolved, WinTestKit checks that the match
really fits the declared type, by the UI Automation **patterns** the type needs (`ComboBox`:
ExpandCollapse and Selection; `CheckBox`: Toggle; `TextBox`: Value or Text; `DataGrid`: Grid; ...),
falling back to the control type where there is no pattern (`TreeView`: `Tree`; `Text`: `Text`,
`Edit` or `Document`). A mismatch fails at once, without waiting, and names everything you need:

```text
CustomerPage.country is declared as ComboBox but matched control type 'Edit' (class 'TextBox',
name 'Country'), which does not support the ExpandCollapse and Selection pattern. Fix the locator,
declare it as the right type or as a plain Element, or pass validate=False
```

`wtk check` and `Page.check()` report the same message as a failure. For an odd control that
legitimately lacks the patterns, switch the check off for that declaration:
`country = ComboBox(automation_id="Country", validate=False)`.

## Custom controls

Give a custom WPF control its own type with two small classes: a **bound** class with the actions,
and an **element** class that names it.

```python
# pseudo-code
import datetime

from wintestkit import BoundControl, Element
from wintestkit.engine import actions


class BoundDatePicker(BoundControl):
    required_patterns = ("Value",)  # optional: what a DatePicker must support

    def pick(self, day: datetime.date, *, timeout: float | None = None) -> None:
        with self.step("pick", {"day": day.isoformat()}):
            self.perform(timeout, lambda el: actions.type_text(el, day.isoformat()))


class DatePicker(Element[BoundDatePicker]):
    """A date picker."""


class BookingPage(Page):
    window = Window(title="Booking")

    start = DatePicker(automation_id="Start")


def test_booking(booking: BookingPage) -> None:
    booking.start.pick(datetime.date(2026, 1, 2))
    expect(booking.start).to_have_value("2026-01-02")
```

The type argument of `Element[...]` is the only link between the two; it also gives
`booking.start` its type in the editor and under pyright strict. Inside a bound class:

- `self.perform(timeout, act)` waits until the element exists, is enabled and visible, then calls
  `act(element)` with the live UI Automation element and returns its result (retrying once if the
  element disappears mid-action). The helpers in `wintestkit.engine.actions` (`click`, `type_text`,
  `select`, `set_checked`, `expand`, ...) and `wintestkit.uia.patterns` take such an element.
- `self.step(name, args, secret=False)` reports the action in logs and the report like the
  built-in ones; `secret=True` hides the arguments.
- `self.resolve()`, `self.text`, `self.locator`, `self.qualname` and the other common members are
  available.
- `required_patterns` (UIA patterns that must all be present; `"A|B"` accepts either) or
  `accepted_control_types` define the type check. For any other rule, override
  `check_type(element)` and raise `self.type_mismatch(element, "reason")`.

To extend a built-in control, subclass its bound class (`class BoundMyCombo(BoundComboBox)`) and
declare `class MyCombo(Element[BoundMyCombo])`; an existing typed element can also be subclassed
as is (`class StateCombo(ComboBox)`). Discovery (`wtk discover`, the Explorer **Pages** tab)
finds your element classes statically, including across modules, and shows their type.

## Inheritance

Pages are classes, so they inherit. A subclass has every element of its base and can add or
override elements:

```python
# pseudo-code
class SignedInPage(MainPage):
    """Inherits every element of MainPage and adds its own."""

    welcome = Element(automation_id="StatusText", name=re.compile("^Welcome"))
```

Use this for windows that share a menu or toolbar, or for states of the same window.

## Components

A box that appears in several windows, or that may move from one window to another (an address
group, a toolbar, a dialog region, a user control), is a **component**: a `Page` subclass
without a window of its own, with a `root` element that finds the box. Declare the component
once and **mount** it on every page that shows it with `name = Box()`.

```python
# pseudo-code
class AddressBox(Page):
    """The AddressBox user control."""

    root = Element(class_name="AddressBox")
    street = Element(control_type="Edit", name="Street")
    city = Element(control_type="Edit", name="City")


class CustomerPage(Page):
    window = Window(title="Customer")

    address = AddressBox()


def test_fill_the_address(customer: CustomerPage) -> None:
    customer.address.street.type("1 Main St")
    expect(customer.address.city).to_have_text("")
```

Rules:

- **One page per window, one component per reusable or movable box.** Pages declare the
  `window`; components declare the `root`. A component without a `window` is searched in the
  window of the page it is mounted on.
- **Elements of a component are searched inside its `root`.** The `root` itself is searched in
  the window. It is not searched inside the root of the page that mounts it, so a component does
  not care what else surrounds it.
- A page can have a `root` too. Its own elements are then searched inside it, but mounted
  components are still searched in the window.
- A component that declares its own `window` uses it wherever it is mounted.
- Tests reach into a component through the mount: `customer.address.street`. Errors and `wtk
  check` show the full path (`CustomerPage.address.street`), so a failure says where the box is
  mounted.

### Per-mount overrides

A mount can replace the component's `root` or `window` for that one use. This is how one
component serves two boxes in the same window: give each mount a `root` that is told apart with
`within`, using an element declared on the page.

```python
# pseudo-code
class CheckoutPage(Page):
    window = Window(title="Checkout")

    shipping_panel = Element(control_type="Group", name="Shipping")
    billing_panel = Element(control_type="Group", name="Billing")

    shipping = AddressBox(root=Element(class_name="AddressBox", within=shipping_panel))
    billing = AddressBox(root=Element(class_name="AddressBox", within=billing_panel))
    invoice = AddressBox(window=Window(title="Invoice"))
```

`within=` in a mount's `root` refers to elements of the page that mounts it, and follows that
page's own rules. `AddressBox(app)` also works on its own: the box is searched in its window.

### Moving a box to another window

When the box moves, move its mount line. The component and every test stay as they are:

```python
# pseudo-code
class CustomerPage(Page):
    window = Window(title="Customer")
    # address = AddressBox()      <- removed

class CustomerDetailsPage(Page):
    window = Window(title="Customer details")

    address = AddressBox()        # <- added
```

Tests that used `customer.address` now use `details.address`. If the box also gets a new
location inside the window, change the component's `root` once.

You do not have to guess which test broke because of a move: a failing member of a component reports whether its root, or the element itself, was found in another window and prints the mount line to change (see [Found in another window](troubleshooting.md#found-in-another-window)).

## Organizing pages

- One module per window or group of related dialogs under `pages/`, re-exported from
  `pages/__init__.py` so tests can write `from pages import MainPage`.
- One `Page` per window or dialog; a page per tab or region of a large window keeps classes
  small.
- Name elements after what the user sees and what they are for (`sign_in`, `username`), not after
  their locator (`button_3`).
- Keep locators in pages and behaviour in tests or fixtures. A fixture that returns the bound
  page keeps tests short:

```python
# pseudo-code
@pytest.fixture(autouse=True)
def reset_demo(main: MainPage) -> None:
    """Start every test from a clean app: the app is shared by the whole session."""
    main.menu_file.click()
    main.menu_reset.click()
    expect(main.status).to_have_text("Ready")
```

Pages are discovered statically (without importing your code) by `wtk discover`, the Explorer
**Pages** tab and CodeLens, so define them as plain class attributes at class level.
