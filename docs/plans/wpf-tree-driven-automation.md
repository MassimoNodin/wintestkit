# WPF-tree-driven automation: migration plan

Status: decisions D1–D7 made (§3); implementation not started. Planning date: 2026-10-29.
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
| D4 | **Attach model** | Attach automatically when WinTestKit launches or attaches to a WPF app; one attach per app process |
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
| 3 | Actions: OS input at WPF geometry (`mouse`, default), then peer patterns (`pattern`); typed controls on WPF; **switch the default to `backend: auto`** (D7) | Parity suite for every typed control and input mode; actions on objects with no UIA peer; `wtk doctor` detects agent blocks |
| 4 | Spy WPF-native: tree, picker, Identity, suggestions with uniqueness | Spy DOM + live tests; suggested locators round-trip on the fixture and the real suite's pages |
| 5 | Virtualization (D6) and TestComplete helpers + importer output | Find a row 5,000 items down without realizing others; migrated `FindChild` samples pass |
| 6 | Optional writes/calls (D2) with allowlist and audit | Off by default; allowlist enforced; audit in reports; security review |
| 7 | Auto-attach on launch, events, stress (100 cycles), six-cell matrix, CI desktop job | Inspector-plan release gates plus new action/stress gates |
| 8 | Docs, skill, migration guide; deprecate the managed post-filter path | Real 27-page suite runs on `auto` with no regressions versus UIA |

Phase 1 alone delivers the biggest TestComplete-like gain (true WPF-tree `FindChild`) while
actions stay on proven UIA.

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
