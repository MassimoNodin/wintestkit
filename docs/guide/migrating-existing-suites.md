# Migrating an existing suite

This guide helps you migrate an existing **WPF desktop test suite** to WinTestKit, Python and pytest.

## Concept mapping

| Existing concept | WinTestKit |
|---|---|
| Project suite / project | A folder with `pyproject.toml` containing `[tool.wintestkit]` |
| Tested Applications | `[tool.wintestkit.app]` (`path`, `args`, `cwd`, `env`) and the launch mode |
| Name mapping and aliases | A `Page` per window and reusable `Page` components per movable box; page and component attributes name the controls |
| Key strings with `^`, `!`, `~`, `[Enter]` and `[Hold]` | `finders.send_keys(el, text)` / `keyboard.keys(text)` for the desktop form; see [keys](#keys) |
| Drag and drop | `element.drag_to(target)` / `drag_by(dx, dy)` |
| Positioned or modified mouse clicks | `click(x=..., y=..., modifiers=...)` and corresponding double/right/middle clicks; `-1` is the centre of an axis; `el.width` / `el.height` for computed offsets |
| Mouse wheel | `element.scroll(clicks, horizontal=False)` |
| `Drag(x, y, dx, dy, Shift)` | `element.drag(x, y, dx, dy, modifiers="Shift")` |
| `Activate()`, `Close()`, `Refresh()` | `element.activate()`, `element.close()`, `element.refresh()` (windows have them too) |
| Property checks with a condition | `finders.check_property(el, prop, condition, value)`; see [checks](#checks) |
| Soft failures: log an error and continue | `log.error(text)`, `soft=True`, `soft.continue_on_error()`; see [errors that do not stop the test](#errors-that-do-not-stop-the-test) |
| Global keys | `wintestkit.keyboard.press`, `type` and `hold`; the app must own the foreground |
| Menu path clicks | `Menu.click_path` / `element.open_context_menu().click_path` |
| Tree item paths | `TreeView.select`, `expand`, `collapse`, `items(path)` |
| Multi-select | `ListBox` / `DataGrid.select([...], add=...)`, `deselect`, `clear_selection` |
| Window position, size and activation | `window.move`, `resize`, `rect`, `activate`, `is_active` |
| Table checks | `expect(grid).to_have_rows(...)` |
| Extra control types | `Slider`, `ScrollBar`, `ProgressBar`, `DatePicker`, `Expander`, `ToggleButton`, `Hyperlink`, `ToolBar`, `StatusBar` |
| `FindChild` / `FindAllChildren` / `Find` calls | `wintestkit.finders.find_child`, `find_all_children`, `find`, or declared locators |
| `WPFObject(...)` / `Window(...)` call chains and `Sys.Process(...)` | `.WPFObject(...)` / `.Window(...)` on `App`, elements and windows (or `wpf_object`, `window`, `from_label`): see [object labels](#object-labels-wpfobject-and-window) |
| A `Name` property in `FindChild`, holding an object label | `find_child(parent, "Name", 'WPFObject("Button", "OK", 2)', depth)` |
| Walking to an object's parent or children, and naming an object | `el.parent`, `el.children()`, `el.child_count`, `el.label`, `el.full_name` |
| `ClrClassName` | `where={"type:Name": "OrderWindow"}` (managed short type name) |
| `<path>.ClrClassName` / `<path>.ClrFullClassName` | `where={"type:Name@DataContext": "OrderViewModel"}`: the type of the value at the path |
| Numbers and booleans passed as strings | `AsText("15")`: compares the managed value's invariant text; `find_child` and the importer apply it to plain string values on property paths |
| `Items.Item[0].Name` | `clr:Items[0].Name` (both spellings are accepted) |
| `WndClass` / `ClassName` | `class_name` (UIA peer class) |
| `WndCaption` | `name`, with mnemonic ampersands removed |
| `ControlId` / `WinFormsControlName` | `automation_id`; numeric IDs become decimal strings |
| `FrameworkId` / `LocalizedControlType` | UIA `where` properties |
| `VisibleOnScreen` | On-screen visibility condition |
| `ClrFullClassName` | `where={"type:FullName": "Namespace.Type"}`; `type:Is` includes derived types |
| `WPFControlName` | `automation_id`: peer or peerless attached AutomationId, falling back to `x:Name` with the WPF backend |
| `WPFControlText` | `wpf:Text`, the text the element shows, on WPF windows; the UIA Name on other windows |
| `WPFControlOrdinalNo` | `wpf:Ordinal`: 1-based position among siblings of the same runtime type, on WPF windows; a zero-based index over all matches on other windows |
| `Visible` / `Enabled` | `clr:IsVisible` / `clr:IsEnabled` via helpers or `where` |
| `ObjectIdentifier` | No direct equivalent: inspect and choose stable properties, not an invented ID |
| Conditional mapping (OR groups) | `any_of=[...]` |
| Required child objects | `has=Element(...)` |
| Wildcards | Helpers translate `*` and `?` to whole-value patterns; locators accept compiled regexes |
| Extended find / depth | `depth` counts [object-tree](#the-object-tree-model) levels on WPF windows (peer levels elsewhere); extended find uses descendant search |
| Direct property writes / method calls | Prefer UI actions; managed writes and calls are opt-in with an allowlist and audit (see [managed inspection](managed-inspection.md#writes-and-method-calls)) |
| Reading object properties (e.g. `obj.DataContext.Name`) | `el.get("clr:DataContext.Name")` |
| `WaitProperty(prop, value, timeout_ms)` | `finders.wait_property(el, prop, value, timeout_ms)` returns `True`/`False`, see [waits](#waits); `el.wait_for_property(name, expected)` raises on timeout |
| Inspecting objects | The Spy (`wtk spy` or the VS Code Spy view) and `wtk inspect` |
| Highlight on screen | `wtk highlight` or the **Highlight** CodeLens |
| Test routines / script routines | pytest test functions |
| Property checkpoints and region checks | `expect(...)` assertions; `finders.check_property` for the old names and conditions |
| Property and child waits | Automatic waiting in actions and `expect`; `wait_for()`, `exists()` |
| Auto-wait timeout | `timeout` setting, per-element `timeout=`, per-call `timeout=` |
| Event handlers (`OnUnexpectedWindow`, …) | pytest fixtures (setup and teardown) |
| Test items / execution plan | Test files, folders and pytest markers (`wtk run -m smoke`) |
| Data-driven loops | `@pytest.mark.parametrize` |
| Command-line runner | `wtk run` (or `pytest`) |
| Test log messages, warnings, errors, checkpoints and pictures | `log.message`, `log.warning`, `log.error`, `log.checkpoint`, `log.picture` |
| Log folders | Nested `step` contexts |
| Test log | The HTML report (`wtk-report/index.html`) and JUnit XML |
| Screenshots | `screenshots = "on-failure"` or `"every-step"` |

## What's different

- **Strict matching.** An existing mapping may resolve to the first of several
  matches. WinTestKit fails when a locator matches more than one element, so ambiguous mappings
  surface at the line that is wrong. Expect to add `within=` scopes while migrating.
- **UI Automation discovery.** There is no image-based or OCR recognition. Controls a screen reader can't
  see cannot be found by the UIA backend. The WPF backend can find peerless elements.
- **No recorder.** Use the Spy to build pages and write tests in Python; the editor
  completes element names from your pages.
- **Code review and version control.** Pages and tests are plain Python files that diff, review
  and merge like any other code.

First-match finders warn on ambiguity in the report and pytest; use identifying properties, scope, or `strict=True` instead. An explicit `WPFControlOrdinalNo` suppresses the warning.

## The object-tree model

Existing suites search a particular tree, and `find_child`, `find_all_children`, `find` and the importer
reproduce it on WPF windows (`tree="objects"`, see [the object tree](managed-inspection.md#the-object-tree)):

- **Tree.** The WPF visual tree without the parts of control templates and items panels; their visible
  descendants move up to the nearest visible ancestor. A grid cell is a direct child of its row, a combo
  box item of its popup and a ribbon's tabs of the ribbon. Each popup is a root of its own.
- **Depth** counts levels of that tree. From an `App`, depth 1 is the window nodes (`HwndSource: <x:Name or type>`,
  the window title as text), depth 2 the root visuals and depth 3 their children. From a window or a page
  without a root element, depth 1 is the root visual itself.
- **First match** is the depth-first pre-order one.
- **Ordinal** (`WPFControlOrdinalNo`) is the 1-based position among object-tree siblings of the same type,
  in visual order, whatever their text. It is a condition, not a global index. Window nodes count the window nodes
  of the same type.
- **Text** (`WPFControlText`) follows the element's class: `Text` for text blocks and text boxes, `Title` for
  a window, the first non-empty of `Content` and `Header` for headered content controls, `Header` for
  headered items controls, `Content` for other content controls and presenters, and `''` for anything
  else. An element value contributes its own text, and another object its `ToString()` when it overrides it.

These searches need the inspector on WPF windows. On a window that is not a WPF window
(a Win32 dialog) or with `backend: uia`, the same helper call keeps the UIA tree and the old mapping
(`WPFControlText` is the UIA Name, an ordinal a zero-based index). Declared locators opt in with
`Element(tree="objects", where={"wpf:Text": ..., "wpf:Ordinal": ...})`.


## Object labels: `WPFObject` and `Window`

Existing suites rarely search; they walk a chain of calls such as
`grid.WPFObject("DataGridRow", "", row).WPFObject("DataGridCell", "*", col)`. The Spy tree labels objects in the same
grammar, so a label copied from the Spy and the code of an existing suite are the same thing, and both work in Python.
The grammar and its meaning live in one module, `wintestkit.labels`; `wintestkit.finders` turns it into lazy elements.

The Spy shows the same object tree, with the same rules: the label of a row is the lone `x:Name` when no sibling shares
it, else the runtime type and the text (`""` for an empty text), plus the `wpf:Ordinal` only when type and text repeat
among siblings. A WPF window is `HwndSource: <x:Name of the root visual>`, or `HwndSource: <root type>` when the root
visual has no x:Name. The Properties view of the Spy shows the label as **Name**, the chain from the process as
**FullName** and the parent's label as **Parent**, and its actions menu copies the chain (**Copy label chain**) or the
statement `from_label(app, '<chain>')` (**Copy as code**). The Spy's *Show template parts* option shows the full
visual tree instead; its labels are marked as not pasteable. The Spy and the library are held to one set of cases
(`python/tests/fixtures/label_conformance.json`), so the two cannot drift apart.

```python
# pseudo-code
from wintestkit.finders import from_label, window, wpf_object

main = app.WPFObject("HwndSource: MainView", "Orders*").WPFObject("MainView", "Orders*")
cell = main.WPFObject("DataGrid", "").WPFObject("DataGridRow", "", 2).WPFObject("DataGridCell", "*", 1)
combo_item = app.WPFObject("HwndSource: PopupRoot", "").WPFObject("PopupRoot", "").WPFObject("ComboBoxItem", "Two")
edit = app.Window("#32770", "Save As").Window("Edit", "", 1)
same = from_label(app, 'WPFObject("HwndSource: MainView", "Orders*").WPFObject("MainView", "Orders*")')
```

`wpf_object(parent, cls, text=None, index=None)`, `window(parent, cls, caption="*", index=None)` and
`from_label(parent, label)` are in `wintestkit.finders`. `parent` is an `App`, a page, a bound element or a bound
window. The same calls are methods of bound elements, bound windows and `App`, as `.wpf_object(...)` and `.window(...)`
and under the names of existing suites, `.WPFObject(...)` and `.Window(...)`. `App` takes the aliases too because a
ported chain starts at the process (`Sys.Process("x").WPFObject(...)`), which the `App` stands for. Every result is an
ordinary lazy bound element: it re-resolves on each use and supports actions, `expect`, `get()` and further finders.

**`WPFObject`** selects a *direct* object-tree child of its parent (see [the object tree](#the-object-tree-model)):

| Call | Selects |
|---|---|
| `WPFObject(name)` | the direct child whose x:Name (`FrameworkElement.Name`) is `name` |
| `WPFObject(cls, text, index)` | the `index`-th (1-based, `wpf:Ordinal`) child of runtime type `cls`; `text` is checked too unless it is `""` or `"*"` |
| `WPFObject(cls, text)` | the first child of type `cls`, in object-tree order, whose text matches: `"*"` is any text, `""` empty text, anything else matches with `*` and `?` as wildcards |
| `WPFObject(cls, index)` | an integer second argument is the Spy form of an empty text: `WPFObject(cls, "", index)` |

`cls` is the runtime CLR short type name (`type:Name`). `"HwndSource: X"` as `cls` is a *window node*: a top-level
WPF window of the application whose root visual's x:Name is `X` (or, when that root visual has no x:Name, whose short type
name is `X`), with the window title as its text (wildcards allowed) and the index among the window nodes with the same
label. A window whose root type is `SettingsView` and whose x:Name is `SettingsViewWindow` is
`HwndSource: SettingsViewWindow`; the type spelling `HwndSource: SettingsView` still resolves it (the x:Name is
tried first, then the type; the index of the type spelling counts the windows of that root type). Labels are always
generated with the x:Name form. Window nodes are selected from an `App`; popups are window
nodes too (`"HwndSource: PopupRoot"`, text `""`). The only child of a window node is its root visual, so
`app.WPFObject("HwndSource: MainView", "T*").WPFObject("MainView", "T*")` is the root visual. A lone argument is always an
x:Name, never a type; use `("HwndSource: X", "*")` for a window of any title. Without an index the first match wins
without a warning (the call defines that); pass `strict=True` to fail when several children match. When nothing
matches, the error lists the parent's children of that type with their texts and ordinals.

**`Window(cls, caption, index)`** is a Win32 child window, or a top-level window when written from an `App`. `cls` is the
window class; `caption` the raw Win32 caption, mnemonic `&` removed, wildcards allowed, `"*"` by default (`""` is an
empty caption). `index` is 1-based among the sibling windows *of the same class* in child (z) order; the caption is
checked too unless it is `""` or `"*"`, and a mismatch is an error naming the window that was counted. `Window(cls, index)`
is `Window(cls, "", index)`. It uses UI Automation, not the managed tree, so it works for Win32 dialogs and their
controls; it does not look inside a WPF window's object tree.

**`Process("name")`** and the prefix `Sys.Process("name")` start a label *string*: `from_label` uses the `parent` when it
is that application and otherwise attaches to the process by name (`parent` may then be `None`). Quotes may be single
or double, backslash escapes (`\"`, `\`, `\n`, `\uXXXX`) work, whitespace is free, and a mistake raises
`LabelSyntaxError` with the position of the problem and a caret under it.

**The `Name` property.** `find_child(parent, "Name", label_step, depth)` matches any object within `depth` whose own
label step matches, with the semantics above: `find_child(app, "Name", 'WPFObject("HwndSource: MainView", "Orders*")', 2)`.
It combines with other properties in a list (a clash such as `Name` with `ClrClassName` is an error). Only `WPFObject`
steps are accepted; use `window()` for a `Window` step.

**Navigation.** Bound elements know their neighbours, on the object tree for WPF and among child windows (windows with a
handle) otherwise:

| | |
|---|---|
| `el.parent` | the parent element, or `None` at the top; the parent of a root visual is its window node, and a window node has no parent |
| `el.children()` | the children as bound elements that re-resolve by their label step |
| `el.child_count` | how many children there are (a window node has one) |
| `el.label` | the element's own label step: the x:Name when no sibling shares it, else the type and text (an empty text is written `""`, as a lone argument would be an x:Name), plus the ordinal among same-type siblings only when needed (`WPFObject("ListBoxItem", "Beta", 2)`, `WPFObject("ListBoxItem", 3)`, `Window("Edit", "", 2)`) |
| `el.full_name` | the label chain from the process, `Process("x").WPFObject("HwndSource: …", "…").WPFObject(…)…`; `from_label` parses it back to the same element |

An unreadable text (redacted or a throwing getter) is addressed by the ordinal alone. More than 200 object-tree children
are not listed in one query; address the one you want with a label or `find_child`.

## Migrating FindChild

The originals below are existing JavaScript-style calls; `p` is the fixture page and
`group` is its mapped group. The WinTestKit examples use `page` and `page.group`.
Import `find_child`, `find_all_children`, and `find` from `wintestkit.finders`.

| Existing call | WinTestKit call |
| --- | --- |
| `p.FindChild("WPFControlName", "FancyAutomationId", 20)` | `find_child(page, "WPFControlName", "FancyAutomationId", 20)` |
| `group.FindChild("ClrFullClassName", "System.Windows.Controls.Button", 20)` | `find_child(page.group, "ClrFullClassName", "System.Windows.Controls.Button", 20)` |
| `p.FindChild(["WPFControlName", "ClrFullClassName"], ["FancyAutomationId", "*FancyButton"], 20)` | `find_child(page, ["WPFControlName", "ClrFullClassName"], ["FancyAutomationId", "*FancyButton"], 20)` |
| `p.FindChild("WPFControlName", "Fancy*Id", 20)` | `find_child(page, "WPFControlName", "Fancy*Id", 20)` |
| `p.FindChild("WPFControlName", "FancyAutomationI?", 20)` | `find_child(page, "WPFControlName", "FancyAutomationI?", 20)` |
| `p.FindChild("WPFControlName", "NestedButton", 1)` | `find_child(page, "WPFControlName", "NestedButton", 1)` |
| `p.FindChild("WPFControlName", "NestedButton", 20)` | `find_child(page, "WPFControlName", "NestedButton", 20)` |
| `p.FindAllChildren("WPFControlName", "Duplicate", 20).length` | `find_all_children(page, "WPFControlName", "Duplicate", 20)` |
| `group.Find("WPFControlName", "ParityGroup", 1)` | `find(page.group, "WPFControlName", "ParityGroup", 1)` |
| `p.FindChild("WPFControlText", "Fancy action", 20)` | `find_child(page, "WPFControlText", "Fancy action", 20)` |
| `p.FindChild(["WPFControlName", "WPFControlOrdinalNo"], ["Duplicate", 2], 20)` | `find_child(page, ["WPFControlName", "WPFControlOrdinalNo"], ["Duplicate", 2], 20)` |
| `p.FindChild(["WPFControlName", "Visible", "Enabled"], ["FancyAutomationId", true, true], 20)` | `find_child(page, ["WPFControlName", "Visible", "Enabled"], ["FancyAutomationId", True, True], 20)` |
| `p.FindChild(["WPFControlName", "DataContext.Label"], ["FancyAutomationId", "fixture"], 20)` | `find_child(page, ["WPFControlName", "DataContext.Label"], ["FancyAutomationId", "fixture"], 20)` |
| `p.FindChild("ClrFullClassName", "WinTestKit.Fixture.PeerlessMarker", 20)` | `find_child(page, "ClrFullClassName", "WinTestKit.Fixture.PeerlessMarker", 20)` |

The depth-one nested lookup deliberately does not find the deeper button. Depth counts
[object-tree](#the-object-tree-model) levels; `None` means unlimited. From a page without a root
element depth 1 is the window's root visual, so the button inside the group is found at depth 20 but
not at depth 1; from `page.group` its content is a direct child.
`WPFControlText` matches the element's text (`wpf:Text`), which need not be the peer Name.
`WPFControlOrdinalNo` accepts integers or numeric strings, is one-based and is a position among
same-type siblings (`wpf:Ordinal`), not an index over all matches; matches that still share it are
ordered, and the first wins.
`find_all_children` returns indexed, re-resolving results: later tree reordering can
change their identities. `find` includes a bound parent; rootless pages and scopes start at their window, whose root
visual is depth 1 on WPF windows and cannot be included elsewhere. Managed properties
require inspector access, and UIA cannot discover elements without automation peers.
An `App` parent searches all top-level windows and their descendants; depth 1 is the window nodes, depth 2 the root visuals. Window titles accept wildcards. `Exists=True` adds no condition and `Exists=False` raises an error. A trailing `.OleValue` is stripped from property paths.
An element found from an `App` (a dialog, a message box, a popup, any window's descendant) is a parent like
any other: `find_child(dialog, "WndClass", "Edit", 5)` searches inside the dialog, not in the main window.
A search skips candidates whose value cannot be read and says how many it skipped when nothing matches
(see [unreadable candidates](managed-inspection.md#unreadable-candidates)).

## Operations of a migrated test

A migrated suite does a handful of things thousands of times: click, send keys, check a property, wait for one and keep going
after an error. Each has a counterpart; the ones that read like the old call are in `wintestkit.finders`.

### Actions

| Existing call | WinTestKit |
|---|---|
| `Click()` | `el.click()` |
| `Click(x, y)`: a point relative to the element | `el.click(x=x, y=y)` (physical pixels from the top-left) |
| `-1` for an axis: the centre | `-1` means the centre of that axis in every offset: `el.click(x=-1, y=-1)`, `el.click(x=-1, y=4)` |
| `Click(-1, -1, Shift)`: with a modifier key | `el.click(x=-1, y=-1, modifiers="Shift")`; combinations are `"Ctrl+Shift"` |
| `Click(width - 320, 40)`: computed from the size | `el.click(x=el.width - 320, y=40)`; `el.height` and `el.rect` also exist |
| `DblClick(...)` / `ClickR(...)` | `el.double_click(x=, y=, modifiers=)` / `el.right_click(x=, y=, modifiers=)` |
| `ClickItem(name)` on a combo box | `combo.select("name")` (a name, a 0-based index or a regex) |
| `SetText(text)` | `textbox.type(text)`: replaces the text, through the Value pattern when possible |
| `Drag(x, y, dx, dy, Shift)` | `el.drag(x, y, dx, dy, modifiers="Shift")`: from the point by the delta; `-1` is the centre. `drag_to(target)` drags to another element |
| `MouseWheel(n)` | `el.scroll(n)` (`x=`, `y=` to choose the point; positive is up). Check the sign of the migrated calls once against the application |
| `Activate()` | `el.activate()` for the window that holds the element (a window node, a control) and `window.activate()` |
| `Close()` | `el.close()` / `window.close()`; the request is posted and the call returns, so wait for the window to go with `expect(win).not_.to_exist()` |
| `Refresh()` | `el.refresh()`: looks the element up again and returns it. Bound elements never cache, so this is rarely needed |

### Keys

`obj.Keys(text)` is `finders.send_keys(obj, text)` (an element or a window); the desktop form `Sys.Desktop.Keys(text)` is
`keyboard.keys(text)`, which sends to the foreground window of the application under test. Both take the same grammar:
`^` Ctrl, `!` Alt, `~` Shift before a key, `[Name]` for named keys (`[Enter]`, `[Del]`, `[BS]`, `[Tab]`, `[Down]`, `[Win]`, `[F1]`..`[F24]`...),
doubled `^ ! ~ [` for the literal character, `[Hold]` and `[Release]` for modifiers that stay down, and everything else typed as text.

| String | Sends |
|---|---|
| `[Enter]`, `[Tab]`, `[Down]`, `[F5]`, `[F11]`, `[Win]` | that key |
| `[Del]`, `[BS]` | Delete, Backspace |
| `^a`, `^c`, `^e`, `^i`, `^n`, `^o`, `^p`, `^s`, `^t`, `^v` | Ctrl and that letter |
| `^A` | the same as `^a` (Ctrl+A): a capital after a modifier is the same key; add `~` for Shift |
| `![Down]`, `![Right]`, `![F8]` | Alt and that key |
| `~[F4]` | Shift+F4 |
| `^[Del]`, `^[F4]`, `^[Right]`, `^[Left]`, `^[Up]`, `^[Down]` | Ctrl and that key |
| `[Hold]![F5]` | holds Alt, presses F5, releases Alt at the end of the string |
| `[Hold]^[Hold]![F8]` | holds Ctrl and Alt, presses F8, releases both at the end |
| `5`, `hello` | typed text |
| `hello[Enter]`, `^a[Del]new[Tab]`, `5[Tab]5[Tab]` | text and keys in order |

A modifier prefix applies to the next key only; `[Hold]` keeps modifiers down until `[Release]` or the end of the string, and
they are released even when sending fails. `[Hold]` may stand in front of the prefix (`[Hold]^`) or after it (`^[Hold]`).
`to_keys(text)` converts key-only strings to the `press()` form (`"Ctrl+Alt+F8"`) and a malformed string raises `ValueError`
before anything is sent.

### Checks

`finders.check_property(el, prop, condition, value, timeout=None, soft=False)` takes the property and condition names of
the old checks and runs them as an `expect` assertion, so a failure is a failed step with the property, the condition, the
expected and the actual value. It returns `True` when the check passed; a failure raises `AssertionError`, unless `soft=True`
(or the block is under `soft.continue_on_error()`), when it is recorded and `False` is returned. It waits like `expect` does
(`timeout=0` looks once).

| Old property | Read as |
|---|---|
| `WPFControlText` | `wpf:Text` on a WPF element; the UIA name on any other |
| `Exists` | `exists` (`False` passes for a missing element) |
| `VisibleOnScreen` | `visible_on_screen` |
| `IsEnabled`, `Enabled` | `clr:IsEnabled` on WPF; the UIA enabled state elsewhere |
| `IsVisible`, `Visible` | `clr:IsVisible` on WPF; on-screen visibility elsewhere |
| `IsChecked` | `clr:IsChecked` on WPF; the toggle state elsewhere |
| `Value` | `clr:Value` on WPF; the Value pattern elsewhere |
| `wText` | `text`: the element's text (value, document text or name) |
| `wItemList`, `wItemCount` | `item_list` (the items, one per line, for `contains`) and `item_count` |
| `ChildCount` | `child_count`: the children in the object tree |
| `WndCaption` | `name` |
| `WPFControlName`, `ControlId`, `WndClass`, `ClassName`, `FrameworkId`, `ClrClassName`... | the UIA property or `type:` key of the same meaning |
| `Count`, `Label`, `SeriesCount`, `DataContext.X` and every other name | the managed property `clr:<name>` (a path may be dotted) |
| `X.OleValue` | `X`: the wrapper is dropped |

`finders.map_property(name, wpf=True)` returns the name a property is read as. A name with a `:` (`clr:Header`) is used as it is.
Properties that only exist on a native control and that UI Automation does not expose cannot be read: `clr:` keys need a WPF
element and the inspector. For a non-WPF element only the names that are UIA properties (`HelpText`...) work.

| Old condition | WinTestKit `op` |
|---|---|
| `equal` | `"=="`; plain text, numbers and booleans are compared by value (`"True"` equals `True`, `"15"` equals 15) |
| `notEqual` | `"!="` |
| `contains` | `"contains"`: text in text, or a member of a list (`wItemList` is text: substrings) |
| `lessOrEqual`, `greaterOrEqual` | `"<="`, `">="`: numbers (also numeric text) numerically, other text alphabetically |

`expect(el).to_have_property(name, expected, op=...)` takes the new names directly (see
[property conditions](actions-and-assertions.md#property-conditions)); `check_property` is the migration form of it.

```python
# pseudo-code
from wintestkit.finders import check_property

check_property(page.orders, "wItemCount", "greaterOrEqual", 3)
check_property(page.title, "WPFControlText", "contains", "Orders")
check_property(page.total, "DataContext.Total.OleValue", "lessOrEqual", "100", soft=True)
check_property(page.dialog, "Exists", "equal", False)
```

### Waits

`finders.wait_property(el, prop, value, timeout_ms=None, condition="equal") -> bool` is `WaitProperty`: it waits until the
property meets the condition and returns `True`, or `False` when the time passed first (600 000 ms is fine). It never
raises for a timeout and uses the property names above. `wait_property(el, "Exists", False, 5000)` waits for the element to go
away, `"Exists", True` for it to appear, `"Enabled", True`, `"VisibleOnScreen", True`, `"Visible", True` and `"wItemCount", n`
for those states. A missing element is simply not there yet, except for `Exists` and `VisibleOnScreen`, which answer for it.
The step is in the report with `matched` and the last value seen. Prefer `expect` where the suite fails on `False` anyway.

```python
# pseudo-code
from wintestkit.finders import wait_property

if wait_property(page.progress, "Exists", True, 2000):
    wait_property(page.progress, "Exists", False, 600_000)
```

### Errors that do not stop the test

An existing suite that runs "on error: continue" logs an error and goes on. WinTestKit does the same, and fails the test when it ends:

| Existing | WinTestKit |
|---|---|
| a log-error call | `log.error(text, **details)`: recorded, the test continues, then fails with every error listed |
| a passed-check log entry | `log.checkpoint(text)` |
| a check that fails without stopping | `check_property(..., soft=True)` or `expect(el, soft=True)...` |
| the whole run "on error: continue" | `soft.continue_on_error()` for a block, `@pytest.mark.wtk(soft=True)` for a test or module (`pytestmark`) |

The failure message lists the errors, numbered, and the report shows each as an error entry next to the failed steps.
Only assertions are soft: a click or lookup that fails still raises, because what follows would not mean anything.
See [soft errors](actions-and-assertions.md#soft-errors).

## NameMapping importer

Run `wtk import-namemapping NameMapping.xml pages/imported.py`. The command reads the export
and generates an editable skeleton: a `Page` class per top-level window, with the window's `Window(...)`
and an `Element` for every mapped object below it, preserving the mapped parent relationships with
`within=`. It prints how many `# TODO` comments the output holds and writes warnings to stderr.
It does not yet convert OR groups; add `any_of` manually. It does not migrate actions or tests. Existing output is preserved; pass `--force` to replace it.

The export is an XML file whose root is `Root`. The importer reads these parts and ignores `Storages`:

- **Mapped objects** are the `Child` elements below `Nodes/Children`, nested through
  `Children/Child`. Each holds one `Properties` element of `Property Name` / `Value Value` pairs
  (the identifying value is the `Value` attribute); `Image` and `TypeInfo` are ignored. All
  properties of a node are combined with AND. `ExtendedFind="True"` searches all descendants
  (no `depth`); without it the node is a direct child (`depth=1`).
- **Values** follow `Type`: absent is a string, `0` an integer and `6` a boolean (`True`, in any case).
  `*` and `?` in a string are wildcards (compiled whole-value patterns); an empty string tests for empty text.
- **The top.** `Sys` is the system node and each `ProcessName` node below it a process; neither becomes
  an element. The process nodes name the applications (the generated module says which; with several
  processes each `Window` gets `process=`). The children of a process node are its top-level windows:
  `WndCaption` is the window's `title`, `WndClass` its `class_name`, `WinFormsControlName` its
  `automation_id`, and `RootVisual.ClrClassName`, `RootVisual.ClrFullClassName` and `RootVisual.Name` describe
  the WPF root visual (the class-name keys below, and the automation id). Everything under a window is an element.
- **Aliases** are the `Child` elements nested directly in `LogicalNodes Name="Aliases"`; `Owner` is the
  `Key` of a mapped node. Tests use the alias names, so the generated attributes and page classes are named by
  alias, falling back to the mapped name for a node without one. An alias may point at a descendant of
  its alias parent's node: aliases skip mapped levels, so the skipped nodes are declared under their mapped
  names and `within=` follows the mapped tree. A node with several aliases is named by the first. An alias
  whose `Owner` matches no node is skipped with a warning.
- **Unknown** elements and attributes, malformed values and duplicate keys give warnings, not failures.

`ObjectIdentifier` and `ObjectGroupIndex` have no WinTestKit equivalent and are emitted as `# TODO`
comments with their values; `FrameworkId`, `ClassName` and `LocalizedControlType` become UIA properties.

`WPFControlName` (and `RootVisual.Name`) becomes `automation_id` (verify the AutomationId or WPF x:Name fallback in Spy).
`ClrFullClassName` and `ClrClassName` are retained as corresponding `where` aliases by default. Configure
the managed alias described below when the inspector is enabled, or use
`property_aliases: {ClrFullClassName: ItemStatus}` only if the application exposes the full
name through UIA ItemStatus. Other properties use the same mapping as `to_locator`: text, ordinal, visible,
and enabled become corresponding locator fields or managed conditions (with `--managed-class-names`, text and
ordinal become `wpf:Text` and `wpf:Ordinal` and the element declares `tree="objects"`; otherwise they stay
the UIA `name` and a zero-based `index`); unknown valid names become
`clr:` paths; their plain string values are generated as `AsText(...)` so that `"15"` matches the integer 15. `*` and `?` become compiled whole-value patterns. Unmappable properties appear as
`# TODO` comments; an unmappable parent and its descendants require manual reconstruction.
Review and validate every generated locator against the live app before using it.

## Managed class names

With the [WPF backend](managed-inspection.md), use `wtk import-namemapping NameMapping.xml pages/imported.py --managed-class-names`
to generate qualified managed class-name keys and object-tree text and ordinal keys. Alternatively configure
`property_aliases: {ClrFullClassName: 'type:FullName', ClrClassName: 'type:Name'}` in `wintestkit.yaml`. Both require
authorized attachment. Confirm values in Spy; use the ItemStatus alias above as a fallback.

Input is limited to 10 MiB. DTD/entity declarations and malformed XML are rejected. This parser
does not execute XML or resolve external entities. It reads properties only from each mapped
object's own `Properties`, avoiding ancestor/descendant property duplication. Files in other
shapes (for example `Item` or `MappedObject` elements) are not recognised.

## A migrated test

A test routine that signs in and checks the welcome text becomes a page and a test function:

```python
# pseudo-code
def test_invalid_login(main: MainPage) -> None:
    main.sign_in_as("admin", "wrong")
    expect(main.status).to_have_text("Invalid credentials")
```

A data-driven loop over a table becomes a parametrized test:

```python
# pseudo-code
@pytest.mark.parametrize(
    ("username", "password", "message"),
    [
        ("admin", "secret", "Welcome, admin"),
        ("admin", "nope", "Invalid credentials"),
        ("guest", "secret", "Invalid credentials"),
        ("", "", "Invalid credentials"),
    ],
)
```

## Suggested order

1. Inventory windows and reusable boxes. Set `backend: auto` in shared `wintestkit.yaml`, put
   machine-specific paths in `wintestkit.local.yaml`, and run `wtk doctor`.
2. Import a starter with `wtk import-namemapping NameMapping.xml pages/imported.py --managed-class-names`.
   Inspect each window in Spy and split the skeleton into a `Page` per window and a component per
   movable box. Each component owns its `root`; mount it on multiple pages, using per-mount `root=`
   or `window=` overrides when necessary.
3. Open each relevant application state and run `wtk check pages/<window>.py`. Fix red results
   before migrating that page's tests. Relocation diagnostics search all windows and suggest moves;
   they never self-heal or change locators.
4. Rewrite repeated scripts as page/component intent methods and cross-window flows. Tests call
   those methods and use element paths only in `expect` assertions. Replace checkpoints with `expect`.
5. Repeat page by page. Compare with `backend: uia` where useful, but managed keys require
   `backend: auto` for WPF and cannot be compared directly under UIA. Run the suite and migrate CI
   to `wtk run` ([CI](ci.md)). Security software must allow the authorized agent attachment.
