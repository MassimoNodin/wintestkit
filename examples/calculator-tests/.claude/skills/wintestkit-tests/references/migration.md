# Migrating an existing suite

Input: a NameMapping (objects with identification properties, nested in a hierarchy), Aliases, and
scripts or test routines. Output: pages, components, flows, tests.

## Concept mapping

| Existing concept | WinTestKit |
|---|---|
| Drag and drop | `drag_to(target)` / `drag_by(dx, dy)` |
| Positioned or modified clicks | `click(x=..., y=..., modifiers=...)`, double/right/middle clicks |
| Wheel | `scroll(clicks, horizontal=False)` |
| Global keyboard input | `wintestkit.keyboard.press`, `type`, `hold`; app window must own foreground |
| Menu paths | `Menu.click_path` / `element.open_context_menu().click_path` |
| Tree paths | `TreeView.select`, `expand`, `collapse`, `items(path)` |
| Multi-select | `ListBox` / `DataGrid.select([...], add=...)`, `deselect`, `clear_selection` |
| Window position, size, activation | `move`, `resize`, `rect`, `activate`, `is_active` |
| Grid checkpoints | `expect(grid).to_have_rows(...)` |
| Other controls | `Slider`, `ScrollBar`, `ProgressBar`, `DatePicker`, `Expander`, `ToggleButton`, `Hyperlink`, `ToolBar`, `StatusBar` |
| Project / project suite | a folder with `pyproject.toml` containing `[tool.wintestkit]` |
| Tested Application | `[tool.wintestkit.app]` (`path`, `args`, `cwd`, `env`, `process`) and `launch` mode |
| A window node in NameMapping | one `Page` with `window = Window(...)` |
| A user control / group / region node, or a box used in several windows | one component (`Page` with `root`), mounted per use |
| A leaf (button, edit, ...) | a typed element on the page or component |
| Alias | the attribute name (`customer.address.street`) |
| `WPFControlName` | `automation_id` (peer or peerless attached ID, or `x:Name` when empty with `backend: auto`) |
| `ClrFullClassName` | `where={"type:FullName": ...}`; `type:Is` includes derived types |
| `WPFControlText` | `where={"wpf:Text": ...}` with `tree="objects"`: the text the element shows (not the peer Name) |
| `Content`, `Caption` | `name` |
| Conditional mapping (OR groups) | `any_of=[...]` |
| Required child objects | `has=Element(...)` |
| `WPFControlOrdinalNo` | `where={"wpf:Ordinal": n}` with `tree="objects"`: 1-based position among same-type siblings (not a global `index`) |
| mapped parent chain | the component root; never a `within=` chain |
| script routine / reusable test routine | an intent method on the page or component, or a flow |
| test or test routine | a pytest function using intent + `expect` |
| checkpoint | `expect(...)`; with an old property and condition name `finders.check_property(el, prop, condition, value)` |
| log an error and continue ("on error: continue") | `log.error(text)`; `soft=True` on `expect` / `check_property`; `soft.continue_on_error()`; `@pytest.mark.wtk(soft=True)` |
| `Click(-1, -1, Shift)`, `Click(width - 320, 40)` | `el.click(x=-1, y=-1, modifiers="Shift")`, `el.click(x=el.width - 320, y=40)`; `-1` is the centre of an axis |
| `Drag(x, y, dx, dy, Shift)`, `MouseWheel(n)` | `el.drag(x, y, dx, dy, modifiers="Shift")`, `el.scroll(n)` |
| `Keys(text)`, `Sys.Desktop.Keys(text)` | `finders.send_keys(el, text)`, `keyboard.keys(text)` (`[Hold]` before or after a prefix works) |
| `Activate()`, `Close()`, `Refresh()` | `el.activate()`, `el.close()`, `el.refresh()` |
| Reading object properties (e.g. `obj.DataContext.Name`) | `el.get("clr:DataContext.Name")`; indexers work: `clr:Rows[3].Value` (`Items.Item[0]` means `Items[0]`) |
| Native members of a WinForms control (an int `SeriesCount`, a nested `Footer.Text`) | `el.get("clr:SeriesCount")`, `el.get("clr:Footer.Text")`, `where={"clr:SeriesCount": 3}`: UIA finds the control, the agent reads it (also inside a `WindowsFormsHost`); `WinFormsControlName` stays `automation_id` (the control's `Name`), `ClrClassName` is `type:Name` |
| `<path>.ClrClassName` / `.ClrFullClassName` | `type:Name@DataContext` / `type:FullName@DataContext`: the type of the value at the path |
| Numbers/booleans passed as strings | `AsText("15")` compares a managed value's invariant text; `find_child` applies it to plain strings on property paths |
| `WaitProperty(prop, value, timeout_ms)` | `finders.wait_property(el, prop, value, timeout_ms)`: returns `True`/`False`, never raises (`Exists` `False` waits for disappearance); `el.wait_for_property(name, expected)` raises on timeout |
| `Delay`, `Sleep`, `WaitChild` | use `expect` or `wait_for()` for the required state; actions wait for existence by default; a plain `Delay(ms)` is `time.sleep(ms / 1000)` |
| data-driven loop / table / data dictionary | `@pytest.mark.parametrize` |
| project variables (a Boolean) | configuration, an environment variable or a pytest option read by a fixture |
| the clipboard text | `clipboard.get_text()` / `set_text(text)` / `clear()` |
| another application in the same test | `apps.launch(path, args=[...])` / `apps.attach("x.exe")` and a page per `App` |
| elevated launch | `App.launch(path, elevated=True)` or `app.elevated` in the configuration (needs an elevated runner to drive it) |
| `Sys.Process(name)`, `Sys.WaitProcess(name, ms)` | `finders.process(name)`, `finders.wait_process(name, ms)` (or `finders.Sys.Process(...)`) |
| close with Alt+F4, answer a prompt, wait, force-kill | `app.request_close("alt_f4")`, `app.close_gracefully(on_prompt=fn, kill=True)`, `app.kill()` |
| `OnUnexpectedWindow` and other event handlers | fixtures; for known dialogs, a page plus a flow step |
| test items / execution plan | files, folders and markers (`wtk run -m smoke`) |
| Command-line runner | `wtk run` / `pytest` |

## ClrFullClassName

Use `where={"type:FullName": "Acme.Views.AddressBox"}` to preserve the namespace, or
`type:Is` to include derived types. With `backend: auto`, WPF uses the managed tree; qualified
keys fail under `backend: uia`. Confirm paths in Spy and never put secrets in `where`.
Use `wtk import-namemapping NameMapping.xml pages/imported.py --managed-class-names` for
managed class-name keys in generated skeletons. The importer reads the real export (mapped objects under
`Nodes`, `Property`/`Value Value` pairs typed by `Type`, aliases under `LogicalNodes`) and writes a `Page`
per top-level window whose elements are named by alias; `# TODO` comments mark what it could not map
(`ObjectIdentifier`, `ObjectGroupIndex`). An alias may skip mapped levels: the skipped nodes keep their
mapped names, so keep only the containers that are boxes when you split the skeleton into components.

## Object labels (`WPFObject`, `Window`)

Ported code and Spy labels share one grammar; use it where a chain is shorter than a locator (one grid cell, one popup item):

    from wintestkit.finders import from_label, window, wpf_object   # also .wpf_object/.window and .WPFObject/.Window methods

    root = app.WPFObject("HwndSource: MainView", "Orders*").WPFObject("MainView", "Orders*")  # window node, then its root visual
    cell = root.WPFObject("DataGrid", "").WPFObject("DataGridRow", "", 2).WPFObject("DataGridCell", "*", 1)
    item = app.WPFObject("HwndSource: PopupRoot", "").WPFObject("PopupRoot", "").WPFObject("ComboBoxItem", "Two")
    edit = app.Window("#32770", "Save As").Window("Edit", "", 1)
    same = from_label(app, 'Process("x.exe").WPFObject("HwndSource: MainView", "Orders*")')

- `WPFObject(name)` is the x:Name of a direct object-tree child. `WPFObject(cls, text, index)`: `cls` is the runtime
  type name; with `index` (1-based, `wpf:Ordinal`) it is the index-th child of that type and the text is checked unless `""` or `"*"`;
  without it the first child of that type whose text matches (`"*"` any, `""` empty, `*`/`?` wildcards). `WPFObject(cls, 2)` is `(cls, "", 2)`.
- `"HwndSource: X"` as `cls` is a window node (selected from an `App`; `X` is the root visual's x:Name, else its type, and a
  step may use either spelling; text is the title; index among window nodes with that label; popups are `HwndSource: PopupRoot`);
  its only child is the root visual.
- `Window(cls, caption, index)` is a Win32 child window (top-level from an `App`): class, caption (mnemonic `&` removed,
  wildcards, `"*"` default) and 1-based index among same-class siblings; the caption is checked too unless `""`/`"*"`. UIA, not the managed tree.
- Results are lazy elements; not-found errors list the type-matching siblings with texts and ordinals. `strict=True` fails on several matches.
- `find_child(parent, "Name", 'WPFObject("Button", "OK", 2)', depth)` matches any object within `depth` by its label step.
- `el.parent`, `el.children()`, `el.child_count`, `el.label` (only the arguments needed to tell siblings apart) and `el.full_name`
  (`Process("x").WPFObject(...)...`, parsed back by `from_label`) walk the tree. A syntax error in a label string names its position.

## Procedure

1. **Inventory.** List the windows (top-level nodes) and, for each, the boxes. A box is a component
   if it appears in more than one window, is likely to be moved, repeats in a window, or is a
   user control. Note which windows are dialogs.
2. **Environment.** `wtk init --app C:/path/App.exe`, set `launch`, `wtk doctor`.
3. **Per window.** Open the window in the running app. Run `wtk inspect --depth 8` and `wtk spy`
   to read the WPF tree. Create `pages/<window>.py` with the `Page` and its `window`.
4. **Per box.** Create `pages/components/<box>.py`: `root` from the box's mapping node (with the
   properties Spy actually shows), members from its leaves with typed elements. Mount it on the
   page(s). Do not keep intermediate container nodes; keep a container only when it is a box.
