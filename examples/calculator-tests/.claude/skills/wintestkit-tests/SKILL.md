---
name: wintestkit-tests
description: Write, migrate or fix WinTestKit (pytest-based WPF / Windows UI Automation) page objects, components, flows and tests. Use when creating or editing files under pages/, flows/ or tests/ of a project that imports `wintestkit`, when migrating a TestComplete NameMapping or script to WinTestKit, when `wtk check` or a test reports "found in another window" or "No element matches", or when asked how to structure UI tests for a WPF application.
---

# Writing WinTestKit tests

WinTestKit drives a Windows application through UI Automation (UIA) with pytest. The design goal of
this skill is that **a box that moves to another window is fixed by changing one line**. Follow the
structure below exactly; do not invent API. Longer material: [API cheat sheet](references/api.md),
[TestComplete migration](references/migration-from-testcomplete.md),
[fixing breakages](references/fixing-breakages.md). A complete reference implementation is the
Calculator example (`examples/calculator-tests` in the WinTestKit repository).

## Project layout

```text
pyproject.toml            # [tool.wintestkit] and [tool.wintestkit.app]; pytest and pyright settings
wintestkit.yaml           # shared settings; machine paths go in wintestkit.local.yaml (git-ignored)
conftest.py               # fixtures: the app, a page already opened, a reset before each test
pages/
  __init__.py
  customer.py             # one Page per WINDOW (declares `window`)
  components/
    address.py            # one component per reusable or movable BOX (declares `root`)
flows/
  navigation.py           # cross-window navigation, multi-page scenarios, plain functions
tests/
  test_customer.py        # intent calls + expect(...)
```

## What goes where

| You are describing | It is a | Declares |
|---|---|---|
| A top-level window or dialog | **Page** (`class X(Page)`) | `window = Window(...)` |
| A box inside a window that is reused, may move, or repeats (dialog region, input group, toolbar, user control, navigation pane) | **Component** (also `class X(Page)`) | `root = Element(...)`, no `window` |
| Steps that cross windows or pages (open a screen, log in, create then verify) | **Flow** (function in `flows/`) | takes `app`, returns the page it ends on |
| One scenario and its assertions | **Test** | nothing: it calls intent methods, then `expect` |

Rules:

- One Page per window. A component's `root` is searched **in its window, never under the parent's
  root**, so a component does not care what surrounds it. Mount it with `address = AddressBox()`.
- Moving a box to another window = moving **one mount line** to the other page. The component and
  the tests do not change.
- A mount can override the component: `AddressBox(root=Element(...))` (second instance in the same
  window, told apart with `within=` on a page element) and `AddressBox(window=Window(title=...))`
  (a box that always lives in another window).
- A single control that is not worth a box (a title text, one toggle) is just an element on the page.
- Put behaviour in **intent methods** on pages and components; put cross-window behaviour in flows.
- Pages are discovered statically: declare elements and mounts as plain class attributes at class
  level, never in `__init__` or loops.

## Elements: typed, plain or custom

```python
from wintestkit import Button, CheckBox, ComboBox, Element, Page, TextBox, Window
```

- Prefer a **typed element** when a built-in fits: `Button`, `TextBox`, `CheckBox`, `RadioButton`,
  `ComboBox`, `ListBox`, `ListItem`, `DataGrid`, `TreeView`, `TabControl`, `Text`. The bound element offers
  only the actions that apply (`save.type("x")` on a `Button` is a type error), and a mismatch
  between the declared type and the real control fails at once with a clear message.
- Use plain **`Element`** for containers (component roots, panels), for controls without a fitting
  type, and for anything unusual. `Elements` is for repeated items (`texts()`, `count()`).
