# Migrating from TestComplete

WinTestKit covers the part of TestComplete used for **WPF desktop testing**, with Python and
pytest instead of a proprietary IDE and project format.

## Concept mapping

| TestComplete | WinTestKit |
|---|---|
| Project suite / project | A folder with `pyproject.toml` containing `[tool.wintestkit]` |
| Tested Applications | `[tool.wintestkit.app]` (`path`, `args`, `cwd`, `env`) and the launch mode |
| NameMapping | `Page` classes with `Element` attributes |
| Aliases | Page attribute names (`main.sign_in`) |
| Mapping criteria (properties) | `automation_id`, `name`, `control_type`, `class_name`, `index` |
| Mapped object hierarchy | `within=` |
| Conditional / extended find | Regular expressions in `name=` and friends, `Elements(...).filter()` |
| Object Spy / Object Browser | The Spy (`wtk spy` or the VS Code Spy view) and `wtk inspect` |
| Highlight on screen | `wtk highlight` or the **Highlight** CodeLens |
| Keyword tests / script routines | pytest test functions |
| Checkpoints (property, region) | `expect(...)` assertions |
| `WaitProperty`, `WaitChild`, `Exists` | Automatic waiting in actions and `expect`; `wait_for()`, `exists()` |
| Auto-wait timeout | `timeout` setting, per-element `timeout=`, per-call `timeout=` |
| Event handlers (`OnUnexpectedWindow`, …) | pytest fixtures (setup and teardown) |
| Test items / execution plan | Test files, folders and pytest markers (`wtk run -m smoke`) |
| Data-driven loops | `@pytest.mark.parametrize` |
| TestExecute / command-line runs | `wtk run` (or `pytest`) |
| Test log | The HTML report (`wtk-report/index.html`) and JUnit XML |
| Visualizer screenshots | `screenshots = "on-failure"` or `"every-step"` |

## What's different

- **Strict matching.** A mapped object in TestComplete may silently resolve to the first of several
  matches. WinTestKit fails when a locator matches more than one element, so ambiguous mappings
  surface at the line that is wrong. Expect to add `within=` scopes while migrating.
- **UI Automation discovery.** There is no image-based or OCR recognition. Controls a screen reader can't
  see cannot be found by the UIA backend. The WPF backend can find peerless elements.
- **No recorder.** Use the Spy to build pages and write tests in Python; the editor
  completes element names from your pages.
- **Code review and version control.** Pages and tests are plain Python files that diff, review
  and merge like any other code.

## Migrating FindChild

The originals below are TestComplete JavaScript-style calls; `p` is the fixture page and
`group` is its mapped group. The WinTestKit examples use `page` and `page.group`.
Import `find_child`, `find_all_children`, and `find` from `wintestkit.testcomplete`.

| TestComplete call | WinTestKit call |
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
`WPFControlOrdinalNo` is one-based and maps to a zero-based index over matches.
`find_all_children` returns indexed, re-resolving results: later tree reordering can
change their identities. `find` includes a bound parent, but rootless pages and scopes
start at the window descendants and cannot include the window itself. Managed properties
require inspector access, and UIA cannot discover elements without automation peers.
The NameMapping extended-find XML spellings accepted below are unconfirmed.

## NameMapping importer

Run `wtk import-namemapping NameMapping.xml pages/imported.py`. The command generates an editable
`Page` skeleton, preserving mapped parent relationships with `within=`. Direct searches use
`depth=1`; extended searches use the default descendant depth. It assumes children are nested
`Item`, `Node`, or `MappedObject` elements (possibly inside containers), and accepts the
unverified flag forms `extendedFind="True"` on the object or an `ExtendedFind` property.
It does not migrate actions or tests. Existing output is preserved; pass `--force` to replace it.

`WPFControlName` becomes `automation_id` (verify that it is exposed as UIA AutomationId in Spy).
`ClrFullClassName` is retained as `where={"ClrFullClassName": ...}`. Configure
the managed alias described below when the inspector is enabled, or use
`property_aliases: {ClrFullClassName: ItemStatus}` only if the application exposes the full
name through UIA ItemStatus. Other properties use the same mapping as `to_locator`: text, short class name, ordinal, visible,
and enabled become corresponding locator fields or managed conditions; unknown valid names become
`clr:` paths. `*` and `?` become compiled whole-value patterns. Unmappable properties appear as
`# TODO` comments; an unmappable parent and its descendants require manual reconstruction.
Review and validate every generated locator against the live app before using it.

## Managed class names

With the [WPF backend](managed-inspection.md), use `wtk import-namemapping NameMapping.xml pages/imported.py --managed-class-names`
to generate qualified managed class-name keys. Alternatively configure
`property_aliases: {ClrFullClassName: 'type:FullName'}` in `wintestkit.yaml`. Both require
authorized attachment. Confirm values in Spy; use the ItemStatus alias above as a fallback.

Input is limited to 10 MiB. DTD/entity declarations and malformed XML are rejected. This parser
does not execute XML or resolve external entities. It reads properties only from each mapped
object's direct `Properties` collection, avoiding ancestor/descendant property duplication.

## A migrated test

A keyword test that signs in and checks the welcome text becomes a page and a test function:

```python
# pseudo-code
def test_invalid_login(main: MainPage) -> None:
    main.username.type("admin")
    main.password.type("wrong")
    main.sign_in.click()
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

1. Configure shared settings in `wintestkit.yaml` and the application path in
   `wintestkit.local.yaml`, then check the machine with `wtk doctor`.
2. Translate the NameMapping for one window into a `Page` (or generate a starter skeleton with
   `wtk import-namemapping`), using the Spy to confirm each locator. Run **Check All Elements**
   in VS Code (or `wtk check`) until it is green.
3. Move the tests that use that window, replacing checkpoints with `expect` and removing explicit
   waits.
4. Repeat per window, then switch CI from TestExecute to `wtk run` ([CI](ci.md)).
