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

An element is found by its UI Automation properties:

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

Pages are discovered statically (without importing your code) by `wtk discover`, the VS Code
Pages section and CodeLens, so define them as plain class attributes at class level.
