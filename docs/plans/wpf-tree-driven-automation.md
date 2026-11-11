# WPF-tree-driven automation: migration plan

Status: decisions D1–D7 made (§3); phases 0–3 done (phase 2 gate passed 2026-11-06,
§6.3; phase 3 gate passed 2026-11-09, §6.5). Phase 4 done (fixture gate passed 2026-11-10, §6.6); phase 5 done (gate passed 2026-11-11, §6.8); phase 6 done (gate passed 2026-11-11, §6.11); phase 7 in progress (§6.12). Planning date: 2026-10-29.
Builds on: `wpf-dotnet-attribute-analyzer.md` (the *inspector plan*) and the implemented
inspector on `master` (agent, protocol, Python client, managed locators, Spy panel).

## 1. Goal

Make the WPF object tree, not UI Automation, the primary model WinTestKit uses to **find,
identify, wait on, act on, assert on, and inspect** elements in WPF applications, so suites
migrated from TestComplete behave like TestComplete: `FindChild`-style searches over the real
WPF tree, identification by `ClrFullClassName`, `WPFControlName`, `DataContext` and any .NET
property, and reach to objects that UIA does not expose.

Today the inspector is an *add-on to UIA*: UIA finds candidates, the agent filters them, UIA
acts. After this plan, for WPF windows the agent finds and describes elements and drives the
actions; UIA remains for non-WPF windows, and for repositories that opt out with `backend: uia`.

### Non-goals

- Replacing UIA for non-WPF content (Win32 dialogs, `MessageBox`, WinForms, WebView2, OS
  file pickers). Those keep the UIA backend.
- Recording/playback, keyword tests, or a TestComplete object-mapping repository.
- Running test logic inside the target. Tests stay Python; the agent executes bounded,
  typed operations only.

## 2. Where the current design stops

| Area | Today | Blocks TestComplete parity because |
| --- | --- | --- |
| Discovery | UIA tree; managed keys post-filter UIA candidates (`engine/query.py`) | Objects without UIA peers are unreachable; 1,000-candidate cap; batch round trips |
| Identity | UIA runtime ID → exact mapping (`Mapping/ElementMapper.cs`) | Every managed lookup starts from UIA |
| Actions | UIA patterns or mouse at UIA bounds (`uia/patterns.py`, `uia/input.py`, `controls.py`) | Need a UIA element to act |
| Agent scope | Read-only by contract (inspector plan §1, §6, §9) | No invoke, set, focus, scroll, realization |
| Virtualization | Never realizes items (`ScrollIntoView`/generation forbidden) | Cannot find rows that are not on screen |
| Spy | UIA tree, UIA picker (`engine/spy.py`), managed section bolted on | Tree and picker show UIA's view, not WPF's |
| Attach | Explicit or on-demand per locator | WPF-first needs the agent present for every operation |

## 3. Decisions (owner, 2026-10-29)

