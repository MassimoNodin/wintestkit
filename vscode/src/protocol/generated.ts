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
 * via the `definition` "Key".
 */
export type Key = string;
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "AttributeLiteral".
 */
export type AttributeLiteral = AttributeLiteral1;
/**
 * Recursive binding trees have maximum depth 8 and 32 total entries.
 *
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "BindingInfo".
 */
export type BindingInfo = BindingInfo1;
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "Identifier".
 */
export type Identifier = string;
/**
 * @minItems 1
 * @maxItems 1024
 *
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "RuntimeId".
 */
export type RuntimeId = [number, ...number[]];
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "CandidateResult".
 */
export type CandidateResult = CandidateResult1;
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "Mapping".
 */
export type Mapping = Mapping1;
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "TypeName".
 */
export type TypeName = string;
/**
 * A type segment must be alone. Serialized paths must not exceed 1024 UTF-8 bytes.
 *
 * @minItems 1
 * @maxItems 8
 *
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "Path".
 */
export type Path = Path1;
export type Path1 =
  | [PathSegment]
  | [PathSegment, PathSegment]
  | [PathSegment, PathSegment, PathSegment]
  | [PathSegment, PathSegment, PathSegment, PathSegment]
  | [PathSegment, PathSegment, PathSegment, PathSegment, PathSegment]
  | [
      PathSegment,
      PathSegment,
      PathSegment,
      PathSegment,
      PathSegment,
      PathSegment
    ]
  | [
      PathSegment,
      PathSegment,
      PathSegment,
      PathSegment,
      PathSegment,
      PathSegment,
      PathSegment
    ]
  | [
      PathSegment,
      PathSegment,
      PathSegment,
      PathSegment,
      PathSegment,
      PathSegment,
      PathSegment,
      PathSegment
    ];
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "PathSegment".
 */
export type PathSegment =
  | {
      kind: "property";
      name: Key;
      declaringType?: Key;
      memberKey?: Key;
    }
  | {
      kind: "field";
      name: Key;
      declaringType?: Key;
      memberKey?: Key;
    }
  | {
      kind: "dependency";
      ownerType: Key;
      ownerAssembly: Key;
      name: Key;
    }
  | {
      kind: "type";
      name:
        | "Name"
        | "FullName"
        | "AssemblyName"
        | "AssemblyQualifiedName"
        | "BaseTypes";
    };
/**
 * For truncated values truncatedAt is greater than the Unicode scalar length of scalar; dependencySource is present only for dependency reads.
 *
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "Value".
 */
export type Value = Value1;
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ScalarString".
 */
export type ScalarString = string;
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "CloseParams".
 */
export type CloseParams = Record<string, never>;
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
 * @maxItems 200
 *
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "Features".
 */
export type Features = (
  | "typeMetadata"
  | "clrMembers"
  | "dependencyProperties"
  | "bindings"
  | "exactUiaMapping"
  | "batchReads"
)[];
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
 * Recursive binding trees have maximum depth 8 and 32 total entries.
 */
export type ManagedBindingInfo = {
  memberKey: Key;
  kind: "none" | "binding" | "multiBinding" | "priorityBinding";
  status: string;
  mode: string;
  updateSourceTrigger: string;
  path?: string;
  elementName?: string;
  relativeSource?: RelativeSource;
  sourceType?: Key;
  converterType?: Key;
  /**
   * @maxItems 32
   */
  children?: BindingInfo[];
  /**
   * @maxItems 32
   */
  validationErrors?: Key[];
};
/**
 * nextToken is present iff further items exist; incomplete pages may instead indicate partial failure.
 */
export type InspectManagedChildrenResult = {
  /**
   * @maxItems 200
   */
  items: ManagedNode[];
  complete: boolean;
  snapshotId: Identifier;
  /**
   * @maxItems 200
   */
  diagnostics: ManagedDiagnostic[];
  nextToken?: Identifier;
};
/**
 * nextToken is present iff further items exist; incomplete pages may instead indicate partial failure.
 */
export type InspectManagedMembersResult = {
  /**
   * @maxItems 200
   */
  items: Member[];
  complete: boolean;
  snapshotId: Identifier;
  /**
   * @maxItems 200
   */
  diagnostics: ManagedDiagnostic[];
  nextToken?: Identifier;
};
/**
 * A type segment must be alone. Serialized paths must not exceed 1024 UTF-8 bytes.
 *
 * @minItems 1
 * @maxItems 8
 */
