# Match properties

Use `where` on `Element`, typed elements, `Elements` and `Window`. All conditions must
match, together with the other locator fields. On WPF, managed paths search the WPF tree
directly, including peerless objects. Use Spy to inspect paths and values before matching.

```python
# pseudo-code
import re
from wintestkit import Element, Window

window = Window(where={"type:FullName": "Company.Views.OrdersWindow"})
address = Element(where={"type:FullName": "Company.Controls.AddressBox"})
ready = Element(where={"clr:DataContext.Status": "Ready", "clr:IsEnabled": True})
order = Element(where={"clr:DataContext.Number": re.compile(r"^ORD-")})
```

Pass `tree="objects"` to any `Element`, `Elements` or typed element to search the migration
[object tree](managed-inspection.md#the-object-tree) instead of the UIA-shaped one, and the keys
`wpf:Text` (the element's text) and `wpf:Ordinal` (its same-type position among siblings, 1-based)
to match on it:

```python
# pseudo-code
save = Element(tree="objects", depth=3, where={"wpf:Text": "Save", "type:Name": "Button"})
second = Element(tree="objects", where={"type:Name": "Button", "wpf:Ordinal": 2})
```

With it, `depth`, the first match and `index` follow that tree. It needs a WPF window; elsewhere
the locator fails with a clear error.

Strings match exactly; compiled regular expressions use `re.search`. Use actual booleans
and numbers for scalar values: managed values are exactly typed, so `"15"` does not match
the integer 15. `AsText("15")` compares the value's invariant text instead (`15`, `"True"`
for a boolean), which suits migrated suites that pass numbers and booleans as strings.
Paths can index (`clr:DataContext.Rows[3].Value`), and `type:Name@DataContext` matches the
runtime type of a nested value. `type:Is` matches the named full type or a derived type.
Managed paths can read application getters: see [security and path syntax](managed-inspection.md#managed-locators).
Managed conditions require a WPF window with `backend: auto`; `backend: uia` and non-WPF
windows reject them. UIA properties such as `HelpText`, `ItemStatus` and `IsEnabled` are
also available where the backend exposes them. `class_name` is a short peer class name,
not the full CLR type. Do not place secrets in locators.

## Property-name find helpers

`wintestkit.finders` provides `to_locator`, `find_child`, `find_all_children` and
`find`. `ClrFullClassName` maps to `type:FullName`, `ClrClassName` to `type:Name`, `WPFControlName` to `automation_id`,
and other property paths such as `DataContext.Status` to managed properties. A path ending in
`.ClrClassName` or `.ClrFullClassName` (for example `DataContext.ClrClassName`) matches the type
of the value at that path (`type:Name@DataContext`). Paths accept indexers such as
`Items.Item[0].Name` (the .NET `Item[n]` spelling) or `Rows[3].Value`. The helper
accepts `*` and `?` wildcards; ordinary `where` strings are exact. A plain string given for
a managed property path is compared with `AsText`, so `"15"` matches the integer 15 and
`"True"` the boolean true; a wildcard string stays a pattern, which only matches string values. With `backend: auto`,
`automation_id` uses the peer AutomationId, or the attached AutomationId for peerless elements, then falls back to `x:Name` when empty. UIA-only matching uses the provider's ID.

```python
# pseudo-code
from wintestkit.finders import find, find_all_children, find_child, to_locator

locator = to_locator("ClrFullClassName", "Company.Controls.*")
button = find_child(page, "WPFControlName", "Save*", depth=20, strict=True)
matches = find_all_children(page, "DataContext.Status", "Ready", depth=20)
parent_or_child = find(page.editor, "WPFControlName", "Editor", depth=1)
```

A trailing `.OleValue` is removed from migration property paths. `VisibleOnScreen` matches the same on-screen state as `is_visible()`, while `Visible` matches WPF `IsVisible`. `Exists=True` adds no condition; `Exists=False` is invalid for a finder.

Supply your own bound `page` or an `App`. An App search includes every top-level window at depth 1 and searches their descendants at greater depths, routing each window to its appropriate backend. `find_child` defaults to the first match; `strict=True`
requires one. `find_all_children` returns indexed, re-resolving elements, so later tree
reordering can change their identities. On WPF windows the helpers search the
[object tree](managed-inspection.md#the-object-tree): depth counts its levels, the first match is the
pre-order one, `WPFControlText` is the element's text (`wpf:Text`, not the peer Name) and
`WPFControlOrdinalNo` is its 1-based position among siblings of the same type (`wpf:Ordinal`).
Other windows (Win32 dialogs, UIA-only matching) keep the UIA tree: there `WPFControlText` is the
UIA Name, an ordinal is a zero-based index over all matches, and depth counts peer levels. The
[migration guide](migrating-existing-suites.md) covers the NameMapping importer and
helper semantics.

Lazy first-match finders warn in the report and pytest when multiple elements match. Add identifying properties or scope, or use `strict=True`; an explicit `WPFControlOrdinalNo` suppresses the warning.


## Property aliases

Shared `property_aliases` can rename a UIA property or a qualified managed key. For example:

```yaml
property_aliases:
  OrderStatus: clr:DataContext.Status
```

Then `Element(where={"OrderStatus": "Ready"})` uses that path. Aliases merge across
configuration layers; later definitions win. They cannot shadow real UIA properties or
form alias chains. See [configuration](running-tests.md#configuration).
