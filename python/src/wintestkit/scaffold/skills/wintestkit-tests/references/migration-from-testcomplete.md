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
| `ClrFullClassName` | `where={"ClrFullClassName": ...}` with a configured UIA alias; see below |
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

**Preview:** If the repository enables the inspector and attachment is authorized, prefer
`wtk import-namemapping NameMapping.xml pages/imported.py --managed-class-names`, or configure
`property_aliases: {ClrFullClassName: 'type:FullName'}`. Verify the key and value in Spy;
never invent managed paths or put secrets in `where`. Prefer UIA when sufficient. The
following ItemStatus approach is the fallback when managed inspection is unavailable.

Do not translate a full .NET name directly to `class_name=`: UIA `ClassName` is commonly only a
short name. Preserve namespace identity by exposing the full name in an existing UIA property
(for example `ItemStatus` in a test build), then configure:

```yaml
property_aliases:
  ClrFullClassName: ItemStatus
```

Declare `Element(where={"ClrFullClassName": "Acme.Views.AddressBox"})`, or use a compiled regex
for a pattern. This fallback alias renames a UIA property; it does not read .NET properties.
Verify the value in Spy or `wtk inspect` before migrating. If the application cannot expose it,
use a verified short `class_name` and scope to a distinct component/container; never silently drop
the namespace or add an index to hide ambiguity.

## Procedure

1. **Inventory.** List the windows (top-level nodes) and, for each, the boxes. A box is a component
   if it appears in more than one window, is likely to be moved, repeats in a window, or is a
   user control. Note which windows are dialogs.
2. **Environment.** `wtk init --app C:/path/App.exe`, set `launch`, `wtk doctor`.
3. **Per window.** Open the window in the running app. Run `wtk inspect --depth 8` and `wtk spy`
   to read the real UIA tree. Create `pages/<window>.py` with the `Page` and its `window`.
4. **Per box.** Create `pages/components/<box>.py`: `root` from the box's mapping node (with the
   properties UIA really exposes), members from its leaves with typed elements. Mount it on the
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

## Things that differ

- Strict matching: TestComplete may resolve to the first of several matches; WinTestKit fails.
  Expect to add roots or properties while migrating.
- UI Automation only: no image or OCR recognition.
- Pattern input is the default for clicks and typing; mouse input only when the app needs real
  mouse events (`click(mode="mouse")`).
- There is no recorder: use the Spy and write Python.
