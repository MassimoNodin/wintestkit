# WinTestKit extension: product and usability review

Reviewer: Claude Opus 5.5 (design sub-agent). Date: 18 October 2026. Scope: a product and usability review only. No source, build, or configuration changes were made. This file is the only output.

Parent audit note: screenshot observations and the principal source findings were checked after this review. References below to a 27-page suite, a few hundred tests, TestComplete migration goals, a particular main pain, or an agreed never-self-heal principle came from reviewer-local project memory, not from this user's current request or the screenshot. Treat those as unconfirmed background assumptions, not established user requirements. Feature proposals and effort estimates are hypotheses, not validated research. The original review text is retained for attribution.

---

## 1. Materials inspected and overall assessment

### What I actually looked at

- **The full feature inventory**: `docs/reviews/extension-feature-inventory-2026-10-18.md` (all 19 sections).
- **The user's screenshot**: `C:/Users/massi/.t3/userdata/attachments/fab1f2f2-…-734b64fa-….png`. I viewed it directly with an image-capable reader. It is 2000×835 px. I also made enlarged local crops of the Test Target, Page Tree, Spy, editor and status bar regions in `%TEMP%\wtkcrop`. The original file was not modified. The crops only enlarge the existing pixels, so some small glyphs (for example, whether **Add to page…** is enabled) are still uncertain. I say so where it matters.
- **Source spot checks** to verify or correct claims in the inventory:
  - `vscode/package.json`
  - `vscode/media/spy/spy.js`
  - `vscode/src/settings/testAppModel.ts` and `testApp.ts`
  - `vscode/src/statusBar.ts`
  - `vscode/src/editor/highlightCommands.ts`, `diagnostics.ts`, `checkStatus.ts`, `flowRuns.ts`
  - `python/src/wintestkit/server.py`, `coverage.py`, `targets.py`, `commands/check.py`
  - `vscode/README.md`
- **Background context** from project memory: the real target is a WPF suite of about 27 pages and a few hundred tests, migrating from TestComplete. The main stated pain is "a box moved to another window: what broke and where did it go?" The agreed principle is to diagnose relocations and never self-heal.

I did not run the extension, start a test application, or run tests. Everything I say about runtime behaviour is either visible in the screenshot or read from code, and I label which.

### Independent product assessment (short version)

WinTestKit's engine and its supporting features are stronger than its first impression suggests. These are features many commercial desktop tools lack:

- strict locator resolution
- relocation diagnostics ("found in another window")
- exact-object definition coverage in Spy
- staged launch progress
- a page-model navigator that understands mounted components
- Check/Highlight offering to launch the app and retry

The weakness is not missing capability. It is **orientation**:

- The sidebar presents three panels with overlapping vocabulary: *Explorer*, which collides with VS Code's own Explorer; *Page Tree*; and *Spy → Objects*.
- The lifecycle has two names for one idea (Spawn and Launch).
- The most important run surface, native Testing, has no signpost inside the WinTestKit container.
- Several surfaces behave differently when the target is stopped. The screenshot catches exactly that: the app is stopped, Spy shows unrelated desktop windows without saying why, and the inspector says "This project has no pages" next to a populated Page Tree.

My central recommendation is to make three things visible at all times:

1. **Which app** is targeted.
2. **Whether it's running and who owns it.**
3. **Whether you're looking at code or at the live app.**

Then add one deliberate signpost each for the hidden capabilities: Testing, reports, trace, and relocation hints. Most of the high-value work is copy, state handling and entry points (S/M effort), not new subsystems.

---

## 2. Screenshot observations

The screenshot is a full-screen overview of an ultrawide display, so text that looks tiny here is not evidence of tiny UI fonts. I don't comment on font size.

### 2.1 Test Target (top of sidebar)

| Observation (visible) | Inference (mine) |
|---|---|
| Header reads **Test Target · Stopped**, with a gear icon on the right. | The state badge is in the header's secondary text, which is low-contrast. It's correct but easy to miss. |
| Four equal-sized tiles in one row: **calc** (calculator icon and chevron), **Spawn** (rocket and chevron), **wintestkit / calculator-tests** (folder icon), **Launch** (green play icon). | Configuration choices (app, mode, project) and the one action (Launch) have identical visual weight. A beginner can't tell which tile *does* something and which *chooses* something. |
| The mode tile says **Spawn**; the action tile says **Launch**. | The same lifecycle concept has two verbs. This confirms the naming inconsistency noted in the inventory. |
| The project tile shows **wintestkit** as the title and **calculator-tests** as the subtitle. The breadcrumb shows `examples > calculator-tests > pages > components`. | It's ambiguous whether "wintestkit" is the workspace, the repository, or the project name. The meaningful identifier (calculator-tests) is in the smaller text. |
| There's an empty band roughly one tile high between the tile row and the Explorer header. | Probably a reserved slot for status messages. When there's no message, it is dead space in a crowded sidebar. |

### 2.2 Explorer: Page Tree and Flows