| # | Decision | Chosen |
| --- | --- | --- |
| D1 | **How actions are performed** | Both offered, real input is the default. `input_mode: mouse` (default): the agent reports the element's screen geometry and WinTestKit sends real mouse/keyboard input there. `input_mode: pattern`: the agent performs the automation-peer action (Invoke, Toggle, Value, …) inside the app. Same per-call `mode=` override as today |
| D2 | **Direct writes and method calls** (TestComplete's `obj.IsChecked = True`, `obj.Method()`) | Allowed, opt-in: off by default, only for properties/methods on a repository allowlist, every use recorded in the report |
| D3 | **Inspector plan amendment** | Approved: the read-only contract is amended (see §9); protocol 2.0 |
| D4 | **Attach model** | Partially delivered: on-demand attach by default at the phase 3 gate (owner, 2026-11-08); phase 7 retains launch-time attach and reattach on restart |
| D5 | **Agent cannot load** (blocked by policy, unsupported runtime) | Fail. Test steps on WPF windows fail with the agent's error code (`blockedByPolicy`, `unsupportedTarget`, …); there is no silent fallback to UIA. Spy shows the blocked state and its fix instead of a UIA view |
| D6 | **Virtualized items** | Search the items' data (`ItemsSource`/`Items`) first, then scroll only the single match into view to act on it |
| D7 | **Default backend** | WPF-first becomes the default as soon as it works: at the end of phase 3 (find, waits and actions pass the parity suite), not after the real-suite gate |

Consequence of D5 + D7: once WPF-first is the default, a machine where security software
blocks the agent fails every WPF test until an allow rule is added. `backend: uia` remains an
explicit per-repository opt-out, and `wtk doctor` must detect the block before a run starts.

## 4. Target architecture

```text
pytest / CLI / Spy
      │
Python engine ── Backend router (per window: WPF if agent ready, else UIA)
      │                      │
      │                 UIA backend (existing uia/*)
      │
WPF backend ── inspector client (pipe, protocol 2.0)
      │
Agent in target ── Query engine (tree search in-process, predicates pushed down)
                ── Geometry & state (bounds, visibility, enabled, focus)
                ── Action engine (peer patterns, focus, scroll, realize)
                ── Optional write/invoke (allowlisted, D2)
                ── Wait engine (conditions evaluated on the Dispatcher)
                ── Hit testing (picker), events (tree/property changes)
```

Key principle: **push the search into the agent.** One request carries the whole locator
(scope, predicates, depth, index); the agent walks the WPF tree on the Dispatcher and returns
matching handles with the properties needed for identity and diagnostics. This removes the
UIA candidate step, the 1,000 cap and the 32-per-batch round trips.

## 5. Moves by layer

### 5.1 Agent (C#, `wpf-inspector/src/Agent`)

1. **Query engine** (new `Query/`): evaluate a typed locator in-process.
   - Scope: an object handle, a window root, or all PresentationSource roots.
   - Tree: visual, logical, or combined (default combined, deduplicated — as `TreeWalker`).
   - Predicates: equality and regex on typed paths (existing `PathSegment`), type tests
     (`type:FullName` exact, `type:Is` assignable-to by full name, no type loading),
     peer-derived UIA-equivalents (`automation_id` from `AutomationProperties.AutomationId`
     then `x:Name`; `name` from the peer's `GetName`; `control_type` from
     `GetAutomationControlType`) so existing locators keep working.
   - Depth limit, `index`, `limit`, and strict-ambiguity reporting (count + first N handles).
   - Regex runs in the agent with a per-call timeout (`Regex` match timeout), replacing the
     inspector plan's "regex in Python only" rule.
   - Budget: same slicing/limits as `DispatcherExecutor`; report `limitExceeded` honestly.
2. **Geometry and state** (new `State/`): screen bounds via `PointToScreen` with DPI, clipped
   visibility (`IsVisible`, opacity, clipping by ancestors and scroll viewport), `IsEnabled`,
   `IsKeyboardFocused`, off-screen detection — the inputs for waits and OS-input actions.
3. **Action engine** (new `Actions/`), per D1:
   - `focus`, `bringIntoView` (`FrameworkElement.BringIntoView`), `scrollIntoView` for
     items controls.
   - Peer patterns in-process: Invoke, Toggle, Value, RangeValue, ExpandCollapse,
     SelectionItem, Scroll — the same verbs `uia/patterns.py` exposes.
   - All actions run via `InvokeAsync` on the owning Dispatcher with the existing deadlines;
     results report outcome, never values.
4. **Virtualization** (D6): data-level item search over `ItemsSource`/`Items` with bounded
   enumeration (new rule: explicit, capped, only for item searches), then realize one
   container via `ScrollIntoView` + `ItemContainerGenerator` to act on it.
5. **Optional writes and calls** (D2): `setProperty` (DP via `SetCurrentValue`, CLR setter)
   and `call` (public instance method, scalar arguments only), each gated by a repository
   allowlist sent in the bootstrap; every use is logged in the report.
6. **Hit testing** for the Spy picker: `VisualTreeHelper.HitTest` at a screen point on the
   window under the cursor → handle.
7. **Waits** (`Wait/`): evaluate conditions (exists, visible, enabled, property equals)
   on the Dispatcher, re-checking on `LayoutUpdated`/property-change, bounded by the request
   deadline; fewer round trips than Python polling.
8. **Events** (optional, phase 7): subscribe to window open/close and tree changes so the
   Python side stops polling for windows.
9. **Safety changes**: a write/act operation can change app state, so (a) actions run one
   at a time per Dispatcher, (b) a hung action marks the Dispatcher unresponsive exactly as
   reads do, (c) redaction still applies to every value returned.

### 5.2 Protocol (`wpf-inspector/protocol`, `schemas/`)

- Version **2.0** (major bump; 1.x agents refused with `agentVersionMismatch`-style error).
- New pipe methods: `query.find`, `query.findAll`, `state.get`, `act.<verb>`,
  `wait.until`, `hitTest`, `write.setProperty`, `write.call`, `events.subscribe`.
- New DTOs: `Locator` (typed predicates), `ElementState` (bounds, visibility, enabled, focus),
  `ActResult`, `WaitResult`, write audit records.
- New features in `session.hello`: `query`, `geometry`, `actions`, `virtualItems`, `writes`,
  `hitTest`, `waits`, `events`. Python only uses advertised features.
- Fixtures, schema tests and generated TypeScript as in stage 0 of the inspector plan.

### 5.3 Python engine (`python/src/wintestkit`)

1. **Backend abstraction** (new `backends/`): a `TargetElement` protocol covering what the
   engine uses from `uia/element.py::UIAElement` today — properties, bounds, children,
   patterns/actions, focus, screenshot rectangle. Two implementations: `UiaBackend`
   (wraps existing code) and `WpfBackend` (inspector client).
2. **Router**: per window, WPF when the window belongs to a WPF process, UIA for non-WPF
   windows. If a WPF window's process has no usable agent, the step fails with the agent's
   error (D5) — no fallback. One place, `engine/resolve.py`.
3. **Locators** (`engine/locator.py`, `engine/properties.py`): existing keys
   (`automation_id`, `name`, `class_name`, `control_type`, `where`) translate to agent
   predicates; managed keys become first-class rather than post-filters; add `type:Is`.
   Semantics of `within`, `depth`, `index`, ambiguity and polling are unchanged.
4. **Queries** (`engine/query.py`): WPF backend sends one `query.find` per poll instead of
   UIA search + batched reads; the 1,000-candidate rule applies only to the UIA backend.
5. **Actions** (`controls.py`, `engine/actions.py`, `uia/input.py`): `mouse` mode computes
   the click point from agent geometry and reuses the existing input code; `pattern` mode
   calls `act.<verb>`. Typed controls (`BoundButton`, `BoundComboBox`, `BoundDataGrid`, …)
   gain WPF implementations with identical public APIs.
6. **Waits and expectations** (`engine/waits.py`, `expect.py`): use `wait.until` when on the
   WPF backend; same timeouts and error messages.
7. **TestComplete helpers**: `find_child(parent, props, values, depth=...)`,
   `find_all_children(...)`, `find(...)` with TestComplete property names via aliases,
   `*`/`?` wildcards, and an optional first-match mode; NameMapping importer emits them.
8. **App lifecycle** (`app.py`, `runtime.py`): attach after the first WPF window appears on
   launch (D4); reattach on process restart; detach at app close.
9. **Diagnostics** (`engine/diagnose.py`, `engine/relocate.py`, `engine/treedump.py`):
   tree dumps, "did you mean" and relocation suggestions use the WPF tree and properties.
10. **Config** (`config.py`): `backend: uia|auto` (`auto` = WPF for WPF windows; default from
    phase 3), `input_mode: mouse|pattern` (default `mouse`), `inspector.writes.allow: [...]`,
    keeping `inspector.*` keys and layering rules. No fallback key (D5).

### 5.4 VS Code extension (`vscode/`)

1. **Spy tree**: shows the WPF tree (visual/logical toggle) for WPF windows, UIA for others;
   labels use type name plus `x:Name`/AutomationId.
2. **Picker**: agent hit test instead of UIA `ElementFromPoint`; highlight from agent
   geometry (`engine/overlay.py` takes a rectangle, unchanged).
3. **Properties pane**: Identity shows WPF identity (`ClrFullClassName`, `x:Name`,
   AutomationId, peer Name, control type) with a source badge; the managed member groups
   become the main property view; UIA properties move to a secondary group.
4. **Suggested locator**: built from WPF identity, verified unique with `query.findAll`
   (unblocks "Copy locator"); prefers stable keys (AutomationId, `x:Name`, type + DataContext)
   over indexes.
5. **Attach UX**: one confirmation per process run, then automatic; when the agent is
   blocked, Spy shows the blocked state and how to fix it (D5), not a UIA view.
6. **Page tree, coverage, element captures, previews**: unchanged contracts; their element
   lookups go through the router.

### 5.5 Reports, replay, coverage

- Step records include the backend used and, for writes/calls (D2), an audit line.
- Coverage maps WPF handles to page definitions the same way it maps UIA nodes.
- Element captures use agent geometry for the crop rectangle.

## 6. Phases and gates

Each phase is separately shippable behind configuration; none changes UIA-only behaviour.

### Implementation workflow (owner instruction, 2026-10-29)

- **All implementation is done by `gpt-6.1-terra` subagents** (Codex provider chosen by the
  owner), one at a time, in the shared checkout, each scoped to a narrow slice with exclusive
  file ownership as in the inspector brief.
- **The parent agent does not write implementation code.** It only plans slices, writes
  subagent briefs, reviews the result (diff, independent re-runs of tests, CI), and hands
  any gaps back to a new `gpt-6.1-terra` subagent to fix.
- The parent owns git: it stages only the slice's changes (never the owner's unrelated
  uncommitted edits), commits, pushes, and confirms CI.
