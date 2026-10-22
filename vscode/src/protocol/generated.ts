/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "AppCloseParams".
 */
export type AppCloseParams = Record<string, never>;
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "AppCloseResult".
 */
export type AppCloseResult = null;
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "AppLaunchParams".
 */
export type AppLaunchParams = Record<string, never>;
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "AppProcessesParams".
 */
export type AppProcessesParams = Record<string, never>;
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "AppStatusParams".
 */
export type AppStatusParams = Record<string, never>;
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "Matcher".
 */
export type Matcher =
  | string
  | {
      regex: string;
      flags?: string;
    };
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ItemSelectorData".
 */
export type ItemSelectorData =
  | {
      kind: "row";
      row: number;
      column?: number | string;
    }
  | {
      kind: "cell";
      row: number;
      column: number | string;
    };
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectChildrenResult".
 */
export type InspectChildrenResult = NodeInfo[];
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectHighlightResult".
 */
export type InspectHighlightResult = null;
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectRootsResult".
 */
export type InspectRootsResult = NodeInfo[];
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "TestOutcome".
 */
export type TestOutcome = "passed" | "failed" | "skipped" | "error";
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "RunEvent".
 */
export type RunEvent =
  | {
      event: "session_start";
      time: number;
      root: string;
      command?: string;
      pid: number;
      wintestkitVersion: string;
    }
  | {
      event: "collected";
      time: number;
      tests: CollectedTest[];
      errors: CollectError[];
    }
  | {
      event: "test_start";
      time: number;
      id: string;
    }
  | {
      event: "step";
      time: number;
      id: string;
      step: StepEvent;
    }
  | {
      event: "test_output";
      time: number;
      id: string;
      stream: "stdout" | "stderr" | "log";
      text: string;
    }
  | {
      event: "test_end";
      time: number;
      id: string;
      outcome: TestOutcome;
      duration: number;
      message?: string;
      location?: {
        file: string;
        line: number;
      };
      error?: ErrorInfo;
      screenshots: string[];
      artifactsDir?: string;
      treeDiff?: string;
      replay?: Replay;
    }
  | {
      event: "session_end";
      time: number;
      exitCode: number;
      summary: Summary;
      reportPath?: string;
      junitPath?: string;
    };
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ShutdownParams".
 */
export type ShutdownParams = Record<string, never>;
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ShutdownResult".
 */
export type ShutdownResult = null;
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "SpyStartResult".
 */
export type SpyStartResult = null;
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "SpyStopParams".
 */
export type SpyStopParams = Record<string, never>;
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "SpyStopResult".
 */
export type SpyStopResult = null;