5. **Green per page.** `wtk check pages/<window>.py` with the window open. Fix every red line by
   comparing with the closest candidates in the message. Do not migrate tests until this page is
   green. Re-run `wtk check` for states that expose more controls (open pane, expanded panel).
6. **Intent methods.** Translate each script routine or repeated sequence into a method with a
   user-level name on the page or component, taking the data it needs as parameters.
7. **Flows.** Navigation that opens a window or crosses pages becomes a function in `flows/`
   that takes `app` and returns the destination page, waiting with `expect`.
8. **Tests.** One pytest function per scenario; calls intent methods and flows; assertions are
   `expect(...)`. Loops over data become `parametrize`; setup/teardown becomes fixtures.
9. **Run.** `wtk run tests/test_<window>.py`, then move to the next window. Finally switch CI to
   `wtk run`.
10. **Finish.** Run the pre-finish checklist in SKILL.md.

## Find helpers and imported mappings

Use `find_child(parent, props, values, depth=1)` for a lazy first match,
`find_all_children(parent, props, values, depth=1)` for a snapshot, and
`find(parent, props, values, depth=...)` for descendant searches. Use `strict=True` on
`find_child` when ambiguity should fail. Property names use the shared existing mapping;
`*` and `?` are whole-value wildcards. On WPF windows the helpers search the object tree (`tree="objects"`): depth
counts its levels (from an `App`, 1 is window nodes and 2 root visuals; from a window, 1 is its root visual), the
first match is the pre-order one, `WPFControlText` is `wpf:Text` and `WPFControlOrdinalNo` is `wpf:Ordinal`. Other
windows keep UIA (`name`, zero-based global `index`, peer levels). Verify AutomationId and text in Spy.

