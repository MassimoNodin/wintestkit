# WPF/.NET attribute analyzer: implementation specification

Status: implementation in progress; release gates are not yet satisfied. Planning date: 2026-10-27.
Revision: 3 (see section 15). Protocol 2.0 is specified in [wpf-protocol-2.md](wpf-protocol-2.md).
Scope: authorized Windows desktop test infrastructure.

Implementation evidence and remaining integration gates are recorded in
[`wpf-inspector-implementation-brief.md`](wpf-inspector-implementation-brief.md). Implemented
slices and passing component tests do not imply that the full stage or release gate passes.

Terminology: "attributes" in the feature request means the properties a TestComplete-style
object browser shows for a control (`ClrFullClassName`, `DataContext`, nested view-model
members), not only .NET custom attributes. This document calls them *members*; .NET custom
attributes are *attribute metadata* (section 8, step 6). The subsystem is the *inspector*.

## 1. Outcome and binding requirements

Build a WinTestKit-owned managed-object inspector in this repository. It must attach to an
already running, unchanged WPF application: no target NuGet package, source edit, rebuild,
startup hook, startup flag, or configuration change. Runtime instrumentation is permitted:
attachment loads an inspector assembly into the selected process. This is not zero-impact
observation. Keep the inspector a separate subsystem, packaged with WinTestKit.

Do not implement special-case getters for `ClrFullClassName` and `DataContext`. Discover types,
inherited properties, fields, dependency/attached properties, binding metadata, and expandable
object values generally. `DataContext` appears through normal WPF property discovery; nested
view-model members use the same reader as other objects. `ClrFullClassName` is a compatibility
projection of general type metadata, not necessarily a real property declared by the target.

Implement section 12 sequentially. Each stage has a fixed boundary and verification gate.
Implementors must not substitute technology, broaden platforms, invent identity heuristics,
change matching semantics, or bypass failed gates. Report a blocked gate and obtain a design
amendment instead. Normal coding fixes within the contract are permitted. This planning task
does not authorize implementing the analyzer itself.

Required outcomes:

1. UI Automation (UIA) inspection and actions remain unchanged when the inspector is disabled.
2. Explicit attachment to a selected PID reports actual runtime/architecture capabilities.
3. UIA selection maps to the exact managed object or returns an explicit mapping failure.
4. Member discovery is separate from getter evaluation; nested values load lazily.
5. Null, exception, stale, redacted, truncated, and unavailable remain distinguishable.
6. Spy separates UIA, managed type, CLR members, dependency properties, and bindings.
7. CLI, pytest, and Spy share one Python client and structured contracts.
8. Explicit managed scalar paths work in `where`, without becoming native UIA conditions.
9. Versioned artifacts, local protocol, compatibility tests, and operational docs ship together.
10. Suites migrated from TestComplete can match `ClrFullClassName` against the real runtime
    type through an explicit, opt-in alias (section 10), instead of a UIA `ItemStatus` guess.
11. The core `wintestkit` package stays installable and UIA-only everywhere it installs today;
    the inspector is an optional, platform-specific add-on (section 11).

### Meaning of all attributes

**Revision 3 amendment (D2, D6):** The V1 exclusions below are superseded for protocol 2.0: explicit, bounded item-data searches may enumerate items and realize only the single match; allowlisted writes and public instance calls are opt-in and audited. Arbitrary execution remains forbidden. WPF handles can be action targets without UIA association. See [protocol 2.0](wpf-protocol-2.md).

List every member discovered in the specified categories, including unreadable declarations;
do not promise arbitrary private state or an infinite graph. V1 reads public instance CLR
properties/fields and relevant WPF dependency properties. It lists nonpublic property/field
declarations and custom-attribute metadata without reading nonpublic values or instantiating
attributes. Static application values, indexer evaluation, methods/events, arbitrary execution,
mutation, resource materialization, collection enumeration, and control realization are not
supported. Represent excluded values explicitly, not as empty strings.

Discover relevant attached properties through local values and WPF descriptors. Do not read
the private global dependency-property registry or initialize every loaded application type.
Objects absent from UIA may appear in the managed tree but cannot become action targets
without exact UIA association.

## 2. Existing architecture and integration boundaries

Each stage starts from a clean, reviewed base. Never fold unrelated uncommitted work into an
inspector change, and commit or push only when the owner explicitly asks.

| Existing location | Integration contract |
| --- | --- |
| `python/src/wintestkit/uia/element.py` | Preserve UIA access; use PID and dot-joined runtime ID as external identity |
| `python/src/wintestkit/engine/properties.py` | Add a managed condition variant; preserve UIA catalog; aliases may target managed keys only as in section 10 |
| `python/src/wintestkit/name_mapping.py` | Importer may emit `type:FullName` behind an explicit flag; default output unchanged |
| `python/src/wintestkit/engine/query.py` | Partition UIA and managed constraints before native-condition creation |
| `python/src/wintestkit/engine/locator.py` | Preserve qualified paths through serialization |
| `python/src/wintestkit/engine/suggest.py` | Default suggestions stay UIA-only; managed locator copy is explicit |
| `python/src/wintestkit/config.py` | Typed configuration from section 10; extend `_TOP_LEVEL_KEYS`/flattening, not `_ENV_VARS` |
| `python/src/wintestkit/runtime.py` | Own session registry here, respecting its global-state convention |
| `python/src/wintestkit/server.py` | Managed RPC methods in the strict `_PARAMS` table; lifecycle invalidation |
| `python/src/wintestkit/pytest_plugin.py` | Report-header line listing inspector mode and attached process identities |
| `python/src/wintestkit/object_previews.py`, `vscode/src/views/capturePreviewDocument.ts` | Element captures never contain managed values or metadata |
| `python/src/wintestkit/commands/inspect.py` | Managed CLI options using the same client |
| `schemas/common.schema.json` | Preserve UIA `InspectionProperty`; add separate managed DTOs |
| `schemas/rpc.schema.json` | Strict managed method contracts and capability advertisement |
| `vscode/src/protocol/generated.ts` | Regenerate with `npm run gen:types`, never hand-edit |
| `vscode/src/spy/spyView.ts`, `vscode/media/spy/` | Explicit attach and lazy sections |
| `vscode/media/settings/editor.js` | Repository Settings shows the `inspector` keys with existing modified-marking |
| `python/tests/unit/`, `python/tests/contract/` | Fake-client and schema coverage |
| `vscode/test/unit/`, `.github/workflows/ci.yml` | UI tests and separate Windows inspector jobs (section 13) |
| `scripts/check_wheel.ps1`, `scripts/check_release.py` | Core wheel stays `py3-none-any`; release check enforces inspector version lockstep |
| `python/src/wintestkit/scaffold/skills/`, `skills/`, `scripts/sync_skill.py` | Test-writing skill learns managed locator keys (stage 12) |
| `docs/guide/migrating-from-testcomplete.md`, `docs/guide/property-matching.md` | Replace the `ItemStatus` workaround with the managed option where available |

Existing UIA-to-UIA `property_aliases` keep their meaning. Never map a managed name to an
unrelated UIA value. Preserve `inspect.properties` summaries and existing inspection
responses; managed data uses separate responses.

## 3. Fixed architecture and repository layout

```text
Spy / CLI / pytest -> Python client -> same-user local named pipe
  -> managed Agent in selected WPF process -> owning WPF Dispatcher
Python -> matching-bitness launcher -> pinned attach transport -> Agent.EntryPoint.Start
```

Use C# for agent/DTOs and Python for orchestration. No MCP server, TCP listener, remote service,
embedded Python, debugger evaluator, or application-side SDK is introduced.

Future implementation layout:

```text
wpf-inspector/
  README.md
  global.json                         # SDK 10.0.400; rollForward=latestPatch
  WinTestKit.Inspector.sln
  Directory.Build.props
  Directory.Packages.props
  third_party/snoop/                   # source archive, not a Git submodule
  third_party/snoop.lock.json          # repository/commit/archive SHA256/file hashes
  THIRD-PARTY-NOTICES.md
  src/Protocol/                       # netstandard2.0, no WPF dependency, no package references
    StrictJson.cs                     # bounded reader/writer used on both sides of the pipe
  src/Agent/                          # net48;net8.0-windows;net10.0-windows
    EntryPoint.cs
    SessionHost.cs
    DispatcherExecutor.cs
    ObjectRegistry.cs
    PeerRuntimeIdAdapter.cs
    ElementMapper.cs
    MemberCatalog.cs
    ValueReader.cs
    BindingReader.cs
    PipeServer.cs
  src/Launcher/
  tests/Unit/
  tests/Integration/
  tests/Fixtures/                      # targets never reference Agent
  protocol/                           # pipe JSON Schema
  artifacts/                          # ignored build output
python/src/wintestkit/inspector/        # client code, ships in the core wheel
  __init__.py
  client.py
  transport.py
  models.py
  sessions.py
  paths.py
  payload.py                          # locates the optional payload distribution
inspector-payload/                      # separate wintestkit-inspector distribution
  pyproject.toml
  src/wintestkit_inspector/           # generated payload + manifest.json
scripts/build_inspector.ps1
scripts/check_inspector.ps1
```

Shared agent source compiles for all three TFMs. Everything loaded into the target process
(Agent and Protocol) has **zero third-party runtime dependencies**, including
`System.Text.Json`. Reasons: on .NET 8/10 the target has already loaded the shared-framework
`System.Text.Json`, so an agent compiled against a newer package version fails to bind in the
default load context; on .NET Framework 4.8 the package drags in `System.Memory`,
`System.Buffers`, and `Unsafe` versions that conflict with the target's own copies and would
need the binding redirects section 11 forbids; and duplicate-key rejection (section 5) is not
available in older `System.Text.Json`. `StrictJson` is a small hand-written codec over the
closed DTO set: it enforces frame, depth, duplicate-key, unknown-field, and string-length
limits during parsing, and its tests share the stage 0 golden fixtures with the Python side.
Test projects and the launcher may use pinned packages. Stage 1 records exact versions and
lockfiles. No dependencies are downloaded while attaching.