- If `gpt-6.1-terra` is unavailable (usage limit, capacity, auth error), the parent stops and
  asks the owner rather than switching model or provider or writing the code itself.

| Phase | Scope | Exit gate |
| --- | --- | --- |
| 0 | Amend the inspector plan per D1–D7; protocol 2.0 contracts and fixtures | Owner sign-off; schemas and golden fixtures pass in Python and C# |
| 1 | Agent query engine + geometry/state (read-only); Python `query.find`; WPF-backed *find* with UIA-mapped *act* | Same results as today's managed post-filter on the fixture; no 1,000 cap; latency budget met |
| 2 | Backend abstraction + router; WPF backend for properties, waits, `expect` | Parity suite: existing locator/wait tests pass on both backends |
| 3 | Actions: OS input at WPF geometry (`mouse`, default), then peer patterns (`pattern`); typed controls on WPF; virtualized item selection (D6); **switch the default to `backend: auto`** (D7) | Parity suite for every typed control and input mode; actions on objects with no UIA peer; `wtk doctor` detects agent blocks; find a row 5,000 items down without realizing others |
| 4 | Spy WPF-native: tree, picker, Identity, suggestions with uniqueness | Spy DOM + live tests; suggested locators round-trip on the fixture and the real suite's pages |
| 5 | TestComplete helpers + importer output (virtualization moved to phase 3, §6.4) | Migrated `FindChild` samples pass |
| 6 | Optional writes/calls (D2) with allowlist and audit | Off by default; allowlist enforced; audit in reports; security review |
| 7 | Auto-attach on launch, events, stress (100 cycles), six-cell matrix, CI desktop job | Inspector-plan release gates plus new action/stress gates |
| 8 | Docs, skill, migration guide; deprecate the managed post-filter path | Real 27-page suite runs on `auto` with no regressions versus UIA |

Phase 1 alone delivers the biggest TestComplete-like gain (true WPF-tree `FindChild`) while
actions stay on proven UIA.

### 6.1 Phase 1 outcome (2026-10-31)

Managed locators run one `query.findAll` in the agent and map matches back to UIA by
`ElementState.uiaRuntimeId`; `inspector.query: postfilter` keeps the old path. Live gate on the
owned fixture: 18/18 locators identical on both paths, no 1,000-candidate cap, `query.find`
20 ms median on a 5,000-object window. Open cost: end-to-end resolution of a unique match on
that window is ~1.2 s, dominated by the UIA RuntimeId lookup that phase 2 removes for finds.

### 6.2 Phase 2 design (2026-10-31)

Decisions:

- **Backend selection.** `backend: uia | auto` (now default `auto` after the phase 3 implementation switch, D7).
  Under `auto` the router picks per top-level window: the WPF backend when the window's
  process is a WPF process, UIA otherwise. If a WPF window's agent is unavailable the step
  fails with the agent error (D5); there is no fallback. On-demand attach is the default
  from the phase 3 gate; launch-time attach and restart reattach remain in phase 7 (D4).
- **Depth (owner, 2026-10-31).** On the WPF backend `depth=` counts only ancestors that have
  an automation peer, so a locator's depth means the same on both backends. Protocol: Locator
  gains a required `depthMode: "tree" | "peers"`; `peers` counts depth in peer-bearing
  objects below the scope (the scope is depth 0).
- **Identity reads.** The protocol `read` method accepts the single-segment `uia` paths
  (`automation_id`, `name`, `class_name`, `control_type`) with the same peer-derived values as
  predicates, so a WPF element can describe itself for diagnostics and `info()`.
- **Element model.** A `TargetElement` protocol in `backends/` covers what resolution, waits
  and expectations use from `UIAElement` (identity, bounds, enabled, offscreen, focus, process,
  window handle, alive, parent/children, same_as, info). `UIAElement` satisfies it; the new
  `WpfElement` wraps an agent ObjectRef and implements it from `read`, `state.get` and
  `query.*`. Anything else — UIA patterns (text, value, toggle, selection, grid), actions,
  arbitrary UIA `get_property` names, diagnostics — goes through `WpfElement.as_uia()`, the
  phase 1 RuntimeId mapping. This is the designed phase 2/3 split, not a fallback: actions and
  peer pattern reads move into the agent in phase 3. Pattern-based checks on an element
  without a peer fail with a clear "needs a UI Automation peer" error.
- **Resolution.** On the WPF backend every locator link is one `query.findAll` (or
  `query.find` with `index`) scoped to the window or the previous link's handle; `within`,
  `index`, ambiguity and popup search keep their semantics. Results keep agent traversal order.
