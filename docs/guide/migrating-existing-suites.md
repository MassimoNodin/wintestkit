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
| `WPFControlText` | `name` (peer Name, not necessarily actual text) |
| `Visible` / `Enabled` | `clr:IsVisible` / `clr:IsEnabled` via helpers or `where` |
| `ObjectIdentifier` | No direct equivalent: inspect and choose stable properties, not an invented ID |
| Conditional mapping (OR groups) | `any_of=[...]` |
| Required child objects | `has=Element(...)` |
| Wildcards | Helpers translate `*` and `?` to whole-value patterns; locators accept compiled regexes |
| Extended find / depth | `depth` (automation-peer levels); extended find uses descendant search |
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

First-match finders warn on ambiguity in the report and pytest; use identifying properties, scope, or `strict=True` instead. Explicit ordinals suppress the warning.


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
automation-peer levels, not arbitrary WPF visual-tree levels; `None` means unlimited.
`WPFControlText` matches the peer Name, which need not be the actual control text.
`WPFControlOrdinalNo` accepts integers or numeric strings and is one-based and maps to a zero-based index over matches.
`find_all_children` returns indexed, re-resolving results: later tree reordering can
change their identities. `find` includes a bound parent, but rootless pages and scopes
start at the window descendants and cannot include the window itself. Managed properties
require inspector access, and UIA cannot discover elements without automation peers.
An `App` parent searches all top-level windows and their descendants; depth 1 includes the windows. Window titles accept wildcards. `Exists=True` adds no condition and `Exists=False` raises an error. A trailing `.OleValue` is stripped from property paths. The NameMapping extended-find XML spellings accepted below are unconfirmed.

## NameMapping importer

Run `wtk import-namemapping NameMapping.xml pages/imported.py`. The command generates an editable
`Page` skeleton, preserving mapped parent relationships with `within=`. Direct searches use
`depth=1`; extended searches use the default descendant depth. It assumes children are nested
`Item`, `Node`, or `MappedObject` elements (possibly inside containers), and accepts the
unverified flag forms `extendedFind="True"` on the object or an `ExtendedFind` property.
It does not yet convert OR groups; add `any_of` manually. It does not migrate actions or tests. Existing output is preserved; pass `--force` to replace it.

`WPFControlName` becomes `automation_id` (verify the AutomationId or WPF x:Name fallback in Spy).
`ClrFullClassName` and `ClrClassName` are retained as corresponding `where` aliases by default. Configure
the managed alias described below when the inspector is enabled, or use
`property_aliases: {ClrFullClassName: ItemStatus}` only if the application exposes the full
name through UIA ItemStatus. Other properties use the same mapping as `to_locator`: text, ordinal, visible,
and enabled become corresponding locator fields or managed conditions; unknown valid names become
`clr:` paths; their plain string values are generated as `AsText(...)` so that `"15"` matches the integer 15. `*` and `?` become compiled whole-value patterns. Unmappable properties appear as
`# TODO` comments; an unmappable parent and its descendants require manual reconstruction.
Review and validate every generated locator against the live app before using it.

## Managed class names

With the [WPF backend](managed-inspection.md), use `wtk import-namemapping NameMapping.xml pages/imported.py --managed-class-names`
to generate qualified managed class-name keys. Alternatively configure
`property_aliases: {ClrFullClassName: 'type:FullName', ClrClassName: 'type:Name'}` in `wintestkit.yaml`. Both require
authorized attachment. Confirm values in Spy; use the ItemStatus alias above as a fallback.

Input is limited to 10 MiB. DTD/entity declarations and malformed XML are rejected. This parser
does not execute XML or resolve external entities. It reads properties only from each mapped
object's direct `Properties` collection, avoiding ancestor/descendant property duplication.

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