Assemblies cannot be unloaded from the target (section 4), so a later attach in the same
process reuses whatever agent version is already loaded. The agent assembly version equals
the inspector version; `session.hello` reports it, and Python refuses a mismatch with
`agentVersionMismatch` ("restart the application to use the new inspector") instead of
talking to stale code. Assembly names are WinTestKit-specific and strong-named so they cannot
collide with target assemblies.

### Attach transport decision

Reuse only Snoop loading infrastructure, not its inspection UI, scripting, object model, or
mutation features. Pin `snoopwpf/snoopwpf` at
`2bf48f60c2bb1753001f6be9122395def9070fa9`. Reviewed source includes
`Snoop.InjectorLauncher`, `Snoop.GenericInjector`, and `Shared/InjectorData.cs`. Preserve
upstream source/notices within the third-party boundary. WinTestKit licensing does not replace
upstream licensing. The owner approves the third-party inventory before publication; this
plan makes no legal compliance determination.

Build matching-bitness upstream launcher/native libraries via `build_inspector.ps1`, retaining
upstream layout/shared imports. The wrapper supplies absolute `--assembly`,
`--className WinTestKit.Inspector.Agent.EntryPoint`, `--methodName Start`, `--targetPID`, and
`--settingsFile` values. Source review of the pinned commit (stage 3,
`wpf-inspector/third_party/snoop-loader-notes.md`) established: the PID path loads the agent
with `CreateRemoteThread` (no window hook), using the already loaded runtime
(`ExecuteInDefaultAppDomain` on CLR v4 / CoreCLR); `--targetHwnd` is optional and parsed as a
signed 32-bit integer, so the wrapper omits it. Do not expose arbitrary assembly/type/method
selection. Agent entry is `public static int Start(string settingsFile)`: validate settings,
schedule SessionHost, return promptly. `Start` runs on a loader thread, not a UI thread: it must
not assume any Dispatcher, must not block, and must reach each window's Dispatcher through the
executor. The launcher's exit code and `Start`'s return value are not propagated reliably (a
missing export can still exit 0); launcher success is never readiness, and only an
authenticated pipe handshake within the attach deadline counts.

Upstream writes log files that include the settings file path. The path carries no secret
(the token is only inside the file, which the agent deletes after reading), but the docs state
where these logs go and Python never passes secrets on the command line. The upstream launcher
project imports seven `Snoop.Core` source files and an icon; keep `Snoop.Core` itself out of
the vendored inventory and remove those imports with a reviewed build-time patch under
`third_party/patches/`, applied to a copy in `artifacts/` so vendored files stay
byte-identical to the lock file (owner decision, 2026-10-27). Native builds take the CLR
hosting headers `mscoree.h`/`metahost.h` from the installed .NET Framework 4.8 Developer Pack
(`%ProgramFiles(x86)%\Windows Kits\NETFXSDK\4.8\Include\um`); the build script locates that
folder and fails with an actionable message when it is absent (owner installed it,
2026-10-27). CI must install the same Developer Pack.
Upstream runtime-hosting internals require empirical compatibility tests. A failed load blocks
that support cell; do not invent replacement injection code.

Endpoint security products treat cross-process loading as suspicious. Microsoft Defender
ASR rules, third-party EDR, Smart App Control, WDAC, or AppLocker may block the launcher or
native library. Detect blocked process creation/module load where Windows reports it and
return `blockedByPolicy` with the blocked file name, never a generic `attachFailed`. Release
payload executables and DLLs (WinTestKit-built and rebuilt upstream binaries) are Authenticode
signed; unsigned development payloads are labeled as such in `wtk doctor`. Document that
corporate machines may need an allow rule, and never suggest disabling protection.

## 4. Compatibility and lifecycle

| Required release cell | Target architecture | Agent |
| --- | --- | --- |
| .NET Framework 4.8 WPF | x86, x64 | net48 |
| .NET 8 WPF | x86, x64 | net8.0-windows |
| .NET 10 WPF | x86, x64 | net10.0-windows |

Start with .NET 10 x64; stage 11 verifies the other five cells. .NET 10 is the current LTS,
and .NET 8 reaches end of support on 2026-11-10, before this work can ship. .NET 8 stays a
required cell because existing applications keep running on it. If the owner's primary
target application uses a different cell, amend the vertical-slice cell before stage 3 rather
than reordering later. Advertise cells only after their gates pass. Baseline deployment is
framework-dependent WPF. Unsupported V1: ARM64, non-WPF,
NativeAOT, trimmed builds, self-contained/single-file deployment, multiple WPF CLR runtimes or
AppDomains in one process, different-user/session targets, protected processes, and mismatched
integrity levels. Unlisted .NET versions are unsupported, not guessed compatible. Custom
controls, multiple windows, popups, and multiple UI Dispatchers are in scope.

Process identity is `(pid, creationTimeUtc)`. Probe architecture, runtime/WPF modules, user SID,
Windows session, integrity level, and executable identity. Unreadable facts fail explicitly.
Never auto-elevate, enable debug privileges, or alter either process token.

States: `detached -> probing -> attaching -> ready -> detaching -> detached`. Failures become
`faulted`; target exit becomes `exited`. Only explicit attach leaves those terminal states.
Python owns one registry entry per process identity; concurrent callers share an attach
attempt. Revalidate creation time during launch/handshake to reject PID reuse. A process-wide
agent named mutex prevents duplicate listeners; return `alreadyAttached` for a live incumbent.
Never replace another backend session. Closed sessions may restart with new IDs/tokens.
A re-attach after detach reuses the already loaded agent assembly; it must start a fresh
SessionHost with empty registries, and only the matching agent version may do so (section 3).

Detach stops admission, cancels queued work, closes pipes, unsubscribes events, and clears
registries. It cannot guarantee assembly/native-library unload, reversal of getter side
effects, or cancellation of running managed code. Never abort a thread or terminate the target.
Only the integration harness may terminate its own fixture processes.

## 5. Local transport, authorization, scheduling, and limits

**Revision 3 amendment:** WPF query regex executes in the agent with a bounded match timeout; the Python-only rule below applies to the UIA backend. Automatic attachment for WPF processes follows D4, subject to the trusted-workspace and process confirmation safeguards. D5 forbids silent UIA fallback on agent failure.

Attachment is opt-in. Spy must show executable path, PID, runtime, architecture, and an
in-process execution warning before attaching. Require a trusted workspace. A picker or
UIA selection alone never authorizes attachment to another application. pytest/CLI require
the explicit configuration in section 10; do not instrument every process visible on desktop.
A Spy confirmation covers one process identity `(pid, creationTimeUtc)` for the lifetime of
the extension host. Re-attaching the same identity after an idle or explicit detach needs no
second prompt; a restarted application (new creation time) does.

Python generates a cryptographically random 256-bit token and session UUID. Use a local named
pipe named `WinTestKit.Inspector.<pid>.<sessionUuid>`. The agent owns the server; Python is
the client. Apply an explicit pipe ACL allowing the initiating user only, reject remote clients,
verify the connecting SID, and authenticate the first frame with the token. Also verify server
PID/creation time from the client using Windows pipe/process APIs. ACLs and tokens prevent
accidental cross-session access, not a hostile process running as the same user.

Bootstrap settings contain protocol version, identity, pipe name, token, expiry, and limits.
Write them to a per-session user-only ACL directory under the user local application-data
directory; use a random filename, exclusive creation, and a 30-second expiry. Reject reparse
points, oversized files, unknown keys, wrong identity, and paths outside that directory. Delete
the file after the agent reads it and in every launcher failure cleanup. The token must not
appear in command arguments, logs, reports, extension messages, or committed configuration.
Verify installed payload hashes before launch; refuse any payload path outside its manifest
root. No runtime download, DLL search via current directory, arbitrary payload path, or shell
command construction. Launch hidden, using an argument array and fixed executable path.

Pipe framing is a four-byte unsigned little-endian byte length followed by UTF-8 JSON. Maximum
frame size is 1,048,576 bytes. Reject oversized lengths before allocation, invalid UTF-8,
duplicate JSON keys, excessive JSON depth, unknown fields, and unsupported methods. Read exact
byte counts across partial reads; EOF mid-frame fails the session. JSON depth limit is 32.
One authenticated connection per session; monotonically increasing positive integer request
IDs. Never reuse IDs; response IDs must match outstanding requests. No remote CLR type names
may cause dynamic type loading/deserialization. All DTOs are explicit, not polymorphic CLR DTOs.

| Limit | Fixed V1 value and behavior |
| --- | --- |
| Attach readiness | 10 seconds; stop waiting, close attempt, no automatic retry |
| Normal request | 2 seconds wall clock, bounded by outer locator deadline |
| Dispatcher queue wait | 500 ms; cancel operation if not yet running |
| Metadata traversal slice | At most 200 objects or 10 ms; yield between slices |
| Managed tree/mapping scan | 10,000 objects and 2 seconds; report `limitExceeded` |
| Result page | Default 100, maximum 200 members/nodes |
| Explicit read batch | Maximum 32 paths and 32 UIA candidates per request |
| Single scalar string | 4,096 Unicode scalar values; explicit truncation status |
| Strong reference lease | 30 seconds inactivity, maximum 256 object handles |
| Weak object registry | Maximum 10,000 entries, prune dead entries first |
| Graph path | Maximum 8 segments, maximum 1,024 UTF-8 bytes |
| Queued work | Maximum 16 operations; overflow returns `busy` |
| Active work | One operation per Dispatcher and at most 4 per session |
| Response ceiling | 1 MiB; return partial page/token before exceeding it |
| Idle session | Detach after 5 minutes with no requests; Spy shows `detached (idle)`, clears values and handles, and offers re-attach |

Limits are protocol constants, not implementor-selected defaults. Configurable timeouts may
only lower request/attach deadlines; resource ceilings cannot be raised in V1.

Perform pipe I/O and serialization off the UI thread. Discover each object on its owning
Dispatcher; never assume `Application.Current.Dispatcher` owns all windows. No synchronous
Dispatcher.Invoke from pipe threads; enqueue async operations at Background priority. Never
hold a registry/transport lock while executing target code. Never spin a nested message loop.
For ordinary CLR objects reached through a UI object, retain that traversal Dispatcher; a
DispatcherObject must use its own Dispatcher. Cancellation is checked between reads/slices.