export type ManagedPath =
  | [PathSegment]
  | [PathSegment, PathSegment]
  | [PathSegment, PathSegment, PathSegment]
  | [PathSegment, PathSegment, PathSegment, PathSegment]
  | [PathSegment, PathSegment, PathSegment, PathSegment, PathSegment]
  | [
      PathSegment,
      PathSegment,
      PathSegment,
      PathSegment,
      PathSegment,
      PathSegment
    ]
  | [
      PathSegment,
      PathSegment,
      PathSegment,
      PathSegment,
      PathSegment,
      PathSegment,
      PathSegment
    ]
  | [
      PathSegment,
      PathSegment,
      PathSegment,
      PathSegment,
      PathSegment,
      PathSegment,
      PathSegment,
      PathSegment
    ];
export type InspectManagedResolveResult = {
  status:
    | "exact"
    | "notFound"
    | "ambiguous"
    | "unsupportedPeer"
    | "stale"
    | "limitExceeded";
  process: ProcessIdentity;
  runtimeId: RuntimeId;
  object?: ObjectRef;
};
/**
 * nextToken is present iff further items exist; incomplete pages may instead indicate partial failure.
 */
export type InspectManagedRootsResult = {
  /**
   * @maxItems 200
   */
  items: ManagedNode[];
  complete: boolean;
  snapshotId: Identifier;
  /**
   * @maxItems 200
   */
  diagnostics: ManagedDiagnostic[];
  nextToken?: Identifier;
};
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectRootsResult".
 */
export type InspectRootsResult = NodeInfo[];
/**
 * nextToken is present iff further items exist; incomplete pages may instead indicate partial failure.
 */
export type ManagedInspectorNodePage = {
  /**
   * @maxItems 200
   */
  items: ManagedNode[];
  complete: boolean;
  snapshotId: Identifier;
  /**
   * @maxItems 200
   */
  diagnostics: ManagedDiagnostic[];
  nextToken?: Identifier;
};
export type ManagedMapping = {
  status:
    | "exact"
    | "notFound"
    | "ambiguous"
    | "unsupportedPeer"
    | "stale"
    | "limitExceeded";
  process: ProcessIdentity;
  runtimeId: RuntimeId;
  object?: ObjectRef;
};
/**
 * nextToken is present iff further items exist; incomplete pages may instead indicate partial failure.
 */
export type ManagedMemberPage = {
  /**
   * @maxItems 200
   */
  items: Member[];
  complete: boolean;
  snapshotId: Identifier;
  /**
   * @maxItems 200
   */
  diagnostics: ManagedDiagnostic[];
  nextToken?: Identifier;
};
/**
 * nextToken is present iff further items exist; incomplete pages may instead indicate partial failure.
 *
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ManagedNodePage".
 */
export type ManagedNodePage = ManagedNodePage1;
/**
 * nextToken is present iff further items exist; incomplete pages may instead indicate partial failure.
 *
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "MemberPage".
 */
export type MemberPage = MemberPage1;
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ResponseEnvelope".
 */
export type ResponseEnvelope = ResponseEnvelope1 & ResponseEnvelope2;
export type ResponseEnvelope1 = {
  [k: string]: unknown;
};
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
/**
 * Recursive binding trees have maximum depth 8 and 32 total entries.
 *
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ManagedBindingInfo".
 */
export type BindingInfo2 = ManagedBindingInfo1;
/**
 * nextToken is present iff further items exist; incomplete pages may instead indicate partial failure.
 *
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ManagedInspectorNodePage".
 */
export type ManagedNodePage2 = ManagedInspectorNodePage1;
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ManagedMapping".
 */
export type Mapping2 = ManagedMapping1;
/**
 * nextToken is present iff further items exist; incomplete pages may instead indicate partial failure.
 *
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ManagedMemberPage".
 */
export type MemberPage2 = ManagedMemberPage1;
/**
 * A type segment must be alone. Serialized paths must not exceed 1024 UTF-8 bytes.
 *
 * @minItems 1
 * @maxItems 8
 *
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ManagedPath".
 */
export type Path2 = ManagedPath1;
export type ManagedPath1 =
  | [PathSegment]
  | [PathSegment, PathSegment]
  | [PathSegment, PathSegment, PathSegment]
  | [PathSegment, PathSegment, PathSegment, PathSegment]
  | [PathSegment, PathSegment, PathSegment, PathSegment, PathSegment]
  | [
      PathSegment,
      PathSegment,
      PathSegment,
      PathSegment,
      PathSegment,
      PathSegment
    ]
  | [
      PathSegment,
      PathSegment,
      PathSegment,
      PathSegment,
      PathSegment,
      PathSegment,
      PathSegment
    ]
  | [
      PathSegment,
      PathSegment,
      PathSegment,
      PathSegment,
      PathSegment,
      PathSegment,
      PathSegment,
      PathSegment
    ];
