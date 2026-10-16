# Fixing breakages

The common breakage is a box that moved to another window. Start with `wtk check <file>` (or the
failing test's message), not with the test.

## Read the diagnostic

```text
No element matches Edit#Street in Window "Customer" (waited 5.0s)
  -> found in another window: Window "Edit Customer" > Group #AddressBox "Address" > Edit #Street "Street"
  -> the component root Home.address.root (AddressBox) was found in: Window "Edit Customer"
  hint: the box moved - move `address = AddressBox()` (pages/home.py:12) to the page for that window, or set its window
  declared: pages/components/address.py:9
```

- First line: what was searched and where (the page's window).
- `found in another window`: the element's own locator (ignoring `within=` and the window) matched in
  another top-level window, with a short ancestor path. At most five matches are listed. Nothing
  found this way is ever used for an action; the test still fails.
- `found in the same window under a different container`: the element exists in the declared
  window, but not under the container its locator names (no window in the path). The hint says
  `update root at <file:line>` (component root) or to fix the `within=` chain; this is not a move.
- `the component root ... was found in`: the whole box moved, not just one member.
- `hint`: names the mount line and its file:line.
- `declared`: the line that defines the failing element.
- The same data is in `wtk check --json` (`relocations`), the editor and the HTML report.

## What to change

| Diagnostic | Change |
|---|---|
| component root found in another window, hint names the mount | Move the mount line (`address = AddressBox()`) from the old page to the page of the new window. Tests that used `old.address` now use `new.address` (or keep an intent method on a flow). Alternatively `address = AddressBox(window=Window(title=...))` if the box should stay reachable from the old page. |
| only one element found elsewhere | Declare that element on the page for the new window, or give it `window=Window(...)`. |
| member found in the same window under a different container | The container locator is stale: update the component's `root` (file:line in the hint) or the element's `within=` chain. |
| root found in the same window, member not found | The box layout changed: fix the member's locator (compare the closest candidates in the message). |
| root not found, nothing found elsewhere | The box's root locator changed: Spy it, change the component's `root` once. |
| `2 elements match ... add within= or index=` | Add a distinguishing property; else a component root or `within=` one level; `index=` only as a last resort. |
| `... is declared as ComboBox but matched control type ...` | Fix the locator, declare the right type or plain `Element`, or `validate=False` for an odd control. |
| timed out waiting for enabled/visible | Something keeps the control disabled or covered; fix the precondition in the intent method (do not add sleeps). |

## Procedure

1. `wtk check pages/<page>.py` with the application on the right window; read every red line.
2. Apply the single change from the table. Prefer moving one mount line over editing members.
3. Re-run `wtk check` for the old and the new page, then the affected tests.
4. If the box moved for good, also update the intent methods or flows that navigate to its window.

## What not to do

- Do not remove the failing assertion or widen a locator until it passes (a loose locator clicks the
  wrong control later).
- Do not add `index=` to silence ambiguity you do not understand.
- Do not copy the old mapped hierarchy into `within=` chains.
- Do not access the element from the tests directly to work around a move.
