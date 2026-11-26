# Changelog

All notable changes to WinTestKit (the `wintestkit` Python package and this extension, which are
sharing a version by default for stable releases) are documented here. Formal Python prereleases use
an explicitly selected, distinct numeric extension version and prerelease channel metadata.
Unreleased changes must be moved to a dated candidate section before a release can pass checks.

## [Unreleased]

- **Initialization:** `wtk init --app X` generates a starter page and test for your application instead of VS Code (or a clearly marked `TODO` and a starter test that fails with an explanation when no executable name is known), `--args` records launch arguments, and a new `pyproject.toml` is reported as "Created".
- **App lifecycle:** Launch for tests no longer closes or kills an application that was already running: it attaches to it for the session, says so once, and leaves it running. The new `app.close_existing` setting closes it gracefully first, and a blocked close fails the run instead of force-killing an app WinTestKit did not start. Relaunches keep the configured launch arguments.
- **Grid access:** Indexed row and cell access (`cell(r, c)`, `row(i)`, selecting by index) stops at the wanted row and reads no cell text, and `find_row` reads only the searched column, so large grids are much faster.
- **Grids:** DataGrid helpers skip group headers when counting, selecting and comparing rows, and selected items show their cell text.
- **Checks and toggles:** Immediate element and collection checks now work when the WPF inspector needs to attach, and checkbox actions honor mouse input mode.

- **Busy applications:** Picking or reading elements deep inside Ribbon and other nested templates no longer freezes the application for seconds.
- **Diagnostics:** When an inspector request times out, the log and messages say whether the application's UI thread was busy or the inspector's own request ran long, with timings.
- **Spy:** Stops queuing more reads behind a stalled request, and repeated stalls are logged with a count.
- **Picking:** Ctrl+Click on an element deep inside Ribbon or other templates no longer freezes the application for about 0.4 s, because the inspector reads each ancestor's x:Name directly instead of building its whole member list.
- **Spy:** Revealing a picked element 50 to 60 levels deep takes about 3 s instead of 13 s, because the defined-object markers wait until the reveal has finished instead of delaying every level.
- **Spy:** A Properties list continued after its page expired (for example after the getter dialog stayed open for more than 30 s) reads its earlier pages again instead of showing `invalidPageToken` with an Attach button, and an expired page no longer counts as an attach failure.
- **Spy:** An object without a UI Automation peer, such as a Border in a template, shows its type in the Selected object header, ChildCount counts its children without expanding its row, and its suggested locator is named after its x:Name or type instead of `_1`.
- **Check all:** Checking a page with elements that are not on screen takes about 13 s instead of 75 s, because all previews share one scan of the window for sensitive controls and a missing component root is searched once for all of its elements.

## [0.1.1rc7] - 2026-11-26

Seventh prerelease. Install the extension's pre-release channel together with `pip install --pre "wintestkit[inspector]==0.1.1rc7"`. The first upgrade from rc6 asks to close applications that still have the rc6 inspector loaded.

- **Picking:** Picks on large WPF panels take about 4 s instead of 9 s, because Spy maps a page of tree rows to UI Automation in batched searches. Spy re-resolves a picked object at its screen position when the application replaces it, reveals the visual host of WPF content, repairs missing managed ancestors, matches recreated nodes by their full identity, and logs each reveal step. Large managed trees stay inspectable because the least recently used object leases are demoted.
- **Busy applications:** The inspector raises a queued read to normal dispatcher priority after 250 ms, so a busy UI thread no longer starves it. While the UI thread is hung, Refresh keeps the tree and the selection, the Properties sidebar says the UI thread is busy instead of offering Attach and loads its values by itself when the application responds, and Check exists and Check all report **App not responding** instead of "not found", without red underlines.
- **Previews:** Check exists saves previews for windows (with sensitive controls blacked out) and for collections (the first match with its window and the match count), captures peerless WPF elements, and says why a preview was not saved in the editor hover, Page Tree and output log. Spy shows a live preview for every row, including top-level windows and Process rows, never larger than the element's natural size.
- **Properties sidebar:** Pins choose the rows of the Basic view and **Reset Basic view** restores the defaults; the list is the user setting `wintestkit.spy.basicProperties`, which replaces `wintestkit.spy.shownProperties`. Descriptions are tooltips on the row names, a "Name copied" or "Value copied" label appears beside the pointer, WPF Visible, IsEnabled and HasKeyboardFocus read `true` and `false`, a top-level window's Parent is its process, and the **…** menu focuses its first item.
- **Spy:** The Objects tree gets the width the Selected object pane does not need, the splitter is remembered per workspace (double-click resets it), unnamed objects keep their tree label in the Selected object header, processes that exit leave the tree without a Refresh, and Show Other Apps stays available while the app under test is stopped.
- **Protection:** Only password fields stay protected, so bindings, text and values of windows and panels without their own automation peer are readable.
- **App lifecycle:** WinTestKit remembers that it launched the app while any process it launched still runs, and Close App says when it would also close instances WinTestKit did not start.
- **Diagnostics:** Inspector injection and bootstrap failures are reported precisely, the injector log is included in Save Diagnostics, and configuration changes no longer restart the server needlessly.