| Observation | Inference |
|---|---|
| Header reads **Explorer · Page Tree**, with refresh on the right. | "Explorer" is VS Code's file explorer to every user. Two Explorers in one window is a naming collision. |
| **Page Tree** and **Flows** are large card-style buttons, each roughly the height of a Test Target tile. | The tab switcher uses about as much vertical space as a row of content. Compact tabs or a segmented control would recover it. |
| `CalculatorModePage` (pages\calculator.py) is expanded. Beneath it, `navigation: NavigationPane` (pages\components\navigation.py) is expanded, showing `root *[id="NavView"]`, `toggle Button · *[id="TogglePaneButton"]`, and `standard`, `scientific`, `programmer` (all ListItem). The collapsed siblings are number_pad, operators and display_controls. Below are the root pages: CalculatorWindow, ProgrammerPage, ScientificPage, StandardPage. | The tree communicates composition (mounted components) well. That is one of its real strengths. |
| The selected `root` row shows **eye** and **tick** icons at the right edge. | These are the restored per-row Highlight and Check affordances. They appear on hover or selection, so new users won't know they exist until they hover. |
| No check-status icons are visible on any row. | No checks have been run in this session, which is consistent with the stopped app. |
| The tree shows locators as `*[id="NavView"]`, while the Python source says `automation_id="NavView"`. | That's a third locator notation (alongside Python and the Spy property names) for users to learn. It's compact, but `#NavView` or `automation_id="NavView"` would align better with the code users write. |

### 2.3 Spy

| Observation | Inference |
|---|---|
| Toolbar: a primary blue **Pick element** button, then refresh, collapse-all and pin icons. There is no **Show Other Apps** toggle. | Confirmed in code: that toggle is hidden when the app isn't running (`spy.js:265-267`). So in the stopped state there's no visible scope control *and* no explanation of the current scope. |
| **Objects · 9 loaded**: Taskbar, *navigation.py - wintestkit - Visual Studio Code* (selected), T3 Code (Beta), F1® 25, Steam, a Chrome window with the user's profile name, Epic Games Launcher, NVIDIA GeForce Overlay, Program Manager. | With calc stopped, Spy shows the whole desktop. That's legitimate (you can explore another app), but **nothing says "calc is not running; these are other desktop windows"**. The "Application not running" empty state only appears when no roots are loaded (`spy.js:366-372`), so it never appears here. |
| Object names are truncated ("…Visual Studio Co", "…Google C"), while a type column ("Pane"/"Window") uses part of the width. | In the narrow side-by-side layout, the type column costs name space. |
| Inspector: VS Code window icon, the name, "Window · Win32". **Defined in pages: "This project has no pages."** Identity: Name; Control type: Window; Automation ID: —; Class: Chrome_WidgetWin_1. State: Enabled true, Offscreen false. | See 2.5: the "no pages" text is explained by the code. |
| **Suggested locator**: "Select a window descendant to generate an element locator", in monospace inside a code-like box. **Copy locator** looks disabled. **Add to page…** is accent-coloured; I can't tell at this resolution whether it's enabled. | Putting guidance text inside a code box makes it read like generated code. If Add to page… is enabled for a root window that has no locator, that's confusing; if it's disabled, its accent colour still invites a click. |
| **Highlight** (top right of the inspector) appears enabled. | Highlighting the VS Code window from VS Code is harmless, but it shows that Spy's context isn't anchored to the target app when the app is stopped. |

### 2.4 Editor, terminal and status bar

| Observation | Inference |
|---|---|
| `navigation.py`: a CodeLens **Check all elements in this class exist** above `class NavigationPane(Page)`, and **Highlight element \| Check exists** above each of the five attributes (lines 9, 11–14). | The intended restored behaviour is visible and correct. For dense page files, the per-element lens lines double the vertical height of the definitions block. |
| Lines 28–31: `_open_pane` with the docstring **"The pane items only exist while the pane is open."** | This is the most important line in the screenshot for product design. **Check all elements in this class exist** run against a closed pane reports `standard`, `scientific` and `programmer` as not found, and the status-bar summary calls them **broken/moved** (`checkStatus.ts`). The product's own example shows that existence checks depend on the current UI state. |
| A lightbulb on line 9 (VS Code code-action indicator). | There's no WinTestKit-specific code action yet. See U8. |
| The terminal fills the lower editor area with repeated VSIX installation logs and Node DEP0169 warnings. | This is the developer workflow, not the product UI. Not a product issue, though it shows how much screen the product competes for. |
| Status bar: **WTK: ○ app stopped**, 0 errors, 0 warnings. The interpreter reads `wintestkit (3.13.5)`. The activity bar shows the Testing (beaker) icon separately from the active WinTestKit icon. | The status bar item is a useful global signal. Native Testing is one icon away but nothing links WinTestKit to it. |

### 2.5 The "This project has no pages" discrepancy (root cause found in code)

The inventory treats this as an unexplained discrepancy. The code explains it with high confidence:

- In `python/src/wintestkit/server.py:482-485`, `inspect.definitions` calls `self._app(False)`. If no target app is running or attachable, it returns `{"definitions": [], "errors": [], "pageCount": 0}`.
- In `vscode/media/spy/spy.js:204-208`, `pageCount === 0` with no errors is rendered as **"This project has no pages."**

