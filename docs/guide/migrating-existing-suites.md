# Migrating an existing suite

This guide helps you migrate an existing **WPF desktop test suite** to WinTestKit, Python and pytest.

## Concept mapping

| Existing concept | WinTestKit |
|---|---|
| Project suite / project | A folder with `pyproject.toml` containing `[tool.wintestkit]` |
| Tested Applications | `[tool.wintestkit.app]` (`path`, `args`, `cwd`, `env`) and the launch mode |
| Name mapping and aliases | A `Page` per window and reusable `Page` components per movable box; page and component attributes name the controls |
| Key strings with `^`, `!`, `~` and `[Enter]` | `wintestkit.finders.send_keys` / `to_keys` |
| Drag and drop | `element.drag_to(target)` / `drag_by(dx, dy)` |
| Positioned or modified mouse clicks | `click(x=..., y=..., modifiers=...)` and corresponding double/right/middle clicks |
| Mouse wheel | `element.scroll(clicks, horizontal=False)` |
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
| `WaitProperty` | `el.wait_for_property(name, expected)` |
| Inspecting objects | The Spy (`wtk spy` or the VS Code Spy view) and `wtk inspect` |
| Highlight on screen | `wtk highlight` or the **Highlight** CodeLens |
| Test routines / script routines | pytest test functions |
| Property checkpoints and region checks | `expect(...)` assertions |
| Property and child waits | Automatic waiting in actions and `expect`; `wait_for()`, `exists()` |
| Auto-wait timeout | `timeout` setting, per-element `timeout=`, per-call `timeout=` |
| Event handlers (`OnUnexpectedWindow`, …) | pytest fixtures (setup and teardown) |
| Test items / execution plan | Test files, folders and pytest markers (`wtk run -m smoke`) |
| Data-driven loops | `@pytest.mark.parametrize` |
| Command-line runner | `wtk run` (or `pytest`) |
| Test log messages, warnings and pictures | `log.message`, `log.warning`, `log.picture` |
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
- **Depth** counts levels of that tree. From an `App`, depth 1 is the window nodes (`HwndSource: <type>`,
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
WPF window of the application whose root visual's short type name is `X`, with the window title as its text (wildcards
allowed) and the index among window nodes of the same type. Window nodes are selected from an `App`; popups are window
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