- **Waits.** The agent implements `wait.until` (feature `waits`) per the protocol; Python uses
  it for `attached`, `visible` and `enabled` on the WPF backend and keeps polling for the
  other states.
- **Out of scope for phase 2:** diagnostics, relocation and suggestions on the WPF tree (use
  `as_uia()` roots); Spy; actions in the agent.

Slices: P2a protocol `depthMode` and `uia` reads; P2b agent `wait.until`; P2c Python
`backends/` with `TargetElement` and `WpfElement`; P2d router, config and resolution on the
WPF backend; P2e waits and `expect` on the WPF backend; P2f parity suite (existing locator,
wait and expect tests run on both backends against the fixture; differences listed and
justified).

### 6.3 Phase 2 parity results (2026-10-31)

This is a **partial result, not phase 2 gate sign-off**. The parametrized live fixture
test uses on-demand inspector attach and exercises the same cases with each backend.

| Scenario | uia | auto |
| --- | --- | --- |
| Identity locators, depth, within, UIA and managed where, shared and lookahead regex | Pass | Pass |
| Duplicate count, index, ambiguity, missing results | Pass | Pass |
| Duplicate element order, compared by UIA RuntimeId | Pass | Pass |
| Popup content resolution | Pass | Pass |
| Wait: attached, detached, visible, hidden, enabled, stable | Pass | Pass |
| Expect: exist, visible, enabled, text, contains, count; selected negations | Pass | Pass |
| Expect: value and UIA property, including negative cases | Pass | Pass |
| TextBox type and clear, checked through its value | Pass | Pass |
| Missing, ambiguous, index and within diagnostic text (two locators each) | Match | Match |
| FullName, nested CLR, field, dependency property, numeric and regex flag predicates | Pass | Pass |
| Click and resulting text | Pass | Pass |
| CheckBox check, uncheck, toggle, checked and negated checked | Pass | Pass |
| RadioButton select and selected assertion | Pass | Pass |
| ComboBox select by name, regex and index; selected value | Pass | Pass |
| ListBox select by name and index; selected items | Pass | Pass |
| Expander expand and collapse; content visibility | Pass | Pass |
| Focused TextBox keyboard input | Pass | Pass |
| Top-level and context menu popup item actions | Pass | Pass |
| DataGrid row and cell items | Pass (UIA) | Pass (UIA) |
| Hover, double-click and right-click visible effects | Pass | Pass |
| Expect: all 12 methods, positive and negated pass/failure; failure messages compared | Pass | Pass |
| Wait: disabled timeout and delayed enable; timeout messages compared | Pass | Pass |
| Managed numeric, boolean and enum equality; nested and absent members; unreadable getter | Pass | Pass |
| Regex case-insensitive, anchored and unanchored predicates | Pass | Pass |

The serial backend-filtered module runs took 43.72 s for uia (10 passed, 42
deselected) and 33.32 s for auto (10 passed, 42 deselected), including startup.
These filters select backend-specific tests and tests whose names mention a backend;
they exclude the shared assertion and wait message comparisons, which exercise both
backends within each case. They are therefore not full-matrix timings.

A missing nested managed member previously raised `memberNotFound` instead of
being treated as a non-match; the query predicate now applies decision 10 at every
path depth. A deadline during a final assertion poll also no longer drops the last
completed missing-element diagnostic. The throwing-getter case remains an explicit
`valueUnreadable` error.
Grid item operations remain on UIA on both backends. Integration tests use native/Tk
windows or no app, and the Calculator example targets Windows Calculator rather than
this WPF fixture.

**Gate verdict (owner, 2026-11-06): passed.** Every row of the parity matrix passes on both
backends. The one accepted difference is that DataGrid row and cell operations go through
UIA on both backends via `as_uia()`, per the §6.2 phase 2/3 split. The two bugs found by the
matrix (nested missing managed member and lost diagnostic on a final-poll deadline) are
fixed with regression tests. The intermittent assertion-redaction failure seen once was not
reproduced in later runs and remains an open observation. Per-backend timings exclude the
shared message comparisons. The phase 3 implementation has since switched the default to `backend: auto` (D7).

### 6.4 Phase 3 design (2026-11-06)

Owner decision (2026-11-08): enable the inspector and use on-demand attach by default
with `backend: auto`. This pulls the essential first-use portion of D4 into the phase 3
gate. Phase 7 retains launch-time attach, reattach on restart, and events.

Decisions (owner, 2026-11-06):

- **Input mode default.** `input_mode` now defaults to `mouse` on both backends, switched together with
  `backend: auto` (D1, D7); per-call `mode=` keeps overriding it.
- **Item selection.** `act.realizeItem` and the `virtualItems` feature (D6) move from phase 5
  into phase 3, so typed-control item selection on the WPF backend never goes through
  `as_uia()`. Phase 5 keeps only the TestComplete helpers and importer output.

Design:

- **Agent actions** (new `Agent/Actions/`). Every `act.*` method in the protocol runs on the
  owning Dispatcher through the existing executor and deadlines, using the element's
  automation peer in-process. One action runs at a time per Dispatcher; a hung action marks
  the Dispatcher unresponsive as reads do. An unsupported pattern, or an element without a
  peer, fails `actionUnsupported`; results never carry control values. The agent advertises
  `actions` and `virtualItems` only when implemented.
- **Pattern mode on WPF.** `engine/actions.py` dispatches a `WpfElement` to the `act.*` verb
  from the protocol mapping table instead of `uia_of()`. Reads (`get_text`, `get_value`,
  `is_checked`, `is_selected`, `selected_items`, item names) come from the agent, with the
  same redaction rules as today (password fields are never read).
- **Mouse mode on WPF.** Click points come from `state.get`: the centre of the element's
  bounds, or of the named part for sub-part actions (`comboDropDown`, `expanderToggle`,
  `treeItemExpander`, scroll parts, `gridColumnHeader`). Python verifies the foreground
  window from `state.windowHandle` before injecting input, and fails rather than guessing on
  a missing, invisible, clipped or unsafe rectangle. Elements without an automation peer can
  be clicked, hovered and typed into in this mode.