An already running getter cannot be hard-timed-out safely. On a client deadline, discard late
results, mark that Dispatcher `unresponsive`, reject further reads on it, and preserve UIA-only
operation on the client. Do not start another worker against the same blocked Dispatcher.
Mark other Dispatchers independently. A hung getter can hang the target UI; present this risk
before the first value read. Never claim that timeouts sandbox application code.

## 6. Exact protocol and DTO contract

**Revision 3 amendment:** The following is the retained protocol 1.0 contract. Protocol 2.0 adds `query.find`, `query.findAll`, `state.get`, `act.<verb>`, `wait.until`, `hitTest`, `write.setProperty`, `write.call`, `events.subscribe`, and `events.unsubscribe`, as defined in [wpf-protocol-2.md](wpf-protocol-2.md). The V1 prohibition of invoke and write below is superseded for peer actions (D1) and opt-in allowlisted, audited writes/calls (D2); arbitrary evaluation and execution remain forbidden.

There are two boundaries: internal pipe protocol version `1.0`, and additive public WinTestKit
RPC methods. Store pipe schemas in `wpf-inspector/protocol/inspector.schema.json`; reference
the same managed definitions from repository RPC schemas rather than hand-maintaining copies.
Extend the schema generation script to resolve this local schema; it must not fetch network
schemas. Public methods remain unavailable until capability `managedInspector: true` is
advertised by initialization. A new client with an old server disables managed controls.

Each post-authentication pipe request is `{id, method, params}`. Each response is exactly
`{id, result}` or `{id, error: {code, message, details}}`. Authentication uses a single
`session.hello` request with `{protocolMajor:1, protocolMinor:0, sessionId, token, process}`;
response includes agentVersion, selected TFM, architecture, runtimeVersion, supported features,
and process identity. Reject a different major; accept a minor only if all required features
are present. Do not send values before authentication.
Feature identifiers are exactly `typeMetadata`, `clrMembers`, `dependencyProperties`,
`bindings`, `exactUiaMapping`, and `batchReads`. A complete V1 agent must advertise all six;
an experimental partially capable agent advertises only verified features and cannot pass
the release gate. Requests needing an absent feature return unsupportedTarget.

### Core DTOs

All objects use `additionalProperties:false`. Strings are bounded in schemas; identifiers
are nonempty, at most 128 characters, except member keys/type names (maximum 1,024).
Optional means absent, not an accidental null. Every enum is closed in V1.

| DTO | Required fields | Optional fields / invariant |
| --- | --- | --- |
| ProcessIdentity | `pid` positive integer, `creationTimeUtc` RFC3339 string | No PID-only lookup |
| Session | `sessionId`, `process`, `state`, `protocolMajor`, `protocolMinor`, `features` string array | `runtimeVersion`, `architecture`, `agentVersion`, `error` |
| TypeInfo | `name`, `fullName`, `assemblyName`, `assemblyQualifiedName`, `baseTypes` string array | Missing CLR FullName becomes empty plus a diagnostic; do not call ToString |
| ObjectRef | `sessionId`, `objectId`, `generation`, `type`, `dispatcherId` | Handle is opaque; generation is positive integer; `dispatcherId` is a session-scoped opaque ID for the owning or traversal Dispatcher (section 5), never a managed thread ID |
| Member | `memberKey`, `name`, `category`, `declaringType`, `declaredType`, `visibility`, `readable`, `attributes` | `pathSegment`, `dependency`, `reason`, `wrapperKey` (CLR wrapper ↔ DP cross-link), `compatibilityAlias` (for example `ClrFullClassName` on the `type:FullName` row) |
| AttributeInfo | `typeName`, `constructorArguments`, `namedArguments` | Metadata only; safe scalar literals or type names, never attribute instances |
| Value | `status`, `kind`, `declaredType`, `runtimeType` | `scalar`, `object`, `message`, `truncatedAt`, `cycleTo`, `failedSegment`, `dependencySource` according to variants below |
| DependencySource | `baseValueSource` (WPF `BaseValueSource` name), `isExpression`, `isAnimated`, `isCoerced`, `isCurrent` | Present only on values read through a dependency segment |
| Page | `items`, `complete`, `snapshotId`, `diagnostics` | `nextToken`; present iff there are further items |
| Mapping | `status`, `process`, `runtimeId` | `object`; only when exact and unique |

Member categories: `typeMetadata`, `clrProperty`, `clrField`, `dependencyProperty`,
`attachedProperty`. `typeMetadata` rows have keys `type:Name`, `type:FullName`,
`type:AssemblyName`, `type:AssemblyQualifiedName`, and `type:BaseTypes`, declaring type equal
to the object's runtime type, visibility `public`, readable true; reading one uses a single
`type` path segment and never runs target code.
Visibility: `public`, `protected`, `internal`, `private`, `protectedInternal`,
`privateProtected`. Use the effective getter visibility for properties.
Value kinds: `null`, `string`, `boolean`, `integer`, `number`, `enum`, `object`, `array`,
`type`, `unavailable`. Value statuses: `ok`, `notRead`, `notReadable`, `nullIntermediate`,
`exception`, `stale`, `redacted`, `truncated`, `cycle`, `timeout`, `unsupported`.

For `ok` scalar values exactly one `scalar` is present. Null uses kind `null` and scalar null;
it is not equivalent to omitted scalar or `notRead`. Object/array values carry ObjectRef, not
serialized object properties. `cycle` carries `cycleTo`, never recursive JSON. Every status
other than `ok`, `cycle`, and `truncated` uses kind `unavailable` and carries neither `scalar`
nor `object`. `truncated` is the single exception that carries data: kind `string`, the
bounded prefix as `scalar`, and `truncatedAt` (original length in Unicode scalar values) so
Spy can display it; locators and Copy value still treat it as unusable (section 10).
`nullIntermediate` and `exception` carry the zero-based `failedSegment`. Redacted values never
carry data. TypeInfo is safe metadata and may remain visible.
Each diagnostic is `{code,message,category?}`, using bounded strings without target values.
Page complete is true only on the final page of an otherwise successful discovery; false
means more pages, partial failure, or a resource limit, distinguished by nextToken/diagnostics.
Member metadata contains no Value until an explicit read; the UI derives notRead from that
absence, never from a fake null.
Mapping statuses: `exact`, `notFound`, `ambiguous`, `unsupportedPeer`, `stale`, `limitExceeded`.
Only `exact` includes an ObjectRef. Never return the closest candidate as exact.

### Operations

All public method names below must be added to the server's strict `_PARAMS` dispatch table.
Pipe methods use the same suffix without `inspect.managed.` except where noted. Python
resolves UIA `nodeId` to process identity/runtime ID itself; it never treats a client-provided
object ID as belonging to an unrelated session. All object operations include sessionId and
generation.

Attach and status take a full ProcessIdentity, not a bare PID. Spy sends the identity it
showed in the confirmation dialog, so a PID reused between confirmation and launch fails with
`processReused` instead of instrumenting a different process.

| Public RPC | Exact params | Result / pipe action |
| --- | --- | --- |
| `inspect.managed.identify` | `{nodeId}` | ProcessIdentity plus executable path, runtime, architecture, WPF presence; probe only, never loads code |
| `inspect.managed.attach` | `{process}` | Session; Python probe/launch/hello |
| `inspect.managed.status` | `{process}` | Session or detached identity; no implicit attach |
| `inspect.managed.detach` | `{sessionId}` | `{detached:true}`; pipe `session.close` |
| `inspect.managed.resolve` | `{sessionId,nodeId}` | Mapping; pipe `element.resolve` with exact runtime ID integer array |
| `inspect.managed.roots` | `{sessionId,pageSize?,pageToken?}` | Page of managed node DTOs |
| `inspect.managed.children` | `{sessionId,objectId,generation,tree,pageSize?,pageToken?}` | Page; tree is `visual` or `logical` |
| `inspect.managed.members` | `{sessionId,objectId,generation,pageSize?,pageToken?}` | Page of Member; never evaluate getters |
| `inspect.managed.read` | `{sessionId,objectId,generation,paths}` | `{values:[{path,value}],readId}` in input order |
| `inspect.managed.bindings` | `{sessionId,objectId,generation,memberKeys}` | `{bindings:[BindingInfo]}`; maximum 32 keys |
| `inspect.managed.release` | `{sessionId,objectIds}` | `{releasedCount}`; maximum 256 IDs |

Managed node DTO is `{object,label,hasVisualChildren,hasLogicalChildren,runtimeId?}`; the label
is type name, not ToString or a getter-derived display name. Runtime ID is present only when
obtained from an associated peer. A `paths` entry is a parsed typed path-segment array (section
9), not code; Python parses canonical strings (section 10) into this form before sending. A
segment built from a Member row carries that row's `memberKey`, which selects the exact
declaration and cannot be ambiguous. Internal `element.readBatch` additionally accepts at most 32 runtime IDs and scalar
paths for locator filtering; it returns per-candidate mapping and per-path value results.
No other evaluation, invoke, write, attach-to-arbitrary-payload, or screenshot operation exists.

Error codes: `invalidParams`, `unsupportedProtocol`, `unsupportedTarget`, `accessDenied`,
`authenticationFailed`, `payloadMissing`, `payloadMismatch`, `alreadyAttached`, `notAttached`,
`attachFailed`, `blockedByPolicy`, `agentVersionMismatch`, `processExited`, `processReused`,
`sessionStale`, `objectStale`, `mappingFailed`,
`memberAmbiguous`, `memberNotFound`, `dispatcherUnavailable`, `timeout`, `busy`, `limitExceeded`,
`invalidPageToken`, `cancelled`, `internalError`. Getter exceptions are Value results, not
whole-request failures. Messages omit tokens, stack traces, property contents, and full paths
unless explicitly needed for the installation error. Details contain codes and identities only.

Cancellation: pipe `request.cancel` has `{requestId}` and returns `{accepted}`; cancelling
queued work removes it. Cancelling running work suppresses its eventual response content.
No unsolicited value notifications or automatic polling in V1. Target exit/transport loss
invalidates the client session and updates the UI through the existing host message channel.

Pagination snapshots freeze sorted metadata/node handles, not application values. Tokens are
opaque session-owned random IDs referencing bounded snapshots, expire after 30 seconds, and
are bound to object/generation/operation/tree. At most 16 snapshots per session; reject new
snapshots when full. Invalid/expired tokens return `invalidPageToken`, never restart silently.

