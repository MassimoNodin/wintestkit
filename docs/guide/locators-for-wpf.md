# Locators for WPF

For additional UIA properties and TestComplete aliases, see [property matching](property-matching.md).

## Strict matching

Every `Element` locator must match **exactly one** control. When nothing matches, WinTestKit waits
up to the timeout and then fails with `ElementNotFoundError`. When several controls match, it
fails **immediately** with `AmbiguousElementError`, because waiting cannot fix an ambiguous
locator:

```python
# pseudo-code
def test_an_ambiguous_locator_fails_fast_with_a_clear_message(main: MainPage) -> None:
    class Ambiguous(MainPage):
        either_ok = Element(control_type="Button", name="OK")

    with pytest.raises(AmbiguousElementError) as error:
        Ambiguous(main.app).either_ok.click()
    assert str(error.value) == (
        '2 elements match Button[name="OK"] in Window "WTK Demo"; '
        "add within= or index= to pick one"
    )
```

There is no "self-healing". A locator that silently picks the first of several matches, or the
closest of several near misses, clicks the wrong control as soon as the application changes, and
the failure shows up far from its cause. Strict matching fails at the line that is wrong.

## Reading diagnostics

A not-found failure lists the closest candidates and how each differs:

```text
No element matches Button[name="Sign In"] in Window "WTK Demo" (closest: Button "Sign in" — name differs) (waited 1.0s)
```

The HTML report and the VS Code test results show the full diagnostic as a table (candidate,
class, rectangle, mismatched properties), plus screenshots of the window and desktop and a dump of
the UI tree (`tree.txt`) at the moment of failure. **Check Element** in VS Code and `wtk check`
show the same diagnostic without running a test.

## Choosing properties

Prefer, in this order:

1. **`automation_id`**: stable and language-independent. WPF sets it from `x:Name` only for some
   controls; many applications have none, which is why the rest of this list exists.
2. **`name`** with **`control_type`**: the visible label (`Button "Sign in"`). It changes with the
   UI language and wording.
3. **`class_name`**: the WPF type (`TextBox`, `PasswordBox`, `ComboBox`). Useful for unlabeled
   inputs.
4. **`within`**: scope the search to a uniquely identifiable container (a `GroupBox`, panel, tab or
   dialog).
5. **`index`**: the n-th of several matches. Use it last; it breaks when controls are added or
   reordered.

When an application exposes few AutomationIds, its page definition can combine these strategies:

```python
# pseudo-code
    # asynchronous loading
    load = Element(control_type="Button", name="Load")
    continue_button = Element(control_type="Button", name="Continue")
    data_loaded = Element(control_type="Text", name="Data loaded")

    # choices
    color = Element(automation_id="ColorCombo")
    color_items = Elements(control_type="ListItem", within=color)

    # virtualized list and grid
    items = Element(control_type="List", class_name="ListBox")
    products = Element(control_type="DataGrid")
```

Use the Spy (`wtk spy` or the VS Code Spy view): its suggested locator follows the same order and
is checked for uniqueness before it is shown.

## Applications without AutomationIds

- Find a container with a unique name (`Group "Credentials"`), then use `within=` for controls
  inside it. Unlabeled `TextBox`es next to a label are usually unique by `class_name` inside their
  group.
- Use a regular expression for names that contain changing data: `name=re.compile(r"^Order \d+")`.
- If two identical controls differ only by position, `index=` within the smallest container is the
  most robust choice.

## Popups, menus and combo boxes

WPF opens menus, combo box drop-downs and context menus in separate popup windows. WinTestKit
searches the application's popups too, so menu items are declared like any other element:

```python
# pseudo-code
    # menu
    menu_file = Element(control_type="MenuItem", name="File")
    menu_reset = Element(control_type="MenuItem", name="Reset")
```

For combo boxes, `select()` opens the drop-down when needed and selects by name, index or pattern:

```python
# pseudo-code
def test_select_a_color_by_index_and_by_pattern(main: MainPage) -> None:
    main.color.select(0)
    expect(main.status).to_have_text("Color: Red")
    main.color.select(re.compile("^Gr"))
    expect(main.status).to_have_text("Color: Green")
```

## Virtualized lists and grids

WPF only creates UI elements for the rows that are visible. Items that were never scrolled into
view do not exist in the UI tree, so an `Element` locator cannot find them. Ask the container
instead:

- `select(item)` on a list, combo box, tree, tab or grid finds the item by name, index or regular
  expression, realizing it if necessary.
- `row(i)` and `cell(row, column)` address grid items by index; `column` may be a header name.
- `find_row(column, value)` scans a grid for the first row whose cell matches.
- `row_count()` and `column_count()` read the grid size.

```python
# pseudo-code
def test_select_a_far_away_list_item(main: MainPage) -> None:
    main.items.select("Item 450")  # not realized yet: WinTestKit asks the container for it
    expect(main.status).to_have_text("Selected: Item 450")
```

```python
# pseudo-code
def test_read_grid_cells(main: MainPage) -> None:
    assert main.products.cell(5, "Name").text == "Product 6"
    assert main.products.cell(9, "Qty").text == "1"  # Product 10: (10 * 7) mod 23


def test_find_a_row_by_value(main: MainPage) -> None:
    main.products.find_row("Name", "Product 180").click()
    expect(main.status).to_have_text("Row: Product 180")
```

## Dialogs and message boxes

Give each dialog its own page with its own `Window(...)`. Owned WPF windows are found by title;
native message boxes (`MessageBox.Show`) are Win32 dialogs with class `#32770`:

```python
# pseudo-code
def test_message_box(main: MainPage) -> None:
    main.show_message.click()
    box = MessageBox(main.app)
    expect(box.window).to_exist()
    expect(box.text).to_have_text("Hello from application")
    box.ok.click()
    expect(main.status).to_have_text("Message closed")
```