## [0.1.1rc6] - 2026-11-24

Sixth prerelease. Install the extension's pre-release channel together with `pip install --pre "wintestkit[inspector]==0.1.1rc6"`. The first upgrade from rc5 asks to close applications that still have the rc5 inspector loaded.

- **Upgrades:** The inspector is now injected from a verified copy next to the Python environment (or under `%LOCALAPPDATA%\WinTestKit\inspector`), so a running application no longer locks the installed package. Before installing, the extension names the applications that still hold older inspector files and offers to close them; force closing needs a second confirmation. A locked-file failure names the applications instead of showing the raw pip error, and pip rollback leftovers (`~intestkit…`) are removed after a successful install.
- **Properties sidebar:** Click a name or value to copy it. Readable rows have a **Read again** icon and methods an **Invoke** icon; the row menu, Copy locator key and pinning are gone. `MappedName` is no longer listed. The Detach, Refresh metadata and Export metadata menu moved to a button beside the search box.
- **Spy:** Expanding a WPF tree row no longer fails with `objectStale` after the Properties sidebar changes selection, and a stale row reloads the tree instead of showing an error. When the application's UI thread is busy, Spy says so and names the application and PID instead of reporting a failed attach, and inspector timeouts report how long the work waited and ran.
- **Diagnostics:** **WinTestKit: Save Diagnostics…** collects versions, the WinTestKit log, `wtk doctor` checks and settings into a local zip for debugging. User, computer and domain names, home paths, email addresses and secret settings are redacted, the bundle opens for review before it is saved, and nothing is uploaded. The Spy trace, which may contain application values, is opt-in. See the diagnostics guide.

## [0.1.1rc5] - 2026-11-24

Fifth prerelease. Install the extension's pre-release channel together with `pip install --pre "wintestkit[inspector]==0.1.1rc5"`. Restart a target that still runs an older inspector agent.

- **Properties sidebar:** A **Show all properties** switch replaces the Basic and Advanced button, and the row menu's **Pin** and **Unpin** replace Show in and Remove from Basic view. The search box has a search icon, Properties, Fields and Methods form one split button, and the **…** menu (Detach, Refresh metadata, Export metadata) moves to the preview heading after **In App context**.

- **Properties sidebar:** Collapsible sections now show managed members in one alphabetical .NET list, with property-kind markers and control identification values when **Show all properties** is off.

- **Managed inspection:** Selecting a WPF object now lists its **Events** under .NET in the Properties sidebar, with who handles them. Every routed event that applies to the type (and its base types) shows as `routed (Bubble), 2 handlers`, with the handlers added in code or XAML listed by declaring type and method name and marked `handledEventsToo` where they take handled events; every CLR event the type declares, instance or static, shows as `CLR, 1 subscriber`, with the subscribers read from its backing delegate field. A CLR event that only wraps a routed event (`Button.Click`) is listed once, as routed. An event whose handlers the inspector cannot read says `handlers unknown`; a password control lists names only. Events somebody handles come first, and each opens to one row per handler. Only metadata and delegate lists are read: no handler runs, so events do not spend the automatic read budget. New `members.events` request (`membersEvents` feature, `InspectorClient.events` and the `inspect.managed.events` RPC); restart a target that still runs an older agent.