export interface ProtocolContracts {
  AppCloseParams?: AppCloseParams;
  AppCloseResult?: AppCloseResult;
  AppLaunchParams?: AppLaunchParams;
  AppLaunchResult?: AppLaunchResult;
  AppProcessesParams?: AppProcessesParams;
  AppProcessesResult?: AppProcessesResult;
  AppStartingNotification?: AppStartingNotification;
  AppStatusParams?: AppStatusParams;
  AppStatusResult?: AppStatusResult;
  Candidate?: Candidate;
  CheckResult?: CheckResult;
  ChildPageEntry?: ChildPageEntry;
  CollectError?: CollectError;
  CollectedTest?: CollectedTest;
  DefinitionError?: DefinitionError;
  DefinitionMatch?: DefinitionMatch;
  Diagnostic?: Diagnostic;
  DiscoverParams?: DiscoverParams;
  DiscoverResult?: DiscoverResult;
  DiscoveryError?: DiscoveryError;
  DiscoveryResult?: DiscoveryResult;
  ElementEntry?: ElementEntry;
  ElementHighlightParams?: ElementHighlightParams;
  ElementHighlightResult?: ElementHighlightResult;
  ElementInfo?: ElementInfo;
  ElementResult?: ElementResult;
  ErrorInfo?: ErrorInfo;
  FlowEntry?: FlowEntry;
  FlowRunParams?: FlowRunParams;
  FlowRunResult?: FlowRunResult;
  InitializeParams?: InitializeParams;
  InitializeResult?: InitializeResult;
  InspectChildrenParams?: InspectChildrenParams;
  InspectChildrenResult?: InspectChildrenResult;
  InspectCoverageParams?: InspectCoverageParams;
  InspectCoverageResult?: InspectCoverageResult;
  InspectDefinitionsParams?: InspectDefinitionsParams;
  InspectDefinitionsResult?: InspectDefinitionsResult;
  InspectHighlightParams?: InspectHighlightParams;
  InspectHighlightResult?: InspectHighlightResult;
  InspectPartialErrorData?: InspectPartialErrorData;
  InspectPreviewParams?: InspectPreviewParams;
  InspectPreviewResult?: InspectPreviewResult;
  InspectPropertiesParams?: InspectPropertiesParams;
  InspectPropertiesResult?: InspectPropertiesResult;
  InspectRefreshParams?: InspectRefreshParams;
  InspectRefreshResult?: InspectRefreshResult;
  InspectRootsParams?: InspectRootsParams;
  InspectRootsResult?: InspectRootsResult;
  InspectionProperty?: InspectionProperty;
  ItemSelectorData?: ItemSelectorData;
  LocatorData?: LocatorData;
  LogNotification?: LogNotification;
  Matcher?: Matcher;
  Mismatch?: Mismatch;
  NodeCoverage?: NodeCoverage;
  NodeInfo?: NodeInfo;
  PageCheckParams?: PageCheckParams;
  PageCheckResult?: PageCheckResult;
  PageEntry?: PageEntry;
  Position?: Position;
  PreviewImage?: PreviewImage;
  Range?: Range;
  Rect?: Rect;
  Relocation?: Relocation;
  Replay?: Replay;
  Results?: Results;
  RunEvent?: RunEvent;
  RunningProcess?: RunningProcess;
  ShutdownParams?: ShutdownParams;
  ShutdownResult?: ShutdownResult;
  SpyCancelledNotification?: SpyCancelledNotification;
  SpyHoverNotification?: SpyHoverNotification;
  SpyPickedNotification?: SpyPickedNotification;
  SpyStartParams?: SpyStartParams;
  SpyStartResult?: SpyStartResult;
  SpyStopParams?: SpyStopParams;
  SpyStopResult?: SpyStopResult;
  StepEvent?: StepEvent;
  SuggestLocatorParams?: SuggestLocatorParams;
  SuggestLocatorResult?: SuggestLocatorResult;
  Suggestion?: Suggestion;
  Summary?: Summary;
  TestEntry?: TestEntry;
  TestOutcome?: TestOutcome;
  TestResult?: TestResult;
  WindowLocatorData?: WindowLocatorData;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "AppLaunchResult".
 */
export interface AppLaunchResult {
  pids: number[];
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "AppProcessesResult".
 */
export interface AppProcessesResult {
  processes: RunningProcess[];
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "RunningProcess".
 */
export interface RunningProcess {
  name: string;
  pids: number[];
  windowTitle: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "AppStartingNotification".
 */
export interface AppStartingNotification {
  stage: "process" | "window";
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "AppStatusResult".
 */
export interface AppStatusResult {
  running: boolean;
  /**
   * True only while the server still owns the exact PID set it launched.
   */
  owned: boolean;
  pids: number[];
  mainWindowTitle?: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "Candidate".
 */
export interface Candidate {
  info: ElementInfo;
  score: number;
  mismatches: Mismatch[];
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ElementInfo".
 */
export interface ElementInfo {
  automationId: string;
  name: string;
  controlType: string;
  className: string;
  frameworkId: string;
  processId: number;
  rect: Rect | null;
  isEnabled: boolean;
  isOffscreen: boolean;
  hasKeyboardFocus: boolean;
  runtimeId: string;
  patterns?: string[];
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "Rect".
 */
export interface Rect {
  left: number;
  top: number;
  width: number;
  height: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "Mismatch".
 */
export interface Mismatch {
  property: string;
  expected: string;
  actual: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "CheckResult".
 */
export interface CheckResult {
  status: "found" | "not_found" | "ambiguous" | "error";
  element?: ElementInfo;
  diagnostic?: Diagnostic;
  message?: string;
  durationMs: number;
  qualname: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "Diagnostic".
 */
export interface Diagnostic {
  kind:
    | "not_found"
    | "ambiguous"
    | "window_not_found"
    | "within_failed"
    | "index_out_of_range"
    | "app_not_running";
  message: string;
  locator: string;
  searchedIn: string;
  matchCount: number;
  /**
   * @maxItems 5
   */
  candidates:
    | []
    | [Candidate]
    | [Candidate, Candidate]
    | [Candidate, Candidate, Candidate]
    | [Candidate, Candidate, Candidate, Candidate]
    | [Candidate, Candidate, Candidate, Candidate, Candidate];
  within?: Diagnostic;
  /**
   * @maxItems 5
   */
  relocations?:
    | []
    | [Relocation]
    | [Relocation, Relocation]
    | [Relocation, Relocation, Relocation]
    | [Relocation, Relocation, Relocation, Relocation]
    | [Relocation, Relocation, Relocation, Relocation, Relocation];
  hint?: string;
  declared?: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "Relocation".
 */
export interface Relocation {
  kind: "element" | "component_root";
  target: string;
  window: string;
  path: string;
  sameWindow?: boolean;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ChildPageEntry".
 */
export interface ChildPageEntry {
  name: string;
  pageId: string;
  range: Range;
  nameRange: Range;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "Range".
 */
export interface Range {
  start: Position;
  end: Position;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "Position".
 */
export interface Position {
  line: number;
  character: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "CollectError".
 */
export interface CollectError {
  file: string;
  message: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "CollectedTest".
 */
export interface CollectedTest {
  id: string;
  file: string;
  line: number;
  name: string;
  markers?: string[];
  parent: string | null;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "DefinitionError".
 */
export interface DefinitionError {
  file: string;
  message: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "DefinitionMatch".
 */
export interface DefinitionMatch {
  id: string;
  qualname: string;
  kind: "element" | "elements" | "window";
  elementType?: string;
  locator: string;
  file: string;
  line: number;
  range?: Range;
  pages: string[];
  pageCount: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "DiscoverParams".
 */
export interface DiscoverParams {
  overrides?: {
    [k: string]: string;
  };
}
export interface DiscoverResult {
  version: 1;
  root: string;
  tests: TestEntry[];
  pages: PageEntry[];
  flows?: FlowEntry[];
  errors: DiscoveryError[];
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "TestEntry".
 */
export interface TestEntry {
  id: string;
  file: string;
  name: string;
  kind: "class" | "function";
  parent: string | null;
  range: Range;
  nameRange: Range;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "PageEntry".
 */
export interface PageEntry {
  id: string;
  file: string;
  name: string;
  qualname: string;
  bases: string[];
  range: Range;
  nameRange: Range;
  elements: ElementEntry[];
  children?: ChildPageEntry[];
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ElementEntry".
 */
export interface ElementEntry {
  id: string;
  name: string;
  qualname: string;
  kind: "window" | "element" | "elements";
  range: Range;
  nameRange: Range;
  locator: LocatorData;
  withinName?: string;
  windowName?: string;
  /**
   * The class the element is declared with: Element, Elements, a built-in typed element such as ComboBox, or a user-defined subclass of Element. Absent for windows.
   */
  elementType?: string;
  dynamic: boolean;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "LocatorData".
 */
export interface LocatorData {
  where?: {
    [k: string]: Matcher | boolean | number;
  };
  automationId?: Matcher;
  name?: Matcher;
  controlType?: string;
  className?: Matcher;
  index?: number;
  depth?: number;
  within?: LocatorData;
  window?: WindowLocatorData;
  item?: ItemSelectorData;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "WindowLocatorData".
 */
export interface WindowLocatorData {
  where?: {
    [k: string]: Matcher | boolean | number;
  };
  title?: Matcher;
  process?: string;
  className?: Matcher;
  automationId?: Matcher;
  index?: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "FlowEntry".
 */
export interface FlowEntry {
  id: string;
  file: string;
  name: string;
  range: Range;
  nameRange: Range;
  runnable?: boolean;
  parameters?: {
    name: string;
    type: "str" | "int" | "float" | "bool";
    required: boolean;
    default?: string | number | boolean;
  }[];
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "DiscoveryError".
 */
export interface DiscoveryError {
  file: string;
  message: string;
  line: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "DiscoveryResult".
 */
export interface DiscoveryResult {
  version: 1;
  root: string;
  tests: TestEntry[];
  pages: PageEntry[];
  flows?: FlowEntry[];
  errors: DiscoveryError[];
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ElementHighlightParams".
 */
export interface ElementHighlightParams {
  file: string;
  qualname: string;
  durationMs?: number;
}
export interface ElementHighlightResult {
  status: "found" | "not_found" | "ambiguous" | "error";
  element?: ElementInfo;
  diagnostic?: Diagnostic;
  message?: string;
  durationMs: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ElementResult".
 */
export interface ElementResult {
  status: "found" | "not_found" | "ambiguous" | "error";
  element?: ElementInfo;
  diagnostic?: Diagnostic;
  message?: string;
  durationMs: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ErrorInfo".
 */
export interface ErrorInfo {
  type: string;
  message: string;
  diagnostic?: Diagnostic;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "FlowRunParams".
 */
export interface FlowRunParams {
  file: string;
  name: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "FlowRunResult".
 */
export interface FlowRunResult {
  status: "passed" | "failed";
  message?: string;
  durationMs: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InitializeParams".
 */
export interface InitializeParams {
  root: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InitializeResult".
 */
export interface InitializeResult {
  protocolVersion: 1;
  wintestkitVersion: string;
  python: string;
  config: {
    found: boolean;
    app?: {
      path: string;
      process: string;
    };
    launch: string;
    timeout: number;
    reportDir: string;
  };
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectChildrenParams".
 */
export interface InspectChildrenParams {
  nodeId: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "NodeInfo".
 */
export interface NodeInfo {
  nodeId: string;
  info: ElementInfo;
  hasChildren: boolean;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectCoverageParams".
 */
export interface InspectCoverageParams {
  /**
   * @maxItems 500
   */
  nodeIds: string[];
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectCoverageResult".
 */
export interface InspectCoverageResult {
  covered: {
    [k: string]: NodeCoverage;
  };
  pending: string[];
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "NodeCoverage".
 */
export interface NodeCoverage {
  count: number;
  first: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectDefinitionsParams".
 */
export interface InspectDefinitionsParams {
  nodeId: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectDefinitionsResult".
 */
export interface InspectDefinitionsResult {
  definitions: DefinitionMatch[];
  errors: DefinitionError[];
  pageCount: number;
  appRunning?: boolean;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectHighlightParams".
 */
export interface InspectHighlightParams {
  nodeId: string;
  durationMs?: number;
  bringToFront?: boolean;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectPartialErrorData".
 */
export interface InspectPartialErrorData {
  nodes: InspectRootsResult;
  complete: false;
  errors: {
    index: number;
    message: string;
  }[];
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectPreviewParams".
 */
export interface InspectPreviewParams {
  nodeId: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectPreviewResult".
 */
export interface InspectPreviewResult {
  element?: PreviewImage;
  window?: PreviewImage;
  reason?: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "PreviewImage".
 */
export interface PreviewImage {
  data: string;
  width: number;
  height: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectPropertiesParams".
 */
export interface InspectPropertiesParams {
  nodeId: string;
  /**
   * Read the complete property list and supported patterns; defaults to false.
   */
  full?: boolean;
  /**
   * Include ancestors for revealing a picked object; defaults to false.
   */
  includeAncestors?: boolean;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectPropertiesResult".
 */
export interface InspectPropertiesResult {
  inspection?: InspectionProperty[];
  info: ElementInfo;
  properties: {
    [k: string]: string;
  };
  ancestors: NodeInfo[];
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectionProperty".
 */
export interface InspectionProperty {
  name: string;
  typeName: string;
  kind: "scalar" | "object" | "array" | "unavailable";
  value?: string | number | boolean | null;
  children?: InspectionProperty[];
  status?: string;
}
export interface InspectRefreshParams {
  includeOtherApps?: boolean;
  foregroundForProcessId?: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectRefreshResult".
 */
export interface InspectRefreshResult {
  nodes: InspectRootsResult;
  status: AppStatusResult;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectRootsParams".
 */
export interface InspectRootsParams {
  includeOtherApps?: boolean;
  foregroundForProcessId?: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "LogNotification".
 */
export interface LogNotification {
  level: "debug" | "info" | "warning" | "error";
  message: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "PageCheckParams".
 */
export interface PageCheckParams {
  file: string;
  page: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "PageCheckResult".
 */
export interface PageCheckResult {
  results: CheckResult[];
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "Replay".
 */
export interface Replay {
  startedAt: number;
  duration: number;
  frames: {
    time: number;
    path: string;
  }[];
  truncated: boolean;
  error?: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "Results".
 */
export interface Results {
  root?: string | null;
  command?: string | null;
  version: 1;
  startedAt: number;
  finishedAt: number;
  duration: number;
  environment: {
    python: string;
    wintestkit: string;
    windows: string;
    machine: string;
    screen: {
      width: number;
      height: number;
      scale: number;
    };
  };
  summary: Summary;
  tests: TestResult[];
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "Summary".
 */
export interface Summary {
  total: number;
  passed: number;
  failed: number;
  skipped: number;
  errors: number;
  duration: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "TestResult".
 */
export interface TestResult {
  id: string;
  file: string;
  line: number;
  name: string;
  absoluteFile?: string;
  markers?: string[];
  outcome: TestOutcome;
  duration: number;
  message?: string;
  location?: {
    file: string;
    line: number;
  };
  error?: ErrorInfo;
  steps: StepEvent[];
  screenshots: string[];
  replay?: Replay;
  treeDump?: string;
  treeDiff?: string;
  stdout: string;
  stderr: string;
  log: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "StepEvent".
 */
export interface StepEvent {
  seq: number;
  action: string;
  target: string;
  locator: string;
  args: {
    [k: string]: unknown;
  };
  start: number;
  duration: number;
  status: "passed" | "failed";
  error?: ErrorInfo;
  screenshot?: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "SpyCancelledNotification".
 */
export interface SpyCancelledNotification {
  sessionId?: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "SpyHoverNotification".
 */
export interface SpyHoverNotification {
  sessionId?: string;
  node: NodeInfo;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "SpyPickedNotification".
 */
export interface SpyPickedNotification {
  sessionId?: string;
  node: NodeInfo;
  suggestion?: Suggestion;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "Suggestion".
 */
export interface Suggestion {
  locator: LocatorData;
  code: string;
  attributeName: string;
  helpers: {
    attributeName: string;
    code: string;
    locator: LocatorData;
  }[];
  unique: boolean;
  matchCount: number;
  strategy: "automation_id" | "name" | "class_name" | "within" | "index";
  window?: {
    code: string;
    locator: WindowLocatorData;
  };
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "SpyStartParams".
 */
export interface SpyStartParams {
  sessionId?: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "SuggestLocatorParams".
 */
export interface SuggestLocatorParams {
  nodeId: string;
}
export interface SuggestLocatorResult {
  locator: LocatorData;
  code: string;
  attributeName: string;
  helpers: {
    attributeName: string;
    code: string;
    locator: LocatorData;
  }[];
  unique: boolean;
  matchCount: number;
  strategy: "automation_id" | "name" | "class_name" | "within" | "index";
  window?: {
    code: string;
    locator: WindowLocatorData;
  };
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "DiscoverResult".
 */
export interface DiscoveryResult1 {
  version: 1;
  root: string;
  tests: TestEntry[];
  pages: PageEntry[];
  flows?: FlowEntry[];
  errors: DiscoveryError[];
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ElementHighlightResult".
 */
export interface ElementResult1 {
  status: "found" | "not_found" | "ambiguous" | "error";
  element?: ElementInfo;
  diagnostic?: Diagnostic;
  message?: string;
  durationMs: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectRefreshParams".
 */
export interface InspectRootsParams1 {
  includeOtherApps?: boolean;
  foregroundForProcessId?: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "SuggestLocatorResult".
 */
export interface Suggestion1 {
  locator: LocatorData;
  code: string;
  attributeName: string;
  helpers: {
    attributeName: string;
    code: string;
    locator: LocatorData;
  }[];
  unique: boolean;
  matchCount: number;
  strategy: "automation_id" | "name" | "class_name" | "within" | "index";
  window?: {
    code: string;
    locator: WindowLocatorData;
  };
}