## 7. Managed identity and UIA association

**Revision 3 amendment:** UIA association is optional for WPF-native discovery and actions; a valid WPF ObjectRef is an action target. The exact mapping rules below remain applicable when mapping UIA elements.

Object handles are session UUID plus monotonic object counter plus generation; never memory
addresses or object GetHashCode values. Use reference identity for the registry. Keep weak
references by default and strong references only for bounded active leases. Re-read paths on
every operation; a DataContext change must not return a previously cached view model. Expired,
collected, released, or prior-session handles return `objectStale`. Do not recycle object IDs.

Discovery starts from live `PresentationSource` roots for each Dispatcher. Combine visual
and logical traversal using `VisualTreeHelper` and `LogicalTreeHelper`, deduplicate objects
by reference, and use an explicit queue, not recursion. Include open popup presentation roots.
Never call ApplyTemplate, UpdateLayout, ScrollIntoView, or item-container generation.

Mapping algorithm (fixed):

1. Python obtains live PID, creation time, UIA runtime ID, and ancestor HWND hints. Parse the
   existing dot-separated runtime ID as signed integer components; reject malformed IDs.
2. Enumerate current managed roots/objects within section 5 limits. For UIElement and
   ContentElement obtain existing automation peers first; create a missing peer only when
   explicitly resolving a selected UIA node. Peer creation can execute application code and
   must be disclosed. Do not force peers for the whole managed tree.
3. Isolate runtime-ID access in PeerRuntimeIdAdapter. Bind the WPF base AutomationPeer
   nonpublic instance `GetRuntimeId()` method with zero parameters and `int[]` return type.
   Invoke it on the peer on its Dispatcher. This is a deliberate, version-tested internal-API
   dependency; do not reproduce a runtime-ID formula or use a guessed hash-code suffix.
4. Traverse existing peer children within the same bounds to account for ContentElement and
   data-item/custom peers. Associate a peer with an object only when a documented owner
   mapping exists (`UIElementAutomationPeer.Owner` or `ContentElementAutomationPeer.Owner`).
   Unowned/data-item proxy peers return `unsupportedPeer`; do not reflect arbitrary owner fields.
5. Compare the complete integer runtime-ID array and process identity. HWND, bounding rectangle,
   automation ID, name, and class may narrow roots but are never identity proof. Match neither
   coordinates nor names as a fallback. Multiple matching objects produce `ambiguous`.
6. Revalidate the source UIA identity and target object before returning. A disappearing
   object yields `stale`; a budget-exhausted scan yields `limitExceeded`, not `notFound`.

Top-level windows are usually exposed to UIA by the HWND host provider rather than by the WPF
peer, so their runtime ID is HWND-based and never equals a peer `GetRuntimeId()` result. When
the selected element's UIA NativeWindowHandle is nonzero and the element is the HWND's own
UIA element, map it through `HwndSource.FromHwnd(hwnd)` on that HWND's Dispatcher to its
`RootVisual`. Verify that the HWND belongs to the target PID and is still the same window
(a live, valid handle owned by the same thread) before returning `exact`. This is identity
by window handle, not a coordinate or name fallback. Stage 4 confirms the runtime-ID form
for each cell and records it in the compatibility results.

`element.readBatch` resolves its up to 32 candidates from one bounded traversal: build a
runtime-ID-to-peer index per Dispatcher once per batch, then look each candidate up in it,
instead of scanning the tree once per candidate. The scan limits apply to that traversal.

Use a short-lived mapping cache of weak objects/peers keyed by session, process identity,
runtime ID, and tree generation. Increment generation on observed presentation-source/root
changes; clear mappings on explicit refresh/detach/exit. Revalidate every cache hit against
peer runtime ID and live source/root membership. Mapping failure affects managed inspection
only; ordinary UIA inspection remains available. Recycled item containers must remap/re-read
their current DataContext, not inherit values from a prior row.

If internal GetRuntimeId is absent, has changed signature, or fails a round-trip fixture,
disable managed/UIA association for that runtime and fail its release gate. Other metadata
inspection may still work, but must not be advertised as exact selected-control inspection.

## 8. General member, type, attribute, dependency, and binding discovery

MemberCatalog must implement these steps for every object, not branch on application types:

1. Obtain the runtime Type and produce TypeInfo: simple/full/assembly-qualified names, assembly
   simple name, and complete base-type chain. Do not read Assembly.Location by default. Add
   metadata entries `type:Name`, `type:FullName`, `type:AssemblyName`,
   `type:AssemblyQualifiedName`, and `type:BaseTypes`. Show `ClrFullClassName` as a labeled
   compatibility projection of `type:FullName`; generated locators always use the canonical key.
2. Walk the inheritance chain with DeclaredOnly instance reflection for properties and fields,
   public and nonpublic. Preserve hidden declarations separately. Property keys are
   `clrProperty|<assembly>|<declaringFullName>|<name>|<indexParameterTypeList>`; field keys use
   `clrField|<assembly>|<declaringFullName>|<name>`. These are metadata identifiers, not code.
   Virtual overrides share one effective public property row, with the most-derived declaration
   and base declaration metadata; distinct `new`-hidden properties stay distinct.
3. Merge `TypeDescriptor.GetProperties(instance)` descriptors to include dynamic/custom public
   descriptors and WPF-provided properties, including Browsable(false). Descriptor-only keys
   use component type/name/type; duplicate indistinguishable descriptors are listed as ambiguous
   and unreadable. A descriptor and reflected property merge only with the same declaring
   identity, name, and declared type. Custom descriptor code may execute during discovery;
   run it on the Dispatcher and apply the same fault/timeout policy as getters.
4. Enumerate local dependency values with GetLocalValueEnumerator and obtain applicable
   dependency descriptors through DependencyPropertyDescriptor.FromProperty. Union by the
   actual DependencyProperty object, not its short name. Mark attached properties using the
   descriptor when available; otherwise use the owner/name with attached classification unknown
   in the dependency metadata, not an invented CLR wrapper. The union covers local attached
   values plus relevant nonlocal/default/inherited descriptors.
5. Keep dependency rows distinct from CLR wrapper rows, cross-linking their keys through
   `wrapperKey`. Dependencies
   use `dependencyProperty|<ownerAssembly>|<ownerFullName>|<name>`. Include property type, owner,
   readOnly, local-value presence, and metadata flags when safely available. On explicit read,
   use GetValue and DependencyPropertyHelper.GetValueSource for base source, expression,
   animation, coercion, and current-value state. Do not evaluate every DP during listing.
6. Use CustomAttributeData on reflected declarations/types, never GetCustomAttributes or
   Attribute constructors. Attribute arguments are scalar literals, enum/type identifiers,
   and bounded literal arrays. Descriptor-only attributes are listed as unavailable if obtaining
   them would require materializing arbitrary attribute instances. Do not inspect attributes
   by running their property getters. Obsolete/Browsable metadata does not hide declarations.
   This is a rule for inspector-owned reflection, not a sandbox around a custom descriptor:
   descriptor implementations may themselves instantiate attributes or execute arbitrary code.
   Disclose that risk; do not claim metadata enumeration is universally side-effect-free.
7. Compute readable=false for no public getter, indexers, nonpublic fields, static values,
   by-ref/pointer/byref-like values, ambiguous descriptors, and unsupported members. Store a
   reason enum: `nonPublic`, `writeOnly`, `indexer`, `static`, `unsupportedType`, `ambiguous`.
   Never invoke a nonpublic getter through a public setter or bypass visibility via reflection.
8. Sort with ordinal comparison by category, name, declaring type, then member key. Freeze
   metadata for pagination. Dynamic descriptor results are per-object/per-snapshot, not cached
   globally by CLR Type. Cache only immutable reflection metadata weakly by Type.

Discovery acceptance is set-based: compare the full member catalog of several unrelated custom
controls/view models to expected reflection/descriptor sets. Verifying only the two motivating
names is insufficient. Exceptions from one descriptor/category yield explicit diagnostics and
partial completeness; other categories remain available. Extend Page with `diagnostics` and
`complete:false` for partial failures; `nextToken` exists only when another page actually exists,
not merely because a category failed.

### BindingInfo

On an explicit bindings request, use BindingOperations.GetBindingBase and
GetBindingExpressionBase for the selected DP; no BindingExpression.UpdateTarget/UpdateSource.
Return `{memberKey,kind,status,mode,updateSourceTrigger,path?,elementName?,relativeSource?,
sourceType?,converterType?,children?,validationErrors?}`. kind is `none`, `binding`,
`multiBinding`, or `priorityBinding`; mode/trigger/status use WPF enum names as strings. For
kind none, mode/trigger/status are empty strings. Missing metadata is absent, not guessed.
Multi/Priority children use the same DTO recursively, maximum depth 8 and 32 total entries.

Read only metadata: path text, binding mode, update trigger, source/converter type names,
ElementName, and RelativeSource mode/ancestor type/level. Never invoke converters, enumerate
sources, force source resolution, call ToString on validation ErrorContent, or evaluate
MarkupExtension. Validation entries contain exception/error type names only. Binding source
values require an ordinary explicit object read, not an implicit binding dump. Sensitive-name
rules apply to binding paths and source metadata in exported output.

## 9. Value reading, nested paths, redaction, and serialization

`members` returns notRead metadata, not values. `read` is the only operation that evaluates
target member values. For each path: validate syntax and readability first; dispatch to the
owning thread; resolve one segment at a time using MemberCatalog; read once per segment within
that request. No arbitrary expressions, method calls, arithmetic, indexers, or language eval.
Do not recursively expand every object when showing a selected control.

A pipe path is an array of typed segments: `{kind,name,declaringType?,memberKey?}` for
`property` and `field`, `{kind:dependency,ownerType,ownerAssembly,name}`, or `{kind:type,name}`
for type metadata. When `memberKey` is present it must equal a key in the current object's
catalog and must agree with `kind`/`name`; otherwise the read fails `memberNotFound`. Type metadata is permitted only as the sole segment. Require an explicit declaring
type for hidden-name ambiguity in interactive member reads; unqualified ambiguous paths fail
`memberAmbiguous`. A path is a lookup against a catalog, never a reflection type-loader request.
Only members of the current object may be addressed. Do not load owner assemblies on demand.