- **Managed inspection:** Resources in the Properties sidebar are listed by key and created only when asked for. Listing the resources of an element or the application no longer instantiates the lazily created resources of the dictionaries it lists (nor does naming the key of the element's style); each resource row says `(expand to read)`, and expanding it reads that one value through the new `members.resource` request (`InspectorClient.resource` and the `inspect.managed.resource` RPC), then shows it and, for an object, its members and items. Resource entries in the `members.styling` result now carry `key`, `keyKind` and `index` instead of a value.

- **Managed inspection:** Selecting a WPF element now also shows its **Style and template** and **Resources** under .NET in the Properties sidebar: the style in use (its source, target type and key), its `Setter <Owner.Property>` rows with `DynamicResource`, binding and `TemplateBinding` markup named instead of evaluated, the `BasedOn` chain, and triggers that open to their conditions, setters and, for property triggers, whether they are active now; the control, content, item and item container templates with their triggers and named parts, the items panel and the templated parent; and the element's own resources (string, type and component keys, objects expandable), merged dictionary sources and an **Application resources** summary. It uses the new `members.styling` request (`membersStyling` feature, `InspectorClient.styling` and the `inspect.managed.styling` RPC) and runs no application getter; restart a target that still runs an older agent.

- **Managed inspection:** Bindings in the Properties sidebar open to their full details: mode, update trigger, path, `XPath`, element name, relative source, source and converter types, `ConverterParameter`, `ConverterCulture`, `StringFormat`, `FallbackValue`, `TargetNullValue`, `Delay`, binding group, `IsAsync`, the notify and validation flags, validation rules, the resolved `DataItem` and `ResolvedSource` with its property name, error state and the active child of a `PriorityBinding`. `DataItem` and `ResolvedSource` expand like any object, and the children of Multi- and PriorityBindings nest under their parent. Values follow the redaction rules of member reads; empty and default fields are left out of the list.

- **Managed inspection:** Expanding an object in Spy now lists the items of a collection (arrays, lists, dictionaries and other enumerables) under it: a `Count` row, `[0]`, `[1]`, ... rows (`[key]` for dictionaries), and a **Load more** row for further pages. Items that are objects expand like any other row, and a collection that throws while it is enumerated shows `Enumeration threw <type>: <message>` after the items read so far. Enumeration runs only when you expand a row, never in the automatic read. Restart a target that still runs an older inspector agent.

- Show safe, bounded getter failure messages in managed Spy.

- **Managed inspection:** Show non-default attached properties supplied by styles, templates, and inheritance.

- **Managed inspection:** Spy lists inherited static properties and fields, and groups static methods separately.

- **Properties sidebar:** With **Show all properties** off, Standard and .NET values are separated; with it on, managed members appear under collapsible category headings, with instance and static fields and methods grouped separately. **Read remaining** continues rows left unread after the automatic read budget.

- Highlight peerless WPF elements and report ancestor outlines; configure outline thickness.

## [0.1.1rc4] - 2026-11-23

Fourth prerelease. Install the extension's pre-release channel together with `pip install --pre "wintestkit[inspector]==0.1.1rc4"`.

- **Spy:** Attach failures now show the real .NET error code, a hint and `wtk doctor` guidance in the tree, the Properties header and the WinTestKit output channel, logged once per attempt. A disabled inspector, a different inspector build already loaded in the target (`agentVersionMismatch`) and a blocked attach each get their own message. Re-attaching after **Detach** works, and Spy keeps one shared session.
- **Compatibility:** The extension and the `wintestkit` and `wintestkit-inspector` packages now share a lockstep minimum. Spy and test runs on an older package are blocked with an **Upgrade wintestkit to <minimum>** action that installs the matching release through pip or uv and restarts the server.
- **Spy tree:** Windows are grouped under `Process("<exe>")` rows with the executable's icon and PID. Rows read `WPFObject("name")`, `UIAObject(...)` or `Window("Class")` with only the arguments needed to tell siblings apart, the control's text and a place among repeats, one icon per control type and a **WPF**, **WinForms**, **Win32** or **UIA** badge. WPF rows now show the control's text (`Text`, `Content`, `Header`, `Title`; password boxes are never read). Refresh and pick update the loaded tree in place and keep expansion, selection and scroll. Newly opened or picked labels scroll into view. Children keep their visual order after a pick.
- **Properties sidebar:** A new Properties view in the secondary sidebar shows the live preview and Properties, Fields and Methods tabs, one search box and a Description pane. The **Basic** view lists nine rows; the **Advanced** view groups them as Standard, Extended, .NET and UI Automation, each value once. It adds `FullName` (the locator path), `MappedName` (`Page.element`) and a clickable `Parent`. The row menu offers Copy value, Copy name, Copy locator key, Expand, Read again and Show in Basic view. Every .NET member is read automatically in the background, with a 250 ms getter limit and a 5 s budget per object, and unreadable members say why (for example "Not readable: internal member"). The Methods tab invokes a method from its row menu with an inline argument form and a confirmation, and shows the result inline. Decimal values no longer break the session.
- **Spy:** WinForms (.NET Framework 4.8, .NET 8 and .NET 10) applications now attach like WPF ones. The tree follows `Control.Controls` and the items of a `ToolStrip` or menu, rows read `WinFormsObject("button1")` (the control's `Name`, else type, text and place among siblings) with a **WinForms** badge, and the Properties sidebar's Properties, Fields and Methods tabs, automatic reads, method calls and redaction work as for WPF. The text of a password box is never read. WinForms windows whose process the inspector cannot attach to keep the UI Automation tree. Spy attaches to a WinForms application on demand; launching an application for tests still attaches the agent only for WPF. `wtk doctor --agent` checks WinForms applications too.
- **Spy:** Selecting a control with a native window handle (Win32, MFC, WinForms, dialogs) now shows a **Win32 Window** group: window class, decoded window, extended and class-specific styles (`BS_*`, `ES_*`, `SS_*`, `CBS_*`, `LBS_*`, `DS_*` and the common list, tree and tab styles) with the raw values, control ID, text, process and thread, owner and parent, window and client rectangles, visibility, enabled and topmost state, and DPI. The Basic view shows the class, control ID, text, handle and styles. Such controls are labelled `Window("Class", "text", index)` in the tree. Every UI Automation property and supported pattern now loads with the selection, so the **Load all properties** button is gone.
- **Element checks:** Instant element checks no longer time out at 0.0 s before the inspector attaches, and a failed check says why an element was not found, with the nearest candidates.
- **Page Tree:** Element names stay in full; long locators are cut in the middle and scroll sideways.
- **Diagnostics:** The new `wintestkit.spy.traceFile` setting records Spy messages for replaying a bug, and `wintestkit.spy.showRefreshCounts` reports how many rows a refresh added, removed, kept and redrew.

## [0.1.1rc3] - 2026-11-17

Third prerelease. Install the extension's pre-release channel together with `pip install --pre "wintestkit==0.1.1rc3"`.

- **WPF backend:** The default `backend: auto` now uses an injected inspector agent for WPF windows and UI Automation for other windows. Install `wintestkit[inspector]`, or choose `backend: uia` to opt out. Mouse input is now the default on both backends; choose `input_mode: pattern` to use patterns. Managed `clr:` and `type:` locators, virtualized item search and agent-side events support WPF automation. Use `wtk doctor --agent` to check the agent and `wtk compare` to compare runs.
- **Spy:** Browse paged WPF visual and logical trees, pick elements with WPF hit testing, inspect managed properties and verify locators. The configured app attaches automatically in a trusted workspace; other apps ask for consent. Blocked attachment shows guidance. Insert the new typed controls from Spy.
- **Locators:** Use `any_of` for alternative property groups and `has=` to require a matching child.
- **Actions:** Actions now wait for existence only by default and report disabled or hidden elements immediately. Set `actionability: strict` to also wait for enabled and visible elements. Add `drag_to` and `drag_by`, positioned, middle and modified clicks, scrolling, keyboard and window keys, window move, resize and activation, menu and tree paths, multi-select and `to_have_rows`.
- **Typed controls:** Add Menu, ContextMenu, Slider, ScrollBar, ProgressBar, DatePicker, Expander, ToggleButton, Hyperlink (UIA backend only), ToolBar and StatusBar.
- **Managed access:** Read managed properties with `el.get("clr:Name")`, `wait_for_property` and `to_have_property`. Opt in to audited writes and method calls with an allowlist; typed arguments are available through `wintestkit.managed`, and calls return their results. Public instance methods marked `[Pure]` can be called without an allowlist entry.
- **Migration:** Use `wintestkit.finders` find helpers, import NameMapping files and convert legacy key strings. First-match finders warn when a locator is ambiguous.
- **Reporting:** Add `wintestkit.step` and `log.message`, `log.warning` and `log.picture` for structured reports.
- **Configuration:** Add Action waiting and backend selection to VS Code settings, align defaults with Python and show WPF agent doctor failures in setup health. Preserve unfinished edits, selection and focus during background refreshes. Navigate option groups and highlight swatches with arrow keys, Home and End.
- **Page Tree:** Show the selected element's last checked capture in a pinned Preview section, with Element and In App views, image viewer access, capture age and separate empty states.

## [0.1.1rc2] - 2026-10-23

Second prerelease. Install the extension's pre-release channel together with
`pip install --pre "wintestkit==0.1.1rc2"`.

- Fix **Check all elements in this class** not marking the elements of mounted components (such as a
  page's `navigation` or `number_pad`) in the Page Tree. The check ran and reported its totals, but
  only the page's own elements were updated. Component rows under the page that was checked now get
  their ticks and crosses, and only those: the same component under another page is not touched,
  since it may be in a different state there. Checking a component element on its own still marks it
  wherever it appears.
- Add **Share Check Element captures in the repository** (`object_previews_share`, default off).
  It is a repository-wide choice, so it exists only in Repository Settings and is disabled until
  **Save Check Element captures** is on; User Settings show its state with a button to Repository
  Settings. While off, `object-previews/` is added to `.gitignore` so captures stay on each machine;
  turning it on removes that line. Needs the Python package from this version.
- Fix saved element captures piling up in `object-previews/`. A new capture now deletes the images
  it replaces instead of keeping them for an hour, so each element keeps one pair; older leftovers
  are pruned the next time that element is checked. Needs the Python package from this version.
- **Check all elements in this class** now saves a capture for every uniquely found single element,
  not only for single-element checks, and shows a spinner (a **Checking all elements…** CodeLens, the
  page's row in the Page Tree and a progress notification) while it runs. Needs the Python package
  from this version.
- Keep Check exists and Highlight results (CodeLens status, inline markers, tree icons) when you
  close or leave a file, save or edit it, or the project is rediscovered. Results now follow their
  element to its new line and are only dropped if the element no longer exists. They are cleared on a
  window reload or with the new **Clear results** button in the Page Tree toolbar.
- Fix saved Check exists captures for hosted Windows apps such as Calculator, and scan
  non-rendered UI containers without discarding otherwise safe window captures.
- Keep single-element checks responsive during discovery refreshes, show progress and explicit
  outcomes, and log check requests/results instead of silently skipping stale CodeLens targets.
- Capture saved element images only when a single element's **Check exists** CodeLens succeeds,
  rather than during tests. Hover over its name in Python to see the crop, capture time and links
  to the full image or outlined app window. References work when Python can resolve the declaration.
  Highlight does not capture. Remove saved/offline Spy mode; selecting a page
  element opens its source without replacing live Spy. Older automatic captures need an explicit
  check before they appear in hovers. Needs the Python package from this version.
- Fix Spy's live preview being blurry. Captures were shrunk to 1600 px on their longest edge, so a
  full-screen window on a 3440x1440 monitor lost more than half its resolution and its text turned
  to mush, in the panel and when zoomed in the image viewer. They are now sent at their real size
  (lossless WebP of a UI is small: about 150 KB for a full 3440x1408 window, roughly 0.17 s slower
  to capture); only a capture past 7680 px, or one too busy to fit 12 MiB, is scaled down. The red
  outline now grows with the window so it stays visible when the panel shrinks the picture, and a
  small element crop that the panel enlarges is drawn with sharp pixels instead of a smoothed blur.
  Needs the `wintestkit` package from this version.
- Rename the **Highlight actions** setting to **Flash elements during test runs** in the Configuration
  page, so it is not confused with Spy's Highlight. Only the label and description change: the
  `highlight_actions` key, the `--wtk-highlight` option and existing configuration files are unchanged.
- Add a `highlight_color` setting (`#RRGGBB`, default `#FF0000`) for the outline drawn around an
  element by Flash elements during test runs (`highlight_actions`), Spy, `element.highlight()`, `wtk highlight` and the editor's highlight
  commands. In the Configuration page (User Settings, Debugging) it is a row of swatches plus a
  custom colour picker, with a small diagram of a highlighted button. Quote the value in YAML,
  because an unquoted `#` starts a comment. Needs the `wintestkit` package from this version.
- Allow the committed `wintestkit.yaml` to set `app.path` as a path relative to the project folder and to
  share `app.args`, so a repository can point at its own build output (`bin/Debug/App.exe`) and
  launch flags. Absolute, drive and UNC paths are still rejected there, with a message pointing to
  `wintestkit.local.yaml`, and a local value still overrides the shared one. In the Configuration page
  **Browse…** now also works in Repository Settings and stores the path relative to the project
  (refusing files outside it). Needs the `wintestkit` package from this version.
- Redesign the Configuration page: the collapsed **Advanced options** section is gone, so every
  setting is visible at once, with the application executable now the first row of **Application**.
  Settings sit in rounded cards with the control beside the label,
  numbers get a slider next to the exact value, options become a segmented control and booleans a
  switch. Controls are always editable, so changing a value overrides it in place (replacing the per-row
  override checkbox and the Reset button). In **User Settings** a setting whose value differs from what it would be without your file (its
  default, or the repository value) has a short accent bar on its left edge, inset from the top and bottom. A
  value that merely equals the default is not treated as modified, and Repository Settings mark nothing. A setting that the repository's
  `wintestkit.yaml` also sets is greyed out under a blurred **Override Repository Setting** button while the
  repository value is in use; clicking it makes the control editable (starting from the repository
  value) and shows a grey git tab on the card edge that returns to the repository value.
  Settings without a repository value have neither, and **Repository Settings** warns on a
  setting your User Settings override. Small
  illustrations (shown only while a setting is editable) show what Input mode (UI Automation versus mouse), the Replay capture scope (window versus whole screen) do. Every
  change in **User Settings** (the machine-local file, formerly "This machine") and **Repository
  Settings** (formerly "Shared project") is saved immediately, so there is no Save button. In
  Repository Settings every setting starts off (blank and greyed out);
  a blurred **Enable Setting for Repository** button turns each one on separately, writing its
  default to `wintestkit.yaml` or waiting for a value when it has none, and a red git tab on the
  card edge removes it from the file again; clearing a value, or leaving an enabled setting empty,
  switches it off too. While a change is being written a small "Saving" spinner shows at the right of the
  file line (for at least half a second, so it does not flicker), instead of briefly flashing an
  "unsaved changes" banner. The scope switch
  and Open YAML stay in a sticky bar.
- List the desktop's windows for Spy's "show other apps" scope with `EnumWindows` instead of UI
  Automation's desktop root. UI Automation visits every hidden window of every process, so one slow
  provider on the machine made each refresh take around six seconds, queued status checks behind
  it, and let short-lived windows vanish before they were read (reported as an incomplete
  enumeration). The same roots now load in about 0.1 s.
- Merge Spy's Inspection section into **All properties**: one list sorted alphabetically, in which
  nested values (such as `RuntimeId`, `BoundingRectangle` and element lists) show an arrow and a
  count and open in place, several levels deep, with the nested rows indented, tinted and marked
  as belonging to their parent. Properties that hold UI Automation elements or element arrays
  (`ControllerFor`, `DescribedBy`, `SelectionSelection`, ...) are now read into nested rows
  instead of being shown as opaque.
- Add a pin button, shown on the row under the pointer, to each property in **All properties** to show it, in a new **Pinned** group,
  for every selected object. The list is the user setting `wintestkit.spy.shownProperties`, so it
  is never saved in a project or its git repository. Needs the `include` parameter of
  `inspect.properties` (the `wintestkit` package from this version).
- Search only the direct children of an element with `panel.Element(...)`, `panel.Button(...)` and the other typed elements, or `panel.Elements(...)` for a group. On a declaration it is `within=panel, depth=1` and shows nested under `panel` in the Page Tree; on a bound element (`self.panel.Button(...)`) it looks the child up on the fly. Needs the `wintestkit` package from this version.
- Allow choosing a different application in the Test App settings while the current one is running. The tile used to be locked until the app was closed. The running application is not closed or touched: it stays open, only the target changes (and the extension restarts its server for the new configuration, which never closes the app).
- Generate Spy's suggested locator only when asked, with a **Generate suggested locator** button (its tooltip, and the progress text, warn that large applications can take 20 seconds or
  more) and a spinner while it runs. It no
  longer holds up the rest of the selected object's details (definitions, preview) on selection.
- Replace the "Last-test preview" in Spy's properties with a **Preview** section: a live capture of
  the selected object, switchable between the element alone (the default) and its window with the
  object outlined in red. Every image is fitted inside the same fixed-size frame. Saved
  definitions show their last-test images in the same section. Needs the new `inspect.preview`
  server method (the `wintestkit` package from this version). Click the image, or the button
  beside the toggle, to open it in VS Code’s built-in image viewer to zoom and pan; the file is
  private, temporary and deleted when its tab closes.
- Stop Spy's objects view from reloading by itself. It no longer reloads when the panel tab is
  shown again (the view now keeps its state while hidden), when a project file changes, or after
  an element has vanished. It reloads on the reload button, with the picker, and when nothing has
  loaded yet.
- Mark the selected application's windows in Spy's objects view with a blue tick, and call a window
  that has no title of its own by the application's name instead of "Window".
- Show elements whose provider returns an empty runtime id (such as TeamViewer's custom-drawn
  content) in Spy instead of reporting an incomplete enumeration. They are keyed by their place
  under the parent, so they can be expanded and inspected like any other node.
- Remove the gutter icons beside page elements, and the inline "✓ found" text on passing ones. Only
  elements that are not found, ambiguous or errored are marked inline, after the code on the
  element's line instead of before it; **Check: Found** stays in the CodeLens.
- Make **All properties** a plain, always-visible section instead of a collapsible one, and stop
  listing `HelpText`, `ItemStatus` and `ItemType` in it before the full list is loaded; it fills in
  when you click **Load all properties**. Properties you pin and properties that your configured
  aliases point at are still read on selection. (`wtk inspect` on the command line still prints
  the three.)
- Keep Spy's selection through a reload, a server restart or a VS Code reload: the tree is opened
  down to the object and it is selected again. It is found by the properties of each object on its
  route from the window, with its place among its siblings, rather than by node ids that change
  on restart. A look-alike is never selected in its place: if the object is gone, ambiguous or
  changed, a VS Code warning says so once and the selection is forgotten.
- Stop the server restarting by itself about once an hour. The extension restarted it on every
  change event for `pyproject.toml`, `wintestkit.yaml` or `wintestkit.local.yaml`, and something
  on the machine (an indexer, scanner or sync client) sends such events for files it merely
  touched. A file now restarts the server only when its content is different.
- Fix **Pick element** doing nothing on such elements: every hover and pick in TeamViewer failed with
  "element has no runtime id". A picked element is now keyed by its place below the nearest
  ancestor that has an id, matching the tree, and its ancestors are revealed as usual. Siblings are
  told apart by their properties because UI Automation cannot compare these elements reliably.
  Hovering skips that lookup, which can take a few hundred milliseconds in a deep tree.

## [0.1.1rc1] - 2026-10-22

First public prerelease. Install the extension's pre-release channel together with
`pip install --pre "wintestkit==0.1.1rc1"`.

- Restore reloaded optional tutorials paused and resumable; release tutorial UI state before
  saving completion, and ignore picker activity from hidden, cancelled, or superseded sessions.
- Coalesce Spy refresh requests, share root/status snapshots, cache fresh child descriptions,
  queue coverage work, and cache application icons by executable for the extension-host session.
  Surviving objects remain visible with a warning when enumeration is incomplete.
- Save paired last-successful test-time element images with the project: an element crop for
  Selected object and a separate red-outlined owning-window image retained for future use.
  Saved definitions can show their crop offline; image capture has privacy guards and an opt-out.
- Show bounded, expandable external UI Automation inspection values without reflecting opaque
  CLR objects. Remove verified dead helpers, duplicate dispatch paths, and obsolete historical
  documentation while retaining current usage guidance.

- Guide Spy users through eight concise, value-focused steps in visual order, with separate
  selection and Properties explanations, ending on the Testing tab icon. Keep Pick element and its three adjacent controls
  sharp during the toolbar step, and spotlight Highlight with the selection summary.
- Split the selected object inspector into selection details, page definitions and locator
  on the left, with independently scrolling Properties on the right. Narrow inspectors
  stack the sections, and the tutorial highlights the dedicated Properties section.
- Show all desktop applications in the Spy tutorial snapshot while selecting the hosting
  VS Code example. Blur the introduction background and remove Skip tutorial and Cancel
  setup from all Spy tutorial cards, retaining ordinary navigation and Close.
- Keep the first Spy tutorial step available while its snapshot loads; only wait when
  advancing from step two to three. Clear stale object-loading overlays and preserve
  navigation buttons across unchanged tutorial updates.

- Make the optional Spy tutorial read-only while preserving hover effects and scrolling.
  Select the hosting VS Code window's second direct child automatically and keep its
  snapshot fixed. The generated MainPage defines that pane as content, independent of
  workspace titles, for a real match in Defined in pages.
- Enforce the supported Python package range and RPC protocol before connecting. Incompatible
  packages offer direction-specific recovery actions without crash/retry loops; installation
  selects and verifies a compatible package. CI and releases validate the compatibility policy.
- When a test run has failures, the HTML report opens straight away in the main editor area, with the side bar left open. **Open Report**
  and **Open Last Report** use the same preview. Turn it off with `wintestkit.openReportOnFailure`.
- Classified UI Automation environment failures in Test Target offer **Check Environment** for
  the originating project, while ordinary launch errors retain **Show output**.
- Rename the navigation view to **Pages & Flows** and add an **Open Testing** toolbar action.
  Project initialization now offers to open Testing or the generated smoke test.
- Spy distinguishes a stopped app from a project without pages, preserving the page catalogue
  and explaining how to start live definition checks from **Test Target**.
- Align the element check command with the **Check exists** CodeLens and update stale UI guidance.
- Explorer Page Tree and Flows tabs match the Test Target tiles, with rounded borders,
  themed surfaces and orange icons; an accent border identifies the selected tab.
- "Current Setup" is now **Test Target**: tiles for the application (icon, name, process IDs), its
  launch mode, the project and a Launch / Restart / Close action, with the status next to the title.
  The application and mode tiles open quick picks (browse for an executable, attach to a running
  app, Attach or Launch for tests) that save to `wintestkit.local.yaml`, and the project tile
  switches projects. While the app starts it shows each stage (process started, app responding,
  main window shown) with the time against the startup timeout, and a failed launch keeps the
  reason on the section with a way to retry.
- **Launch for tests** mode owns the app's lifecycle: a copy that is already running is closed first,
  and the app WinTestKit started is closed when the tests finish. The Calculator example now uses
  the standard `app` fixture, so the mode in the Test Target view decides whether it attaches or
  starts Calculator.
- Spy file rows use the Python logo for `.py` files.
- Spy shows which element definitions in your pages already point at the selected object ("Defined
  in pages": page attribute, locator, file; click to open it) and marks those objects in the tree.
  Only definitions that resolve to exactly that object count. Markers can be turned off with
  `wintestkit.spy.markDefinedObjects`.
- Selecting an object in Spy no longer brings its window forward by default: the outline is drawn above
  every window anyway. A pin button next to Collapse all (setting `wintestkit.spy.bringWindowToFront`)
  turns it on; the window is then raised without taking keyboard focus from VS Code, and left alone
  when the element has no on-screen rectangle (the Highlight button is disabled with an explanation).
- Spy no longer lists the transient `PopupHost` windows that XAML apps create for tooltips and menus.
  Selecting a window explains that only its controls get locators, and shows its application icon.

- After a Highlight from VS Code (CodeLens, Explorer or Spy) the outline fades and focus returns to the
  window that had it, so the right VS Code window is selected again. Focus stays where it is if you
  switched windows meanwhile.

- Fix the Spy failing with "No window matches Window" and Current Setup showing "Status unavailable"
  for apps such as UWP Calculator that have no top-level window in their own process.

- Move the Spy scope toggle to the right of the toolbar and label it **Show Other Apps** /
  **Show Only Selected App**. The page CodeLens now reads **Check all elements in this class**.

- Add **Run flow** to the Flows tab and as a CodeLens above flows whose only required parameter is
  `app`. A new `flow.run` request calls the flow with the running application; discovery reports
  `runnable` for each flow.

- Remove the Run Test / Debug Test CodeLens and their commands; use the Testing view instead.

- Remove the Tests tab from the Explorer; tests are run and debugged from VS Code's Testing view.

- Return to the MIT license for all versions.

- Rename Pages to Page Tree and nest child pages under their parents, with separation
  between root trees. Shared children appear under each parent.

- Windows can now be checked like elements: the Explorer and CodeLens show a Check action for
  them, and Check all elements includes them.

- Highlight and Check show per-element progress, success, missing/ambiguous matches and errors
  inline in their CodeLens actions, with hover details and click-to-retry.

- Move application state and contextual launch, close, restart and refresh actions into the
  Current Setup application row; remove app lifecycle controls from Spy.

- Replace the separate Pages, Flows and Tests views with one **Explorer**. A **Pages | Flows |
  Tests** control remembers the selected tab. **Spy** stays below Explorer.

- Spy shows **Other apps** after **Collapse all** while the application is running. It is off
  by default and remembers the choice. **Pick element** and **Refresh objects** stay in the Spy
  toolbar; the Spy view title no longer repeats them.

- The configuration editor shows only **Application executable** under **Start the application**.
  Other settings are under the collapsed **Advanced options** section.

- Highlight brings the owning window to the foreground before drawing its outline. If Windows
  denies that, the outline is still drawn. This applies to the Highlight CodeLens, Spy selection
  and the Spy **Highlight** button, `wtk highlight`, and `Element.highlight()`.

## [0.1.1]

- Elements, typed controls, collections and windows accept `where={...}` constraints on scalar
  UI Automation properties, with exact values and compiled regular expressions.
- Shared and local configuration support `property_aliases` for existing property names.
  Spy and inspection expose matching properties; editor discovery and locator displays preserve them.
- Add a test-build WPF guide for exposing full .NET type names and update migration skills.
- Checks report every missing declaration as broken/moved, show relocation details when available,
  and share a bounded search budget across a run.
- Spy loads basic properties first, with a **Load all properties** button for the full list
  and supported patterns. Basic details appear before locator generation completes, and normal
  tree selection no longer collects the ancestor hierarchy.
- Breaking: page objects now use `Page`, the `page` fixture, and the `pages/` folder.
  Update imports, class names and project paths; the former screen API is removed.
- Discovery returns `pages` and `PageEntry`; checks use `page.check` with a `page` parameter.
  Update the Python backend and extension together. Spy insertion and editor commands use
  page terminology throughout.

## [0.1.0]

First release.

- Python UI Automation engine with strict locators, waits, actions and resolution diagnostics.
- `Screen`, `Window`, `Element` and `Elements` model, `expect` assertions and a pytest plugin with
  app lifecycle fixtures, failure screenshots and tree dumps.
- `wtk` CLI: `run`, `discover`, `highlight`, `check`, `inspect`, `spy`, `doctor`, `init`,
  `report`, `serve`.
- Self-contained HTML report and `results.json`; JUnit XML via `--junit`.
- VS Code: Highlight/Check CodeLens, Test Explorer with run and debug profiles, Elements view,
  Spy with **Add to screen…**, project initialization and report notifications.