- For a **custom WPF control** with its own behaviour, write a type once (see
  [API cheat sheet](references/api.md#custom-controls)) instead of scattering `Element` calls.
- A typed element does not add a `control_type` filter, so custom controls reporting `Custom` still
  match. Use `validate=False` only for a control that truly lacks the patterns.

**Naming:** name an element after what the user sees or what it is for, never after its locator:
`sign_in`, `street`, `vip`, `orders`, not `button_3`, `edit_7`. Name a component after the box
(`AddressBox`, `NavigationPane`) and its mount after its role on that page (`billing_address`).
Name intent methods with a verb the user would say: `set_address`, `add_item`, `open_standard`.

## Locator priority

Every locator must match **exactly one** element (ambiguity fails immediately; there is no
self-healing). Choose, in this order:

1. `automation_id` (WPF `x:Name` or `AutomationProperties.AutomationId`): stable, language-independent.
2. `name` plus `control_type`: the visible label; changes with language and wording.
3. `class_name`: the short WPF type (`TextBox`, `PasswordBox`).
4. The **component root** (or, for a lone element, `within=` on a uniquely identifiable container).
5. `index=`: last resort; breaks when controls are added or reordered.

`name`, `class_name`, `automation_id` accept a string (exact) or a compiled regex (`re.search`).
Confirm every locator in the Spy (`wtk spy`, Ctrl+Click) or with `wtk inspect` (see below); never
guess from the TestComplete mapping alone.

### Mapping from TestComplete properties

| TestComplete | WinTestKit |
|---|---|
| `WPFControlName` | usually `automation_id` (WPF's `x:Name`). Verify in Spy; if the control has no AutomationId, use `name` + `control_type` |
| `ClrFullClassName` | `class_name` is **only the short type name** in UIA (`AddressBox`, not `My.App.Views.AddressBox`). If the namespace was needed to disambiguate, solve it with the **component root**, `within=` or `index=`, and say so in a comment |
| `WPFControlText` / `Content` / `Caption` | `name` |
| ordinal / index properties | `index` (0-based; check the base) |
| the deep mapped parent chain | **not copied**. The component root replaces it |

Never reproduce TestComplete's deep hierarchy as a `within=` chain. One component root says where
the box is; its members are searched inside it. Keep `within=` to one level, and only when two
boxes in one window must be told apart.

## Pages and components

```python
# pages/components/address.py
from wintestkit import Element, Page, TextBox


class AddressBox(Page):
    """The AddressBox user control."""

    root = Element(class_name="AddressBox")
    street = TextBox(automation_id="Street")
    city = TextBox(automation_id="City")

    def set_address(self, street: str, city: str) -> None:
        self.street.type(street)
        self.city.type(city)
```

```python
# pages/customer.py
from pages.components.address import AddressBox
from wintestkit import Button, Page, Text, Window


class CustomerPage(Page):
    window = Window(title="Customer")

    address = AddressBox()
    save = Button(automation_id="Save")
    status = Text(automation_id="Status")

    def fill_in(self, street: str, city: str) -> None:
        self.address.set_address(street, city)

    def save_customer(self) -> None:
        self.save.click()
```

Parts common to several pages of one window (a window with modes) go in a base page; subclasses inherit its elements and mounts
(`class CalculatorModePage(CalculatorWindow)`).
Use `Element(automation_id=..., timeout=...)` only for known slow controls.

Verify roots **in every window or mode where the component is mounted**: the same box can have an
`automation_id` in one place and only a `name` in another (Calculator's operator keys do).

## Tests call intent, assert with `expect`

**Tests call intent methods on pages, components or flows. They touch element paths only inside
`expect(...)`.** No `click()` / `type()` in tests, and no string-based `getattr` lookups of elements.

Good:

```python
def test_save_shows_confirmation(customer: CustomerPage) -> None:
    customer.fill_in("1 Main St", "Oslo")
    customer.save_customer()
    expect(customer.status).to_have_text("Saved")
    expect(customer.address.city).to_have_value("Oslo")
```

Bad (and why):

```python
def test_save(app):
    page = CustomerPage(app)
    # element actions in a test: a moved box or renamed field breaks every test, not one method
    page.address.street.type("1 Main St")
    page.address.city.type("Oslo")
    # string lookup: invisible to rename, check and the type checker
    getattr(page, "save").click()
    # hard sleep: use expect() or wait_for()
    time.sleep(2)
    # assert checks once; expect keeps checking until the timeout
    assert page.status.text == "Saved"
```

Rules for the other direction: a dictionary from page types or enums to element **attributes**
(`{Mode.STANDARD: self.standard}`) or one method per case is fine; `getattr(page, name)` is not.

`expect` assertions: `to_exist`, `to_be_visible`, `to_be_hidden`, `to_be_enabled`, `to_be_disabled`,
`to_be_checked`, `to_be_selected`, `to_have_text`, `to_contain_text`, `to_have_value`,
`to_have_count`, `to_have_property`; negate with `.not_`. Details in the
[API cheat sheet](references/api.md). Actions and `expect` auto-wait; do not add sleeps. Use
`@pytest.mark.wtk(timeout=20)` or `timeout=` for the rare slow step.

### Data-driven tests and reset

```python
@pytest.mark.parametrize(("number", "expected"), [(1, 2), (2, 3), (3, 4)])
def test_add_one(standard: StandardPage, number: int, expected: int) -> None:
    standard.add_one_to(number)
    expect(standard.result).to_have_text(re.compile(rf"(?:Display is )?{expected}$"))
```

```python
# conftest.py
@pytest.fixture
def customer(app: App) -> CustomerPage:
    return open_customer(app)  # a flow: navigates, returns the page


@pytest.fixture(autouse=True)
def reset(customer: CustomerPage) -> None:
    """The app is shared by the session: every test starts from a known state."""
    customer.clear_form()
```

The `app` fixture comes from the plugin (launch mode from config); a project may override it (the
Calculator example attaches or launches itself). Tests that need another window use a flow
(`open_page(app, ScientificPage)`) and then the returned page.

## Flows

```python
# flows/navigation.py
def open_customer(app: App) -> CustomerPage:
    MainPage(app).navigation.open_customers()
    customer = CustomerPage(app)
    expect(customer.window).to_be_visible()
    return customer
```

A flow takes `app`, calls intent methods, synchronizes with `expect`, and returns the page it ends
on. Pages do not import each other for navigation; flows know the pages. Keep flows free of
assertions about behaviour under test: only wait for arrival.

## Migrating from TestComplete

Full procedure in [references/migration-from-testcomplete.md](references/migration-from-testcomplete.md).
Short form:

1. Configure the app (`wtk init --app ...`, `wtk doctor`).
2. **Per window -> a Page.** **Per repeated or movable box -> a component** (its root = the
   NameMapping node of the box; members = the leaves). Do not copy intermediate NameMapping nodes.
3. Open the window in the app, then `wtk check pages/x.py` until **green for that page** before
   migrating any test. Fix locators with the Spy.
4. Turn each script routine into an intent method; each test into a test using intent + `expect`;
   checkpoints into `expect`; `Delay`/`Sleep` into nothing (auto-wait) or `wait_for`; data-driven
   loops into `parametrize`; event handlers into fixtures.
5. Run the tests of that page, then the next window.

## Verifying and fixing

```powershell
wtk inspect --depth 8            # UIA tree of the running app (ids, names, classes, nesting)
wtk inspect --at 640,480         # the element at a screen point and its ancestors
wtk check pages/customer.py      # resolve every element of every page in the file now
wtk check pages/customer.py::CustomerPage
wtk discover                     # what static discovery sees: pages, components, element types
wtk run                          # the test suite (pytest underneath)
```

`wtk check` needs the application open on the window under test; controls that exist only in some
states (a closed pane, another mode, a popup) fail until the app is in that state.

When an element is not found, WinTestKit searches the other windows of the application and prints
`found in another window` with a `hint` naming the mount line. Read it and apply the smallest
change; see [references/fixing-breakages.md](references/fixing-breakages.md):

- component root found elsewhere -> move the mount line to the page of that window (or add
  `window=Window(...)` to the mount);
- a single element found elsewhere -> declare it on the page of that window or give it `window=`;
- found in the same window under a different container -> change the component's `root` once;
- ambiguous (`2 elements match`) -> add a property, then a component root, then `index=`.

Never loosen a locator to make a test pass, never add `index=` to hide ambiguity you have not
understood, and never use found-elsewhere elements through a workaround.

## Pre-finish checklist

- [ ] `uv run pyright` is clean (typed elements make wrong actions type errors); `ruff check` and
      `ruff format --check` pass if the project uses them.
- [ ] `wtk check` is green for every page, with the app on the right window or state.
- [ ] One Page per window; each reusable or movable box is a component mounted once per use.
- [ ] No element access outside `expect(...)` in `tests/`: no `.click()`, `.type()`, `.select()`
      on elements in tests; every action is an intent method or a flow.
- [ ] No `getattr` / `setattr` / string-built attribute names for elements, anywhere.
- [ ] No `time.sleep`, no polling loops; waits are `expect`, `wait_for` or the built-in auto-wait.
- [ ] Locators are `automation_id` first; no `index=` without a comment; no copied TestComplete
      hierarchy; `class_name` is the short type name.
- [ ] Names say what the user sees or what it is for; docstrings on pages and components.
- [ ] Tests are independent (a reset fixture), parametrized instead of copied, and keep their
      original scenarios and expected values.
