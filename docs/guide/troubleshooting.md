# Troubleshooting

## Managed inspection (preview)

**Preview:** For unreleased managed inspection, see the [state and error guide](managed-inspection.md#troubleshooting).
Run `wtk doctor`, and ask your security administrator about policy blocks rather than disabling protection.

## Start with `wtk doctor`

```powershell
wtk doctor
wtk doctor --json
```

It exits with 3 if any check fails; warnings don't change the exit code. `wtk run` runs the three
checks marked *quick* before every run.

| Check | Fails or warns when | Fix |
|---|---|---|
| Windows 10 1809 or later | older Windows or not Windows | Update Windows |
| Python 3.12 or later | older Python | Install Python 3.12+ |
| Interactive desktop session *(quick)* | running as a service or in a non-interactive session | Run from a logged-on user session; see [CI](ci.md) |
| Desktop is unlocked *(quick)* | the workstation is locked, the screen saver or a UAC prompt is active | Unlock, keep the screen on, dismiss the prompt |
| Local session | warns in a Remote Desktop session | Don't minimize or disconnect the RDP window; use `tscon` ([CI](ci.md#remote-desktop)) |
| UI Automation is available *(quick)* | the UI Automation client can't be created | Check `comtypes` is installed and the session is interactive |
| Display scaling | warns when monitors use different scales | Use one scale for reproducible screenshots |
| WinTestKit configuration | `[tool.wintestkit]` is invalid (fails) or missing (warns) | Fix `pyproject.toml` or run `wtk init` |
| Application executable | `app.path` doesn't exist | Fix the path or build the application |
| Application is running | warns when it isn't | Nothing to do for `per-test`; start it for `attach` |
| Privilege level matches the application | the application is elevated and WinTestKit isn't | Run the terminal, VS Code or the CI agent as administrator |
| comtypes cache is writable | warns when the comtypes wrapper cache can't be written | Install into a writable virtual environment |

## Element not found

The failure message lists the closest candidates and which property differs:

```text
No element matches Button[name="Sign In"] in Window "WTK Demo" (closest: Button "Sign in" — name differs) (waited 1.0s)
```

- Compare the locator with the closest candidate; names are case-sensitive and must match exactly
  unless you use a regular expression.
- Check you're searching the right window: elements of a dialog belong on a page whose `window`
  matches the dialog.
- The element might not exist yet or anymore: increase the timeout, or wait for the step that
  creates it.
- Items of virtualized lists and grids only exist once scrolled into view; use `select()`, `row()`,
  `cell()` or `find_row()` on the container ([Locators](locators-for-wpf.md#virtualized-lists-and-grids)).
- Open `tree.txt` in the failure artifacts, or use the Spy, to see what the UI tree actually
  contains.

## Found in another window

The most common breakage is a box, dialog or input that moved to a different window of the
application. Its own properties (class name, control name) still match; only its container
changed. When an element is not found, WinTestKit therefore looks for the element's own locator
(ignoring `within=` and the window) in every top-level window of the application, and says where
it found it. Nothing found there is ever used for the action: the test still fails.

```text
No element matches Edit#Street in Window "Customer" (waited 5.0s)
  → found in another window: Window "Edit Customer" › Group #AddressBox "Address" › Edit #Street "Street"
  → the component root Home.address.root (AddressBox) was found in: Window "Edit Customer"
  hint: the box moved — move `address = AddressBox()` (pages/home.py:12) to the page for that window, or set its window
  declared: pages/components/address.py:9
```

- `found in another window` is the element itself, with its window and a short path of ancestors.
  It lists at most five matches.
- `the component root … was found in` appears for members of a [component](pages-and-elements.md#components):
  the whole box moved. Move the mount line (`address = AddressBox()`, shown as `hint`) to the page
  of that window, or give the mount `window=Window(...)`. Tests and the component stay as they
  are.
- `declared` points at the line that defines the element, `hint` at the mount.
- If the element is found in the window it is declared for, but under a different container, the
  output says so and the window is not repeated in the path. The container locator is wrong, not
  the window:

  ```text
  No element matches Edit#Street in Window "Customer" (waited 5.0s)
    → found in the same window under a different container: Group #Other "Box" › Edit #Street "Street"
    hint: the component root locator no longer matches the container of this element — update `root` at pages/components/address.py:5
    declared: pages/components/address.py:9
  ```

  Update the component's `root` (or the element's `within=` chain) at the line named in the hint.
- For a single element that moved, declare it on the page for the new window or give it
  `window=`.
- The search runs once, after the normal wait has expired, and is limited to about two seconds,
  five matches and twenty windows. It also shows up in `wtk check`, in the editor and in the HTML
  report (`relocations` in the JSON diagnostic).

## Reading `wtk check` results

In `wtk check`, `✗` means the element was not found where it is declared: broken or moved. It is
always a failure and the exit code is 1; the last line summarizes it, for example
`25 found, 4 broken/moved`. If `found in …` lines follow, they say where the element went.
Otherwise it was not visible in the current app state, which does not prove it did not move. Put
the app into the state where the element should exist (open the dialog, pane or tab) and run
`wtk check` again, or use the Spy, before concluding the locator is wrong. All relocation searches
of one check run share a ten second budget.

## Ambiguous element

`2 elements match … add within= or index= to pick one` means the locator matches several controls.
Add a property, scope it with `within=`, or use `index=` as a last resort. See
[strict matching](locators-for-wpf.md#strict-matching).

## Timed out waiting for an element to be enabled or visible

Actions wait for their element to be enabled and visible. The message says which condition wasn't
met: something in the application keeps the control disabled (validation, a busy state) or covers
it, or it's scrolled out of view in a container that can't scroll it back.

## Elevated applications

Windows blocks input and UI Automation from a process with lower privileges. If the application
runs as administrator, run your terminal, VS Code or CI agent as administrator too. `wtk doctor`
checks this when the application is running.

## Display scaling (DPI)

WinTestKit is DPI-aware and handles any scale, including mixed scales across monitors. Screenshots
and mouse coordinates are only comparable between machines with the same resolution and scale,
so pin both on CI machines.

## Locked desktop and Remote Desktop

A locked workstation, active screen saver, UAC prompt or minimized or disconnected RDP window makes
UI Automation and input fail. See [CI](ci.md) for unattended setups.

## comtypes cache

`comtypes` generates Python wrappers for the UI Automation type library on first use and caches
them in its package directory. If that directory isn't writable (a system-wide Python), the first
run can fail or be slow; install WinTestKit into a virtual environment. If the cache is corrupt
after an interrupted first run, reinstall `comtypes` in the environment.

## Logs

- Command line: `wtk --log-level DEBUG run`, or set `WTK_LOG=DEBUG` for any process (including
  plain `pytest`).
- VS Code: the **WinTestKit** output channel (**WinTestKit: Show Output**) contains the
  extension's log and the Python server's log. Set `wintestkit.server.logLevel` to `debug` for
  more detail.
- Test output: captured stdout, stderr and logs of each test are in the HTML report and in the Test
  Explorer results.