/**
 * nextToken is present iff further items exist; incomplete pages may instead indicate partial failure.
 *
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectManagedChildrenResult".
 */
export type ManagedInspectorNodePage2 = InspectManagedChildrenResult1;
/**
 * nextToken is present iff further items exist; incomplete pages may instead indicate partial failure.
 *
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectManagedMembersResult".
 */
export type ManagedMemberPage2 = InspectManagedMembersResult1;
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectManagedResolveResult".
 */
export type ManagedMapping2 = InspectManagedResolveResult1;
/**
 * nextToken is present iff further items exist; incomplete pages may instead indicate partial failure.
 *
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectManagedRootsResult".
 */
export type ManagedInspectorNodePage3 = InspectManagedRootsResult1;

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
  AttributeInfo?: AttributeInfo;
  AttributeLiteral?: AttributeLiteral;
  BindingInfo?: BindingInfo;
  BindingsParams?: BindingsParams;
  BindingsResult?: BindingsResult;
  BootstrapSettings?: BootstrapSettings;
  CancelParams?: CancelParams;
  CancelResult?: CancelResult;
  Candidate?: Candidate;
  CandidateRequest?: CandidateRequest;
  CandidateResult?: CandidateResult;
  CheckResult?: CheckResult;
  ChildPageEntry?: ChildPageEntry;
  ChildrenParams?: ChildrenParams;
  CloseParams?: CloseParams;
  CloseResult?: CloseResult;
  CollectError?: CollectError;
  CollectedTest?: CollectedTest;
  DefinitionError?: DefinitionError;
  DefinitionMatch?: DefinitionMatch;
  DependencyMetadata?: DependencyMetadata;
  DependencySource?: DependencySource;
  Diagnostic?: Diagnostic;
  DiscoverParams?: DiscoverParams;
  DiscoverResult?: DiscoverResult;
  DiscoveryError?: DiscoveryError;
  DiscoveryResult?: DiscoveryResult;
  ElementCheckParams?: ElementCheckParams;
  ElementCheckResult?: ElementCheckResult;
  ElementEntry?: ElementEntry;
  ElementHighlightParams?: ElementHighlightParams;
  ElementHighlightResult?: ElementHighlightResult;
  ElementInfo?: ElementInfo;
  ElementResult?: ElementResult;
  ErrorInfo?: ErrorInfo;
  Features?: Features;
  FlowEntry?: FlowEntry;
  FlowRunParams?: FlowRunParams;
  FlowRunResult?: FlowRunResult;
  HelloParams?: HelloParams;
  HelloResult?: HelloResult;
  Identifier?: Identifier;
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
  InspectManagedAttachParams?: InspectManagedAttachParams;
  InspectManagedAttachResult?: InspectManagedAttachResult;
  InspectManagedBindingsParams?: InspectManagedBindingsParams;
  InspectManagedBindingsResult?: InspectManagedBindingsResult;
  InspectManagedChildrenParams?: InspectManagedChildrenParams;
  InspectManagedChildrenResult?: InspectManagedChildrenResult;
  InspectManagedDetachParams?: InspectManagedDetachParams;
  InspectManagedDetachResult?: InspectManagedDetachResult;
  InspectManagedIdentifyParams?: InspectManagedIdentifyParams;
  InspectManagedIdentifyResult?: InspectManagedIdentifyResult;
  InspectManagedMembersParams?: InspectManagedMembersParams;
  InspectManagedMembersResult?: InspectManagedMembersResult;
  InspectManagedReadParams?: InspectManagedReadParams;
  InspectManagedReadResult?: InspectManagedReadResult;
  InspectManagedReleaseParams?: InspectManagedReleaseParams;
  InspectManagedReleaseResult?: InspectManagedReleaseResult;
  InspectManagedResolveParams?: InspectManagedResolveParams;
  InspectManagedResolveResult?: InspectManagedResolveResult;
  InspectManagedRootsParams?: InspectManagedRootsParams;
  InspectManagedRootsResult?: InspectManagedRootsResult;
  InspectManagedStatusParams?: InspectManagedStatusParams;
  InspectManagedStatusResult?: InspectManagedStatusResult;
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
  Key?: Key;
  LocatorData?: LocatorData;
  LogNotification?: LogNotification;
  ManagedBindingInfo?: ManagedBindingInfo;
  ManagedDiagnostic?: ManagedDiagnostic;
  ManagedErrorInfo?: ManagedErrorInfo;
  ManagedInspectorNodePage?: ManagedInspectorNodePage;
  ManagedMapping?: ManagedMapping;
  ManagedMemberPage?: ManagedMemberPage;
  ManagedNode?: ManagedNode;
  ManagedNodePage?: ManagedNodePage;
  ManagedPath?: ManagedPath;
  ManagedPathValue?: ManagedPathValue;
  ManagedProcessIdentity?: ManagedProcessIdentity;
  ManagedSession?: ManagedSession;
  Mapping?: Mapping;
  Matcher?: Matcher;
  Member?: Member;
  MemberPage?: MemberPage;
  MembersParams?: MembersParams;
  Mismatch?: Mismatch;
  NodeCoverage?: NodeCoverage;
  NodeInfo?: NodeInfo;
  ObjectRef?: ObjectRef;
  PageCheckParams?: PageCheckParams;
  PageCheckResult?: PageCheckResult;
  PageEntry?: PageEntry;
  Path?: Path;
  PathSegment?: PathSegment;
  PathValue?: PathValue;
  Position?: Position;
  PreviewImage?: PreviewImage;
  ProcessIdentity?: ProcessIdentity;
  Range?: Range;
  ReadBatchParams?: ReadBatchParams;
  ReadBatchResult?: ReadBatchResult;
  ReadParams?: ReadParams;
  ReadResult?: ReadResult;
  Rect?: Rect;
  RelativeSource?: RelativeSource;
  ReleaseParams?: ReleaseParams;
  ReleaseResult?: ReleaseResult;
  Relocation?: Relocation;
  Replay?: Replay;
  RequestEnvelope?: RequestEnvelope;
  ResolveParams?: ResolveParams;
  ResponseEnvelope?: ResponseEnvelope;
  Results?: Results;
  RootsParams?: RootsParams;
  RunEvent?: RunEvent;
  RunningProcess?: RunningProcess;
  RuntimeId?: RuntimeId;
  ScalarString?: ScalarString;
  Session?: Session;
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
  TypeInfo?: TypeInfo;
  TypeName?: TypeName;
  Value?: Value;
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
 * via the `definition` "AttributeInfo".
 */