If a segment returns null before the final segment, return `nullIntermediate` with the failing
segment index; final null is an `ok` null value. Getter exceptions return status exception and
exception type only. Never put exception.Message/stack traces in output by default; they can
contain application data. One bad path does not discard successful paths in the same batch.

Serialization is an explicit allowlist:

| CLR value | Wire representation |
| --- | --- |
| null | kind null, scalar null |
| string/char | string, bounded to 4,096 Unicode scalar values |
| bool | boolean |
| integer within JavaScript safe range | integer JSON number |
| integer outside +/-9,007,199,254,740,991 | integer kind with invariant decimal string; runtimeType disambiguates |
| finite float/double | number JSON number |
| decimal | number kind with invariant exact decimal string |
| NaN/Infinity | number kind with scalar string `NaN`, `Infinity`, or `-Infinity` |
| enum | enum kind with symbolic name plus numericValue invariant string |
| DateTime/DateTimeOffset/TimeSpan/Guid | string kind, invariant round-trip format, exact runtimeType |
| System.Type | type kind, TypeInfo metadata, no dynamic activation |
| ordinary object | object kind with ObjectRef and TypeInfo; never arbitrary ToString |
| CLR array | array kind with ObjectRef, rank/length metadata; no implicit iteration |
| IEnumerable/ICollection/dictionary/Task/Lazy/stream/delegate | object reference only; no Count, iteration, awaiting, or Value evaluation |

Add optional `numericValue`, `typeInfo`, `arrayRank`, and `arrayLength` fields to Value schema
for the corresponding variants. Arrays are not index-readable in V1; display their shape and
ordinary public members only. This deliberately avoids collection side effects and does not
promise item browsing. Do not serialize exceptions, COM objects, Dispatcher internals,
SecureString, pointer values, or raw handles; show unsupported/redacted metadata.

Maintain a per-path reference-identity ancestor set. A repeated reference returns cycle with
the ancestor ObjectRef, not recursive traversal. Shared noncyclic references reuse an object ID.
Never call application Equals/GetHashCode/ToString for registry identity or labels. Use
RuntimeHelpers identity facilities and reference comparison only.

Sensitive-name matching is ordinal case-insensitive substring matching for `password`,
`passwd`, `pwd`, `secret`, `token`, `credential`, `connectionstring`, `apikey`, and
`privatekey`, plus any names added by `inspector.redact_names` (section 10). Configuration
can only add names, never remove built-in ones. Apply it to any member in the full path, plus
UIA IsPassword when available. Extra rules are limited to 32 nonempty names of at most
128 Unicode characters each; malformed Unicode is rejected. The additive total across
configuration layers obeys the same limit. A policy change replaces existing sessions. A sensitive member returns redacted before invoking its getter;
do not create an object handle for its value. PasswordBox.Password and SecurePassword are
denied by declaring-type/member identity as well. Never offer reveal in V1. Over-redaction is
accepted (for example `CancellationToken` is redacted); Spy labels the matched rule so users
understand why. Users must be warned that name-based redaction cannot identify every secret.
Managed values are session memory only by default: no replay, screenshot annotation,
object-preview or element-capture content, telemetry, or automatic failure-report dump. Explicit copy/export requires a user action and
retains redaction; export metadata includes protocol version, process identity, timestamp, and
completeness. Logs record method, timing, status, counts, and IDs only, never values.

## 10. Python integration, configuration, and locator semantics

**Revision 3 amendment:** The post-filter pipeline and 1,000-candidate cap below apply to the UIA backend only. WPF locators push managed and UIA-equivalent predicates into the agent query. D7 makes `backend: auto` the default at the phase 3 parity gate; `backend: uia` remains an explicit opt-out. D5 forbids fallback for WPF agent failures. Mouse input is the default; peer patterns are available via `pattern` mode (D1). For WPF mouse input, Python uses `ElementState.windowHandle` from `state.get` to verify foreground window ownership before injection; a null or invalid handle or failed check prevents injection.

Add frozen InspectorConfig to WtkConfig, with equivalent YAML `inspector:` (in
`wintestkit.yaml` and `wintestkit.local.yaml`) and legacy TOML `[tool.wintestkit.inspector]`
nested mappings. It follows the existing layering: shared file, then local override file,
then CLI options. Unknown keys/types are ConfigError. Defaults:

```yaml
inspector:
  enabled: false
  attach: manual               # manual or on-demand
  attach_timeout: 10.0         # >0 and <=10 seconds
  request_timeout: 2.0         # >0 and <=2 seconds
  redact_names: []             # extra sensitive-name substrings; additive only
```

No `WTK_*` environment-variable overrides in V1; do not extend `_ENV_VARS`. Repository
Settings in VS Code edits these keys like other settings and marks them modified.
Committing `enabled: true` with `attach: on-demand` to the shared file authorizes every
person and CI job running the suite to instrument the application under test; the docs say
so plainly, and `wintestkit.local.yaml` is the place for a personal opt-in. When the pytest
plugin is active and the inspector is enabled, its report header prints the attach mode, and
the run summary lists every process identity it attached to.

`enabled:true` opts into the feature; `on-demand`
additionally permits attachment when an explicit managed locator/CLI read needs it. It never
attaches merely because an app starts or UIA properties are requested. `manual` requires a
previous explicit attach in that backend. VS Code trust/confirmation remains required even
when repository configuration requests on-demand attachment. For headless pytest, enabled
plus on-demand is the explicit authorization; document it. Disabled managed queries fail with
an actionable configuration error, never silently fall back to UIA.

Python client uses typed dataclasses, validates all incoming DTOs, maps transport errors to
dedicated InspectorError subclasses, and accepts a monotonic outer deadline. Introduce
InspectorUnavailableError, InspectorMappingError, InspectorReadError, and InspectorLimitError
under the existing project error hierarchy. No client singleton outside runtime context.
Use Windows named pipes via ctypes (stdlib), with overlapped I/O, cancellation, exact framing,
and close-on-finally. Test with an injectable byte transport; no new Python native dependency.

CLI additions on the existing `wtk inspect` command: `--managed` explicitly authorizes attachment
for that invocation when inspector.enabled is true, including manual mode, and requests metadata;
`--read <qualified-path>` is repeatable and explicitly evaluates selected values;
`--json` retains structured statuses; `--managed` never implies reading every value. A standalone
invocation owns its attachment and detaches in finally. V1 does not add standalone attach,
status, or detach subcommands: a short-lived command cannot establish a persistent backend
session for later commands. Do not introduce a daemon. Long-lived Spy/backend sessions expose
attachment lifecycle through the public RPC methods already specified.

### Qualified locator keys

Keep all existing unqualified UIA properties and aliases unchanged. Add only these namespaces:

| Key | Meaning |
| --- | --- |
| `type:FullName` | Exact runtime Type.FullName; ClrFullClassName compatibility copy uses this |
| `type:AssemblyName` | Runtime assembly simple name |
| `clr:DataContext.Customer.Name` | Public property chain |
| `field:PublicField.NestedProperty` | First segment public field, later segments public properties |
| `dp:OwnerAssembly|Namespace.Owner::Property/NestedProperty` | First segment dependency property, later slash-separated public properties |

For clr/field segments, backslash escapes only dot and backslash. For DP owner/property names,
reject delimiter characters `|`, `:`, `/` rather than guessing; nested segments escape slash
and backslash. No brackets, calls, wildcard member names, integer indices, private reads, or
assembly loading. Parse once into typed segments, validate length/depth, and preserve the
original canonical string for serialization. Casing is ordinal and exact. Ambiguous names are
errors; the user must choose a different unambiguous path in V1.

### Managed alias targets (TestComplete migration)

`property_aliases` values may name a qualified managed key, for example
`property_aliases: {ClrFullClassName: "type:FullName"}`. This is the only way an unqualified
name reaches the inspector, and only because the repository wrote it. An alias whose target
has a managed namespace becomes a ManagedCondition; all other aliases keep their UIA meaning.
Managed alias targets are validated at configuration load with the same parser, may not chain
to another alias, and fail with an actionable ConfigError when the inspector is disabled and
a locator uses them. `wtk import-namemapping --managed-class-names` emits
`where={"type:FullName": ...}` directly; without the flag the importer's output is unchanged.
Spy shows the alias name next to the canonical key so users see what is really matched.

Extend condition resolution into a tagged union of UiaCondition and ManagedCondition. Never
insert managed names into SUPPORTED, PROPERTY_IDS, or com.create_condition. Validate managed
syntax at declaration time without attaching or importing target assemblies. Type-check
expected literals as existing WhereValue permits; V1 supports string/bool/int/float/compiled
regex, not object comparison or null locator literals.

Query algorithm:

1. Build native UIA conditions from existing exact UIA filters only.
2. Preserve existing UIA depth/regex behavior and deduplicate in UIA document order.
3. With no managed constraints, return via the current code path: zero inspector calls.
4. With managed constraints, enforce a 1,000-candidate hard cap. More candidates fail
   InspectorLimitError, never silently truncate or claim no match. Encourage tighter UIA scope.
5. Resolve candidates in batches of 32 using element.readBatch, respecting the outer deadline.
   Read each distinct path once per candidate per query attempt; do not cache values across
   attempts. Filter by AND without changing order. Apply locator index/within semantics at
   their existing layer, after filtering, not separately per batch.
6. Evaluate regexes on Python strings using existing re.search behavior, never in target code.
   Scalar equality is type-aware: bool never equals 0/1; strings never coerce to numbers.
   Numeric strings from exact integer/decimal wire encoding are decoded to int/Decimal with
   explicit numeric comparison; floating expected values use exact existing equality, no
   tolerance. Enums match symbolic strings or numeric integer literals, not display summaries.
7. Null/nullIntermediate cannot match supported V1 expected values. Stale candidates are
   skipped for that poll; re-resolve on the next normal locator retry. Mapping ambiguity,
   unsupported peer, getter failure, redaction, truncation, unsupported scalar types, or
   read/transport limits are explicit errors,
   not a nonmatch that could hide another matching control. Evaluate all candidates before
   returning success; incomplete evaluation cannot establish unique matching.