- **Typed controls.** `BoundComboBox`, `BoundListBox`, `BoundDataGrid`, `BoundTreeView` and
  `BoundTabControl` select items by data search (`act.realizeItem`) followed by `act.select`
  (pattern) or a click on the realized container's bounds (mouse); public APIs are unchanged.
- **Doctor.** `wtk doctor` reports when the agent cannot load (`blockedByPolicy`,
  `unsupportedTarget`, ...) so a blocked machine is found before a run under `backend: auto`.
- **Gate.** The parity suite covers every typed control in both input modes on both
  backends, actions on objects with no UIA peer, and selecting a row 5,000 items down
  without realizing the others. Defaults have switched and docs are updated; owner sign-off remains.

Slices: P3a agent actions focus, bringIntoView, scrollIntoView, invoke, toggle, expand,
collapse, select; P3b agent setValue, setRange, scroll and the Python client `act.*`
methods; P3c agent `act.realizeItem`; P3d pattern mode and reads on the WPF backend; P3e
mouse mode on WPF geometry; P3f typed controls on WPF; P3g `wtk doctor` agent-block check;
P3h parity suite, default switch and docs.

### 6.5 Phase 3 parity results (2026-11-08)

The default-config gate exercises a WPF action with no backend, input mode, or inspector
settings, including default on-demand attachment (D4 partially delivered).

The matrix records assertions in `test_wpf_query_gate_real.py`, not a gate verdict.
Pass means the listed outcome is asserted for that configuration; the run results below
must be read separately. `n/a` means the operation is not input-mode-dependent and is
exercised under both configured modes. `not covered` means this module does not assert
that case. Each row names the specific operation or outcome tested, not every control API.

| Parity row | UIA pattern | UIA mouse | auto pattern | auto mouse |
| --- | --- | --- | --- | --- |
| Button: click and effect | Pass | Pass | Pass | Pass |
| TextBox: type, clear and value | Pass | Pass | Pass | Pass |
| CheckBox: check, uncheck, toggle | Pass | Pass | Pass | Pass |
| RadioButton: select | Pass | Pass | Pass | Pass |
| ComboBox: items and selection | Pass | Pass | Pass | Pass |
| ListBox: items and selection | Pass | Pass | Pass | Pass |
| ListItem: select | Pass | Pass | Pass | Pass |
| DataGrid: access and selection | Pass | Pass | Pass | Pass |
| TreeView: select | Pass | Pass | Pass | Pass |
| TabControl: select | Pass | Pass | Pass | Pass |
| Text: read | Pass | Pass | Pass | Pass |
| click: effect | Pass | Pass | Pass | Pass |
| double_click: effect | n/a | n/a | n/a | n/a |
| right_click: context menu effect | n/a | n/a | n/a | n/a |
| hover: effect | n/a | n/a | n/a | n/a |
| focus: followed by keyboard input | n/a | n/a | n/a | n/a |
| type and clear: value | Pass | Pass | Pass | Pass |
| press: value | n/a | n/a | n/a | n/a |
| ensure_visible: outer scrolled descendant | UIA reports on-screen; no-op | UIA reports on-screen; no-op | Pass | Pass |
| ensure_visible: off-screen cached virtualized item | Pass | Pass | Pass | Pass |
| expand/collapse: visibility | Pass | Pass | Pass | Pass |
| context menu: choose item | Pass | Pass | Pass | Pass |
| peerless element: click | no UIA peer | no UIA peer | unavailable pattern metadata error | Pass |
| partly clipped: click | Pass | Pass | Pass | Pass |
| virtualized item 4,999: select | Pass | Pass | Pass | Pass |
| doctor agent check | backend-independent | backend-independent | Pass (auto) | Pass (auto) |
| disabled: click timeout message | Pass | Pass | Pass | Pass |
| missing item: selection message | Pass | Pass | Pass | Pass |
| read-only: typing outcome and text | Pass | Pass | Pass | Pass |
| password: outcomes and redaction | Pass | Pass | Pass | Pass |
| hidden in collapsed Expander: click | omitted by UIA | omitted by UIA | hidden timeout | hidden timeout |
| hidden in collapsed Expander: type | Pass | Pass | Pass | Pass |
| failing typed expectations: messages | Pass | Pass | Pass | Pass |

UIA omits elements inside a collapsed Expander; auto finds them as hidden. The peerless
element is addressable only on auto; pattern mode fails on unavailable pattern metadata,
while mouse mode clicks it. The doctor agent check is covered by
`python/tests/unit/test_doctor_agent_real.py` in auto; it is backend-independent.
The UIA provider reports the outer scrolled descendant as on-screen, so ensure_visible
does not scroll it. Virtualized coverage uses an off-screen item realized in the list's
cache, then verifies that ensure_visible scrolls it into view.
The shared foreground helper retries through a temporarily attached foreground input thread
when Windows denies direct activation; the existing ownership, foreground and hit tests remain. DataGrid `row()`, `cell()`, `row_count()`,
`column_count()` and `find_row()` still use the UIA Grid pattern on both backends. Grid
row mouse selection clicks a safe row header when available, otherwise it uses
`act.select`, as UIA does. UIA select uses the selection pattern in both input modes.
DataGrid cell selection names still use provider conversion.

`clickPoint` tries a bounded set of candidate points, so an irregular visible region can
yield none. A WPF action that times out on a disabled control may spend up to 2 s on one
diagnostic poll. Agent handles to unrooted objects can go stale before their first lookup.

Median wall times over three selections (seconds, pattern/mouse) were: ListBox UIA
0.260/0.288 and auto 0.193/0.296; DataGrid UIA 1.014/1.165 and auto 0.569/0.630.
These are fixture measurements, including selection overhead, and vary with machine load.

Serial measurements with the expanded coverage, from `python/` with
`WTK_INSPECTOR_REAL=1`:

- `-k auto`: 29 passed, 78 deselected in 82.75 s.
- `-k uia`: 29 passed, 78 deselected in 118.67 s (a preceding run hit an inspector limit).
- Full module: 107 passed in 437.75 s.

Earlier post-fix serial runs before the cached virtualized-item cases:

- `-k auto`: 27 passed, 76 deselected in 73.24 s.
- `-k uia`: 27 passed, 76 deselected in 102.20 s.
- The combined five-module live suite passed twice: 109 passed in 386.71 s and 388.09 s.

Historical pre-fix serial module runs measured process wall time:

- `-k uia`: 98.299 s, 23 passed and 71 deselected.
- `-k auto`: 65.717 s, 16 passed, 7 failed and 71 deselected.
- Full module: 369.459 s, 94 passed.

The filters match pytest node IDs, not all tests that exercise a backend. Each selects
23 parametrized or named cases and deselects 71; tests that loop over both backends without
those words in their IDs are omitted. The auto-filtered failures reported inability to
activate the target window, refusing global input.

**Gate verdict (owner, 2026-11-09): passed.** Final verification at commit `e97a824` ran the
full live suite twice serially, with 116/116 passing in each run, and CI was green. The parity
matrix passes with the differences recorded above. Actions on peerless elements work in mouse
mode, while pattern mode reports the pattern as unavailable. Item 4,999 of 5,000 is selected
without realizing the others.

`wtk doctor` block detection is partly proven: each block code and hint is unit-tested with
fakes, and the live test covers the successful case. A real AppLocker or antivirus block has
not been exercised. The real 27-page suite has not yet been run; that remains the phase 8 gate
and is the largest remaining risk now that `backend: auto` is the default.

Open items remain. What occupies the UI thread after `act.bringIntoView` on RichText is
unmeasured, and occasional ~250 ms `release` timeouts are unexplained. One earlier
`limitExceeded` deadline error in `test_auto_expect_missing_message_matches_uia` occurred before
the final retry boundary change and has not recurred. The original `ensure_visible` timeout
cause is likely the busy UI thread (decision 16), but is not proven. DataGrid `row()`, `cell()`,
`row_count()`, `column_count()` and `find_row()` still use the UIA Grid pattern, and DataGrid
cell selection names may be unavailable on some machines. Handles to unrooted objects can go
stale before first lookup, and a timed-out action on a disabled control can take up to 2 s longer.

VS Code follow-ups remain: the settings model still states the old defaults in
`vscode/src/settings/model.ts`, `files.ts`, and `media/settings/editor.js`, and the machine-health
summary does not know the `wpf_agent` check.

### 6.6 Phase 4 design (2026-11-09)

Gate (owner, 2026-11-09): suggested locators round-trip on the WPF fixture, verified here. The
owner checks real suite pages separately; that part of the gate stays open and does not block
phase 5.

Design:

- **Nodes.** The server's node registry holds a `TargetElement`, so a node is either a
  `UIAElement` or a `WpfElement`. A WPF node's id is derived from its session, object id and
  generation and never collides with a runtime id. Nodes carry `source: "wpf" | "uia"`. Existing
  callers of `inspect.*` keep their contracts; element lookups go through the router.
- **Tree.** Top-level windows still come from `inspect.roots`. Under a WPF window,
  `inspect.children` walks the agent tree, with `tree: "visual" | "logical"` (default `visual`,
  the tree TestComplete users know). Other windows stay on UIA. Labels use the type name plus
  `x:Name` or AutomationId.
- **Blocked agent (D5).** A WPF window whose agent cannot load does not fall back to a UIA view:
  the node reports the agent error code and its fix, as `wtk doctor` does.
- **Picker.** The hook keeps the mouse work. For a point over a WPF window the worker resolves
  the window, then calls the agent `hitTest`, so objects with no automation peer can be picked.
  Highlight comes from `state.get` bounds through the unchanged overlay. Other windows keep
  `ElementFromPoint`.
- **Identity and properties.** Identity shows `ClrFullClassName`, `x:Name`, AutomationId, peer
  Name and control type with a source badge. Managed member groups become the main view; UIA
  properties move to a secondary group.
- **Suggested locator.** On a WPF node, candidates are tried in the order AutomationId, `x:Name`,
  CLR type plus peer Name, then ancestor-scoped forms, and an index only as a last resort. Each
  is verified unique with `query.findAll`, and the result is checked by resolving it back to the
  same object. A candidate that cannot be verified is not offered as unique.
- **Attach.** One confirmation per process run, then automatic. A new process run asks again.
- **Unchanged:** page tree, coverage, element captures and previews keep their contracts.

Slices: P4a extension follow-ups from phase 3 (settings defaults, `wpf_agent` in the health
summary); P4b agent `hitTest` and Python client; P4c server WPF nodes, tree and blocked state;
P4d picker and highlight; P4e suggested locators with round-trip verification; P4f extension UI
(tree, toggle, Identity, property groups, blocked state, attach); P4g live round trips, Spy tests
and docs.

#### Phase 4 results

- `python/tests/unit/test_managed_server_real.py` exercises the fixture tree, peerless
  selection, picker and popup, and large pages. Server suggestions round-trip for the
  AutomationId button, both peerless targets, the no-AutomationId `x:Name` target, each
  of the two same-name buttons via a scoped locator, and a realized ListBox item in a
  `VirtualizingStackPanel`. The duplicate query returns two matches; unit coverage checks
  that an unresolved ambiguous candidate is not reported unique. `test_wpf_suggest.py`
  also covers candidate ordering and verification with a fake agent tree.
- All fixture round trips passed; the full owned live suite passed twice (120 tests each).
  The fixture part of the gate is ready for the owner's sign-off. The real-suite page
  checks remain open.
- On pre-phase-4 commit `3dfe44b`, the extension integration suite had 6 passing and 3
  failing: Calculator discovery and configuration editor timed out after 60 seconds,
  and delayed-report preview failed `the report opened once it was written`. The
  Calculator and delayed-report failures therefore reproduce before phase 4.
- Observed 200-child pages on a 5,000-child parent take about 0.7–1.2 seconds. Saved previews
  are skipped for peerless elements. System DPI scaling was not exercised; a 150% layout
  transform was. A real AppLocker or antivirus block was not exercised.

**Gate verdict (owner, 2026-11-10): fixture part passed.** Suggested locators round-trip on
the fixture as listed above. The real-suite page checks stay open for the owner and do not
block phase 5.

