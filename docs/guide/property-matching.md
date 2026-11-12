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

Strings match exactly; compiled regular expressions use `re.search`. Use actual booleans
and numbers for scalar values. `type:Is` matches the named full type or a derived type.
Managed paths can read application getters: see [security and path syntax](managed-inspection.md#managed-locators).
Managed conditions require a WPF window with `backend: auto`; `backend: uia` and non-WPF
windows reject them. UIA properties such as `HelpText`, `ItemStatus` and `IsEnabled` are
also available where the backend exposes them. `class_name` is a short peer class name,
not the full CLR type. Do not place secrets in locators.

## TestComplete helpers

`wintestkit.testcomplete` provides `to_locator`, `find_child`, `find_all_children` and
`find`. `ClrFullClassName` maps to `type:FullName`, `WPFControlName` to `automation_id`,
and other property paths such as `DataContext.Status` to managed properties. The helper
accepts `*` and `?` wildcards; ordinary `where` strings are exact.

```python
# pseudo-code
from wintestkit.testcomplete import find, find_all_children, find_child, to_locator

locator = to_locator("ClrFullClassName", "Company.Controls.*")
button = find_child(page, "WPFControlName", "Save*", depth=20, strict=True)
matches = find_all_children(page, "DataContext.Status", "Ready", depth=20)
parent_or_child = find(page.editor, "WPFControlName", "Editor", depth=1)
```

Supply your own bound `page`. `find_child` defaults to the first match; `strict=True`
requires one. `find_all_children` returns indexed, re-resolving elements, so later tree
reordering can change their identities. Depth counts automation-peer levels. The
[migration guide](migrating-from-testcomplete.md) covers the NameMapping importer and
helper semantics.

## Property aliases

Shared `property_aliases` can rename a UIA property or a qualified managed key. For example:

```yaml
property_aliases:
  OrderStatus: clr:DataContext.Status
```

Then `Element(where={"OrderStatus": "Ready"})` uses that path. Aliases merge across
configuration layers; later definitions win. They cannot shadow real UIA properties or
form alias chains. See [configuration](running-tests.md#configuration).
