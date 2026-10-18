# 05 — Shared Data Contracts

Every JSON shape that crosses a process boundary (Python ↔ VS Code, Python ↔ report, CLI `--json`
output) is defined here. **This file is the source of truth.** T0.5 turns it into JSON Schema files
under `/schemas`; Python output is validated against them in contract tests and TypeScript types are
generated from them.

Notation: TypeScript. `?` = optional key (omit rather than `null` unless the type says `| null`).
All keys camelCase. Lines/characters 0-based. Paths absolute with forward slashes. Times: `start` /
`time` are Unix epoch seconds (float); durations are seconds (float).

---

## 1. Common

```ts
interface Position { line: number; character: number }
interface Range { start: Position; end: Position }

interface Rect { left: number; top: number; width: number; height: number }  // physical pixels

/** Snapshot of one UI Automation element. */
interface ElementInfo {
  automationId: string;        // "" if none
  name: string;                // "" if none
  controlType: string;         // UIA programmatic name without suffix: "Button", "Edit", "DataItem", ...
  className: string;
  frameworkId: string;         // "WPF", "Win32", ...
  processId: number;
  rect: Rect | null;           // null when BoundingRectangle is empty
  isEnabled: boolean;
  isOffscreen: boolean;
  hasKeyboardFocus: boolean;
  runtimeId: string;           // RuntimeId ints joined with "." e.g. "42.1234.4.17"
  patterns?: string[];         // supported patterns, e.g. ["Invoke","Value"]; only when requested
}

/** A locator as data (mirrors engine/locator.py). Matchers: string = exact, {regex} = re.search. */
type Matcher = string | { regex: string; flags?: string };   // flags subset of "imsx"

interface WindowLocatorData {
  title?: Matcher;
  process?: string;            // exe name, case-insensitive, e.g. "DemoApp.exe"
  className?: Matcher;
  automationId?: Matcher;
  index?: number;
}

interface ItemSelectorData {
  kind: "row" | "cell";
  row: number;                 // 0-based
  column?: number | string;    // index or header name; required when kind == "cell"
}

interface LocatorData {
  automationId?: Matcher;
  name?: Matcher;
  controlType?: string;
  className?: Matcher;
  index?: number;
  depth?: number;              // max search depth below scope; omitted = unlimited
  within?: LocatorData;
  window?: WindowLocatorData;  // explicit window override
  item?: ItemSelectorData;     // grid row/cell selection applied after resolving this locator
}

interface Mismatch { property: string; expected: string; actual: string }

interface Candidate {
  info: ElementInfo;
  score: number;               // number of locator properties that matched
  mismatches: Mismatch[];      // empty for elements that matched everything
}

interface Diagnostic {
  kind: "not_found" | "ambiguous" | "window_not_found" | "within_failed" | "index_out_of_range"
      | "app_not_running";
  message: string;             // one-line human summary
  locator: string;             // Locator.describe() output
  searchedIn: string;          // description of the scope, e.g. 'Window "WTK Demo"'
  matchCount: number;
  candidates: Candidate[];     // max 5; for "ambiguous" these are the matches (score = all)
  within?: Diagnostic;         // the failing ancestor when kind == "within_failed"
}

interface ErrorInfo {
  type: string;                // exception class name, e.g. "ElementNotFoundError"
  message: string;
  diagnostic?: Diagnostic;
}
```

## 2. Discovery (`wtk discover --json`, RPC `discover`)

```ts
interface DiscoveryResult {
  version: 1;
  root: string;                         // project root (dir containing pyproject.toml)
  tests: TestEntry[];
  screens: ScreenEntry[];
  errors: DiscoveryError[];             // syntax errors etc.; discovery continues past them
}

interface TestEntry {
  id: string;                           // pytest nodeid: "tests/test_login.py::TestX::test_y"
  file: string;                         // absolute path
  name: string;                         // "test_y" or "TestX"
  kind: "class" | "function";           // methods are "function" with a class parent
  parent: string | null;                // id of containing class, or null
  range: Range;                         // whole def/class statement incl. decorators
  nameRange: Range;                     // just the name token
}

interface ScreenEntry {
  id: string;                           // "screens/main.py::MainScreen"
  file: string;
  name: string;                         // "MainScreen"
  qualname: string;                     // "MainScreen" (or "Outer.MainScreen" if nested)
  bases: string[];                      // base names as written, e.g. ["Screen"]
  range: Range;
  nameRange: Range;
  elements: ElementEntry[];             // in source order
}

interface ElementEntry {
  id: string;                           // "screens/main.py::MainScreen.sign_in"
  name: string;                         // attribute name "sign_in"
  qualname: string;                     // "MainScreen.sign_in"
  kind: "window" | "element" | "elements";
  range: Range;                         // whole assignment statement
  nameRange: Range;
  locator: LocatorData;                 // literal kwargs only; see "dynamic"
  withinName?: string;                  // attribute name passed as within= (same class), if any
  windowName?: string;                  // attribute name passed as window=, if any
  dynamic: boolean;                     // true if any kwarg wasn't a literal (value omitted from locator)
}

interface DiscoveryError { file: string; message: string; line: number }
```