export interface AttributeInfo {
  typeName: Key;
  /**
   * @maxItems 32
   */
  constructorArguments: AttributeLiteral[];
  namedArguments: {
    [k: string]: AttributeLiteral;
  };
}
export interface AttributeLiteral1 {
  kind:
    | "string"
    | "enum"
    | "type"
    | "boolean"
    | "integer"
    | "number"
    | "null"
    | "array";
  value: unknown;
}
export interface BindingInfo1 {
  memberKey: Key;
  kind: "none" | "binding" | "multiBinding" | "priorityBinding";
  status: string;
  mode: string;
  updateSourceTrigger: string;
  path?: string;
  elementName?: string;
  relativeSource?: RelativeSource;
  sourceType?: Key;
  converterType?: Key;
  /**
   * @maxItems 32
   */
  children?: BindingInfo[];
  /**
   * @maxItems 32
   */
  validationErrors?: Key[];
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "RelativeSource".
 */
export interface RelativeSource {
  mode: "FindAncestor" | "PreviousData" | "TemplatedParent" | "Self";
  ancestorType?: Key;
  ancestorLevel?: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "BindingsParams".
 */
export interface BindingsParams {
  sessionId: Identifier;
  objectId: Identifier;
  generation: number;
  /**
   * @maxItems 32
   */
  memberKeys: Key[];
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "BindingsResult".
 */
export interface BindingsResult {
  /**
   * @maxItems 32
   */
  bindings: BindingInfo[];
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "BootstrapSettings".
 */
export interface BootstrapSettings {
  schemaVersion: 1;
  protocolMajor: number;
  protocolMinor: number;
  sessionId: string;
  process: ProcessIdentity;
  pipeName: Key;
  token: string;
  clientSid: Identifier;
  expiresUtc: string;
  requestTimeoutMs: number;
  idleTimeoutMs: number;
  agentVersion: Identifier;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ProcessIdentity".
 */
export interface ProcessIdentity {
  pid: number;
  creationTimeUtc: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "CancelParams".
 */
export interface CancelParams {
  requestId: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "CancelResult".
 */
export interface CancelResult {
  accepted: boolean;
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
 * via the `definition` "CandidateRequest".
 */
export interface CandidateRequest {
  runtimeId: RuntimeId;
  nativeWindowHandle?: number;
}
export interface CandidateResult1 {
  runtimeId: RuntimeId;
  mapping: Mapping;
  /**
   * @maxItems 32
   */
  values: PathValue[];
}
export interface Mapping1 {
  status:
    | "exact"
    | "notFound"
    | "ambiguous"
    | "unsupportedPeer"
    | "stale"
    | "limitExceeded";
  process: ProcessIdentity;
  runtimeId: RuntimeId;
  object?: ObjectRef;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ObjectRef".
 */
export interface ObjectRef {
  sessionId: Identifier;
  objectId: Identifier;
  generation: number;
  type: TypeInfo;
  dispatcherId: Identifier;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "TypeInfo".
 */
export interface TypeInfo {
  name: TypeName;
  fullName: TypeName;
  assemblyName: TypeName;
  assemblyQualifiedName: TypeName;
  /**
   * @maxItems 1024
   */
  baseTypes: TypeName[];
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "PathValue".
 */
export interface PathValue {
  path: Path;
  value: Value;
}
export interface Value1 {
  status:
    | "ok"
    | "notRead"
    | "notReadable"
    | "nullIntermediate"
    | "exception"
    | "stale"
    | "redacted"
    | "truncated"
    | "cycle"
    | "timeout"
    | "unsupported";
  kind:
    | "null"
    | "string"
    | "boolean"
    | "integer"
    | "number"
    | "enum"
    | "object"
    | "array"
    | "type"
    | "unavailable";
  declaredType: TypeName;
  runtimeType: TypeName;
  scalar?: null | boolean | number | ScalarString;
  object?: ObjectRef;
  message?: string;
  truncatedAt?: number;
  cycleTo?: ObjectRef;
  numericValue?: string;
  typeInfo?: TypeInfo;
  arrayRank?: number;
  arrayLength?: number;
  failedSegment?: number;
  redactionRule?: Key;
  dependencySource?: DependencySource;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "DependencySource".
 */
export interface DependencySource {
  baseValueSource:
    | "Unknown"
    | "Default"
    | "Inherited"
    | "DefaultStyle"
    | "DefaultStyleTrigger"
    | "Style"
    | "TemplateTrigger"
    | "StyleTrigger"
    | "ImplicitStyleReference"
    | "ParentTemplate"
    | "ParentTemplateTrigger"
    | "Local";
  isExpression: boolean;
  isAnimated: boolean;
  isCoerced: boolean;
  isCurrent: boolean;
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
 * via the `definition` "ChildrenParams".
 */
export interface ChildrenParams {
  sessionId: Identifier;
  objectId: Identifier;
  generation: number;
  tree: "visual" | "logical";
  pageSize?: number;
  pageToken?: Identifier;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "CloseResult".
 */
export interface CloseResult {
  closed: true;
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
 * via the `definition` "DependencyMetadata".
 */
export interface DependencyMetadata {
  ownerType: Key;
  ownerAssembly: Key;
  propertyType: Key;
  readOnly: boolean;
  isAttached: "true" | "false" | "unknown";
  hasLocalValue: boolean;
  /**
   * @maxItems 32
   */
  metadataFlags: (
    | "None"
    | "AffectsMeasure"
    | "AffectsArrange"
    | "AffectsParentMeasure"
    | "AffectsParentArrange"
    | "AffectsRender"
    | "Inherits"
    | "OverridesInheritanceBehavior"
    | "NotDataBindable"
    | "BindsTwoWayByDefault"
    | "Journal"
    | "SubPropertiesDoNotAffectRender"
  )[];
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
 * via the `definition` "ElementCheckParams".
 */
export interface ElementCheckParams {
  file: string;
  qualname: string;
}
export interface ElementCheckResult {
  status: "found" | "not_found" | "ambiguous" | "error";
  element?: ElementInfo;
  diagnostic?: Diagnostic;
  message?: string;
  durationMs: number;
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
 * via the `definition` "HelloParams".
 */
export interface HelloParams {
  protocolMajor: 1;
  protocolMinor: number;
  sessionId: Identifier;
  token: Identifier;
  process: ProcessIdentity;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "HelloResult".
 */
export interface HelloResult {
  agentVersion: Identifier;
  tfm: "net48" | "net8.0-windows" | "net10.0-windows";
  architecture: "x86" | "x64";
  runtimeVersion: Identifier;
  features: Features;
  process: ProcessIdentity;
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
  capabilities?: {
    managedInspector: boolean;
  };
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
 * via the `definition` "InspectManagedAttachParams".
 */
export interface InspectManagedAttachParams {
  process: ManagedProcessIdentity;
}
export interface ManagedProcessIdentity {
  pid: number;
  creationTimeUtc: string;
}
export interface InspectManagedAttachResult {
  sessionId: Identifier;
  process: ProcessIdentity;
  state:
    | "detached"
    | "probing"
    | "attaching"
    | "ready"
    | "detaching"
    | "faulted"
    | "exited";
  protocolMajor: number;
  protocolMinor: number;
  features: Features;
  runtimeVersion?: Identifier;
  architecture?: Identifier;
  agentVersion?: Identifier;
  error?: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectManagedBindingsParams".
 */
export interface InspectManagedBindingsParams {
  sessionId: string;
  objectId: string;
  generation: number;
  /**
   * @minItems 1
   * @maxItems 32
   */
  memberKeys: [string, ...string[]];
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectManagedBindingsResult".
 */
export interface InspectManagedBindingsResult {
  /**
   * @maxItems 32
   */
  bindings: ManagedBindingInfo[];
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectManagedChildrenParams".
 */
export interface InspectManagedChildrenParams {
  sessionId: string;
  objectId: string;
  generation: number;
  tree: "visual" | "logical";
  pageSize?: number;
  pageToken?: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ManagedNode".
 */
export interface ManagedNode {
  object: ObjectRef;
  label: string;
  hasVisualChildren: boolean;
  hasLogicalChildren: boolean;
  runtimeId?: RuntimeId;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ManagedDiagnostic".
 */
export interface ManagedDiagnostic {
  code: Identifier;
  message: string;
  category?: Identifier;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectManagedDetachParams".
 */
export interface InspectManagedDetachParams {
  sessionId: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectManagedDetachResult".
 */
export interface InspectManagedDetachResult {
  detached: true;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectManagedIdentifyParams".
 */
export interface InspectManagedIdentifyParams {
  nodeId: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectManagedIdentifyResult".
 */
export interface InspectManagedIdentifyResult {
  process: ManagedProcessIdentity;
  executable: string;
  runtime: "net48" | "net8" | "net10" | null;
  architecture: "x86" | "x64" | "arm64" | "unknown";
  wpfLoaded: boolean;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectManagedMembersParams".
 */
export interface InspectManagedMembersParams {
  sessionId: string;
  objectId: string;
  generation: number;
  pageSize?: number;
  pageToken?: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "Member".
 */
export interface Member {
  memberKey: Key;
  name: Key;
  category:
    | "typeMetadata"
    | "clrProperty"
    | "clrField"
    | "dependencyProperty"
    | "attachedProperty";
  declaringType: TypeName;
  declaredType: TypeName;
  visibility:
    | "public"
    | "protected"
    | "internal"
    | "private"
    | "protectedInternal"
    | "privateProtected";
  readable: boolean;
  /**
   * @maxItems 32
   */
  attributes: AttributeInfo[];
  pathSegment?: PathSegment;
  dependency?: DependencyMetadata;
  reason?:
    | "nonPublic"
    | "writeOnly"
    | "indexer"
    | "static"
    | "unsupportedType"
    | "ambiguous";
  wrapperKey?: Key;
  compatibilityAlias?: Identifier;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectManagedReadParams".
 */
export interface InspectManagedReadParams {
  sessionId: string;
  objectId: string;
  generation: number;
  /**
   * @minItems 1
   * @maxItems 32
   */
  paths: [ManagedPath, ...ManagedPath[]];
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectManagedReadResult".
 */
export interface InspectManagedReadResult {
  /**
   * @maxItems 32
   */
  values: ManagedPathValue[];
  readId: string;
}
export interface ManagedPathValue {
  path: Path;
  value: Value;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectManagedReleaseParams".
 */
export interface InspectManagedReleaseParams {
  sessionId: string;
  /**
   * @minItems 1
   * @maxItems 256
   */
  objectIds: [string, ...string[]];
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectManagedReleaseResult".
 */
export interface InspectManagedReleaseResult {
  releasedCount: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectManagedResolveParams".
 */
export interface InspectManagedResolveParams {
  sessionId: string;
  nodeId: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectManagedRootsParams".
 */
export interface InspectManagedRootsParams {
  sessionId: string;
  pageSize?: number;
  pageToken?: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectManagedStatusParams".
 */
export interface InspectManagedStatusParams {
  process: ManagedProcessIdentity;
}
export interface InspectManagedStatusResult {
  sessionId: Identifier;
  process: ProcessIdentity;
  state:
    | "detached"
    | "probing"
    | "attaching"
    | "ready"
    | "detaching"
    | "faulted"
    | "exited";
  protocolMajor: number;
  protocolMinor: number;
  features: Features;
  runtimeVersion?: Identifier;
  architecture?: Identifier;
  agentVersion?: Identifier;
  error?: string;
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
  /**
   * Extra UI Automation property names to read when full is false, such as properties the user pinned.
   *
   * @maxItems 64
   */
  include?: string[];
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
 * via the `definition` "ManagedErrorInfo".
 */
export interface ManagedErrorInfo {
  code:
    | "invalidParams"
    | "unsupportedProtocol"
    | "unsupportedTarget"
    | "accessDenied"
    | "authenticationFailed"
    | "payloadMissing"
    | "payloadMismatch"
    | "alreadyAttached"
    | "notAttached"
    | "attachFailed"
    | "blockedByPolicy"
    | "agentVersionMismatch"
    | "processExited"
    | "processReused"
    | "sessionStale"
    | "objectStale"
    | "mappingFailed"
    | "memberAmbiguous"
    | "memberNotFound"
    | "dispatcherUnavailable"
    | "timeout"
    | "busy"
    | "limitExceeded"
    | "invalidPageToken"
    | "cancelled"
    | "internalError";
  message: string;
  details?: {};
}
export interface ManagedNodePage1 {
  /**
   * @maxItems 200
   */
  items: ManagedNode[];
  complete: boolean;
  snapshotId: Identifier;
  /**
   * @maxItems 200
   */
  diagnostics: ManagedDiagnostic[];
  nextToken?: Identifier;
}
export interface ManagedSession {
  sessionId: Identifier;
  process: ProcessIdentity;
  state:
    | "detached"
    | "probing"
    | "attaching"
    | "ready"
    | "detaching"
    | "faulted"
    | "exited";
  protocolMajor: number;
  protocolMinor: number;
  features: Features;
  runtimeVersion?: Identifier;
  architecture?: Identifier;
  agentVersion?: Identifier;
  error?: string;
}
export interface MemberPage1 {
  /**
   * @maxItems 200
   */
  items: Member[];
  complete: boolean;
  snapshotId: Identifier;
  /**
   * @maxItems 200
   */
  diagnostics: ManagedDiagnostic[];
  nextToken?: Identifier;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "MembersParams".
 */
export interface MembersParams {
  sessionId: Identifier;
  objectId: Identifier;
  generation: number;
  pageSize?: number;
  pageToken?: Identifier;
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
 * via the `definition` "ReadBatchParams".
 */
export interface ReadBatchParams {
  /**
   * @minItems 1
   * @maxItems 32
   */
  candidates: [CandidateRequest, ...CandidateRequest[]];
  /**
   * @minItems 1
   * @maxItems 32
   */
  paths: [Path, ...Path[]];
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ReadBatchResult".
 */
export interface ReadBatchResult {
  /**
   * @minItems 1
   * @maxItems 32
   */
  candidates: [CandidateResult, ...CandidateResult[]];
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ReadParams".
 */
export interface ReadParams {
  sessionId: Identifier;
  objectId: Identifier;
  generation: number;
  /**
   * @minItems 1
   * @maxItems 32
   */
  paths: [Path, ...Path[]];
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ReadResult".
 */
export interface ReadResult {
  /**
   * @maxItems 32
   */
  values: PathValue[];
  readId: Identifier;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ReleaseParams".
 */
export interface ReleaseParams {
  sessionId: Identifier;
  /**
   * @maxItems 256
   */
  objectIds: Identifier[];
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ReleaseResult".
 */
export interface ReleaseResult {
  releasedCount: number;
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
 * via the `definition` "RequestEnvelope".
 */
export interface RequestEnvelope {
  id: number;
  method:
    | "session.hello"
    | "session.close"
    | "request.cancel"
    | "element.resolve"
    | "element.readBatch"
    | "roots"
    | "children"
    | "members"
    | "read"
    | "bindings"
    | "release";
  params: {};
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ResolveParams".
 */
export interface ResolveParams {
  runtimeId: RuntimeId;
  nativeWindowHandle?: number;
}
export interface ResponseEnvelope2 {
  id: number;
  result?: unknown;
  error?: ManagedErrorInfo;
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
 * via the `definition` "RootsParams".
 */
export interface RootsParams {
  sessionId: Identifier;
  pageSize?: number;
  pageToken?: Identifier;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "Session".
 */
export interface Session {
  sessionId: Identifier;
  process: ProcessIdentity;
  state:
    | "detached"
    | "probing"
    | "attaching"
    | "ready"
    | "detaching"
    | "faulted"
    | "exited";
  protocolMajor: number;
  protocolMinor: number;
  features: Features;
  runtimeVersion?: Identifier;
  architecture?: Identifier;
  agentVersion?: Identifier;
  error?: string;
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
export interface ManagedBindingInfo1 {
  memberKey: Key;
  kind: "none" | "binding" | "multiBinding" | "priorityBinding";
  status: string;
  mode: string;
  updateSourceTrigger: string;
  path?: string;
  elementName?: string;
  relativeSource?: RelativeSource;
  sourceType?: Key;
  converterType?: Key;
  /**
   * @maxItems 32
   */
  children?: BindingInfo[];
  /**
   * @maxItems 32
   */
  validationErrors?: Key[];
}
export interface ManagedInspectorNodePage1 {
  /**
   * @maxItems 200
   */
  items: ManagedNode[];
  complete: boolean;
  snapshotId: Identifier;
  /**
   * @maxItems 200
   */
  diagnostics: ManagedDiagnostic[];
  nextToken?: Identifier;
}
export interface ManagedMapping1 {
  status:
    | "exact"
    | "notFound"
    | "ambiguous"
    | "unsupportedPeer"
    | "stale"
    | "limitExceeded";
  process: ProcessIdentity;
  runtimeId: RuntimeId;
  object?: ObjectRef;
}
export interface ManagedMemberPage1 {
  /**
   * @maxItems 200
   */
  items: Member[];
  complete: boolean;
  snapshotId: Identifier;
  /**
   * @maxItems 200
   */
  diagnostics: ManagedDiagnostic[];
  nextToken?: Identifier;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ManagedPathValue".
 */
export interface PathValue1 {
  path: Path;
  value: Value;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ManagedProcessIdentity".
 */
export interface ProcessIdentity1 {
  pid: number;
  creationTimeUtc: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ManagedSession".
 */
export interface Session1 {
  sessionId: Identifier;
  process: ProcessIdentity;
  state:
    | "detached"
    | "probing"
    | "attaching"
    | "ready"
    | "detaching"
    | "faulted"
    | "exited";
  protocolMajor: number;
  protocolMinor: number;
  features: Features;
  runtimeVersion?: Identifier;
  architecture?: Identifier;
  agentVersion?: Identifier;
  error?: string;
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
 * via the `definition` "ElementCheckResult".
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
 * via the `definition` "ElementHighlightResult".
 */
export interface ElementResult2 {
  status: "found" | "not_found" | "ambiguous" | "error";
  element?: ElementInfo;
  diagnostic?: Diagnostic;
  message?: string;
  durationMs: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectManagedAttachResult".
 */
export interface ManagedSession1 {
  sessionId: Identifier;
  process: ProcessIdentity;
  state:
    | "detached"
    | "probing"
    | "attaching"
    | "ready"
    | "detaching"
    | "faulted"
    | "exited";
  protocolMajor: number;
  protocolMinor: number;
  features: Features;
  runtimeVersion?: Identifier;
  architecture?: Identifier;
  agentVersion?: Identifier;
  error?: string;
}
export interface InspectManagedChildrenResult1 {
  /**
   * @maxItems 200
   */
  items: ManagedNode[];
  complete: boolean;
  snapshotId: Identifier;
  /**
   * @maxItems 200
   */
  diagnostics: ManagedDiagnostic[];
  nextToken?: Identifier;
}
export interface InspectManagedMembersResult1 {
  /**
   * @maxItems 200
   */
  items: Member[];
  complete: boolean;
  snapshotId: Identifier;
  /**
   * @maxItems 200
   */
  diagnostics: ManagedDiagnostic[];
  nextToken?: Identifier;
}
export interface InspectManagedResolveResult1 {
  status:
    | "exact"
    | "notFound"
    | "ambiguous"
    | "unsupportedPeer"
    | "stale"
    | "limitExceeded";
  process: ProcessIdentity;
  runtimeId: RuntimeId;
  object?: ObjectRef;
}
export interface InspectManagedRootsResult1 {
  /**
   * @maxItems 200
   */
  items: ManagedNode[];
  complete: boolean;
  snapshotId: Identifier;
  /**
   * @maxItems 200
   */
  diagnostics: ManagedDiagnostic[];
  nextToken?: Identifier;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectManagedStatusResult".
 */
export interface ManagedSession2 {
  sessionId: Identifier;
  process: ProcessIdentity;
  state:
    | "detached"
    | "probing"
    | "attaching"
    | "ready"
    | "detaching"
    | "faulted"
    | "exited";
  protocolMajor: number;
  protocolMinor: number;
  features: Features;
  runtimeVersion?: Identifier;
  architecture?: Identifier;
  agentVersion?: Identifier;
  error?: string;
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