So with calc stopped, the inspector reports zero pages no matter how many exist. This isn't a discovery bug. It's a **state-conflation copy bug**: "no app to resolve against" is shown as "no pages". The user-visible effect is still a contradiction between two panels, and it erodes trust in the coverage feature. Fix it in the backend (return the real page count plus an `appRunning: false` flag, or a distinct reason) and in the copy (see U1). It's worth a 30-second live confirmation, but the code path is unambiguous.

---

## 3. Mental model, onboarding and workflow problems

### 3.1 The core model users have to form

A user must understand five nouns. Here is how the UI could teach them, with proposed copy:

| Concept | What it actually is | Current naming problem | Proposed name and one-line explanation (tooltip or first-run hint) |
|---|---|---|---|
| Test Target | The app under test, how tests get it, and whether it's running | Fine as a name, but tiles mix choices with actions | Keep **Test Target**. Hint: *"The app your tests drive. Choose it, choose how tests get it, launch it to explore."* |
| Page Tree | Your *code*: Page classes, components and element definitions | Lives under **Explorer** | Rename the view to **Pages & Flows**, keeping the tabs. Hint: *"What your code says the app looks like."* |
| Spy | The *live* UI Automation tree of a running app | "Spy" is fine, and TestComplete migrants know "Object Spy" | Keep **Spy**. Add a subtitle in the view description: **Live: calc** / **Live: desktop (calc not running)**. Hint: *"What the running app actually exposes. Pick a control to generate code."* |
| Check | Does this locator resolve to exactly one control, *right now*? | "broken/moved" in the summary over-claims when the state simply isn't open | Keep **Check exists** (CodeLens) and **Check all elements in this class exist** (class lens). Tooltip: *"Looks for this element on calc's current screen. Elements on screens that aren't open show as Not found."* |
| Flows | Reusable Python functions that drive the app | Clear once seen; the hidden part is that only `app`-only flows are runnable | Keep **Flows**. Show non-runnable flows with a muted "needs arguments" hint rather than silently omitting the play icon. |
| Tests | pytest tests in native **Testing** | No signpost from WinTestKit | Add a **Tests ↗** link in the Pages & Flows header (and empty state) that focuses the native Testing view. It's a link, not a duplicate tree. |

The single most useful framing to repeat in the UI is **code (Page Tree) vs live (Spy)**. Spy's **Defined in pages** section and the Page Tree's check icons are the two bridges. Both should say which side they're describing.

### 3.2 Lifecycle naming: Spawn vs Launch

The problem: the mode tile says **Spawn**, the button says **Launch**, the command palette says **Launch App**, and per-test mode says **Spawn per test**. The mode actually answers *"during a test run, who owns the app?"*, while the button answers *"start it now so I can explore it"*.

Proposal: remove "Spawn" everywhere and use one verb family.

- Mode quick pick (first option remains the default):
  - **Launch for tests**: *"Tests start calc and close it when they finish. A copy that's already running is closed first."*
  - **Attach to running app**: *"Tests use the calc you started. WinTestKit never starts or closes it."*
  - (YAML-only) **Launch for every test**: shown read-only when set.
