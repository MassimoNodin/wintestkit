/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "Identifier".
 */
export type Identifier = string;
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "TypeName".
 */
export type TypeName = string;
/**
 * Validate the shared regex subset and bounds before matching; Python re.search semantics with ASCII-only case folding, multiline anchors and singleline dot; reject unsupported constructs and malformed patterns.
 *
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ItemMatch".
 */
export type ItemMatch =
  | {
      kind: "index";
      index: number;
    }
  | {
      kind: "equals";
      path: Path &
        {
          [k: string]: unknown;
        }[];
      value: Scalar;
    }
  | {
      kind: "regex";
      path: Path &
        {
          [k: string]: unknown;
        }[];
      pattern: string;
      flags: RegexFlags;
    };
/**
 * Type and UIA segments must be alone. Serialized paths must not exceed 1024 UTF-8 bytes.
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
    }
  | {
      kind: "uia";
      name:
        | string
        | (
            | "automation_id"
            | "name"
            | "class_name"
            | "control_type"
            | "supported_patterns"
            | "value"
            | "is_read_only"
            | "toggle_state"
            | "is_selected"
            | "expand_state"
            | "range_value"
            | "document_text"
            | "is_password"
            | "selection_count"
            | "item_count"
          );
    };
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "Key".
 */
export type Key = string;
/**
 * Numbers must be finite; writes require exact scalar CLR types and signed 64-bit integer tokens; no conversions or nulls.
 *
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "Scalar".
 */
export type Scalar = string | boolean | number;
/**
 * @maxItems 3
 *
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "RegexFlags".
 */
export type RegexFlags =
  | []
  | ["ignoreCase" | "multiline" | "singleline"]
  | [
      "ignoreCase" | "multiline" | "singleline",
      "ignoreCase" | "multiline" | "singleline"
    ]
  | [
      "ignoreCase" | "multiline" | "singleline",
      "ignoreCase" | "multiline" | "singleline",
      "ignoreCase" | "multiline" | "singleline"
    ];
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ScrollAmount".
 */
export type ScrollAmount =
  | "none"
  | "smallIncrement"
  | "smallDecrement"
  | "largeIncrement"
  | "largeDecrement";
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ScalarString".
 */
export type ScalarString = string;
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
 * For truncated values truncatedAt is greater than the Unicode scalar length of scalar; dependencySource is present only for dependency reads.
 *
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "Value".
 */
export type Value = Value1;
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "CallArgument".
 */
export type CallArgument =
  | Scalar
  | ({
      [k: string]: unknown;
    } & {
      type: string;
      value?: Scalar;
      enum?: string | number;
      null?: true;
    });
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
 * via the `definition` "CloseParams".
 */
export type CloseParams = Record<string, never>;
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ClrMemberEvent".
 */
export type ClrMemberEvent = ClrMemberEvent1;
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
 * via the `definition` "EventKind".
 */
export type EventKind = "windowOpened" | "windowClosed" | "treeChanged";
/**
 * Ordered per subscription; sequence gaps, overflow and reconnect require rescan. Buffer at most 1024; overflow drops pending and triggering events.
 *
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "EventsEventParams".
 */
export type EventsEventParams = EventsEventParams1;
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
  | "query"
  | "geometry"
  | "actions"
  | "virtualItems"
  | "writes"
  | "hitTest"
  | "waits"
  | "events"
  | "treeParent"
  | "membersItems"
  | "membersStyling"
  | "membersEvents"
)[];
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectChildrenResult".
 */
export type InspectChildrenResult =
  | NodeInfo[]
  | {
      attachRequired: true;
      process: ManagedProcessIdentity;
    }
  | {
      blocked: {
        code: string;
        hint: string;
      };
    }
  | {
      nodes: NodeInfo[];
      nextPageToken?: string;
    };
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "SpyHostCapability".
 */