### 6.7 Phase 5 design (2026-11-10)

Scope: TestComplete helpers and importer output (virtualization moved to phase 3).

Design:

- **Property names.** One shared map turns TestComplete property names into locator keys:
  `WPFControlName` to `x:Name` (`clr:Name`), `ClrFullClassName` to `type:FullName`,
  `ClrClassName` to the short type name, `WPFControlText` to the element's text,
  `WPFControlOrdinalNo` to an index, `Visible` and `Enabled` to state conditions. Any other
  name becomes a managed `clr:` path, since TestComplete exposes .NET members directly. Names
  that cannot be mapped are an error, not a silent drop.
- **Wildcards.** `*` and `?` in string values become anchored regexes through the shared
  regex subset; other characters are matched literally.
- **Helpers.** `find_child(parent, props, values, depth=1)`, `find_all_children(parent, props,
  values, depth=1)` and `find(parent, props, values, depth=...)` follow TestComplete's
  argument order and depth meaning. `find_child` returns a lazy element for the first match
  in tree order, so a missing element fails when used, with the normal diagnostic, and
  `.exists()` works; `strict=True` keeps WinTestKit's ambiguity error. `find_all_children`
  returns a snapshot list. They work on both backends.
- **Importer.** The NameMapping importer maps properties through the same table, converts
  wildcards, and turns extended find into a descendant search with the matching depth.
- **Gate samples.** A set of TestComplete-style `FindChild`, `FindAllChildren` and `Find`
  calls with their migrated WinTestKit form, run against the fixture on both backends.

Slices: P5a property map and wildcard translation; P5b helpers; P5c importer output; P5d
gate samples, docs and the test-writing skill's migration reference.

### 6.8 Phase 5 results

The live migration sample file records the original and migrated forms. After protocol
decision 20 (commit `7c67073`), protected elements allow type identity and an allowlist
of WPF base-class members. All 14 samples pass on `auto`; on `uia`, the other 13 pass
and the peerless sample is a verified expected difference because UIA cannot see an
element without an automation peer. The generated NameMapping round trip passes on
`auto`, including the hierarchy, wildcard and depth-one negative case. The full live
suite passed 125/125. The XML extended-find spellings remain unconfirmed.
The phase 5 gate is ready for owner sign-off.

**Gate verdict (owner, 2026-11-11): passed.** All 14 migrated samples pass on `auto`, the
peerless sample is a verified UIA difference, and the NameMapping round trip passes. The
extended-find XML spelling stays unconfirmed until a real NameMapping export is checked.

### 6.9 Phase 6 design (2026-11-11)

Scope: optional writes and calls (D2), off by default, allowlisted and audited. The wire
contract is fixed in wpf-protocol-2.md (`write.setProperty`, `write.call`, `WriteAudit`,
`writeDenied`, `writeRateExceeded`, exact scalar types, 10 attempts per second).

Design:

- **Config.** `inspector.writes.allow` lists entries as strings: `Namespace.Type.Property`
  for a property, `Namespace.Type.Method(System.String,System.Int64)` for one exact method
  overload. Entries match the exact runtime type, never a base type. The list is empty by
  default, so writes are off. It reaches the agent only through the protected bootstrap.
- **Agent.** `write.setProperty` (dependency properties via `SetCurrentValue`, CLR setters
  otherwise) and `write.call` (public instance methods, scalar arguments, no return value)
  run on the owning Dispatcher, serialized like actions. Anything not on the allowlist is
  `writeDenied`. Every attempt, including denied, failed and timed-out ones, produces an
  audit record without values. Protected identities and redacted members are always denied.
- **Python.** `element.set_property(name, value)` and `element.call(name, *args)` on bound
  elements, WPF backend only; on UIA they fail with a clear error.
- **Report.** Every audit record goes into the step record, the HTML report and `wtk report`.
- **Security review.** A written review of the allowlist parsing, bootstrap transport,
  enforcement points, rate limit, audit completeness and redaction, recorded in this plan.

Slices: P6a agent writes, allowlist enforcement, rate limit and audit; P6b config,
bootstrap, client and element API; P6c report audit, docs, live tests and the security
review.

### 6.10 Phase 6 security review (2026-11-11)

- **Policy and layering:** `python/src/wintestkit/inspector/write_policy.py` validates exact
  names, uniqueness and entry limits; `config.py` rejects local allowlists and limits overrides.
  Shared repository configuration supplies the policy. Result: local config cannot grant writes.
- **Bootstrap:** `python/src/wintestkit/inspector/bootstrap.py` creates and verifies a protected,
  user-SID-only ACL and a 30-second expiry. `Agent/Session/BootstrapReader.cs` rejects reparse
  points, consumes the file, and checks expiry and target process identity. The same user and
  privileged administrators can still access or change the material.
- **Enforcement:** `Agent/Writes/WriteEngine.cs` compares the exact runtime type, resolves property
  declarations and dependency-property wrappers, and denies ambiguous, protected and redacted
  members. It accepts only exact scalar types and rejects static, generic, ref/out and params
  methods. Inherited members require an entry naming the actual runtime type.
- **Rate:** `Agent/Session/RequestDispatcher.cs` counts attempts before scheduling or parsing;
  its rolling one-second queue admits ten, including attempts denied for other reasons.
- **Audits and deadlines:** dispatcher error handling supplies an audit for early agent failures;
  `WriteEngine.cs` supplies one at the deadline even if target code remains running. Python's
  `model.py` now supplies a redacted `clientFailure` audit when failure precedes or loses the
  agent response. Its outcome cannot prove whether a lost-response operation took effect.
- **Values and exceptions:** writes omit values from step arguments and agent audits. The
  dispatcher emits generic errors and `WriteEngine.cs` records only the target exception type,
  not its message. Report rendering uses audit fields rather than values. These protections do
  not prevent target application code itself from logging data or embedding it in exception
  type names, or arbitrary application output from appearing elsewhere in a report.
- **Residual risks:** an allowed method can have arbitrary side effects, a setter or method can
  hang the target UI thread or complete after a timeout, and a local administrator or anyone
  able to edit the shared repository policy can grant access. Audit recording requires a live
  test step and cannot guarantee persistence after process termination.