- Mode tile: **Launch for tests** or **Attach**, with the same icon as today.
- Action tile: **Launch calc**, **Restart calc** and **Close calc** (include the app's display name). Putting the app name in the action is what separates the button from the mode label.

Tradeoff: "Launch for tests" is longer than "Spawn". In a narrow sidebar the tile can show **Launch** with the subtitle **for tests**. The tile already supports subtitles; the project tile uses one.

### 3.3 Interactive app vs test-run app

From code and the mode description: in Launch-for-tests mode, a test run closes an already-running copy before starting its own (`testAppModel.ts:69-74`). A user who launched calc from the sidebar, navigated to Scientific mode, and then pressed Run in Testing will see their app closed and relaunched.

That's correct behaviour for reproducible tests, but it should be announced, not discovered:

- While the app is running and the mode is Launch for tests, show a one-line note under the tiles (reuse the dead band from 2.1): **"Test runs restart calc for a clean start."**
- During a run, the Test Target status reads **Running tests: calc is managed by the test run** and disables Close and Restart, or asks for confirmation.

Open question Q3 asks whether a run should instead reuse a sidebar-launched app.

### 3.4 Native Testing discoverability

Today, nothing in the WinTestKit container says where tests live. That's a deliberate decision and the right one, but it needs signposting:

1. In the **Pages & Flows** header, add a **Tests** action (beaker icon, tooltip *"Run and debug tests in VS Code's Testing view"*) that runs `workbench.view.testing.focus`.
2. After **Initialize Project** finishes, show a notification: *"Created a page and a smoke test. Run it from the Testing view."* with buttons **[Open Testing]** and **[Open smoke test]**.
3. In the status-bar quick menu (`statusBar.ts:58-71`), add **Run all tests** and **Open Testing view**. Make Launch and Close state-aware; today both are always listed.
4. Add a VS Code **walkthrough** (`contributes.walkthroughs`; none exists today) with five steps: Choose app → Launch → Pick a control and Add to page → Check exists → Run the smoke test in Testing. Each step uses a real command as its completion event.

### 3.5 Stopped-target behaviour: one rule for every surface

The principle: **when the target is stopped, every surface says so in its own words and offers the one next step that fits the mode.** Today the Test Target and status bar do this well, CodeLens Check/Highlight do it partially (they offer **Launch App**, then retry: `highlightCommands.ts:53-68`), flows say it in text only (`flowRuns.ts:90`), and Spy doesn't do it at all.

| Surface | Proposed stopped-state behaviour | Copy |
|---|---|---|
| Test Target | As today. Use the header badge's warning tone when an action needs the app. | (existing) |
| Spy tree | A persistent info strip above Objects when roots are loaded but the target isn't running. Launch-for-tests mode: **[Launch calc]**; Attach mode: **[Refresh]** plus "Start calc yourself". Keep the desktop windows visible below. | *"calc isn't running. Showing other desktop windows."* |
| Spy "Defined in pages" | Never show "This project has no pages" because of app state. | *"Start calc to see which page definitions point at this object."* (Attach: *"…once calc is running."*) |
| Spy suggested locator (root window selected) | Plain guidance text, not a code box. | *"Windows are top-level: define them with `Window(...)`. Expand this window and select a control inside it to generate an element locator."* |
| CodeLens Check/Highlight | Keep the Launch-and-retry prompt, but route it through the same lifecycle path as the Test Target so staged progress appears there. The current path calls `app.launch` directly and skips `status.beginTransition` (`highlightCommands.ts:99-102`). Attach mode: offer **Refresh** and explain, instead of **Launch App**. | *"calc isn't running. Launch it and check?"* **[Launch and check]** |
| Run flow | Same prompt as Check. | *"calc isn't running. Launch it and run `open_scientific`?"* |
| Native Testing (Attach mode) | Fail fast before the session starts, with one clear message. | *"Attach mode: start calc first, or switch Test Target to Launch for tests."* |

### 3.6 Intended journeys

**Beginner (a QA engineer new to code-first, possibly from TestComplete)**

1. Opens the folder. Walkthrough step 1: **Choose app**. The application tile opens Browse executable or Attach. The mode defaults to Launch for tests.
2. Clicks **Launch calc**. Staged progress appears in the Test Target. Spy reads **Live: calc**.
3. Clicks **Pick element**, holds Ctrl and clicks a calc button. The inspector shows identity and a suggested `Button(automation_id=…)`. Clicks **Add to page… → StandardPage**. The code is inserted, and the Page Tree and CodeLens appear.
4. Clicks **Check exists** in the editor: "Check: Found".
5. Opens the smoke test from the walkthrough, writes `expect(...)`, clicks **Tests ↗**, and runs it in Testing. A failure notification offers **Open Report**.

What they should never have to learn up front: YAML, CLI, trace configuration, Attach, or per-test mode.

**Expert (owner of the 27-page suite)**

- Starts from a failing test in Testing. The failure message carries the relocation diagnostic ("→ found in another window: …"). They need a one-click path to the right file, Page Tree row and Spy node (U8, N3).
- Uses Check from the keyboard (palette and keybindings), runs class checks after a navigation flow (N1), and uses the CLI `wtk check`/`wtk run` in CI.
- Wants dense editors: a CodeLens density option (U16) and Problems-based results.
- Turns on trace for a flaky test with a run profile (U13) rather than editing YAML.

---

## 4. Prioritised usability improvements to current capabilities

Effort: **S** is about a day or two of focused work, **M** is several days, **L** is more than a week. These are rough relative estimates, not commitments.

### P0: trust, safety and orientation

**U1. Replace the false "This project has no pages" in Spy.**
- *Problem:* With the app stopped, Spy says there are no pages while the Page Tree lists five (`server.py:483-485`, `spy.js:204-208`).
- *Behaviour:* The backend returns the real page count plus a reason (`appRunning: false`). The webview shows *"Start calc to see which page definitions point at this object."*
- *Rationale and impact:* Removes a direct contradiction between panels and protects trust in definition coverage.
- *Effort:* S. *Dependencies:* a protocol schema change (`schemas/rpc.schema.json` and generated types) and the contract tests.

**U2. Make Close safe and honest in Attach mode.**
- *Problem:* The Attach description promises *"WinTestKit never starts or closes it"* (`testAppModel.ts:67`). Yet when the app is running, the Close tile is offered regardless of mode (`testAppModel.ts:289-294`), and `app.close` closes whichever process matched the process name (`server.py:368-372`). The status-bar menu always lists Close App.
- *Behaviour (recommended):* In Attach mode, hide Close from the tiles and the status menu. Alternatively, relabel it **Close calc (started by you)** and require a modal confirmation: *"Close calc? WinTestKit didn't start it, and unsaved work in calc will be lost."* In Launch mode, confirm only if WinTestKit didn't launch the current process.
- *Impact:* Prevents data loss in the user's own app and makes the mode's promise true.
- *Effort:* S. *Tradeoff:* Some users attach to a test build and like the shortcut. A confirmation keeps it.

**U3. Spy context strip and scope clarity.**
- *Problem:* In the stopped state, Spy silently shows the whole desktop with no scope toggle and no explanation (screenshot; `spy.js:265-267`, `366-372`).
- *Behaviour:* A view description reading **Live: calc** or **Live: desktop**, plus the info strip and actions from 3.5. When the target is running and other apps are shown, the strip reads *"Showing all desktop windows."* with **[Only calc]**.
- *Impact:* Users always know what tree they're looking at. It also stops accidental code generation against VS Code or other apps.
- *Effort:* S–M.

**U4. Unify the lifecycle vocabulary (Spawn becomes Launch for tests).** See 3.2.
- *Effort:* S for copy, plus updates to README, guide, CHANGELOG and tests that assert labels.
- *Dependency:* decide Q2 first.

**U5. Signpost native Testing.** See 3.4, items 1–3. The walkthrough is separate (U14).
- *Effort:* S. *Impact:* removes the most likely "where do I run tests?" dead end.

**U6. Fix stale and inconsistent copy.**
- `spy.js:371` still says *"Use the app controls in **Current Setup**"*; it should say *Test Target*.
- `package.json:35` titles the context-menu and command entry **Check Element**, while the CodeLens says **Check exists**. Align it to **Check exists** (keeping the dynamic result labels).
- `vscode/README.md:136` still documents *"Run/Debug CodeLens"*. Audit README and the guide for the removed test CodeLens and old setup paths.
- The status-bar summary says **broken/moved**, while the lens says **Not found**. See U7.
- *Effort:* S.

### P1: make existing power reachable

**U7. Make Check's scope explicit and its results navigable.**
- *Problem:* Checks run against the current screen. The class summary calls everything not found **broken/moved**, even for elements on screens that are simply not open (the navigation.py docstring is a live example). After a class check, the results are spread across lens text, gutter icons, Problems and a transient status-bar summary.
- *Behaviour:*
  - (a) Lens tooltip copy as in 3.1.
  - (b) A clickable status-bar summary: **"NavigationPane: 2 found, 3 not found"**. Clicking it opens a quick pick of the not-found items with their relocation hints. Selecting one jumps to the definition.
  - (c) Optional copy: **"3 not found (broken, moved, or not on screen)"**. See Q4. This respects the decision not to add a separate status; it only changes wording.
- *Effort:* M.

**U8. Turn relocation diagnostics into one-click navigation (exposure, not self-healing).**
- *Problem:* The backend already reports *"found in another window: …"*, *"found in the same window under a different container: …"* and component-root relocations (`diagnostics.ts:48-71`, `targets.py check_page`). The inventory doesn't mention this. This is the user's main stated pain, yet in the editor the information is just text in a hover or Problems entry.
- *Behaviour:* Add code actions (the lightbulb already appears) on not-found diagnostics:
  - **Reveal found element in Spy**: select and expand the relocated node.
  - **Show suggested locator for the new location**: opens the Spy inspector with Copy and Add to page.
  - **Open the page that mounts this component**.
  - No automatic edits. Every change stays user-initiated, consistent with "diagnose, never self-heal".
- *Impact:* Shortens the critical "what broke and where did it go" loop from minutes to seconds.
- *Effort:* M. *Dependency:* Spy reveal-by-path. The picker's "reveal through ancestor chain" can likely be reused.

**U9. Launch and retry for Run flow.** Match Check's behaviour (`flowRuns.ts:90` only shows text). *Effort:* S.

**U10. One lifecycle path for every launch.** CodeLens-triggered launches bypass the Test Target's staged progress and failure explanations (`highlightCommands.ts:99-102`). Route every launch through the same command so stages, timeouts and failure messages appear once, consistently. *Effort:* S.

**U11. Test Target information hierarchy.**
- *Problem:* Four equal tiles mix choices with the action, the project tile's title and subtitle are ambiguous, and there's dead space (screenshot 2.1).
- *Behaviour:*
  - Row 1 holds the action tile: **Launch calc** / **Close calc**, accent coloured.
  - Row 2 holds compact chooser chips: `calc ▾`, `Launch for tests ▾`.
  - Show the project only when there is more than one project; otherwise put it in the view description.
  - The project title should be the project name (`calculator-tests`), with the workspace folder as the subtitle.
  - The message band collapses when empty.
- *Effort:* M. *Tradeoff:* Visual churn for existing users. Validate with Q1.

**U12. Rename Explorer to Pages & Flows, and compact the tabs.** Replace the card buttons with a two-option segmented control in the view's header area, or one row of slim tabs with counts (*Pages 5 · Flows 12*). *Effort:* S.

**U13. Evidence controls where people run tests (exposure of trace).**
- *Problem:* Screenshot trace with playback exists but is reachable only through YAML, CLI or environment variables. There is no `trace` reference anywhere in `vscode/src` except generated protocol types.
- *Behaviour:*
  - (a) Add an **Evidence** group to the configuration form: Screenshots (off / on failure / every step), Recording (off / on / keep on failure), Recording FPS, and capture scope.
  - (b) Register an extra native Testing run profile, **Run with recording** (not the default). It's equivalent to passing trace on for that run.
  - (c) The failure notification and Test Results message link straight to the report section with playback.
- *Impact:* A powerful debugging feature becomes discoverable exactly when a test is flaky.
- *Effort:* M. *Dependencies:* the form schema and the backend CLI flags, which already exist.

**U14. First-run walkthrough and empty states.** Add `contributes.walkthroughs` as in 3.4, plus empty-state links in each view (no project, Initialize Project, no app chosen, Choose app). *Effort:* M.

**U15. Make the Debug profile's trade-offs explicit.** Debug runs use `--no-report`, `--no-env-check` and a 3600-second action timeout. Label the profile **Debug (no report)**, or show a once-per-session note: *"Debug runs don't generate an HTML report and wait indefinitely at breakpoints."* *Effort:* S.

**U16. CodeLens density option that preserves the default.** Add `wintestkit.codeLens.elementActions: "all" | "classOnly"`, defaulting to `"all"` (the intentional current behaviour). Users of large page files can switch to class-only plus tree and gutter actions. Also consider merging into one shorter lens line (`$(eye) Highlight  $(check) Check exists`). *Effort:* S. *Tradeoff:* yet another setting. Ship it only if dense files are a real complaint (Q6).

**U17. Last-run summary and report entry point.** After a run, show **Last run: 12 passed, 1 failed · Open report** in the Pages & Flows header or in the Test Target's message band, plus Open Last Report in the status menu (already there). *Effort:* S–M.

**U18. Active-project context.** Everything follows the active editor's project. In multi-project workspaces, show the project in each view's description (*Spy · calculator-tests*) so switching editors doesn't silently change what Spy and Check act on. *Effort:* S.

**U19. Environment errors surfaced where they bite.**
- *Problem:* Doctor runs in a terminal. Elevation mismatches and a locked desktop are classic silent UI Automation failures.
- *Behaviour:* When launch, attach or inspection fails for a recognisable reason, the Test Target message names it and offers the fix. For example: *"calc is running as administrator but VS Code isn't. UI Automation can't read it. Restart VS Code as administrator or run calc normally."* **[Run environment check]**.
- *Effort:* M. *Dependency:* the backend returning classified error codes. I didn't verify which ones exist today.

**U20. Accessibility audit (checklist, not findings).** I can't judge from one dark-theme screenshot. Check:
- Test Target tiles are reachable and operable by keyboard, in visual order.
- State transitions (Starting, Running, Failed) announce through `aria-live`.
- Check states in the Page Tree aren't conveyed by colour alone (use distinct codicons as well as colour).
- The Spy tree exposes `role=tree`/`treeitem` and `aria-expanded`/`aria-selected`. `spy.html` has good aria labels on its controls; verify the rows.
- High-contrast themes and 200% zoom work in all three webviews.
- Hover-only row actions also appear on keyboard focus.
- *Effort:* M. *Impact:* also improves screen-reader QA users' experience of a UI-Automation-focused product, which is an on-brand credibility point.

**U21 (minor). Privacy hygiene in shared screenshots.** Spy's desktop scope lists other apps' window titles, including personal profile names (visible in the screenshot). Consider a setting, or a stopped-state default, that collapses other apps into one "Other desktop windows (8)" group until expanded. *Effort:* S. Low priority.

---

## 5. Genuinely new features (ranked)

None of these duplicate what's shipped: copy/add-to-page, exact definition coverage, trace playback, relocation diagnostics, Check/Highlight, app-only flow runs, and native Run/Debug all already exist.

### N1. "Check after flow": reach the state before checking. *(Highest value)*
- **Who:** anyone with stateful UIs, which in practice is everyone. The example's navigation pane and the 27-page suite's moving boxes both need this.
- **Workflow:** On the class lens, add a secondary action, **Check after flow…**. Pick a runnable flow (for example `open_pane` or `open_scientific`). It runs the flow, then checks the class, and remembers the choice per class in workspace state. Next time the lens reads **Check all elements in this class exist (after `open_pane`)**.
- **Value:** Turns "3 broken/moved" noise into a real signal without adding a new status, which respects the earlier decision.
- **MVP:** Extension only. It sequences the existing `flow.run` and `page.check`, uses a quick pick, and stores the choice in the workspace.
- **Risk:** Flows have side effects. Mitigate by showing the flow name in the lens and by never chaining automatically without the user's choice.
- **Effort:** M.

### N2. Failure-to-fix actions on native Test Results.
- **Who:** the suite owner triaging failures.
- **Workflow:** When a test fails on element resolution, the Test Results message offers **Go to definition**, **Check this element now**, **Reveal relocated element in Spy** and **Open report at this step**. These use VS Code's test-message context menus.
- **Value:** Connects the run surface (Testing), the code surface (Page Tree) and the live surface (Spy) at the moment of pain.
- **MVP:** Two actions: go to definition and reveal in Spy.
- **Risk:** Depends on structured diagnostics reaching the test message, which already happens partly.
- **Effort:** M.

### N3. Insert assertion from Spy.
- **Who:** test authors.
- **Workflow:** With a control selected in Spy that's already defined in pages (exact match), **Insert expect…** offers `to_have_text("7")`, `to_be_enabled()`, `to_be_checked()` and so on, built from the current live values, inserted at the cursor in the active test.
- **Value:** Closes the gap between "I have a page model" and "I have a test" while staying code-first. Add-to-page handles definitions; nothing generates assertions today.
- **MVP:** Text, enabled and checked/selected only, using the already-matched definition path.
- **Risk:** Asserting incidental live values. Show the generated line before inserting.
- **Effort:** M.

### N4. Flow arguments prompt.
- **Who:** flow authors.
- **Workflow:** Flows with simple typed parameters (`str`, `int`, `bool`, `Enum`/`Literal`) become runnable. The play icon opens a small input sequence, and the last values are remembered.
- **Value:** Turns more flows into interactive helpers, for example `login(app, user="qa")`.
- **MVP:** Primitive types only. Anything else stays non-runnable, with the reason shown.
- **Effort:** S–M.

### N5. Unused-definition finder (static, not coverage).
- **Who:** teams migrating or maintaining a large page model.
- **Workflow:** Page Tree rows for definitions never referenced by any test or flow get a muted "unused" marker, plus a filter, **Show unused**.
- **Value:** Prunes dead locators after migration, and complements live definition coverage (Spy) without being confused with test coverage. Name it **Unused definitions**, never "coverage".
- **MVP:** Use VS Code's reference provider (Pylance) per definition, lazily and on demand.
- **Risk:** Dynamic access (`getattr`) gives false positives. Label it as a static estimate.
- **Effort:** M.

### N6. Project-wide model sweep (builds on N1).
- **Who:** the suite owner after each app build.
- **Workflow:** **Check all pages** runs each page's remembered reach-flow, then checks it, and writes the results to Problems plus a summary report section: found, not found, and found elsewhere.
- **Value:** Catches moved boxes before tests fail.
- **MVP:** Only pages with a remembered reach-flow; the rest are skipped and listed.
- **Risk:** Long runs and side effects. Run it in Launch-for-tests mode and make it cancellable.
- **Effort:** L.

### N7. UI tree diff between the last green run and a failure. *(Later bet)*
- **Workflow:** On failure, the report shows the failing container's UI tree compared with the last passing run.
- **Value:** Answers "what changed?" when relocation search finds nothing.
- **Dependency:** Successful runs would need to retain a bounded tree dump, which has storage cost.
- **Effort:** L.

### N8. TestComplete NameMapping importer. *(Conditional)*
- Generates page skeletons from a NameMapping export, mapping ClrFullClassName and WPFControlName to `where={...}` and property aliases.
- High value only if the migration is still manual. See Q8. The planned AI rewrite skill may make it moot.
- **Effort:** M–L.

### What not to build yet

- **AI auto-healing of locators.** It contradicts the explicit "diagnose, never self-heal" decision. Invest in U8 and N2 instead.
- **Cloud dashboards or hosted history.** There's no stated team or CI need. Local reports and JUnit cover CI today.
- **A full record-and-replay recorder or visual designer.** It works against code-first, produces brittle scripts, and is expensive. N3 and Spy insertion give most of the authoring speed-up without it.
- **MP4 encoding or a Playwright-style DOM/network trace.** Sampled screenshots plus steps fit desktop UI Automation, so make them discoverable (U13) instead.
- **A duplicate test tree in the sidebar.** Signpost native Testing (U5) instead.
- **Surfacing per-test mode in the quick pick.** Keep it YAML-only, as now.
- **Visual-diff assertions.** Wait until there's evidence that text and state assertions are insufficient for the real suite.

---

## 6. Sequence and validation

### Quick wins (one small release)

U1, U2, U3, U4 (once Q2 is answered), U5, U6, U9, U10, U15.

Acceptance criteria:
- With calc stopped, Spy never shows "This project has no pages" in a project with pages, and it always shows a context strip naming the target and its state.
- In Attach mode, there's no unconfirmed path (tiles, status menu, palette) that closes the attached process.
- The string "Spawn" appears nowhere in the UI. The mode and action labels share one verb.
- From the WinTestKit container, the native Testing view is one click away. After Initialize Project, the notification opens it.
- Every launch path (tile, CodeLens prompt, flow prompt) shows the same staged progress in the Test Target.
- A grep for "Current Setup", "Run/Debug CodeLens" and "Check Element" in the UI and docs comes back empty or intentional.

How to validate: unit tests on `buildTestAppModel` and the Spy messages for each mode × state combination, plus a scripted manual pass of the stopped, running, Attach and Launch matrix.

### Next release

U7, U8, U11, U12, U13, U14, U16 (only if Q6 says yes), U17, U18, N2 (MVP), N4.

Acceptance criteria:
- For a not-found element that the backend relocated, the user can reach the relocated node in Spy within two interactions from the diagnostic.
- A user can turn on recording for one run without opening YAML, and reach playback from the failure notification.
- The walkthrough completes with real command events.

How to validate: a task-based hallway test with two or three people unfamiliar with the extension, ideally one ex-TestComplete user. Tasks: "add the = button to StandardPage", "run the smoke test", "find out why a test failed and where the control went". Record time to completion and points of hesitation. There's no existing user-research data, so treat this as the baseline.

### Later bets

N1, then N6; N3; N5; N7; N8 (conditional on Q8); U19 (depends on backend error classification); U20 audit fixes.

Acceptance criteria:
- N1: on navigation.py, **Check after `open_pane`** reports all five elements found against a freshly launched calc.
- N6: a sweep over the example project finishes, can be cancelled, and lists skipped pages.
- N3: the inserted assertions pass when run immediately against the same state.
- N5: false-positive rate checked by hand on the real suite before shipping the marker by default.

---

## 7. Open questions that need the user's insight

1. **Who is the primary user?** QA engineers from TestComplete, developers, or both? This decides vocabulary ("Object Spy/Object Browser" versus "Spy", and how much Python to assume) and how much Test Target restructuring (U11) is worth the churn.
2. **Lifecycle naming:** is "Spawn" a term the team already uses and likes? If not, is **Launch for tests / Attach to running app** acceptable as the replacement?
3. **Interactive app vs test run:** when you've launched calc from the sidebar and navigated somewhere, should a test run in Launch-for-tests mode still close and relaunch it (clean start), or reuse it?
4. **Not-found wording:** you decided against a separate "not present in this state" status. Is softer *wording*, such as "not found (broken, moved, or not on screen)", acceptable, or should the summary keep saying "broken/moved" deliberately?
5. **Close in Attach mode:** should it disappear entirely, or stay behind a confirmation?
6. **CodeLens density:** in the real 27-page suite, do per-element lenses feel helpful or noisy? This determines whether U16 is needed.
7. **Relocation quick actions:** are user-initiated "Reveal in Spy" and "Show suggested locator" actions within the spirit of "diagnose, never self-heal", or should diagnostics stay text-only?
8. **Migration:** is the TestComplete NameMapping still the source of truth for any pages, or will the planned AI-assisted rewrite cover it, making N8 unnecessary?
9. **Reach-flows (N1):** are your navigation flows safe to run repeatedly (idempotent, no data changes), or do some have side effects that would make "Check after flow" risky in the real app?
10. **Team setup:** is the extension used by one person or by a team that shares `wintestkit.yaml`? This affects how much weight shared settings, walkthroughs and the evidence defaults deserve.

---

## Appendix: corrections and additions to the inventory

| # | Inventory statement | Correction or addition | Evidence |
|---|---|---|---|
| 1 | "No pages" in the inspector is an unexplained discrepancy | Explained: with no running app, `inspect.definitions` returns `pageCount: 0`, which the webview renders as "This project has no pages." It's a copy and state-conflation bug | `server.py:482-485`, `spy.js:204-208` |
| 2 | Resolution diagnostics include "candidates/closest matches" | Also **relocation** results: found in another window, found in the same window under a different container, and component root found in other windows. Not mentioned in the inventory, yet central to the user's main pain | `diagnostics.ts:48-71`, `targets.py` (`check_page` docstring), `engine/diagnose.py` |
| 3 | (absent) | Class checks produce a status-bar summary: "N found, M broken/moved" | `editor/checkStatus.ts` |
| 4 | Individual action labelled "Check exists" | True for the CodeLens. The command and webview context-menu title is still **Check Element** | `package.json:35` |
| 5 | Attach: "do not start or close it as part of the test-run lifecycle" | True for test runs, but the sidebar **Close** tile is offered in Attach mode while the app is running, and closes the attached process. The status menu always lists Close App | `testAppModel.ts:67,289-294`, `server.py:368-372`, `statusBar.ts:58-71` |
| 6 | Empty and stopped states "have explanations" in Spy | The "Application not running" state only appears when no roots are loaded. When desktop windows load (as in the screenshot), there's no stopped explanation, and its copy references the old name **Current Setup** | `spy.js:366-372` |
| 7 | Show Other Apps scope toggle | Hidden whenever the target isn't running, so in the stopped state there's no visible scope control | `spy.js:265-267` |
| 8 | (absent) | Check/Highlight on a stopped app already offer **Launch App** and then retry. That launch bypasses the Test Target's staged-transition tracking. Run flow offers only a text message | `highlightCommands.ts:53-68, 99-102`, `flowRuns.ts:90` |
| 9 | (absent) | The status-bar item opens a quick menu (Launch, Close, Restart Server, Open Last Report, Check Environment, Show Output) that isn't state-aware, and polls app status every 5 seconds while focused | `statusBar.ts:46-76` |
| 10 | Stale docs mentioned generally | Specifically, `vscode/README.md:136` still describes "Run/Debug CodeLens" | `vscode/README.md:136` |
| 11 | (absent) | No `walkthroughs` or `viewsWelcome` contributions exist | `package.json` |
| 12 | Trace mostly discoverable via configuration/CLI | Confirmed: there are no trace references in `vscode/src` except generated protocol types, and the configuration form has no trace controls | grep over `vscode/src` |