## 3. Step events

```ts
interface StepEvent {
  seq: number;                          // 1-based, per test
  action: string;                       // "click", "type", "select", "expect.to_have_text", ...
  target: string;                       // qualname, e.g. "MainScreen.sign_in" ("<anonymous>" if none)
  locator: string;                      // Locator.describe()
  args: Record<string, unknown>;        // JSON-safe; secrets redacted to "***"
  start: number;
  duration: number;
  status: "passed" | "failed";
  error?: ErrorInfo;
  screenshot?: string;                  // path relative to report dir (screenshots: every-step)
}
```

Redaction rule: args are replaced with `"***"` when the target element's `className` is
`PasswordBox`, or the arg name contains `password`/`secret`/`token` (case-insensitive).

## 4. Test run events (pytest plugin `--wtk-events`)

Transport: newline-delimited JSON (one object per line, UTF-8). Each object has `event` and `time`.

```ts
type RunEvent =
  | { event: "session_start"; time: number; root: string; pid: number; wintestkitVersion: string }
  | { event: "collected"; time: number; tests: CollectedTest[]; errors: CollectError[] }
  | { event: "test_start"; time: number; id: string }
  | { event: "step"; time: number; id: string; step: StepEvent }
  | { event: "test_output"; time: number; id: string; stream: "stdout" | "stderr" | "log"; text: string }
  | { event: "test_end"; time: number; id: string; outcome: TestOutcome; duration: number;
      message?: string; location?: { file: string; line: number }; error?: ErrorInfo;
      screenshots: string[]; artifactsDir?: string }
  | { event: "session_end"; time: number; exitCode: number; summary: Summary;
      reportPath?: string; junitPath?: string };

type TestOutcome = "passed" | "failed" | "skipped" | "error";   // "error" = setup/teardown failure
interface CollectedTest { id: string; file: string; line: number; name: string; parent: string | null }
interface CollectError { file: string; message: string }
interface Summary { total: number; passed: number; failed: number; skipped: number; errors: number;
                    duration: number }
```

Parametrized tests appear with ids like `tests/test_a.py::test_x[admin-secret]`; their `parent` is
the un-parametrized function id `tests/test_a.py::test_x`.

`screenshots` and `artifactsDir` are absolute paths.

## 5. Results file (`<report_dir>/results.json`)

```ts
interface Results {
  version: 1;
  startedAt: number; finishedAt: number; duration: number;
  environment: {
    python: string; wintestkit: string; windows: string; machine: string;
    screen: { width: number; height: number; scale: number };   // primary monitor, scale 1.0 = 96 DPI
  };
  summary: Summary;
  tests: TestResult[];
}

interface TestResult {
  id: string; file: string; line: number; name: string;
  outcome: TestOutcome; duration: number;
  message?: string; location?: { file: string; line: number }; error?: ErrorInfo;
  steps: StepEvent[];
  screenshots: string[];                // relative to report dir
  treeDump?: string;                    // relative path to a .txt dump
  stdout: string; stderr: string; log: string;
}
```

## 6. JSON-RPC (`wtk serve --stdio`)

Transport: **newline-delimited JSON-RPC 2.0** over stdin/stdout. stdout carries protocol only;
logs go to stderr. Requests are processed **sequentially** in arrival order, except `spy.stop` and
`shutdown`, which are handled immediately.

Error codes:

| Code | Meaning |
|---|---|
| -32700 / -32600 / -32601 / -32602 / -32603 | Standard JSON-RPC |
| -32001 | Config error (`data: ErrorInfo`) |
| -32002 | App not running |
| -32003 | Target not found (bad file/qualname, import failure; `data.message` has the traceback summary) |
| -32004 | Environment not ready (locked desktop etc.) |
| -32005 | Unknown node id (stale inspector node) |
| -32006 | No element locator for a top-level window (`suggest.locator` on a window node) |

### Methods