The importer does not yet convert OR groups; add `any_of` manually. Actions default to
`actionability: exists`: disabled or hidden, unscrollable elements fail immediately. Use
`expect(x).to_be_enabled()` or `actionability: strict` to wait for enabled and visible.

The importer emits parent-scoped `Element` declarations with `within=` and `depth=1`, or
unlimited/default depth for extended find. It assumes nested mapped items and accepts either
an `extendedFind="True"` attribute or an `ExtendedFind` property. Unmappable properties and
unmappable parent chains are marked `# TODO`; review them before use. Full managed class names
are emitted as qualified keys with `--managed-class-names`, which also emits `tree="objects"`, `wpf:Text` and
`wpf:Ordinal`; review the generated skeleton.

## Things that differ

- Strict matching: an existing mapping may resolve to the first of several matches; WinTestKit fails.
  Expect to add roots or properties while migrating.
- WPF uses the managed tree under `backend: auto`; other windows use UIA, and a WinForms control is read or matched by the agent only when a `clr:`/`type:`/`field:`/`wpf:` key asks for it. There is no image or OCR recognition.
- Mouse input is the default for clicks; use `click(mode="pattern")` for automation patterns.
- There is no recorder: use the Spy and write Python.

First-match finders warn on ambiguity; add identifying properties, narrow the scope, or use `strict=True`. Explicit ordinals suppress the warning. Use `wintestkit.finders.send_keys(target, text)` for mixed key strings and `to_keys(text)` to convert key-only strings to `press()` syntax.