export type SpyHostCapability = string;
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
  stringFormat?: string;
  fallbackValue?: Value;
  targetNullValue?: Value;
  converterParameter?: Value;
  converterCulture?: string;
  delay?: number;
  bindingGroupName?: string;
  xPath?: string;
  isAsync?: boolean;
  notifyOnSourceUpdated?: boolean;
  notifyOnTargetUpdated?: boolean;
  notifyOnValidationError?: boolean;
  validatesOnDataErrors?: boolean;
  validatesOnExceptions?: boolean;
  validatesOnNotifyDataErrors?: boolean;
  /**
   * @maxItems 32
   */
  validationRules?: Key[];
  hasUpdateSourceExceptionFilter?: boolean;
  activeChildIndex?: number;
  dataItem?: Value;
  resolvedSource?: Value;
  resolvedSourcePropertyName?: string;
  hasError?: boolean;
  hasValidationError?: boolean;
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
export type InspectManagedEventsResult = {
  /**
   * @maxItems 200
   */
  items: MemberEvent[];
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
 * via the `definition` "MemberEvent".
 */
export type MemberEvent = RoutedMemberEvent | ClrMemberEvent;
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "RoutedMemberEvent".
 */
export type RoutedMemberEvent = RoutedMemberEvent1;
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
 * Type and UIA segments must be alone. Serialized paths must not exceed 1024 UTF-8 bytes.
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
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectManagedResolveResult".
 */
export type InspectManagedResolveResult =
  | ManagedMapping
  | {
      status: "exact";
      process: ManagedProcessIdentity;
      object: ObjectRef;
      source: "wpf" | "winforms";
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
export type InspectManagedResourceResult = {
  found: boolean;
  valueType?: string;
  value?: Value;
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
export type InspectManagedSpyMethodsResult = {
  /**
   * @maxItems 200
   */
  items: MethodMetadata[];
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
 * via the `definition` "SpyInvokeArgument".
 */
export type SpyInvokeArgument = SpyInvokeArgument1 & SpyInvokeArgument2;
export type SpyInvokeArgument1 = {
  [k: string]: unknown;
};
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectRootsResult".
 */
export type InspectRootsResult = NodeInfo[];
/**
 * Depth-first pre-order; scoped roots are depth 0; combined visits visual before logical-only children and deduplicates identity.
 *
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "Scope".
 */
export type Scope =
  | {
      kind: "allRoots";
    }
  | {
      kind: "window";
      handle: ObjectRef;
    }
  | {
      kind: "object";
      handle: ObjectRef;
    };
/**
 * Validate the shared regex subset and bounds before matching; Python re.search semantics with ASCII-only case folding, multiline anchors and singleline dot; reject unsupported constructs and malformed patterns. Equality is type-aware; assignability uses already-loaded metadata. Unavailable, redacted, truncated or failed values cannot silently match.
 *
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "Predicate".
 */
export type Predicate =
  | {
      kind: "equals";
      path: Path;
      value: Scalar;
    }
  | {
      kind: "regex";
      path: Path;
      pattern: string;
      flags: RegexFlags;
    }
  | {
      kind: "assignableTo";
      fullName: Key;
    };
export type ManagedEventPage = {
  /**
   * @maxItems 200
   */
  items: MemberEvent[];
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
export type ManagedMethodPage = {
  /**
   * @maxItems 200
   */
  items: MethodMetadata[];
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
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "MemberEventPage".
 */
export type MemberEventPage = MemberEventPage1;
/**
 * nextToken is present iff further items exist; incomplete pages may instead indicate partial failure.
 *
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "MemberPage".
 */
export type MemberPage = MemberPage1;
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "MethodPage".
 */
export type MethodPage = MethodPage1;
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ResourceResult".
 */
export type ResourceResult = ResourceResult1;
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
      event: "log";
      time: number;
      id: string;
      entry: LogEntry;
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
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "WaitCondition".
 */
export type WaitCondition =
  | {
      kind: "exists";
      locator: Locator;
    }
  | {
      kind: "visible";
      locator: Locator;
    }
  | {
      kind: "enabled";
      locator: Locator;
    }
  | {
      kind: "propertyEquals";
      locator: Locator;
      path: Path;
      value: Scalar;
    };
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "WaitResult".
 */
export type WaitResult = WaitResult1;
export type WaitUntilResult = {
  satisfied: boolean;
  handle?: ObjectRef;
  state?: ElementState;
};
/**
 * Recursive binding trees have maximum depth 8 and 32 total entries.
 *
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ManagedBindingInfo".
 */
export type BindingInfo2 = ManagedBindingInfo1;
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ManagedEventPage".
 */
export type MemberEventPage2 = ManagedEventPage1;
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
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ManagedMethodPage".
 */
export type MethodPage2 = ManagedMethodPage1;
/**
 * Type and UIA segments must be alone. Serialized paths must not exceed 1024 UTF-8 bytes.
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
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectManagedEventsResult".
 */
export type ManagedEventPage2 = InspectManagedEventsResult1;
/**
 * nextToken is present iff further items exist; incomplete pages may instead indicate partial failure.
 *
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectManagedMembersResult".
 */
export type ManagedMemberPage2 = InspectManagedMembersResult1;
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectManagedResourceResult".
 */
export type ResourceResult2 = InspectManagedResourceResult1;
/**
 * nextToken is present iff further items exist; incomplete pages may instead indicate partial failure.
 *
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectManagedRootsResult".
 */
export type ManagedInspectorNodePage3 = InspectManagedRootsResult1;
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectManagedSpyMethodsResult".
 */
export type ManagedMethodPage2 = InspectManagedSpyMethodsResult1;
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "WaitUntilResult".
 */
export type WaitResult2 = WaitUntilResult1;

export interface ProtocolContracts {
  ActBringIntoViewParams?: ActBringIntoViewParams;
  ActBringIntoViewResult?: ActBringIntoViewResult;
  ActCollapseParams?: ActCollapseParams;
  ActCollapseResult?: ActCollapseResult;
  ActExpandParams?: ActExpandParams;
  ActExpandResult?: ActExpandResult;
  ActFocusParams?: ActFocusParams;
  ActFocusResult?: ActFocusResult;
  ActInvokeParams?: ActInvokeParams;
  ActInvokeResult?: ActInvokeResult;
  ActRealizeItemParams?: ActRealizeItemParams;
  ActRealizeItemResult?: ActRealizeItemResult;
  ActResult?: ActResult;
  ActScrollIntoViewParams?: ActScrollIntoViewParams;
  ActScrollIntoViewResult?: ActScrollIntoViewResult;
  ActScrollParams?: ActScrollParams;
  ActScrollResult?: ActScrollResult;
  ActSelectParams?: ActSelectParams;
  ActSelectResult?: ActSelectResult;
  ActSetRangeParams?: ActSetRangeParams;
  ActSetRangeResult?: ActSetRangeResult;
  ActSetValueParams?: ActSetValueParams;
  ActSetValueResult?: ActSetValueResult;
  ActToggleParams?: ActToggleParams;
  ActToggleResult?: ActToggleResult;
  AllowEntry?: AllowEntry;
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
  CallArgument?: CallArgument;
  CancelParams?: CancelParams;
  CancelRequestNotification?: CancelRequestNotification;
  CancelResult?: CancelResult;
  Candidate?: Candidate;
  CandidateRequest?: CandidateRequest;
  CandidateResult?: CandidateResult;
  CheckResult?: CheckResult;
  ChildPageEntry?: ChildPageEntry;
  ChildrenParams?: ChildrenParams;
  CloseParams?: CloseParams;
  CloseResult?: CloseResult;
  ClrEventSubscriber?: ClrEventSubscriber;
  ClrMemberEvent?: ClrMemberEvent;
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
  ElementState?: ElementState;
  ErrorInfo?: ErrorInfo;
  EventKind?: EventKind;
  EventsEventParams?: EventsEventParams;
  EventsNotification?: EventsNotification;
  EventsSubscribeParams?: EventsSubscribeParams;
  EventsSubscribeResult?: EventsSubscribeResult;
  EventsUnsubscribeParams?: EventsUnsubscribeParams;
  EventsUnsubscribeResult?: EventsUnsubscribeResult;
  Features?: Features;
  FlowEntry?: FlowEntry;
  FlowRunParams?: FlowRunParams;
  FlowRunResult?: FlowRunResult;
  HelloParams?: HelloParams;
  HelloResult?: HelloResult;
  HitTestParams?: HitTestParams;
  HitTestResult?: HitTestResult;
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
  InspectManagedEventsParams?: InspectManagedEventsParams;
  InspectManagedEventsResult?: InspectManagedEventsResult;
  InspectManagedIdentifyParams?: InspectManagedIdentifyParams;
  InspectManagedIdentifyResult?: InspectManagedIdentifyResult;
  InspectManagedItemsParams?: InspectManagedItemsParams;
  InspectManagedItemsResult?: InspectManagedItemsResult;
  InspectManagedKeepaliveParams?: InspectManagedKeepaliveParams;
  InspectManagedKeepaliveResult?: InspectManagedKeepaliveResult;
  InspectManagedMembersParams?: InspectManagedMembersParams;
  InspectManagedMembersResult?: InspectManagedMembersResult;
  InspectManagedReadParams?: InspectManagedReadParams;
  InspectManagedReadResult?: InspectManagedReadResult;
  InspectManagedReleaseParams?: InspectManagedReleaseParams;
  InspectManagedReleaseResult?: InspectManagedReleaseResult;
  InspectManagedResolveParams?: InspectManagedResolveParams;
  InspectManagedResolveResult?: InspectManagedResolveResult;
  InspectManagedResourceParams?: InspectManagedResourceParams;
  InspectManagedResourceResult?: InspectManagedResourceResult;
  InspectManagedRootsParams?: InspectManagedRootsParams;
  InspectManagedRootsResult?: InspectManagedRootsResult;
  InspectManagedSpyInvokeParams?: InspectManagedSpyInvokeParams;
  InspectManagedSpyInvokeResult?: InspectManagedSpyInvokeResult;
  InspectManagedSpyMethodsParams?: InspectManagedSpyMethodsParams;
  InspectManagedSpyMethodsResult?: InspectManagedSpyMethodsResult;
  InspectManagedSpyPrepareInvokeParams?: InspectManagedSpyPrepareInvokeParams;
  InspectManagedSpyPrepareInvokeResult?: InspectManagedSpyPrepareInvokeResult;
  InspectManagedSpySelectParams?: InspectManagedSpySelectParams;
  InspectManagedSpySelectResult?: InspectManagedSpySelectResult;
  InspectManagedStatusParams?: InspectManagedStatusParams;
  InspectManagedStatusResult?: InspectManagedStatusResult;
  InspectManagedStylingParams?: InspectManagedStylingParams;
  InspectManagedStylingResult?: InspectManagedStylingResult;
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
  Item?: Item;
  ItemMatch?: ItemMatch;
  ItemSearch?: ItemSearch;
  ItemSelectorData?: ItemSelectorData;
  ItemsParams?: ItemsParams;
  ItemsResult?: ItemsResult;
  Key?: Key;
  Locator?: Locator;
  LocatorData?: LocatorData;
  LogEntry?: LogEntry;
  LogNotification?: LogNotification;
  ManagedBindingInfo?: ManagedBindingInfo;
  ManagedDiagnostic?: ManagedDiagnostic;
  ManagedErrorInfo?: ManagedErrorInfo;
  ManagedEventPage?: ManagedEventPage;
  ManagedInspectorNodePage?: ManagedInspectorNodePage;
  ManagedMapping?: ManagedMapping;
  ManagedMemberPage?: ManagedMemberPage;
  ManagedMethodPage?: ManagedMethodPage;
  ManagedNode?: ManagedNode;
  ManagedNodePage?: ManagedNodePage;
  ManagedPath?: ManagedPath;
  ManagedPathValue?: ManagedPathValue;
  ManagedProcessIdentity?: ManagedProcessIdentity;
  ManagedRect?: ManagedRect;
  ManagedSession?: ManagedSession;
  Mapping?: Mapping;
  MatchWarning?: MatchWarning;
  Matcher?: Matcher;
  Member?: Member;
  MemberEvent?: MemberEvent;
  MemberEventPage?: MemberEventPage;
  MemberPage?: MemberPage;
  MembersParams?: MembersParams;
  MethodMetadata?: MethodMetadata;
  MethodPage?: MethodPage;
  MethodParameter?: MethodParameter;
  Mismatch?: Mismatch;
  NativeWindowInfo?: NativeWindowInfo;
  NativeWindowStyle?: NativeWindowStyle;
  NodeCoverage?: NodeCoverage;
  NodeInfo?: NodeInfo;
  ObjectRef?: ObjectRef;
  PageCheckParams?: PageCheckParams;
  PageCheckResult?: PageCheckResult;
  PageEntry?: PageEntry;
  ParentParams?: ParentParams;
  ParentResult?: ParentResult;
  PartGeometry?: PartGeometry;
  Path?: Path;
  PathSegment?: PathSegment;
  PathValue?: PathValue;
  Position?: Position;
  Predicate?: Predicate;
  PreviewImage?: PreviewImage;
  ProcessIdentity?: ProcessIdentity;
  PropertyAllowEntry?: PropertyAllowEntry;
  QueryFindAllParams?: QueryFindAllParams;
  QueryFindAllResult?: QueryFindAllResult;
  QueryFindParams?: QueryFindParams;
  QueryFindResult?: QueryFindResult;
  Range?: Range;
  ReadBatchParams?: ReadBatchParams;
  ReadBatchResult?: ReadBatchResult;
  ReadParams?: ReadParams;
  ReadResult?: ReadResult;
  Rect?: Rect;
  RegexFlags?: RegexFlags;
  RelativeSource?: RelativeSource;
  ReleaseParams?: ReleaseParams;
  ReleaseResult?: ReleaseResult;
  Relocation?: Relocation;
  Replay?: Replay;
  RequestEnvelope?: RequestEnvelope;
  ResolveParams?: ResolveParams;
  ResourceParams?: ResourceParams;
  ResourceResult?: ResourceResult;
  ResponseEnvelope?: ResponseEnvelope;
  Results?: Results;
  RootsParams?: RootsParams;
  RoutedEventHandler?: RoutedEventHandler;
  RoutedMemberEvent?: RoutedMemberEvent;
  RunEvent?: RunEvent;
  RunningProcess?: RunningProcess;
  RuntimeId?: RuntimeId;
  Scalar?: Scalar;
  ScalarString?: ScalarString;
  Scope?: Scope;
  ScrollAmount?: ScrollAmount;
  Session?: Session;
  ShutdownParams?: ShutdownParams;
  ShutdownResult?: ShutdownResult;
  SpyCancelledNotification?: SpyCancelledNotification;
  SpyHostCapability?: SpyHostCapability;
  SpyHoverNotification?: SpyHoverNotification;
  SpyInvokeArgument?: SpyInvokeArgument;
  SpyInvokeParams?: SpyInvokeParams;
  SpyInvokeResult?: SpyInvokeResult;
  SpyPickedNotification?: SpyPickedNotification;
  SpyRepickParams?: SpyRepickParams;
  SpyRepickResult?: SpyRepickResult;
  SpyStartParams?: SpyStartParams;
  SpyStartResult?: SpyStartResult;
  SpyStopParams?: SpyStopParams;
  SpyStopResult?: SpyStopResult;
  StateGetParams?: StateGetParams;
  StateGetResult?: StateGetResult;
  StepEvent?: StepEvent;
  StylingCondition?: StylingCondition;
  StylingLevel?: StylingLevel;
  StylingMergedDictionary?: StylingMergedDictionary;
  StylingParams?: StylingParams;
  StylingPart?: StylingPart;
  StylingResourceEntry?: StylingResourceEntry;
  StylingResources?: StylingResources;
  StylingResult?: StylingResult;
  StylingSetter?: StylingSetter;
  StylingStyle?: StylingStyle;
  StylingTemplate?: StylingTemplate;
  StylingTemplates?: StylingTemplates;
  StylingTrigger?: StylingTrigger;
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
  WaitCondition?: WaitCondition;
  WaitResult?: WaitResult;
  WaitUntilParams?: WaitUntilParams;
  WaitUntilResult?: WaitUntilResult;
  WindowLocatorData?: WindowLocatorData;
  WriteAllowlist?: WriteAllowlist;
  WriteAudit?: WriteAudit;
  WriteCallParams?: WriteCallParams;
  WriteCallResult?: WriteCallResult;
  WriteSetPropertyParams?: WriteSetPropertyParams;
  WriteSetPropertyResult?: WriteSetPropertyResult;
}
export interface ActBringIntoViewParams {
  handle: ObjectRef;
  timeoutMs: number;
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
export interface ActBringIntoViewResult {
  outcome: "performed" | "noChange";
  handle: ObjectRef;
}
export interface ActCollapseParams {
  handle: ObjectRef;
  timeoutMs: number;
}
export interface ActCollapseResult {
  outcome: "performed" | "noChange";
  handle: ObjectRef;
}
export interface ActExpandParams {
  handle: ObjectRef;
  timeoutMs: number;
}
export interface ActExpandResult {
  outcome: "performed" | "noChange";
  handle: ObjectRef;
}
export interface ActFocusParams {
  handle: ObjectRef;
  timeoutMs: number;
}
export interface ActFocusResult {
  outcome: "performed" | "noChange";
  handle: ObjectRef;
}
export interface ActInvokeParams {
  handle: ObjectRef;
  timeoutMs: number;
}
export interface ActInvokeResult {
  outcome: "performed" | "noChange";
  handle: ObjectRef;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ActRealizeItemParams".
 */
export interface ActRealizeItemParams {
  search: ItemSearch;
  timeoutMs: number;
}
/**
 * Enumerate item data in Items order without realizing candidates; select first match.
 *
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ItemSearch".
 */
export interface ItemSearch {
  container: ObjectRef;
  match: ItemMatch;
  maxItems: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ActRealizeItemResult".
 */
export interface ActRealizeItemResult {
  outcome: "performed" | "noChange";
  handle: ObjectRef;
  warning?: MatchWarning;
}
/**
 * Count observed within budget, potentially a lower bound.
 *
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "MatchWarning".
 */
export interface MatchWarning {
  code: "multipleMatches";
  count: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ActResult".
 */
export interface ActResult {
  outcome: "performed" | "noChange";
  handle: ObjectRef;
}
export interface ActScrollIntoViewParams {
  handle: ObjectRef;
  timeoutMs: number;
}
export interface ActScrollIntoViewResult {
  outcome: "performed" | "noChange";
  handle: ObjectRef;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ActScrollParams".
 */
export interface ActScrollParams {
  handle: ObjectRef;
  horizontal: ScrollAmount;
  vertical: ScrollAmount;
  timeoutMs: number;
}
export interface ActScrollResult {
  outcome: "performed" | "noChange";
  handle: ObjectRef;
}
export interface ActSelectParams {
  handle: ObjectRef;
  timeoutMs: number;
}
export interface ActSelectResult {
  outcome: "performed" | "noChange";
  handle: ObjectRef;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ActSetRangeParams".
 */
export interface ActSetRangeParams {
  handle: ObjectRef;
  value: number;
  timeoutMs: number;
}
export interface ActSetRangeResult {
  outcome: "performed" | "noChange";
  handle: ObjectRef;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ActSetValueParams".
 */
export interface ActSetValueParams {
  handle: ObjectRef;
  value: ScalarString;
  timeoutMs: number;
}
export interface ActSetValueResult {
  outcome: "performed" | "noChange";
  handle: ObjectRef;
}
export interface ActToggleParams {
  handle: ObjectRef;
  timeoutMs: number;
}
export interface ActToggleResult {
  outcome: "performed" | "noChange";
  handle: ObjectRef;
}
/**
 * Exact runtime type and public instance member; method keys specify exact CLR parameter types with no whitespace.
 *
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "AllowEntry".
 */
export interface AllowEntry {
  typeFullName: Key;
  memberKey: Key;
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
  stringFormat?: string;
  fallbackValue?: Value;
  targetNullValue?: Value;
  converterParameter?: Value;
  converterCulture?: string;
  delay?: number;
  bindingGroupName?: string;
  xPath?: string;
  isAsync?: boolean;
  notifyOnSourceUpdated?: boolean;
  notifyOnTargetUpdated?: boolean;
  notifyOnValidationError?: boolean;
  validatesOnDataErrors?: boolean;
  validatesOnExceptions?: boolean;
  validatesOnNotifyDataErrors?: boolean;
  /**
   * @maxItems 32
   */
  validationRules?: Key[];
  hasUpdateSourceExceptionFilter?: boolean;
  activeChildIndex?: number;
  dataItem?: Value;
  resolvedSource?: Value;
  resolvedSourcePropertyName?: string;
  hasError?: boolean;
  hasValidationError?: boolean;
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
    | "unsupported"
    | "unavailable";
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
  errorMessage?: string;
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
  protocolMajor: 2;
  protocolMinor: number;
  sessionId: string;
  process: ProcessIdentity;
  pipeName: Key;
  token: string;
  spyInvokeCapability?: string;
  clientSid: Identifier;
  expiresUtc: string;
  requestTimeoutMs: number;
  idleTimeoutMs: number;
  agentVersion: Identifier;
  /**
   * @maxItems 32
   */
  redactNames: string[];
  writeAllowlist: WriteAllowlist;
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
 * via the `definition` "WriteAllowlist".
 */
export interface WriteAllowlist {
  /**
   * @maxItems 128
   */
  properties: PropertyAllowEntry[];
  /**
   * @maxItems 128
   */
  methods: AllowEntry[];
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "PropertyAllowEntry".
 */
export interface PropertyAllowEntry {
  typeFullName: Key;
  memberName: Key;
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
 * via the `definition` "CancelRequestNotification".
 */
export interface CancelRequestNotification {
  id: number | string;
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
  processName?: string;
  processId: number;
  rect: Rect | null;
  isEnabled: boolean;
  isOffscreen: boolean;
  hasKeyboardFocus: boolean;
  runtimeId: string;
  /**
   * The HWND behind the element; omitted when it has none.
   */
  nativeWindowHandle?: number;
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
 * via the `definition` "PathValue".
 */
export interface PathValue {
  path: Path;
  value: Value;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "CheckResult".
 */
export interface CheckResult {
  status: "found" | "not_found" | "ambiguous" | "error" | "not_responding";
  element?: ElementInfo;
  diagnostic?: Diagnostic;
  message?: string;
  code?: string;
  hint?: string;
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
 * via the `definition` "ClrEventSubscriber".
 */
export interface ClrEventSubscriber {
  declaringType: string;
  method: string;
}
export interface ClrMemberEvent1 {
  kind: "clr";
  name: string;
  declaringType: string;
  handlerType: string;
  isStatic: boolean;
  subscribersKnown: boolean;
  subscriberCount: number;
  subscribersTruncated: boolean;
  /**
   * @maxItems 32
   */
  subscribers: ClrEventSubscriber[];
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
  /**
   * @minItems 2
   */
  anyOf?: [LocatorData, LocatorData, ...LocatorData[]];
  has?: LocatorData;
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
  status: "found" | "not_found" | "ambiguous" | "error" | "not_responding";
  element?: ElementInfo;
  diagnostic?: Diagnostic;
  message?: string;
  code?: string;
  hint?: string;
  outlinedAncestor?: string;
  outlinedTarget?: string;
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
  status: "found" | "not_found" | "ambiguous" | "error" | "not_responding";
  element?: ElementInfo;
  diagnostic?: Diagnostic;
  message?: string;
  code?: string;
  hint?: string;
  outlinedAncestor?: string;
  outlinedTarget?: string;
  durationMs: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ElementResult".
 */
export interface ElementResult {
  status: "found" | "not_found" | "ambiguous" | "error" | "not_responding";
  element?: ElementInfo;
  diagnostic?: Diagnostic;
  message?: string;
  code?: string;
  hint?: string;
  outlinedAncestor?: string;
  outlinedTarget?: string;
  durationMs: number;
}
/**
 * Snapshot of physical geometry and all named applied-template parts; null geometry is unusable. Values must be finite; visibility includes clipping and viewport.
 *
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ElementState".
 */
export interface ElementState {
  handle: ObjectRef;
  windowHandle: number | null;
  bounds: ManagedRect | null;
  clickPoint: {
    x: number;
    y: number;
  } | null;
  dpi: {
    x: number;
    y: number;
  };
  visible: boolean;
  clipped: boolean;
  offscreen: boolean;
  enabled: boolean;
  focused: boolean;
  isKeyboardFocusable: boolean;
  parts: PartGeometry[];
  /**
   * @minItems 1
   * @maxItems 1024
   */
  uiaRuntimeId?: [number, ...number[]];
  visibleBounds: ManagedRect | null;
}
/**
 * Physical screen pixels; all numbers finite.
 *
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ManagedRect".
 */
export interface ManagedRect {
  x: number;
  y: number;
  width: number;
  height: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "PartGeometry".
 */
export interface PartGeometry {
  name: Identifier;
  role:
    | "expanderToggle"
    | "comboDropDown"
    | "scrollThumb"
    | "scrollDecrement"
    | "scrollIncrement"
    | "scrollTrack"
    | "treeItemExpander"
    | "gridColumnHeader"
    | "gridRowHeader"
    | "templatePart";
  bounds: ManagedRect | null;
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
export interface EventsEventParams1 {
  subscriptionId: Identifier;
  sequence: number;
  kind: "windowOpened" | "windowClosed" | "treeChanged" | "overflow";
  handle?: ObjectRef;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "EventsNotification".
 */
export interface EventsNotification {
  method: "events.event";
  params: EventsEventParams;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "EventsSubscribeParams".
 */
export interface EventsSubscribeParams {
  /**
   * @minItems 1
   * @maxItems 3
   */
  kinds:
    [EventKind] | [EventKind, EventKind] | [EventKind, EventKind, EventKind];
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "EventsSubscribeResult".
 */
export interface EventsSubscribeResult {
  subscriptionId: Identifier;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "EventsUnsubscribeParams".
 */
export interface EventsUnsubscribeParams {
  subscriptionId: Identifier;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "EventsUnsubscribeResult".
 */
export interface EventsUnsubscribeResult {
  unsubscribed: boolean;
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
  protocolMajor: 2;
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
 * Point is in physical screen pixels; HWND must be a live WPF HwndSource of the target process.
 *
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "HitTestParams".
 */
export interface HitTestParams {
  includePath?: boolean;
  nativeWindowHandle: number;
  point: {
    x: number;
    y: number;
  };
  timeoutMs: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "HitTestResult".
 */
export interface HitTestResult {
  innerElement?: {
    type: string;
    text?: string;
  };
  handle: ObjectRef;
  /**
   * @maxItems 256
   */
  path?: ManagedNode[];
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
  identity?: {
    siblingIndex?: number;
    xName?: string;
    automationId?: string;
  };
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
  /**
   * Opt into the requested tree; omit for the legacy UIA array.
   */
  tree?: "visual" | "logical";
  /**
   * Maximum children per page; defaults to 200.
   */
  pageSize?: number;
  /**
   * Continuation token from the preceding page.
   */
  pageToken?: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "NodeInfo".
 */
export interface NodeInfo {
  nodeId: string;
  info: ElementInfo;
  hasChildren: boolean;
  source?: "wpf" | "winforms" | "uia";
  identity?: {
    type: string;
    xName?: string;
    automationId?: string;
    siblingIndex?: number;
  };
}
export interface ManagedProcessIdentity {
  pid: number;
  creationTimeUtc: string;
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
 * via the `definition` "InspectHighlightResult".
 */
export interface InspectHighlightResult {
  outlinedAncestor?: string;
  outlinedTarget?: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectManagedAttachParams".
 */
export interface InspectManagedAttachParams {
  process: ManagedProcessIdentity;
  hostCapability?: SpyHostCapability;
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
  protocolMajor: 2;
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
export interface InspectManagedEventsParams {
  sessionId: string;
  objectId: string;
  generation: number;
  pageSize?: number;
  pageToken?: string;
}
export interface RoutedMemberEvent1 {
  kind: "routed";
  name: string;
  declaringType: string;
  handlerType: string;
  strategy: "bubble" | "tunnel" | "direct";
  handlersKnown: boolean;
  handlerCount: number;
  handlersTruncated: boolean;
  /**
   * @maxItems 32
   */
  handlers: RoutedEventHandler[];
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "RoutedEventHandler".
 */
export interface RoutedEventHandler {
  declaringType: string;
  method: string;
  handledEventsToo: boolean;
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
  winformsLoaded: boolean;
  appUnderTest: boolean;
}
export interface InspectManagedItemsParams {
  sessionId: string;
  objectId: string;
  generation: number;
  pageSize?: number;
  pageToken?: string;
}
export interface InspectManagedItemsResult {
  kind: "array" | "list" | "dictionary" | "enumerable" | "notEnumerable";
  count: number | null;
  /**
   * @maxItems 200
   */
  items: Item[];
  nextPageToken: Identifier | null;
  complete: boolean;
  error?: {
    type: string;
    message: string | null;
  };
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "Item".
 */
export interface Item {
  index: number | null;
  key: Value | null;
  value: Value;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectManagedKeepaliveParams".
 */
export interface InspectManagedKeepaliveParams {
  sessionId: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectManagedKeepaliveResult".
 */
export interface InspectManagedKeepaliveResult {
  alive: true;
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
    | "staticProperty"
    | "staticField"
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
    "nonPublic" | "writeOnly" | "indexer" | "unsupportedType" | "ambiguous";
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
 * via the `definition` "InspectManagedResourceParams".
 */
export interface InspectManagedResourceParams {
  sessionId: string;
  objectId: string;
  generation: number;
  scope: "local" | "application";
  key: string;
  keyKind: "string" | "type" | "componentResourceKey" | "other";
  index?: number;
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
 * via the `definition` "InspectManagedSpyInvokeParams".
 */
export interface InspectManagedSpyInvokeParams {
  hostCapability: SpyHostCapability;
  ticket: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectManagedSpyInvokeResult".
 */
export interface InspectManagedSpyInvokeResult {
  audit: WriteAudit;
  result: Value;
}
/**
 * Never include values; redacted identifiers use the applicable rule. Deadline failures are audited immediately with reason timeout.
 *
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "WriteAudit".
 */
export interface WriteAudit {
  operation: "setProperty" | "call";
  typeFullName: Key;
  memberKey: Key;
  outcome: "performed" | "denied" | "failed";
  timestampUtc: string;
  authorization?: "allowlist" | "pure";
  reason?: string;
}
export interface InspectManagedSpyMethodsParams {
  sessionId: string;
  objectId: string;
  generation: number;
  pageSize?: number;
  pageToken?: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "MethodMetadata".
 */
export interface MethodMetadata {
  key: string;
  name: Key;
  declaringType: TypeName;
  returnType: TypeName;
  visibility:
    | "public"
    | "private"
    | "protected"
    | "internal"
    | "protectedInternal"
    | "privateProtected";
  isStatic: boolean;
  /**
   * @maxItems 128
   */
  parameters: MethodParameter[];
  unsupportedReason?: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "MethodParameter".
 */
export interface MethodParameter {
  name: string;
  type: TypeName;
  isOut: boolean;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectManagedSpyPrepareInvokeParams".
 */
export interface InspectManagedSpyPrepareInvokeParams {
  hostCapability: SpyHostCapability;
  sessionId: string;
  objectId: string;
  generation: number;
  memberKey: string;
  /**
   * @maxItems 16
   */
  arguments:
    | []
    | [SpyInvokeArgument]
    | [SpyInvokeArgument, SpyInvokeArgument]
    | [SpyInvokeArgument, SpyInvokeArgument, SpyInvokeArgument]
    | [
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument
      ]
    | [
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument
      ]
    | [
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument
      ]
    | [
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument
      ]
    | [
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument
      ]
    | [
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument
      ]
    | [
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument
      ]
    | [
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument
      ]
    | [
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument
      ]
    | [
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument
      ]
    | [
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument
      ]
    | [
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument
      ]
    | [
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument,
        SpyInvokeArgument
      ];
}
export interface SpyInvokeArgument2 {
  type: string;
  value?: string | boolean | number;
  enum?: string | number;
  null?: true;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectManagedSpyPrepareInvokeResult".
 */
export interface InspectManagedSpyPrepareInvokeResult {
  ticket: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectManagedSpySelectParams".
 */
export interface InspectManagedSpySelectParams {
  hostCapability: SpyHostCapability;
  sessionId?: string;
  nodeId?: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectManagedSpySelectResult".
 */
export interface InspectManagedSpySelectResult {
  canInvoke: boolean;
  mapping?: InspectManagedResolveResult;
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
  protocolMajor: 2;
  protocolMinor: number;
  features: Features;
  runtimeVersion?: Identifier;
  architecture?: Identifier;
  agentVersion?: Identifier;
  error?: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectManagedStylingParams".
 */
export interface InspectManagedStylingParams {
  sessionId: string;
  objectId: string;
  generation: number;
}
export interface InspectManagedStylingResult {
  applicable: boolean;
  style?: StylingStyle;
  templates?: StylingTemplates;
  resources?: StylingResources;
  application?: StylingResources;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "StylingStyle".
 */
export interface StylingStyle {
  source: "local" | "implicit" | "typeLookup" | "none";
  key?: string;
  targetType?: string;
  setterCount: number;
  settersTruncated: boolean;
  /**
   * @maxItems 32
   */
  setters: StylingSetter[];
  triggerCount: number;
  triggersTruncated: boolean;
  /**
   * @maxItems 32
   */
  triggers: StylingTrigger[];
  /**
   * @maxItems 8
   */
  basedOn:
    | []
    | [StylingLevel]
    | [StylingLevel, StylingLevel]
    | [StylingLevel, StylingLevel, StylingLevel]
    | [StylingLevel, StylingLevel, StylingLevel, StylingLevel]
    | [StylingLevel, StylingLevel, StylingLevel, StylingLevel, StylingLevel]
    | [
        StylingLevel,
        StylingLevel,
        StylingLevel,
        StylingLevel,
        StylingLevel,
        StylingLevel
      ]
    | [
        StylingLevel,
        StylingLevel,
        StylingLevel,
        StylingLevel,
        StylingLevel,
        StylingLevel,
        StylingLevel
      ]
    | [
        StylingLevel,
        StylingLevel,
        StylingLevel,
        StylingLevel,
        StylingLevel,
        StylingLevel,
        StylingLevel,
        StylingLevel
      ];
  basedOnTruncated: boolean;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "StylingSetter".
 */
export interface StylingSetter {
  property: string;
  owner: string;
  targetName?: string;
  kind:
    | "value"
    | "dynamicResource"
    | "binding"
    | "multiBinding"
    | "priorityBinding"
    | "templateBinding"
    | "other";
  expression?: string;
  value?: Value;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "StylingTrigger".
 */
export interface StylingTrigger {
  kind:
    | "trigger"
    | "dataTrigger"
    | "multiTrigger"
    | "multiDataTrigger"
    | "eventTrigger"
    | "other";
  active: "active" | "inactive" | "unknown";
  routedEvent?: string;
  /**
   * @maxItems 32
   */
  conditions: StylingCondition[];
  setterCount: number;
  settersTruncated: boolean;
  /**
   * @maxItems 32
   */
  setters: StylingSetter[];
  enterActions: number;
  exitActions: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "StylingCondition".
 */
export interface StylingCondition {
  property?: string;
  binding?: string;
  sourceName?: string;
  value: Value;
  active: "active" | "inactive" | "unknown";
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "StylingLevel".
 */
export interface StylingLevel {
  key?: string;
  targetType?: string;
  setterCount: number;
  settersTruncated: boolean;
  /**
   * @maxItems 32
   */
  setters: StylingSetter[];
  triggerCount: number;
  triggersTruncated: boolean;
  /**
   * @maxItems 32
   */
  triggers: StylingTrigger[];
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "StylingTemplates".
 */
export interface StylingTemplates {
  controlTemplate?: StylingTemplate;
  contentTemplate?: StylingTemplate;
  itemTemplate?: StylingTemplate;
  itemContainerStyle?: StylingStyle;
  itemsPanel?: StylingTemplate;
  templatedParent?: Value;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "StylingTemplate".
 */
export interface StylingTemplate {
  kind:
    | "controlTemplate"
    | "dataTemplate"
    | "hierarchicalDataTemplate"
    | "itemsPanelTemplate"
    | "other";
  key?: string;
  targetType?: string;
  dataType?: string;
  rootType?: string;
  triggerCount: number;
  triggersTruncated: boolean;
  /**
   * @maxItems 32
   */
  triggers: StylingTrigger[];
  partsTruncated: boolean;
  /**
   * @maxItems 32
   */
  parts: StylingPart[];
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "StylingPart".
 */
export interface StylingPart {
  name: string;
  type: string;
  element: Value;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "StylingResources".
 */
export interface StylingResources {
  source?: string;
  count: number;
  truncated: boolean;
  /**
   * @maxItems 200
   */
  entries: StylingResourceEntry[];
  mergedTruncated: boolean;
  /**
   * @maxItems 200
   */
  mergedDictionaries: StylingMergedDictionary[];
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "StylingResourceEntry".
 */
export interface StylingResourceEntry {
  key: string;
  keyKind: "string" | "type" | "componentResourceKey" | "other";
  index: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "StylingMergedDictionary".
 */
export interface StylingMergedDictionary {
  source?: string;
  count: number;
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
  source?: "wpf" | "winforms";
  window?: NativeWindowInfo;
  uiaMapped?: boolean;
  uia?: {
    properties: {
      [k: string]: string;
    };
    inspection: InspectionProperty[];
  };
  inspection?: InspectionProperty[];
  info: ElementInfo;
  properties: {
    [k: string]: string;
  };
  ancestors: NodeInfo[];
}
/**
 * Win32 facts about the HWND behind a UI Automation node. Optional fields are omitted when the system would not answer.
 *
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "NativeWindowInfo".
 */
export interface NativeWindowInfo {
  handle: number;
  className: string;
  /**
   * Window text, cut to 2000 characters; omitted for password boxes.
   */
  text?: string;
  styles: NativeWindowStyle[];
  rawStyle: number;
  /**
   * Style bits no name covers.
   */
  unknownStyle?: number;
  exStyles: NativeWindowStyle[];
  rawExStyle: number;
  unknownExStyle?: number;
  /**
   * Dialog control ID; only for child windows.
   */
  controlId?: number;
  processId?: number;
  threadId?: number;
  /**
   * Owner window handle; 0 when unowned.
   */
  owner: number;
  /**
   * Parent window handle; 0 for top-level windows.
   */
  parent: number;
  rect?: Rect;
  clientRect?: Rect;
  visible?: boolean;
  enabled: boolean;
  topmost: boolean;
  dpi?: number;
}
/**
 * One decoded style: its name and the bits it stands for.
 *
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "NativeWindowStyle".
 */
export interface NativeWindowStyle {
  name: string;
  value: number;
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
 * via the `definition` "ItemsParams".
 */
export interface ItemsParams {
  sessionId: Identifier;
  objectId: Identifier;
  generation: number;
  pageSize?: number;
  pageToken?: Identifier;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ItemsResult".
 */
export interface ItemsResult {
  kind: "array" | "list" | "dictionary" | "enumerable" | "notEnumerable";
  count: number | null;
  /**
   * @maxItems 200
   */
  items: Item[];
  nextPageToken: Identifier | null;
  complete: boolean;
  error?: {
    type: string;
    message: string | null;
  };
}
/**
 * Predicates are ANDed; index selects after filtering. Defaults are applied before serialization.
 *
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "Locator".
 */
export interface Locator {
  scope: Scope;
  tree: "visual" | "logical" | "combined";
  /**
   * @maxItems 32
   */
  predicates: Predicate[];
  depth: number;
  index?: number;
  limit: number;
  depthMode: "tree" | "peers";
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "LogEntry".
 */
export interface LogEntry {
  level: "info" | "warning";
  text: string;
  details: {
    [k: string]: unknown;
  };
  timestamp: number;
  parent?: number;
  picture?: string;
  skipped?: boolean;
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
    | "injectionFailed"
    | "injectionStalled"
    | "bootstrapRejected"
    | "agentNotStarted"
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
    | "internalError"
    | "notFound"
    | "actionUnsupported"
    | "regexTimeout"
    | "valueUnreadable"
    | "writeDenied"
    | "writeRateExceeded";
  message: string;
  details?: Record<string, never>;
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
  protocolMajor: 2;
  protocolMinor: number;
  features: Features;
  runtimeVersion?: Identifier;
  architecture?: Identifier;
  agentVersion?: Identifier;
  error?: string;
}
export interface MemberEventPage1 {
  /**
   * @maxItems 200
   */
  items: MemberEvent[];
  complete: boolean;
  snapshotId: Identifier;
  /**
   * @maxItems 200
   */
  diagnostics: ManagedDiagnostic[];
  nextToken?: Identifier;
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
export interface MethodPage1 {
  /**
   * @maxItems 200
   */
  items: MethodMetadata[];
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
 * via the `definition` "ParentParams".
 */
export interface ParentParams {
  sessionId: Identifier;
  objectId: Identifier;
  generation: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ParentResult".
 */
export interface ParentResult {
  handle: ObjectRef | null;
}
export interface QueryFindAllParams {
  locator: Locator;
  timeoutMs: number;
}
/**
 * Count only after full traversal; incomplete results may be capped or budget-limited.
 *
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "QueryFindAllResult".
 */
export interface QueryFindAllResult {
  /**
   * @maxItems 200
   */
  matches: ObjectRef[];
  count?: number;
  complete: boolean;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "QueryFindParams".
 */
export interface QueryFindParams {
  locator: Locator;
  timeoutMs: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "QueryFindResult".
 */
export interface QueryFindResult {
  match: ObjectRef;
  warning?: MatchWarning;
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
    | "spy.fieldRead"
    | "spy.methods"
    | "bindings"
    | "release"
    | "query.find"
    | "query.findAll"
    | "state.get"
    | "act.focus"
    | "act.bringIntoView"
    | "act.invoke"
    | "act.toggle"
    | "act.expand"
    | "act.collapse"
    | "act.select"
    | "act.scrollIntoView"
    | "act.setValue"
    | "act.setRange"
    | "act.scroll"
    | "act.realizeItem"
    | "wait.until"
    | "hitTest"
    | "write.setProperty"
    | "write.call"
    | "spy.invoke"
    | "events.subscribe"
    | "events.unsubscribe"
    | "tree.parent"
    | "members.items";
  params: Record<string, never>;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ResolveParams".
 */
export interface ResolveParams {
  runtimeId: RuntimeId;
  nativeWindowHandle?: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ResourceParams".
 */
export interface ResourceParams {
  sessionId: Identifier;
  objectId: Identifier;
  generation: number;
  scope: "local" | "application";
  key: string;
  keyKind: "string" | "type" | "componentResourceKey" | "other";
  index?: number;
}
export interface ResourceResult1 {
  found: boolean;
  valueType?: string;
  value?: Value;
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
  log: LogEntry[];
  capturedLog: string;
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
  backend?: "uia" | "wpf";
  audits?: {
    operation: "setProperty" | "call";
    typeFullName: string;
    memberKey: string;
    outcome: "performed" | "denied" | "failed";
    timestampUtc: string;
    reason?: string;
    authorization?: "allowlist" | "pure";
  }[];
  error?: ErrorInfo;
  screenshot?: string;
  parent?: number;
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
  protocolMajor: 2;
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
  attachRequired?: true;
  process?: ManagedProcessIdentity;
  blocked?: {
    code: string;
    hint: string;
  };
  source?: "uia";
  node: NodeInfo;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "SpyInvokeParams".
 */
export interface SpyInvokeParams {
  capability: string;
  handle: ObjectRef;
  memberKey: string;
  /**
   * @maxItems 16
   */
  arguments: SpyInvokeArgument[];
  timeoutMs: number;
}
export interface SpyInvokeResult {
  audit: WriteAudit;
  result: Value;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "SpyPickedNotification".
 */
export interface SpyPickedNotification {
  innerElement?: {
    type: string;
    text?: string;
  };
  point: {
    x: number;
    y: number;
  };
  sessionId?: string;
  attachRequired?: true;
  process?: ManagedProcessIdentity;
  blocked?: {
    code: string;
    hint: string;
  };
  source?: "uia";
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
 * via the `definition` "SpyRepickParams".
 */
export interface SpyRepickParams {
  x: number;
  y: number;
  tree?: "visual" | "logical";
}
export interface SpyRepickResult {
  innerElement?: {
    type: string;
    text?: string;
  };
  point: {
    x: number;
    y: number;
  };
  sessionId?: string;
  attachRequired?: true;
  process?: ManagedProcessIdentity;
  blocked?: {
    code: string;
    hint: string;
  };
  source?: "uia";
  node: NodeInfo;
  suggestion?: Suggestion;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "SpyStartParams".
 */
export interface SpyStartParams {
  sessionId?: string;
  tree?: "visual" | "logical";
  /**
   * Remember the foreground window belonging to this process or an ancestor and reactivate it after an element is picked.
   */
  foregroundForProcessId?: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "StateGetParams".
 */
export interface StateGetParams {
  handle: ObjectRef;
  timeoutMs: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "StateGetResult".
 */
export interface StateGetResult {
  state: ElementState;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "StylingParams".
 */
export interface StylingParams {
  sessionId: Identifier;
  objectId: Identifier;
  generation: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "StylingResult".
 */
export interface StylingResult {
  applicable: boolean;
  style?: StylingStyle;
  templates?: StylingTemplates;
  resources?: StylingResources;
  application?: StylingResources;
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
export interface WaitResult1 {
  satisfied: boolean;
  handle?: ObjectRef;
  state?: ElementState;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "WaitUntilParams".
 */
export interface WaitUntilParams {
  condition: WaitCondition;
  timeoutMs: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "WriteCallParams".
 */
export interface WriteCallParams {
  handle: ObjectRef;
  memberKey: Key;
  /**
   * @maxItems 16
   */
  arguments:
    | []
    | [CallArgument]
    | [CallArgument, CallArgument]
    | [CallArgument, CallArgument, CallArgument]
    | [CallArgument, CallArgument, CallArgument, CallArgument]
    | [CallArgument, CallArgument, CallArgument, CallArgument, CallArgument]
    | [
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument
      ]
    | [
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument
      ]
    | [
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument
      ]
    | [
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument
      ]
    | [
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument
      ]
    | [
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument
      ]
    | [
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument
      ]
    | [
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument
      ]
    | [
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument
      ]
    | [
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument
      ]
    | [
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument,
        CallArgument
      ];
  timeoutMs: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "WriteCallResult".
 */
export interface WriteCallResult {
  audit: WriteAudit;
  result: Value;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "WriteSetPropertyParams".
 */
export interface WriteSetPropertyParams {
  handle: ObjectRef;
  memberKey: Key;
  value: Scalar;
  timeoutMs: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "WriteSetPropertyResult".
 */
export interface WriteSetPropertyResult {
  audit: WriteAudit;
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
  stringFormat?: string;
  fallbackValue?: Value;
  targetNullValue?: Value;
  converterParameter?: Value;
  converterCulture?: string;
  delay?: number;
  bindingGroupName?: string;
  xPath?: string;
  isAsync?: boolean;
  notifyOnSourceUpdated?: boolean;
  notifyOnTargetUpdated?: boolean;
  notifyOnValidationError?: boolean;
  validatesOnDataErrors?: boolean;
  validatesOnExceptions?: boolean;
  validatesOnNotifyDataErrors?: boolean;
  /**
   * @maxItems 32
   */
  validationRules?: Key[];
  hasUpdateSourceExceptionFilter?: boolean;
  activeChildIndex?: number;
  dataItem?: Value;
  resolvedSource?: Value;
  resolvedSourcePropertyName?: string;
  hasError?: boolean;
  hasValidationError?: boolean;
}
export interface ManagedEventPage1 {
  /**
   * @maxItems 200
   */
  items: MemberEvent[];
  complete: boolean;
  snapshotId: Identifier;
  /**
   * @maxItems 200
   */
  diagnostics: ManagedDiagnostic[];
  nextToken?: Identifier;
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
export interface ManagedMethodPage1 {
  /**
   * @maxItems 200
   */
  items: MethodMetadata[];
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
  protocolMajor: 2;
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
  status: "found" | "not_found" | "ambiguous" | "error" | "not_responding";
  element?: ElementInfo;
  diagnostic?: Diagnostic;
  message?: string;
  code?: string;
  hint?: string;
  outlinedAncestor?: string;
  outlinedTarget?: string;
  durationMs: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ElementHighlightResult".
 */
export interface ElementResult2 {
  status: "found" | "not_found" | "ambiguous" | "error" | "not_responding";
  element?: ElementInfo;
  diagnostic?: Diagnostic;
  message?: string;
  code?: string;
  hint?: string;
  outlinedAncestor?: string;
  outlinedTarget?: string;
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
  protocolMajor: 2;
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
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectManagedEventsParams".
 */
export interface InspectManagedMembersParams1 {
  sessionId: string;
  objectId: string;
  generation: number;
  pageSize?: number;
  pageToken?: string;
}
export interface InspectManagedEventsResult1 {
  /**
   * @maxItems 200
   */
  items: MemberEvent[];
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
 * via the `definition` "InspectManagedItemsParams".
 */
export interface InspectManagedMembersParams2 {
  sessionId: string;
  objectId: string;
  generation: number;
  pageSize?: number;
  pageToken?: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectManagedItemsResult".
 */
export interface ItemsResult1 {
  kind: "array" | "list" | "dictionary" | "enumerable" | "notEnumerable";
  count: number | null;
  /**
   * @maxItems 200
   */
  items: Item[];
  nextPageToken: Identifier | null;
  complete: boolean;
  error?: {
    type: string;
    message: string | null;
  };
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
export interface InspectManagedResourceResult1 {
  found: boolean;
  valueType?: string;
  value?: Value;
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
 * via the `definition` "InspectManagedSpyMethodsParams".
 */
export interface InspectManagedMembersParams3 {
  sessionId: string;
  objectId: string;
  generation: number;
  pageSize?: number;
  pageToken?: string;
}
export interface InspectManagedSpyMethodsResult1 {
  /**
   * @maxItems 200
   */
  items: MethodMetadata[];
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
  protocolMajor: 2;
  protocolMinor: number;
  features: Features;
  runtimeVersion?: Identifier;
  architecture?: Identifier;
  agentVersion?: Identifier;
  error?: string;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "InspectManagedStylingResult".
 */
export interface StylingResult1 {
  applicable: boolean;
  style?: StylingStyle;
  templates?: StylingTemplates;
  resources?: StylingResources;
  application?: StylingResources;
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
 * via the `definition` "SpyRepickResult".
 */
export interface SpyPickedNotification1 {
  innerElement?: {
    type: string;
    text?: string;
  };
  point: {
    x: number;
    y: number;
  };
  sessionId?: string;
  attachRequired?: true;
  process?: ManagedProcessIdentity;
  blocked?: {
    code: string;
    hint: string;
  };
  source?: "uia";
  node: NodeInfo;
  suggestion?: Suggestion;
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
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ActBringIntoViewParams".
 */
export interface StateGetParams1 {
  handle: ObjectRef;
  timeoutMs: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ActBringIntoViewResult".
 */
export interface ActResult1 {
  outcome: "performed" | "noChange";
  handle: ObjectRef;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ActCollapseParams".
 */
export interface StateGetParams2 {
  handle: ObjectRef;
  timeoutMs: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ActCollapseResult".
 */
export interface ActResult2 {
  outcome: "performed" | "noChange";
  handle: ObjectRef;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ActExpandParams".
 */
export interface StateGetParams3 {
  handle: ObjectRef;
  timeoutMs: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ActExpandResult".
 */
export interface ActResult3 {
  outcome: "performed" | "noChange";
  handle: ObjectRef;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ActFocusParams".
 */
export interface StateGetParams4 {
  handle: ObjectRef;
  timeoutMs: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ActFocusResult".
 */
export interface ActResult4 {
  outcome: "performed" | "noChange";
  handle: ObjectRef;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ActInvokeParams".
 */
export interface StateGetParams5 {
  handle: ObjectRef;
  timeoutMs: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ActInvokeResult".
 */
export interface ActResult5 {
  outcome: "performed" | "noChange";
  handle: ObjectRef;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ActScrollIntoViewParams".
 */
export interface StateGetParams6 {
  handle: ObjectRef;
  timeoutMs: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ActScrollIntoViewResult".
 */
export interface ActResult6 {
  outcome: "performed" | "noChange";
  handle: ObjectRef;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ActScrollResult".
 */
export interface ActResult7 {
  outcome: "performed" | "noChange";
  handle: ObjectRef;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ActSelectParams".
 */
export interface StateGetParams7 {
  handle: ObjectRef;
  timeoutMs: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ActSelectResult".
 */
export interface ActResult8 {
  outcome: "performed" | "noChange";
  handle: ObjectRef;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ActSetRangeResult".
 */
export interface ActResult9 {
  outcome: "performed" | "noChange";
  handle: ObjectRef;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ActSetValueResult".
 */
export interface ActResult10 {
  outcome: "performed" | "noChange";
  handle: ObjectRef;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ActToggleParams".
 */
export interface StateGetParams8 {
  handle: ObjectRef;
  timeoutMs: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "ActToggleResult".
 */
export interface ActResult11 {
  outcome: "performed" | "noChange";
  handle: ObjectRef;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "QueryFindAllParams".
 */
export interface QueryFindParams1 {
  locator: Locator;
  timeoutMs: number;
}
/**
 * This interface was referenced by `ProtocolContracts`'s JSON-Schema
 * via the `definition` "SpyInvokeResult".
 */
export interface WriteCallResult1 {
  audit: WriteAudit;
  result: Value;
}
export interface WaitUntilResult1 {
  satisfied: boolean;
  handle?: ObjectRef;
  state?: ElementState;
}