```ts
// --- lifecycle
"initialize": (p: { root: string }) => {
  protocolVersion: 1; wintestkitVersion: string; python: string;
  config: { found: boolean; app?: { path: string; process: string }; launch: string;
            timeout: number; reportDir: string } }
"shutdown": () => null                  // then the process exits 0

// --- discovery
"discover": (p: { overrides?: Record<string, string> }) => DiscoveryResult
     // overrides: absolute path -> unsaved file content, parsed instead of disk content

// --- app
"app.status": () => { running: boolean; pids: number[]; mainWindowTitle?: string }
"app.launch": () => { pids: number[] }  // uses config; no-op if already running
"app.close":  () => null

// --- element actions from the editor
"element.highlight": (p: { file: string; qualname: string; durationMs?: number }) => ElementResult
"screen.check":      (p: { file: string; screen: string }) => { results: CheckResult[] }

interface ElementResult {
  status: "found" | "not_found" | "ambiguous" | "error";
  element?: ElementInfo;
  diagnostic?: Diagnostic;
  message?: string;                     // for status "error"
  durationMs: number;
}
interface CheckResult extends ElementResult { qualname: string }

// --- inspector
interface NodeInfo { nodeId: string; info: ElementInfo; hasChildren: boolean }
"inspect.roots":     (p?: { includeOtherApps?: boolean }) => NodeInfo[]   // app windows; includeOtherApps returns all top-level windows (also used when no app is configured/running)
"inspect.children":  (p: { nodeId: string }) => NodeInfo[]
"inspect.properties":(p: { nodeId: string }) => { info: ElementInfo;            // includes patterns
                                                   properties: Record<string, string>;  // every readable UIA property, stringified
                                                   ancestors: NodeInfo[] }              // root-first path
"inspect.highlight": (p: { nodeId: string; durationMs?: number }) => null
"suggest.locator":   (p: { nodeId: string }) => Suggestion
"inspect.definitions": (p: { nodeId: string }) => { definitions: DefinitionMatch[];   // page definitions that resolve to exactly this node
                                                    errors: { file: string; message: string }[];  // page files that could not be imported
                                                    pageCount: number }
"inspect.coverage":  (p: { nodeIds: string[] }) => { covered: Record<string, { count: number; first: string }>;
                                                     pending: string[] }   // nodes not finished within the time budget: ask again

interface Suggestion {
  locator: LocatorData;
  code: string;                         // e.g. 'Element(control_type="Button", name="Sign in")'
  attributeName: string;                // suggested snake_case attribute name, e.g. "sign_in"
  helpers: { attributeName: string; code: string; locator: LocatorData }[];
      // ancestor elements that must be defined first (used as within=); code references them by attributeName
  unique: boolean;
  matchCount: number;
  strategy: "automation_id" | "name" | "class_name" | "within" | "index";
  window?: { code: string; locator: WindowLocatorData };   // Window(...) for the element's top-level window
}

// --- spy
"spy.start": () => null
"spy.stop":  () => null
// notifications (server -> client, no id):
"spy.hover":     { node: NodeInfo }
"spy.picked":    { node: NodeInfo; suggestion: Suggestion }
"spy.cancelled": {}
"log":           { level: "debug" | "info" | "warning" | "error"; message: string }
```

`nodeId` format: the element's `runtimeId` string. The server keeps an LRU map (max 5000) of
`nodeId → UIAElement`; unknown ids yield error -32005.

---

## T0.5 — JSON Schemas, type generation, contract harness <a id="t05"></a>

- **Depends on:** T0.1, T0.2
- **Size:** M
- **Files:** `schemas/common.schema.json`, `discovery.schema.json`, `step.schema.json`,
  `events.schema.json`, `results.schema.json`, `rpc.schema.json`; `schemas/README.md`;
  `vscode/scripts/gen-types.mjs`; `vscode/src/protocol/generated.ts`;
  `python/tests/contract/conftest.py`, `python/tests/contract/test_schemas.py`,
  `python/tests/contract/fixtures/*.json`.
- **Spec:**
  - JSON Schema draft 2020-12. One `$defs` entry per interface above, named identically
    (`ElementInfo`, `Diagnostic`, …). `rpc.schema.json` has `$defs` `<Method>Params` and
    `<Method>Result` for every method (method dots become nothing and next letter uppercase:
    `element.highlight` → `ElementHighlightParams` / `ElementHighlightResult`), plus notification
    payloads `SpyHoverNotification` etc.
  - `additionalProperties: false` everywhere except the declared dictionary maps:
    `StepEvent.args`, `InspectPropertiesResult.properties`, and `DiscoverParams.overrides`.
  - Hand-write one valid example per top-level type in `python/tests/contract/fixtures/`
    (`element-info.json`, `diagnostic.json`, `discovery.json`, `events.ndjson`, `results.json`,
    `suggestion.json`) — used by both Python and TS tests.
  - Python helper `tests/contract/conftest.py`: fixture `validate(schema_file, def_name, data)`
    using `jsonschema` with a registry resolving cross-file `$ref`s.
  - `vscode/scripts/gen-types.mjs`: uses dev dependency `json-schema-to-typescript` to emit all
    `$defs` into `vscode/src/protocol/generated.ts`; `npm run gen:types`. CI fails if the generated
    file is out of date (`git diff --exit-code`).
  - Vitest test loads each fixture and type-checks it compiles against the generated types (a
    `satisfies` check in a `.ts` test file is enough).
- **Done when:** all fixtures validate in Python; `npm run gen:types` is deterministic; TS fixture
  test passes. Later tasks add their own contract tests that validate real output with the
  `validate` fixture.
