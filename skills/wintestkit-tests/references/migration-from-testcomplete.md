# Migrating from TestComplete

Input: a NameMapping (objects with identification properties, nested in a hierarchy), Aliases, and
scripts or keyword tests. Output: pages, components, flows, tests.

## Concept mapping

| TestComplete | WinTestKit |
|---|---|
| Project / project suite | a folder with `pyproject.toml` containing `[tool.wintestkit]` |
| Tested Application | `[tool.wintestkit.app]` (`path`, `args`, `cwd`, `env`, `process`) and `launch` mode |
| A window node in NameMapping | one `Page` with `window = Window(...)` |
| A user control / group / region node, or a box used in several windows | one component (`Page` with `root`), mounted per use |
| A leaf (button, edit, ...) | a typed element on the page or component |
| Alias | the attribute name (`customer.address.street`) |
| `WPFControlName` | `automation_id` (usually; verify in Spy) |
| `ClrFullClassName` | `where={"type:FullName": ...}`; `type:Is` includes derived types |
| `WPFControlText`, `Content`, `Caption` | `name` |
| ordinal number | `index` (0-based; avoid) |
| mapped parent chain | the component root; never a `within=` chain |
| script routine / reusable keyword test | an intent method on the page or component, or a flow |
| test or keyword test | a pytest function using intent + `expect` |
| checkpoint | `expect(...)` |
| `Delay`, `Sleep`, `WaitProperty`, `WaitChild` | nothing (actions and `expect` wait) or `wait_for()` / `exists(timeout=)` |
| data-driven loop / table | `@pytest.mark.parametrize` |
| `OnUnexpectedWindow` and other event handlers | fixtures; for known dialogs, a page plus a flow step |
| test items / execution plan | files, folders and markers (`wtk run -m smoke`) |
| TestExecute | `wtk run` / `pytest` |

## ClrFullClassName

Use `where={"type:FullName": "Acme.Views.AddressBox"}` to preserve the namespace, or
`type:Is` to include derived types. With `backend: auto`, WPF uses the managed tree; qualified
keys fail under `backend: uia`. Confirm paths in Spy and never put secrets in `where`.
Use `wtk import-namemapping NameMapping.xml pages/imported.py --managed-class-names` for
managed class-name keys in generated skeletons.

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
`find_child` when ambiguity should fail. Property names use the shared TestComplete mapping;
`*` and `?` are whole-value wildcards. Depth counts WPF automation-peer levels, which can
differ from TestComplete's visual tree. Verify AutomationId and text in Spy.

The importer emits parent-scoped `Element` declarations with `within=` and `depth=1`, or
unlimited/default depth for extended find. It assumes nested mapped items and accepts either
an `extendedFind="True"` attribute or an `ExtendedFind` property. Unmappable properties and
unmappable parent chains are marked `# TODO`; review them before use. Full managed class names
are emitted as qualified keys with `--managed-class-names`; review the generated skeleton.

## Things that differ

- Strict matching: TestComplete may resolve to the first of several matches; WinTestKit fails.
  Expect to add roots or properties while migrating.
- WPF uses the managed tree under `backend: auto`; other windows use UIA. There is no image or OCR recognition.
- Pattern input is the default for clicks and typing; mouse input only when the app needs real
  mouse events (`click(mode="mouse")`).
- There is no recorder: use the Spy and write Python.