### 6.11 Phase 6 results

The owned-fixture live gate passed 128 tests on 2026-11-11. The write checks cover default
denial, allowed dependency and CLR properties and method calls, adjacent and protected-member
denials, local configuration rejection, rate limiting, audit recording and value-free reports.
The gate (off by default, allowlist enforced, audit in reports and security review) is ready for
the owner's sign-off.

Open item: a lost response or timeout cannot establish whether target code eventually performed
the operation; the recorded failure must not be treated as proof of no side effects. Target code
can also log its own inputs, outside the audit's control. The missing client-side failure audit
identified in the review was fixed with a redacted fallback and a regression test.

**Gate verdict (owner, 2026-11-11): passed.** Writes are off by default, the allowlist is
enforced, every attempt is audited in reports, and the security review is recorded in §6.10
with its residual risks.

### 6.12 Phase 7 design (2026-11-11)

Owner decisions (2026-11-11): the CI desktop job runs on a self-hosted runner on the owner's
machine, registered by the owner and running interactively in a logged-in desktop session;
release signing is deferred, so payloads stay labelled as unsigned development builds and
signing becomes its own task once a code-signing certificate exists.

Design:

- **Attach on launch (D4).** A new `inspector.attach: on-launch` mode, and the default, attaches
  as soon as the first WPF window of a launched or attached process appears, so a blocked agent
  fails the first step instead of a later one. `on-demand` and `manual` stay available. When the
  process restarts, the runtime reattaches to the new process run; at app close it detaches.
- **Events.** The agent implements `events.subscribe` / `events.unsubscribe` for `windowOpened`,
  `windowClosed` and `treeChanged`, bounded and coalesced. Python uses them to wait for windows
  and tree changes instead of polling where a session exists, keeping polling as the fallback
  for UIA windows.
- **Stress.** 100 attach/detach cycles and 100 launch/close cycles without growth in listeners,
  handles, threads, leases or memory, plus a sustained action run; thresholds are written into
  the tests.
- **Six-cell matrix.** The fixture runs on .NET 10, .NET 8 and .NET Framework 4.8, each x64 and
  x86, with a live smoke subset per cell, as the inspector plan's release gates require.
- **CI desktop job.** A workflow job on the self-hosted runner wakes the display, runs the live
  suite and the six-cell smoke, and publishes results. Setup instructions live in the docs.
- **Release gates, except signing.** Reproducible package, `check_release.py` lockstep, and a
  clean-environment install smoke test.

Slices: P7a attach on launch, reattach and detach; P7b agent events; P7c Python event waits;
P7d stress tests; P7e six-cell matrix; P7f CI desktop job and runner setup docs; P7g release
gates except signing.

P7d results: the attach test measured 400 cycles at 20-cycle checkpoints; sustained
actions were sampled every 100 cycles. Growth uses the median of three endpoint samples,
with recorded-series unit tests. The launch thread gate counts named WinTestKit threads.
No product leak was found; pattern clicks use the no-op `NestedButton`.

P7e results: two live smoke runs passed all six cells: net48 x86 and x64
(`4.0.30319.42000`), net8 x86 (`8.0.6`) and x64 (`8.0.20`), and net10 x86
(`10.0.15`) and x64 (`10.0.11`). The manifest cell list matches the six cells;
its `verified` flags remain false pending the full P7g release gates.

## 7. Test strategy

- **Parity suite**: run the same locator, wait, action and typed-control tests under
  `backend: uia` and `backend: wpf` against the fixture; differences must be listed and
  justified.
- **Fixture additions** (`wpf-inspector/tests/Fixtures`): elements without UIA peers, template
  parts, adorners, deep virtualized lists (10,000+ rows), controls whose AutomationId differs
  from `x:Name`, slow and hanging actions, writes with side-effect counters.
- **Agent unit tests** for query, geometry, actions, waits, virtualization on STA Dispatchers.
- **Live tests** (`WTK_INSPECTOR_REAL=1`) for each phase's gate.
- **Real-suite check**: the owner's 27-page WPF suite (see project memory) on each phase that
  changes discovery or actions.
- **Performance budgets** (owned .NET 10 x64 fixture): `query.find` on a 5,000-object window
  ≤ 100 ms median; click (geometry + input) ≤ 150 ms; wait re-check ≤ 50 ms.

## 8. Risks

| Risk | Mitigation |
| --- | --- |
| Actions and writes change app state from inside the process | D1 prefers real input; D2 opt-in allowlist and audit; actions serialized per Dispatcher |
| A hung action or getter blocks the UI thread (and UIA) | Existing unresponsive-Dispatcher handling; per-call deadlines; documented |
| Behaviour differs from a real user (peer patterns bypass input handling) | `mouse` mode default for clicks; parity tests per control |
| Agent unavailable (policy block, unsupported runtime) | Steps fail with the agent error (D5); `wtk doctor` detects blocks before a run; signed payloads; `backend: uia` opt-out |
| Realizing virtualized items has side effects | Data-level search first; realize only the single match on explicit action |
| Divergence between backends confuses users | Router logs the backend per step; parity suite; one public API |
| Larger trusted surface in the agent | Protocol 2.0 security review; allowlists; no arbitrary code execution |
| Cost per test with `launch: per-test` (attach every launch) | Measure in phase 7; recommend `launch: attach` for large suites |

## 9. Changes to the inspector plan (to amend in phase 0)

- §1 "Meaning of all attributes": allow realization (D6) and writes/calls (D2) as opt-in.
- §5 regex rule: allow agent-side regex with a timeout.
- §6 operations: add protocol 2.0 methods; remove "no invoke, write" except where D2 says so.
- §7: UIA association becomes optional — WPF handles are valid action targets.
- §10: managed constraints are no longer only post-filters; the candidate cap applies to the
  UIA backend only.
- §11 Spy: WPF tree and picker become primary for WPF windows.

## 10. What stays as is

- The agent loader, session, pipe security, bootstrap and redaction.
- Python client transport, sessions and payload packaging.
- UIA backend code paths for non-WPF windows and the `backend: uia` opt-out.
- Page objects, test APIs and reports — callers do not change.