8. Attachment time consumes the same locator deadline. Transport/blocked-Dispatcher failures
   fail promptly, without repeated attach. Preserve strict ambiguity and existing retry policy.
9. Before the first batch, estimate the work (candidate count / 32 batches) against the
   remaining deadline. If the per-batch budget observed so far shows the deadline cannot cover
   every candidate, fail with InspectorLimitError naming the candidate count and suggesting a
   tighter UIA scope, rather than timing out midway with a vague error. A 1,000-candidate scan
   is a ceiling, not an expectation: managed constraints are meant to disambiguate a handful
   of UIA matches (for example, repeated rows or relocated boxes with the same AutomationId).

Do not add managed paths to automatic suggestions in V1. Spy can explicitly copy a scalar
property as a qualified where entry only after the full query verifies uniqueness in scope.
Unavailable/redacted/truncated/object values are not copyable as locator literals.

## 11. Spy UX, packaging, and operational behavior

### Spy

**Revision 3 amendment:** For WPF windows the WPF tree and agent hit-test picker are primary; `hitTest` takes the cursor point and native HWND, verifies target-process ownership, and maps the HWND via `HwndSource.FromHwnd` on its Dispatcher; a non-WPF or foreign HWND fails `mappingFailed`, while no hit returns `notFound`; UIA is secondary and remains primary for non-WPF windows. On a blocked WPF agent show the blocked state and fix, not a UIA substitute (D5).

Keep the current UIA basic/all-properties view intact. Add a separate Managed inspection
section with state badge, Attach, Detach, and Refresh metadata buttons. Attach uses the selected
node PID, checks workspace trust, and confirms the process identity and instrumentation risks.
Changing selection to another PID never auto-attaches. Show `not enabled`, `not installed`,
`unsupported target`, `blocked by policy`, `restart required` (agent version mismatch),
`attach failed`, `mapping unavailable`, `detached (idle)`, and `ready` as distinct states.
Each error offers an actionable explanation; do not display an empty DataContext as success.
`not installed` shows the exact install command for the selected Python environment
(`pip install "wintestkit[inspector]"` or the `uv` equivalent) with a copy button; the
extension never installs packages itself.

On successful attachment and exact resolution, render these collapsible groups in order:
Managed type; CLR properties; CLR fields; Dependency/attached properties; Bindings. Type metadata
may display immediately; all member rows initially show notRead. An explicit row Read control
evaluates a value. An object Expand control first reads that member, then lists its metadata;
expansion does not evaluate child getters. A Read visible button reads at most 32 checked visible
readable members, after the getter warning. Do not start background polling or eager recursive
expansion. Refresh invalidates metadata/value display and rereads only type metadata.

Every row shows name, declared/runtime type, declaring type, source category, visibility,
readability, and status. Dependency rows additionally expose owner, source, binding, and
local/effective distinctions. Hidden declarations are distinguishable by declaring type.
Cycle rows link to an ancestor rather than expand forever. Paginated lists have explicit
Load more; never label a partially loaded list complete. Search filters loaded metadata only
and says so; do not silently execute a full target-process search.

Reuse existing webview CSP, nonce, and text-escaping conventions. Render member names/values
as text, not HTML. Validate every webview message with a closed shape; the host derives PID
and session identity, not untrusted DOM attributes. Gate late responses by session ID, node ID,
and selection sequence. On selection change release old leases and cancel queued reads.
On detach/exit/backend restart discard all handles and pending page tokens. Persist only
namespaced pinned paths in user settings; never persist values, tokens, object IDs, or sessions.

Copy actions: Copy value (safe scalar only); Copy canonical path; Copy locator (section 10
uniqueness gate); Export metadata (explicit, redacted, includes completeness). Clipboard reads
do not bypass redaction or trigger additional getter evaluation. Nonpublic/unreadable rows
cannot expose a reveal/read action. Existing UIA pinning remains compatible.

### Packaging

Keep source in this repository. Publish the payload as a separate distribution,
`wintestkit-inspector`, exposed to users as the extra `wintestkit[inspector]`. The core
`wintestkit` wheel stays `py3-none-any`, contains the Python client (`wintestkit.inspector`)
but no binaries, and keeps building from its sdist without a .NET toolchain, so the existing
`check_wheel.ps1` contract and every current install target remain valid. Putting native
executables into the core wheel would force a `win_amd64` tag and drop installs that work
today (for example ARM64 or 32-bit Python running UIA-only suites).

`wintestkit-inspector` contains only data files (no Python extension modules), so its wheel
is tagged `py3-none-win_amd64`. It includes both x86 and x64 target payloads, enabling a
64-bit Python controller to inspect either. Do not advertise 32-bit or ARM64 Python
controllers in V1; they return a clear controller-architecture error. Its version equals the
`wintestkit` version, the extra pins it with `==`, and `wintestkit.inspector.payload` refuses a
payload whose manifest version differs (`payloadMismatch`). `check_release.py` fails a release
whose two versions differ. The extension uses its selected Python environment, not a second
bundled inspector copy. No .NET SDK/Visual Studio is needed on an end-user machine.

`wintestkit_inspector/manifest.json` contains schemaVersion=1, protocolMajor/minor, inspectorVersion,
source commit, upstream commit, supported runtime/architecture cells, executable/assembly
relative paths, every file SHA256, and third-party notice paths. Refuse incomplete or modified
payloads. Include agent dependencies in a private inspector directory; do not install into
the target app directory or overwrite target DLLs. Do not globally change target assembly
resolution. The compatibility gate must cover conflicting target dependency versions; failure
requires a design amendment, not a process-wide binding redirect.

`build_inspector.ps1` restores locked dependencies, builds the required native/managed projects,
stages only manifest-listed files, computes hashes, signs release binaries, and copies them to
`inspector-payload/src/wintestkit_inspector/`. `check_inspector.ps1` verifies hashes,
signatures (release only), TFM/architecture headers, notices, loading, and absence of
accidental Snoop UI/scripting entry points. The `wintestkit-inspector` sdist includes the
inspector sources/notices and build documentation; building its wheel from source requires
the documented Windows build toolchain. Never publish an inspector wheel missing payload.

Core UIA-only import works without the payload distribution; only enabling inspector
operations then raises payloadMissing, naming the install command. `wtk doctor` reports
payload presence, version match, signature state, and the controller architecture. Use the
project version as inspectorVersion in V1, while protocol version evolves independently.
No runtime auto-update or external install URL.

## 12. Sequential implementation work packages

Each stage is a separate implementor assignment, reviewed and validated before the next.
Do not start a later stage while its prerequisite gate is failing. Every completion record
must list touched paths, exact commands, test counts, logs/artifacts, supported matrix cells,
and unresolved issues. Do not claim a test passed if only a mock version ran. Tests that must
attach to processes run against owned fixtures only. Standard code review is required at every
gate; it does not authorize departures from this specification.

### Stage 0 — Contract and requirement fixtures

Entry: this plan is approved. Scope: protocol schemas, golden JSON fixtures, test skeletons;
no attach code. Add managed DTO definitions and public method schemas, sample requests/results
for every method, invalid fixtures, and existing UIA regression fixtures. Add a traceability
file `wpf-inspector/tests/requirements.json` mapping requirement/stage IDs to named tests.

Gate: positive/negative schema tests cover all closed enums, unknown fields, null versus absent,
page continuation/completeness, malformed paths, and handshake mismatch. Existing contracts
pass unchanged. Regenerated TypeScript has no unexplained manual differences. No public feature
is advertised yet. Commit of a contract alone does not assert a working inspector.

### Stage 1 — Build skeleton and independent test applications

Entry: stage 0 passes. Create section 3 layout, SDK pin, deterministic builds, locked restore,
and exact central package pins for test projects only: xunit 2.9.3,
xunit.runner.visualstudio 3.1.4, Microsoft.NET.Test.Sdk 17.14.1. Agent and Protocol have no
package references (section 3); the build fails if one appears. Preserve upstream package pins
inside the third-party build boundary. Record transitive dependency lockfiles. No floating
versions or prerelease dependency substitution. A security advisory or restore incompatibility
blocks the gate for owner review rather than allowing an implementor-selected upgrade.

Create a WPF fixture from shared source targeting net48/net8.0-windows/net10.0-windows, each
published as x86 and x64. Fixture process must not reference Agent or inspector DTO assemblies.
Include: inherited custom control; base/hidden/override members; public/private fields;
write-only property; indexer; type/enum/decimal/large integer values; null and nested view models;
cycles; sensitive-name getters with invocation counters; throwing, slow, and hanging getters;
custom TypeDescriptor with dynamic property; attached DP; inherited/default/local/bound DP;
Binding/MultiBinding/PriorityBinding; popup; duplicate UIA names/IDs; second Dispatcher;
virtualized rows with changing DataContext; and custom/unowned automation peers. Provide a
fixture-only control channel for deterministic scenario selection and counters, not for reading
values on behalf of the inspector. Its protocol is test-only and never ships.

Fixture assemblies deliberately reference conflicting versions of common packages (for
example an old `System.Text.Json`, `System.Memory`, and `Newtonsoft.Json` on net48) so later
stages can prove the agent does not disturb the target's own dependency resolution.

Gate: all six executables build/start, show an interactive WPF window, and pass an independent
UIA smoke test. Pure object-reader unit fixtures exercise counters without attachment. The
fixture binary hash is recorded before inspection to prove subsequent tests require no rebuild.

### Stage 2 — Pipe framing, authentication, and session state machine

Entry: stages 0–1 pass. Implement transport, the `StrictJson` codec and DTO parser (C#) and
the matching Python parser, both checked against the stage 0 golden fixtures, bootstrap
ACL/file handling,
session registry, limits, deadlines, cancellation, and injectable fake transport. Initially
run SessionHost in a harness process; no injection or real target reads.

Gate: split header/body reads, zero/oversized lengths, invalid UTF-8/JSON, duplicate keys,
depth overflow, EOF, request-ID mismatch, stale token, wrong SID/identity, malformed bootstrap,
reparse point, expired bootstrap, wrong major, concurrent attach, full queue, idle close, and
cancellation all have deterministic tests. Denied connections expose no target values.
Wrong-user/session tests may use a dedicated Windows test account; skipped tests are recorded
as unverified and block claims of passing that security gate.

### Stage 3 — Attach the .NET 10 x64 vertical slice

Entry: stage 2 passes. Import the pinned source archive and lock it with hashes; build only
required loader artifacts and implement the fixed wrapper. Load a minimal Agent returning
version/process metadata only. Do not implement property discovery to conceal attach problems.

Gate: attach to an already running .NET 10 x64 fixture without startup flags or app-side files;
authenticated hello confirms exact creation time/runtime; detach leaves the window interactive.
Test duplicate backend attach, load failure, missing/tampered payload, spaces/Unicode in paths,
target exit during handshake, identity reuse through a fake process probe, denied integrity,
no WPF loaded, a target window HWND owned by another process, agent version mismatch on
re-attach (`agentVersionMismatch`), and a launcher blocked by a test AppLocker/WDAC rule or a
simulated block (`blockedByPolicy`). Repeat attach/detach 100 times without accumulating listeners or handles.
Retain independent evidence that the target executable/configuration hash stayed unchanged.
If upstream runtime hosting fails, stop here and amend the attach design; do not proceed with
an app-modifying SDK workaround.

### Stage 4 — Tree traversal and exact identity

Entry: real attach passes. Implement ObjectRegistry, DispatcherExecutor, managed roots/trees,
PeerRuntimeIdAdapter, and ElementMapper. No property getters beyond peer/tree APIs.

Gate: round-trip at least 20 distinct UIA selections to correct managed objects; distinguish
identically named/sized siblings, nested HWNDs, popup roots, custom controls, top-level
windows whose runtime ID is HWND-based (section 7), and windows on two Dispatchers. Recycled rows, closed windows, collected objects, and stale generations cannot
return previous objects. Unowned peers fail explicitly. Missing/changed internal runtime-ID
method is tested with an adapter fake. No coordinate/name fallback is present. Hitting scan
limits is distinguished from a complete notFound. UIA-only inspection survives every failure.

### Stage 5 — General metadata discovery

Entry: exact mapping passes. Implement TypeInfo, MemberCatalog, DP discovery, CustomAttributeData,
and immutable metadata pagination. Do not evaluate values on catalog creation.

Gate: compare complete expected member sets for three unrelated fixture types, including
inherited/hidden/overridden members, nonpublic declarations, dynamic descriptors, indexers,
and default/local/attached DPs. Invocation counters prove ordinary getters and attribute
constructors were not called. Assert no unrelated static type initializers run. Verify
duplicate DP/wrapper handling, category/source metadata, deterministic ordering, failed
descriptor partial diagnostics, and token expiry. Type.FullName drives the compatibility row
without a target-name-specific getter; DataContext is not in a special read table.

### Stage 6 — Explicit values, bindings, and pathological getters

Entry: metadata gate passes. Implement ValueReader, typed paths, BindingReader, safe scalars,
redaction, weak/strong leases, and per-Dispatcher fault isolation.

Gate: read at least 10 unrelated properties and fields, not only motivating examples. Assert
correct null/nullIntermediate, enum, decimal, safe/large integer, date, array-shape, string
Unicode truncation, cycles, shared references, and throwing getters. Every sensitive getter
counter remains zero. A getter is called once per segment/request. Binding tests prove no
converter/UpdateSource/UpdateTarget invocation. Read changing DataContext twice and observe
the new value without stale-cache reuse.

Run slow/hanging-getter tests in dedicated owned fixture processes. The test client returns
at its deadline, marks only the affected Dispatcher unresponsive, sends no later values, and
does not enqueue replacement work. Another Dispatcher stays inspectable. The fixture may be
killed by its harness after evidence capture; do not describe this as target-safe cancellation.
Detach/selection release removes strong leases; tests force fixture GC to prove normal
inspected objects become collectible once all fixture-owned references are also removed.

### Stage 7 — Python client, server, config, and CLI metadata

Entry: stages 0–6 pass. Implement the Python package, runtime-scoped sessions, typed config,
RPC methods, capability advertisement, server shutdown/refresh invalidation, and CLI options.
No locator support yet. Keep all old RPC results backward compatible.

Gate: fake-client server tests exercise every method/error; strict schemas validate every real
response. Disabled defaults produce no probe, attach, or target code. Manual/on-demand modes
and configuration precedence (shared, local, CLI; no environment layer) are covered in
YAML/TOML tests, including additive-only `redact_names`. The pytest report header and run
summary show attach mode and attached identities. `wtk doctor` reports payload presence,
version, signature state, and controller architecture. Standalone CLI ownership attaches
and detaches in finally, including exceptions and Ctrl+C. Unsupported/missing payload gives a
nonzero exit and actionable message; UIA-only CLI still works. Backend shutdown clears all
sessions, pending requests, and bootstrap files without terminating targets.

### Stage 8 — Managed locator post-filtering

Entry: Python client gate passes. Implement namespaces, path parser, tagged conditions,
query batching, type-aware matching, and diagnostics. Do not change default suggestions.

Gate: UIA-only query tests prove zero inspector calls and unchanged native conditions. Mixed
where constraints narrow first by UIA, then match nested view-model strings, public fields,
DP values, runtime type, bools/numbers/enums, and regexes. Reject bool/int confusion, malformed
escapes, unsupported keys, object equality, redacted values, partial results, and ambiguity.
Validate 1,000-candidate success versus 1,001-candidate failure without silent truncation.
Across batches preserve UIA order and index semantics. Unknown aliases retain existing errors.
Managed alias targets (`ClrFullClassName: "type:FullName"`) resolve to ManagedCondition, reject
chaining, and fail clearly when the inspector is disabled; UIA aliases behave exactly as before.
`wtk import-namemapping --managed-class-names` output is golden-tested, and output without the
flag is byte-identical to today. One batch performs one tree traversal (section 7), and an
unaffordable candidate count fails early with the count in the message.
Slow attachment consumes the original locator deadline; no repeated injection on polling.
Locator serialization round-trips exactly through Python/schema/generated TypeScript.

### Stage 9 — Spy managed UX

Entry: server/locator gates pass. Implement section 11 using current host/webview patterns.
Do not introduce a second property-engine implementation in JavaScript.

Gate: extension unit tests cover trust/confirmation, PID changes, disabled/unsupported/missing
payload states, lazy reads, pagination, object expansion, cycle links, hidden declarations,
binding metadata, redaction (including the matched-rule label), copy/export, the install
command shown for `not installed`, `blocked by policy`/`restart required`/`detached (idle)`
states, Repository Settings `inspector` keys, and strict message validation. Element captures
saved on check contain no managed data even while attached. Simulate out-of-order
responses and verify old session/selection data is discarded. No getters run merely by opening
All properties or selecting another node. Manual end-to-end acceptance uses unchanged fixture
controls with both motivating values and at least 10 other unrelated members. Capture screenshots
of basic UIA, attached metadata, nested values, and a mapping failure for reviewer inspection.

### Stage 10 — Reproducible package and release artifacts

Entry: the .NET 10 x64 vertical slice and UI gates pass. Implement the `wintestkit-inspector`
distribution (manifest generation, `py3-none-win_amd64` tagging, `[inspector]` extra with an
exact version pin), build/check scripts, signing, notices, release-version lockstep in
`check_release.py`, and clean-environment smoke tests. Intermediate artifacts may list only the verified cell; they are not a full V1 release.

Gate: the core wheel is still `py3-none-any`, contains no binaries, builds from its sdist
without .NET, and passes the unchanged `check_wheel.ps1`. Unpack the inspector wheel and verify
every hash, signature, architecture, dependency, protocol version, and notice. Install
`wintestkit[inspector]` in a clean x64 Python environment on Windows without the SDK; launch
unchanged fixture, attach/read/detach using CLI and extension-selected Python. Tampering one
DLL fails before launch. No current-directory DLL hijack and no dependency-version conflict
with the target fixture. No Snoop inspector UI/scripting is exposed. Source distribution can
rebuild payload with the documented toolchain and locked restore. Release checks reject missing
payload or version drift between the two distributions. Installing a mismatched payload
version fails with `payloadMismatch` before launch. Owner approval of third-party inventory is a publication gate.

### Stage 11 — Complete the runtime/architecture matrix

Entry: packaged .NET 10 x64 slice passes. Add cells in this exact order: .NET 10 x86, .NET 8
x64, .NET 8 x86, Framework 4.8 x64, Framework 4.8 x86. For each cell rerun attach/handshake,
identity round trip, descriptor/DP discovery, nested values, bindings, timeout/redaction,
dependency conflict, and detach against the corresponding unchanged executable.

Gate: publish a machine-readable `compatibility-results.json` with OS build, runtime and WPF
file versions, architecture, source/payload hashes, test names, counts, and failures. Any failed
cell blocks the full planned release; do not silently delete it from requirements. A narrowed
release requires explicit owner amendment. Cross-bitness controller tests use x64 Python with
the x86 loader, not an accidentally x64 fixture. Unsupported targets must fail before loading.

### Stage 12 — Documentation and final regression gate

Entry: all six cells and packaging gates pass. Update `docs/development.md`, the property
matching/WPF/troubleshooting/VS Code guides, `docs/guide/migrating-from-testcomplete.md`
(replace the `ItemStatus` alias workaround with the managed alias and importer flag where the
inspector is available), `docs/releasing.md` (two distributions, signing), Python/extension
release notes, and inspector README. Update the test-writing skill in
`python/src/wintestkit/scaffold/skills/wintestkit-tests/` and sync `skills/` with
`scripts/sync_skill.py`, so generated tests use qualified managed keys only when the
repository enables the inspector.
Document exact supported cells, source-build toolchain, explicit authorization, name-based
redaction limits, getter/descriptor risks, incomplete discovery, internal WPF API dependence,
detach versus unload, security-product blocks and allow rules, the restart needed after an
inspector upgrade, and what committing `attach: on-demand` authorizes. Provide examples for public type metadata, nested view-model paths,
DP paths, and field paths; do not document aliases as real CLR inspection.

Gate: run commands in section 13, review requirement traceability, inspect screenshots, and
verify old UIA-only workflows on an unrelated non-WPF application. No claim that the two sample
properties alone constitute complete implementation. All errors/limitations in the docs match
actual statuses. Only an explicit user request authorizes commit/push of implementation work.

## 13. Validation commands and definition of done

These are implementation-stage commands, not evidence that an inspector currently exists.
Add the named scripts/suite filters exactly; do not leave documentation-only test commands.
From repository root, in PowerShell:

```powershell
# Pure contracts and existing backend regression suite
uv run --directory python pytest tests/contract tests/unit
uv run --directory python ruff check .
uv run --directory python ruff format --check .
uv run --directory python pyright

# Generated contracts and extension tests
npm --prefix vscode run gen:types
git diff --exit-code -- vscode/src/protocol/generated.ts
npm --prefix vscode run typecheck
npm --prefix vscode run lint
npm --prefix vscode test

# New subsystem; all referenced flags are required script interfaces
./scripts/build_inspector.ps1 -Configuration Release -LockedRestore
dotnet test wpf-inspector/WinTestKit.Inspector.sln -c Release --no-restore --filter Category=Unit
./scripts/check_inspector.ps1 -Suite Security
./scripts/check_inspector.ps1 -Suite Integration -Runtime net10 -Architecture x64
./scripts/check_inspector.ps1 -Suite Matrix
./scripts/check_inspector.ps1 -Suite Stress -Iterations 100
./scripts/check_inspector.ps1 -Suite Package    # builds and checks wintestkit-inspector
./scripts/check_wheel.ps1                       # core wheel: unchanged py3-none-any contract
uv run --directory python python ../scripts/check_release.py compatibility
npm --prefix vscode run package
```

CI split. GitHub-hosted runners are not a reliable interactive desktop, which is why the
existing suite already excludes `integration` tests there. In `.github/workflows/ci.yml`:

| Job | Runs in CI | Runs on a recorded desktop machine only |
| --- | --- | --- |
| Python/extension (existing) | Unchanged, plus inspector client unit/contract tests with fake transport | — |
| `inspector-build` (new, windows-latest) | Locked restore, build, `Category=Unit`, `-Suite Security` cases needing no second account, `-Suite Package`, both wheel checks | — |
| Desktop gates | — | `Integration`, `Matrix`, `Stress`, wrong-user/session security cases, Spy screenshots |

Desktop-only suites produce the evidence artifacts below and are attached to the release
record; CI never reports them as passed.

Integration xUnit fixtures must expose Category traits matching the script suite selectors.
Scripts return nonzero on any failed assertion, missing required test, skipped required cell,
or unverified release notice. Serialize process-attaching suites per fixture identity; do not
run unrelated agents against the same target. Do not commit generated transient reports.
The generated-types diff command is a final-clean-tree check after the intended regenerated
file is included in the implementation change; during development inspect its expected diff.

Required evidence artifacts under ignored `wpf-inspector/artifacts/verification/`:

- `requirements-results.json`: each section-1 requirement, implementing stage, named tests, result.
- `compatibility-results.json`: all six cells with actual environment/version/hash details.
- Unit/contract/integration JUnit or TRX reports, including explicit skip explanations.
- Sanitized attach/detach logs, latency measurements, process/OS handle counts, GC lease tests.
- Package manifest verification, source archive/hash inventory, and notice approval record.
- Spy screenshots for the scenarios required in stage 9; no unredacted real application data.

Performance acceptance uses the owned .NET 10 x64 fixture on a recorded local reference machine:
attach reaches authenticated ready within 10 seconds; mapping a 1,000-object realized tree
completes within 2 seconds; listing the first 100 members and reading 10 trivial scalar paths
each complete within 2 seconds. Record median and p95 over 20 warm operations, separately from
the initial attach. Never drop properties or weaken mapping to meet a timing threshold.

Stress acceptance: after five warm-up attach/detach iterations and 100 measured iterations,
target OS handle count must not grow monotonically and ending count must be within 10 handles
of the warmed baseline. All session pipes/listeners and strong leases are zero after detach.
Do not require zero assembly-memory growth: the documented loader cannot guarantee unloading.
Repeated reads over changing objects must return weak-registry usage to the configured bound
after pruning; reaching the bound returns a visible limit error, not process memory growth.

The feature is done only when every requirement has real evidence, all six cells pass, old
UIA workflows pass, the core wheel is unchanged in kind, `wintestkit[inspector]` works
without a developer SDK, all limitations are documented, and the owner approves the
distribution inventory. A convincing Spy screenshot,
mock-only tests, or two hard-coded property values does not satisfy completion.

## 14. Primary references and design-sensitive verification

The attach source files below were reviewed at the pinned commit when writing this plan.
They establish the available loader inputs and managed entry convention; they do not establish
that every proposed compatibility cell works. Those claims require the stage gates.

- Snoop source: https://github.com/snoopwpf/snoopwpf/tree/2bf48f60c2bb1753001f6be9122395def9070fa9
- Loader options: `Snoop.InjectorLauncher/InjectorLauncherCommandLineOptions.cs`.
- Launcher orchestration: `Snoop.InjectorLauncher/Program.cs` and `Injector.cs`.
- Native runtime bridges: `Snoop.GenericInjector/NetExecutor.cpp` and `NetFrameworkExecutor.cpp`.
- Loader DTO: `Shared/InjectorData.cs`; third-party terms: `License.txt`.
- WPF peer implementation: https://github.com/dotnet/wpf/blob/main/src/Microsoft.DotNet.Wpf/src/PresentationCore/System/Windows/Automation/Peers/AutomationPeer.cs
- Type discovery: https://learn.microsoft.com/dotnet/api/system.componentmodel.typedescriptor.getproperties
- Dependency property source: https://learn.microsoft.com/dotnet/api/system.windows.dependencypropertyhelper.getvaluesource
- Descriptor discovery: https://learn.microsoft.com/dotnet/api/system.componentmodel.dependencypropertydescriptor.fromproperty
- Binding metadata: https://learn.microsoft.com/dotnet/api/system.windows.data.bindingoperations.getbindingbase
- Attribute metadata: https://learn.microsoft.com/dotnet/api/system.reflection.customattributedata
- Dispatcher work: https://learn.microsoft.com/dotnet/api/system.windows.threading.dispatcher.invokeasync
- Pipe endpoint identity: https://learn.microsoft.com/windows/win32/api/winbase/nf-winbase-getnamedpipeserverprocessid
- HWND root lookup: https://learn.microsoft.com/dotnet/api/system.windows.interop.hwndsource.fromhwnd
- .NET support dates: https://dotnet.microsoft.com/platform/support/policy/dotnet-core

The WPF runtime-ID method is internal and not a stability promise. The reviewed current source
has a zero-argument nonpublic int-array method; the implementation must bind and test the
method, not copy its current numeric formula. Record actual WPF binary versions in each
compatibility run. If any source/dependency pin becomes unavailable or unsuitable, stop its
stage and request a versioned amendment rather than silently choosing a substitute.

## 15. Revision history

Revision 3 (2026-10-29) adopts decisions D1–D7 and supersedes the identified V1 rules in sections 1, 5, 6, 7, 10 and 11; see the [WPF-tree-driven migration plan](wpf-tree-driven-automation.md) and [protocol 2.0 contract](wpf-protocol-2.md). The V1 text remains as historical and UIA-backend context.


Revision 2 (2026-10-27) corrected these defects in revision 1:

- Agent dependencies: revision 1 pinned `System.Text.Json` 10.0.0 inside the target. That
  cannot bind next to the shared-framework copy already loaded by .NET 8/10 targets and
  conflicts with .NET Framework targets' own `System.Memory` family without the binding
  redirects this plan forbids. The agent now has no runtime package dependencies and uses a
  strict, purpose-built JSON codec (section 3).
- Process identity: `attach`/`status` took a bare PID while the plan forbade PID-only lookup.
  They now take a full ProcessIdentity, with a probe-only `identify` method (section 6).
- Value contract: `truncated` was declared non-ok yet needed to show a prefix; the kind of
  non-ok values was undefined; `dispatcherId` and the failing segment index were undefined.
  All are specified now (section 6).
- Packaging: putting native binaries in the core wheel would have changed it from
  `py3-none-any` to `win_amd64`, broken the existing `check_wheel.ps1` contract, and dropped
  UIA-only installs that work today. The payload is now an optional `wintestkit-inspector`
  distribution behind `wintestkit[inspector]` (section 11).
- Window mapping: top-level windows usually carry HWND-based runtime IDs that a peer never
  produces, so revision 1 would have reported them `notFound`. Section 7 maps them through
  `HwndSource.FromHwnd`.
- Loader input: corrected after stage 3 source review. The PID path uses `CreateRemoteThread`,
  not a window hook; `--targetHwnd` is omitted, `Start` must not assume a UI thread, and
  launcher exit codes are not trusted (section 3).
- Contract gaps found by stage 5 work: `typeMetadata` member category with a
  `compatibilityAlias` field for `ClrFullClassName`, and a `dependencySource` object on Value
  for dependency-property value source (section 6).
- Stale agent code: assemblies never unload, so re-attaching after a WinTestKit upgrade would
  have talked to the old agent. Hello now rejects a version mismatch.
- Configuration: the plan now matches the real layering (shared, local, CLI; `WTK_*`
  environment variables deliberately not extended) and the strict server `_PARAMS` table.
- Runtime order: .NET 8 leaves support on 2026-11-10, so the vertical slice is .NET 10 x64.
- The transient note about this checkout's uncommitted changes was replaced by a general rule.

Revision 2 added these improvements:

- Opt-in managed alias targets (`ClrFullClassName: "type:FullName"`) and an importer flag,
  so TestComplete-migrated suites use the real runtime type (section 10).
- `blockedByPolicy` handling, Authenticode-signed release payloads, and `wtk doctor` checks
  for security software and Smart App Control (section 3).
- Additive `redact_names`, extra built-in sensitive names, and visible redaction reasons.
- One tree traversal per locator batch and early failure when the deadline cannot cover
  the candidates (sections 7 and 10).
- Spy states for idle detach, policy blocks, and restart-required; one confirmation per
  process identity; install command for a missing payload; Repository Settings support;
  no managed data in element captures (sections 5, 9, 11).
- pytest report header/summary of attached processes and plain documentation of what a
  committed `attach: on-demand` authorizes (section 10).
- Fixtures with conflicting package versions, an explicit CI-versus-desktop test split, and
  skill/migration-guide updates (sections 12 and 13).
