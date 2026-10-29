# WPF inspector: parallel implementation brief (wave 1)

This brief accompanies `docs/plans/wpf-dotnet-attribute-analyzer.md` (the *plan*, revision 2).
Thirteen implementation slices (S1–S12, with S4 split into S4a and S4b) initially ran
**in parallel, in one shared checkout**. The plan is
the specification; this brief pins the interfaces between slices so they fit together without
coordination. Where this brief and the plan disagree, this brief wins for names, file paths,
and signatures; the plan wins for behavior.

The owner deliberately overrode the plan's "sequential stages" rule for wave 1: every slice
builds its stage(s) now against the pinned interfaces. Gates that need another slice's output
(for example a real attach) are recorded as *deferred to integration*, not faked as passed.

## 1. Rules for every agent

1. Repository root: `C:\Users\massi\.t3\projects\wintestkit`. Read the whole plan and this whole
   brief before writing code.
2. **File ownership is exclusive.** Create or edit only paths in your slice's *Owns* list. You
   may read anything. If you need a change elsewhere, do not make it: list it under
   "Requests for other slices" in your final report. Never delete or rewrite another slice's
   files, even if they look broken or unfinished — they are being written right now.
3. The checkout contains the owner's own uncommitted work (for example in `server.py`,
   `schemas/rpc.schema.json`, `spyView.ts`, `generated.ts`). Preserve it: make additive edits.
4. **No state-changing git commands for slice subagents**: no `add`, `commit`, `stash`, `checkout`, `switch`,
   `reset`, `restore`, `clean`, `rebase`, `merge`, `push`. `git status`/`diff`/`log` are fine.
   The parent agent owns slice commits and pushes under the workflow below.
5. Python: always `uv run --frozen --directory python ...` (from the repo root). Never run
   `uv sync`, `uv lock`, `uv add`, or `pip install`. Do not edit `python/uv.lock`.
6. Node: never run `npm install`/`npm ci`, `npm run package`, or `npm run gen:types` (only S1
   runs `gen:types`). `npm --prefix vscode test -- <file>` and `typecheck`/`lint` are fine.
7. .NET: use `C:\Users\massi\AppData\Local\wintestkit-dev\dotnet\dotnet.exe` (SDK 10.0.400,
   runtimes Microsoft.NETCore.App 10.0.11, WindowsDesktop 10.0.11 and 8.0.33). In PowerShell set
   `$env:DOTNET_ROOT` to that folder and `$env:DOTNET_MULTILEVEL_LOOKUP = "0"` for the session.
   Never install SDKs, runtimes, workloads, or Visual Studio components. Restoring NuGet
   packages from nuget.org during build is allowed. net48 builds use the
   `Microsoft.NETFramework.ReferenceAssemblies` package. Native C++ builds use the installed
   Visual Studio 2022 Community 17.10 (MSVC 14.40) MSBuild:
   `C:\Program Files\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe`.
   Another agent may be building a referenced project at the same moment; if a build fails on a
   locked file, wait briefly and retry instead of deleting `obj/` folders you do not own.
8. Do not install anything machine-wide, change PATH, edit the registry, elevate, or touch
   processes you did not start. Kill every process you start (fixtures, harnesses) before you
   finish. Do not attach to or inject into any process except fixtures you launched yourself.
9. Do not edit the plan or this brief. Do not ask questions; choose the option most faithful
   to the plan, and record the decision under "Decisions" in your report.
10. Match the surrounding code style. Python: ruff (line length 100) and pyright strict must
    pass for files you touch. TypeScript: existing ESLint/tsc config. C#: nullable enabled,
    warnings as errors.
11. Never claim a test passed unless it ran. Mark mock-only coverage as mock-only.
12. Finish with a final report containing exactly these headings: **Files** (created /
    modified), **Commands run** (with pass/fail and test counts), **Plan coverage** (plan
    sections/stage gates done, partial, deferred), **Decisions**, **Deviations from the brief
    or plan**, **Requests for other slices**, **Open issues**.
13. **Slices are being retried after earlier partial runs.** Before writing, inspect the files
    your slice already owns: continue and fix them rather than starting over, and assume they
    contain defects. Finish the whole slice in one run. A missing dependency from another
    slice is never a reason to stop: implement against this brief, and if you need the other
    slice's code to compile, poll for it every few minutes for up to 90 minutes before
    reporting a blocker with the exact missing members.
14. Contract amendments after wave 1 started are marked "amended" in sections 3.3 and 3.7 and
    in plan sections 3 and 6. They override anything you wrote earlier.

### Commit and push workflow (owner instruction, 2026-10-29)

After the current S7 slice finishes, the parent agent must review and partition the existing
inspector work into separate commits for each slice, rather than one combined commit.
Preserve unrelated owner changes; use hunk-level staging where a file mixes slice work with
other changes. Generated build outputs, bootstrap files, tokens, and local configuration
must not be included. A committed partial slice remains partial; record its outstanding
gates rather than presenting the commit as proof of completion.

From that point onward, commit and push each slice when it is completed and validated,
before advancing to the next slice. Inspect the staged diff before each commit, use normal
non-force pushes to the configured remote, and report commit IDs, push results, and any
remaining gates. Git operations remain parent-owned so shared-checkout subagents do not
compete over the index or commit another slice's active edits.

## 2. Slices and ownership

| Slice | Scope (plan stages) | Owns |
| --- | --- | --- |
| S1 Contracts | Stage 0 | `wpf-inspector/protocol/**`, `wpf-inspector/tests/requirements.json`, `schemas/common.schema.json`, `schemas/rpc.schema.json`, `vscode/scripts/gen-types.mjs`, `vscode/src/protocol/generated.ts` (regenerate only), `python/tests/contract/test_managed_*.py` |
| S2 .NET skeleton + Protocol | Stage 1 build skeleton; stage 2 C# codec | `wpf-inspector/README.md`, `wpf-inspector/.gitignore`, `wpf-inspector/global.json`, `wpf-inspector/WinTestKit.Inspector.sln`, `wpf-inspector/Directory.Build.props`, `wpf-inspector/Directory.Packages.props`, `wpf-inspector/WinTestKit.Inspector.snk`, `wpf-inspector/src/Protocol/**`, `wpf-inspector/tests/Unit/Protocol.Tests/**` |
| S3 Agent session | Stage 2 agent side, stage 3 entry | `wpf-inspector/src/Agent/Agent.csproj`, `wpf-inspector/src/Agent/*.cs` (top level only), `wpf-inspector/src/Agent/Contracts/**`, `wpf-inspector/src/Agent/Session/**`, `wpf-inspector/tests/Unit/Agent.Session.Tests/**`, `wpf-inspector/tests/Harness/**` |
| S4a Agent tree + mapping | Stage 4 | `wpf-inspector/src/Agent/Inspection/*.cs` (top level only), `wpf-inspector/src/Agent/Mapping/**`, `wpf-inspector/tests/Unit/Agent.Mapping.Tests/**` |
| S4b Agent members + values | Stages 5–6 | `wpf-inspector/src/Agent/Inspection/Members/**`, `wpf-inspector/tests/Unit/Agent.Members.Tests/**` |
| S5 Snoop loader + build scripts | Stage 3 build, stage 10 scripts | `wpf-inspector/third_party/**`, `wpf-inspector/THIRD-PARTY-NOTICES.md`, `wpf-inspector/src/Launcher/**`, `scripts/build_inspector.ps1`, `scripts/check_inspector.ps1` |
| S6 Python client | Stage 7 client | `python/src/wintestkit/inspector/{__init__,client,transport,models,sessions,paths,probe,launcher,bootstrap,pipe}.py`, `python/src/wintestkit/errors.py` (additions only), `python/tests/unit/test_inspector_*.py` |
| S7 Python integration | Stage 7 server/config/CLI | `python/src/wintestkit/config.py`, `python/src/wintestkit/runtime.py`, `python/src/wintestkit/server.py`, `python/src/wintestkit/commands/inspect.py`, `python/src/wintestkit/pytest_plugin.py`, `python/src/wintestkit/doctor.py`, `python/tests/unit/test_managed_server*.py`, `python/tests/unit/test_inspector_config*.py`, `python/tests/unit/test_inspect_managed_cli*.py`, `python/tests/unit/test_doctor_inspector*.py`, `python/tests/unit/test_pytest_inspector*.py` |
| S8 Managed locators | Stage 8 | `python/src/wintestkit/engine/properties.py`, `python/src/wintestkit/engine/query.py`, `python/src/wintestkit/engine/locator.py`, `python/src/wintestkit/engine/managed.py` (new), `python/src/wintestkit/name_mapping.py`, `python/src/wintestkit/commands/import_namemapping.py`, `python/src/wintestkit/cli.py` (the import-namemapping flag only), `python/tests/unit/test_managed_locator*.py`, `python/tests/unit/test_name_mapping_managed*.py` |
| S9 Spy UX | Stage 9 | `vscode/src/spy/**`, `vscode/media/spy/**`, `vscode/src/settings/**`, `vscode/media/settings/**`, `vscode/package.json` (`contributes` only), `vscode/test/unit/spyManaged*.test.ts`, `vscode/test/unit/settingsInspector*.test.ts`, plus additive edits to `vscode/test/unit/spyView.test.ts` |
| S10 Fixtures | Stage 1 fixtures | `wpf-inspector/tests/Fixtures/**` |
| S11 Packaging + CI | Stage 10 packaging | `inspector-payload/**`, `python/pyproject.toml`, `python/src/wintestkit/inspector/payload.py`, `python/tests/unit/test_inspector_payload*.py`, `scripts/check_release.py`, `scripts/bump_version.py`, `.github/workflows/ci.yml`, root `.gitignore`, `docs/releasing.md` |
| S12 Docs + skill | Stage 12 docs | `docs/guide/**`, `docs/development.md`, `python/src/wintestkit/scaffold/skills/**`, `skills/**`, `vscode/CHANGELOG.md` (new Unreleased entry only), `vscode/README.md` (additive section only) |

## 3. Pinned names, paths, and wire contracts

### 3.1 Projects and assemblies

| Project path | Assembly / namespace | Targets |
| --- | --- | --- |
| `wpf-inspector/src/Protocol/Protocol.csproj` | `WinTestKit.Inspector.Protocol` | `netstandard2.0` |
| `wpf-inspector/src/Agent/Agent.csproj` | `WinTestKit.Inspector.Agent` | `net48;net8.0-windows;net10.0-windows`, `UseWPF` |
| `wpf-inspector/tests/Unit/Protocol.Tests/Protocol.Tests.csproj` | | `net10.0` |
| `wpf-inspector/tests/Unit/Agent.Session.Tests/...csproj` | | `net10.0-windows` |
| `wpf-inspector/tests/Unit/Agent.Mapping.Tests/...csproj` | | `net10.0-windows;net48` |
| `wpf-inspector/tests/Unit/Agent.Members.Tests/...csproj` | | `net10.0-windows;net48` |
| `wpf-inspector/tests/Fixtures/WpfFixture/WpfFixture.csproj` | `WinTestKit.Fixture` | `net48;net8.0-windows;net10.0-windows`, x86 and x64 |

Agent and Protocol are strong-named with `wpf-inspector/WinTestKit.Inspector.snk` (S2 creates
it) and have **no PackageReference** except `Microsoft.NETFramework.ReferenceAssemblies`
(build-only, `PrivateAssets=all`). Agent's assembly version comes from the `InspectorVersion`
MSBuild property, defaulting to the Python package version in
`python/src/wintestkit/__init__.py` (currently `0.1.1rc2`; map prereleases to a numeric
assembly version such as `0.1.1.0` and keep the full string in
`AssemblyInformationalVersion`). Test projects reference sources rather than the Agent project
when they need to avoid another slice's half-written files: S4a/S4b test projects use
`<Compile Include="..\..\..\src\Agent\Contracts\**\*.cs;...own folders...">` plus a
ProjectReference to Protocol, so their builds do not depend on S3's files.

`Directory.Packages.props` (S2) enables central package management with these exact pins:
`xunit 2.9.3`, `xunit.runner.visualstudio 3.1.4`, `Microsoft.NET.Test.Sdk 17.14.1`,
`Microsoft.NETFramework.ReferenceAssemblies 1.0.3`, and fixture-only conflict packages
`Newtonsoft.Json 13.0.3`, `System.Text.Json 8.0.5`, `System.Memory 4.5.5`. Projects needing
another package request it from S2 in their report (S2 cannot see the request in time, so
use `VersionOverride` locally and report it). `Directory.Build.props` (S2): `Nullable=enable`,
`LangVersion=latest`, `TreatWarningsAsErrors=true`, `Deterministic=true`,
`RestorePackagesWithLockFile=true`, `EnableWindowsTargeting=true`.

`WinTestKit.Inspector.sln` (S2) initially lists Protocol and Protocol.Tests only; the other
projects are added during integration.

### 3.2 Protocol library (S2 implements; S3/S4a/S4b consume)

Namespace `WinTestKit.Inspector.Protocol`. C# property names are the PascalCase form of the
JSON names in plan section 6; JSON keys are camelCase exactly as in the plan.

```csharp
public static class ProtocolInfo { public const int Major = 1; public const int Minor = 0; }

public static class ProtocolLimits {   // plan section 5 and 6, all values exact
    public const int MaxFrameBytes = 1048576, MaxJsonDepth = 32, AttachReadinessMs = 10000,
        RequestTimeoutMs = 2000, DispatcherQueueWaitMs = 500, TraversalSliceObjects = 200,
        TraversalSliceMs = 10, ScanMaxObjects = 10000, ScanMaxMs = 2000, DefaultPageSize = 100,
        MaxPageSize = 200, MaxBatchPaths = 32, MaxBatchCandidates = 32, MaxScalarChars = 4096,
        LeaseInactivityMs = 30000, MaxStrongHandles = 256, MaxWeakEntries = 10000,
        MaxPathSegments = 8, MaxPathBytes = 1024, MaxQueuedOps = 16, MaxActivePerSession = 4,
        MaxActivePerDispatcher = 1, MaxResponseBytes = 1048576, IdleSessionMs = 300000,
        PageTokenTtlMs = 30000, MaxSnapshots = 16, MaxBindingDepth = 8,
        MaxBindingEntries = 32, MaxBindingKeys = 32, MaxReleaseIds = 256,
        MaxIdentifierLength = 128, MaxKeyLength = 1024, BootstrapExpirySeconds = 30,
        MaxBootstrapBytes = 16384;
}

public static class ErrorCodes { /* one const string per plan section 6 code, value == name,
   e.g. public const string InvalidParams = "invalidParams"; includes BlockedByPolicy,
   AgentVersionMismatch */ }
public static class Features { public const string TypeMetadata = "typeMetadata", ClrMembers =
   "clrMembers", DependencyProperties = "dependencyProperties", Bindings = "bindings",
   ExactUiaMapping = "exactUiaMapping", BatchReads = "batchReads"; }
public static class PipeMethods { public const string Hello = "session.hello", Close =
   "session.close", Cancel = "request.cancel", Resolve = "element.resolve", ReadBatch =
   "element.readBatch", Roots = "roots", Children = "children", Members = "members",
   Read = "read", Bindings = "bindings", Release = "release"; }

public sealed class ProtocolException : Exception {
    public ProtocolException(string code, string message, JsonObjectNode? details = null);
    public string Code { get; } public JsonObjectNode? Details { get; } }

// Strict JSON: ordered objects, duplicate keys rejected, depth <= MaxJsonDepth,
// numbers kept as their exact source text, invalid UTF-8 rejected.
public abstract class JsonNode { }
public sealed class JsonObjectNode : JsonNode { IReadOnlyList<KeyValuePair<string, JsonNode>> Members; bool TryGet(string, out JsonNode); JsonNode Get(string); void Add(string, JsonNode); }
public sealed class JsonArrayNode : JsonNode { IReadOnlyList<JsonNode> Items; void Add(JsonNode); }
public sealed class JsonStringNode : JsonNode { string Value; }
public sealed class JsonNumberNode : JsonNode { string RawText; static JsonNumberNode From(long); static JsonNumberNode From(double); bool TryGetInt64(out long); }
public sealed class JsonBoolNode : JsonNode { bool Value; }
public sealed class JsonNullNode : JsonNode { static JsonNullNode Instance; }
public static class StrictJson {
    public static JsonNode Parse(byte[] utf8, int offset, int count);   // ProtocolException(invalidParams)
    public static byte[] Serialize(JsonNode node); }

public static class FrameCodec {   // 4-byte unsigned LE length + UTF-8 JSON
    public static Task<byte[]?> ReadFrameAsync(Stream s, CancellationToken ct); // null = clean EOF between frames
    public static Task WriteFrameAsync(Stream s, byte[] payload, CancellationToken ct); }
```

DTO classes, each `sealed` with `JsonObjectNode ToJson()` and
`static T FromJson(JsonNode node)` that enforces required/optional/unknown-field rules and
string bounds: `ProcessIdentity`, `SessionInfo`, `TypeInfoDto`, `ObjectRef`, `MemberInfo`,
`AttributeInfo`, `ValueDto`, `Diagnostic`, `PageDto<T>` (with a `Func<JsonNode,T>` reader),
`MappingDto`, `ManagedNodeDto`, `BindingInfoDto`, `PathSegment`, `PathValue` (`Path`,
`Value`), `ReadResult` (`Values`, `ReadId`), `CandidateResult` (`RuntimeId`, `Mapping`,
`Values`), `ReadBatchResult` (`Candidates`), `HelloParams`, `HelloResult`,
`RequestEnvelope` (`Id` long, `Method`, `Params` JsonObjectNode), `ResponseEnvelope`
(`Id`, `Result` or `Error` = `ErrorInfo{Code,Message,Details}`), `BootstrapSettings`.
`ValueDto.Kind`/`Status`, `MemberInfo.Category`/`Visibility`/`Reason`, mapping status, and
binding kind are `string` properties validated against the closed sets in the plan, with
`public static class ValueStatus { const string Ok = "ok", ... }`-style constant classes.

### 3.3 Wire shapes not spelled out in the plan

* Pipe `session.hello` params: `{protocolMajor, protocolMinor, sessionId, token, process}`;
  result: `{agentVersion, tfm, architecture, runtimeVersion, features, process}` where `tfm`
  is `net48`, `net8.0-windows`, or `net10.0-windows` and `architecture` is `x86`/`x64`.
* Pipe `element.resolve` params: `{runtimeId: int[], nativeWindowHandle?: integer}`; result:
  Mapping. `nativeWindowHandle` is sent only when the UIA element is its HWND's own element.
* Pipe `element.readBatch` params: `{candidates: [{runtimeId: int[], nativeWindowHandle?}]
  (1..32), paths: PathSegment[][] (1..32)}`; result `{candidates: [{runtimeId, mapping,
  values: [{path, value}]}]}` in input order; `values` is empty unless mapping is `exact`.
* Pipe `roots`/`children`/`members`/`read`/`bindings`/`release` params equal the public RPC
  params of plan section 6 minus nothing (they include `sessionId`). `request.cancel`:
  `{requestId}` → `{accepted}`. `session.close`: `{}` → `{closed: true}`.
* `PathSegment` JSON: property/field `{kind, name, declaringType?, memberKey?}`;
  dependency `{kind:"dependency", ownerType, ownerAssembly, name}`; type `{kind:"type", name}`
  where name is one of `Name`, `FullName`, `AssemblyName`, `AssemblyQualifiedName`,
  `BaseTypes`.
* `ValueDto` extra optional fields (plan section 9): `numericValue`, `typeInfo`, `arrayRank`,
  `arrayLength`, `failedSegment`, `redactionRule` (the matched sensitive-name substring or
  `identity`), `dependencySource` (`{baseValueSource, isExpression, isAnimated, isCoerced,
  isCurrent}`, C# `DependencySourceDto`, Python `DependencySource`).
* `MemberInfo` extras (plan section 6, amended): category `typeMetadata` (constant
  `MemberCategory.TypeMetadata`) for the five `type:*` rows, and optional `compatibilityAlias`
  (string; `ClrFullClassName` on the `type:FullName` row).
* Bootstrap settings file (UTF-8 JSON, written by Python, read by the agent, deleted by the
  agent after reading): `{schemaVersion: 1, protocolMajor, protocolMinor, sessionId (UUID),
  process: {pid, creationTimeUtc}, pipeName, token (base64 of 32 random bytes), clientSid,
  expiresUtc (RFC3339), requestTimeoutMs, idleTimeoutMs, agentVersion}`. Unknown keys reject.
  Directory: `%LOCALAPPDATA%\WinTestKit\inspector\bootstrap\<sessionId>\` (user-only ACL), file
  name `<32 random hex chars>.json`.
* Pipe name: `WinTestKit.Inspector.<pid>.<sessionId>`; agent mutex name:
  `Local\WinTestKit.Inspector.Agent.<pid>`.
* Golden fixtures (S1): `wpf-inspector/protocol/fixtures/valid/<name>.json` and
  `.../invalid/<name>.json`. Each file is `{"schema": "<definition name>", "instance": ...}`.
  Both the C# and Python parsers must accept every valid fixture and reject every invalid one.

### 3.4 Agent internal contracts (S3 creates these files verbatim; S4a/S4b create them verbatim too if absent; nobody edits them)

`wpf-inspector/src/Agent/Contracts/IInspectionService.cs`:

```csharp
using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Contracts
{
    /// <summary>Everything the session layer asks of WPF. Implementations throw ProtocolException.</summary>
    public interface IInspectionService : IDisposable
    {
        Task<MappingDto> ResolveAsync(int[] runtimeId, long? nativeWindowHandle, CancellationToken ct);
        Task<ReadBatchResult> ReadBatchAsync(IReadOnlyList<CandidateRequest> candidates, IReadOnlyList<IReadOnlyList<PathSegment>> paths, CancellationToken ct);
        Task<PageDto<ManagedNodeDto>> RootsAsync(int? pageSize, string? pageToken, CancellationToken ct);
        Task<PageDto<ManagedNodeDto>> ChildrenAsync(string objectId, long generation, string tree, int? pageSize, string? pageToken, CancellationToken ct);
        Task<PageDto<MemberInfo>> MembersAsync(string objectId, long generation, int? pageSize, string? pageToken, CancellationToken ct);
        Task<ReadResult> ReadAsync(string objectId, long generation, IReadOnlyList<IReadOnlyList<PathSegment>> paths, CancellationToken ct);
        Task<IReadOnlyList<BindingInfoDto>> BindingsAsync(string objectId, long generation, IReadOnlyList<string> memberKeys, CancellationToken ct);
        Task<int> ReleaseAsync(IReadOnlyList<string> objectIds, CancellationToken ct);
    }

    public sealed class CandidateRequest
    {
        public CandidateRequest(int[] runtimeId, long? nativeWindowHandle) { RuntimeId = runtimeId; NativeWindowHandle = nativeWindowHandle; }
        public int[] RuntimeId { get; }
        public long? NativeWindowHandle { get; }
    }

    public interface IInspectionServiceFactory
    {
        IInspectionService Create(string sessionId);
    }
}
```

`wpf-inspector/src/Agent/Contracts/IObjectInspector.cs`:

```csharp
using System;
using System.Collections.Generic;
using System.Threading;
using System.Windows.Threading;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Contracts
{
    /// <summary>Handle registry owned by S4a. Thread-safe.</summary>
    public interface IObjectRegistry
    {
        /// <summary>Returns the existing handle for the same reference, or registers a new one.</summary>
        ObjectRef Register(object target, Dispatcher traversalDispatcher, TypeInfoDto type);
        /// <summary>False means objectStale (unknown, released, collected, or wrong generation).</summary>
        bool TryGet(string objectId, long generation, out object target, out Dispatcher dispatcher);
        int Release(IEnumerable<string> objectIds);
    }

    /// <summary>Member discovery and value reading owned by S4b. Every call runs on the object's Dispatcher thread.</summary>
    public interface IObjectInspector
    {
        TypeInfoDto DescribeType(Type type);
        /// <summary>Complete, sorted catalog. Never evaluates getters. Adds diagnostics for partial failures.</summary>
        IReadOnlyList<MemberInfo> GetMembers(object target, List<Diagnostic> diagnostics);
        ValueDto ReadPath(object root, IReadOnlyList<PathSegment> path, IObjectRegistry registry, Dispatcher dispatcher, CancellationToken ct);
        IReadOnlyList<BindingInfoDto> GetBindings(object target, IReadOnlyList<string> memberKeys);
    }
}
```

Class names other slices instantiate:
`WinTestKit.Inspector.Agent.Inspection.WpfInspectionServiceFactory` (S4a; parameterless
constructor; it constructs `new WinTestKit.Inspector.Agent.Inspection.Members.ObjectInspector()`
from S4b), `WinTestKit.Inspector.Agent.EntryPoint` with
`public static int Start(string settingsFile)` (S3).

### 3.5 Python API (S6 implements; S7, S8, S11 consume)

```python
# wintestkit/errors.py (S6 adds; all subclass WtkError)
class InspectorError(WtkError):            # .code: str (plan section 6 error code)
    def __init__(self, message: str, *, code: str) -> None: ...
class InspectorUnavailableError(InspectorError): ...   # disabled, payloadMissing, unsupportedTarget, blockedByPolicy, attachFailed ...
class InspectorMappingError(InspectorError): ...       # mapping statuses other than exact
class InspectorReadError(InspectorError): ...          # unusable values in locators
class InspectorLimitError(InspectorError): ...         # limitExceeded, busy, candidate cap

# wintestkit/inspector/models.py — frozen dataclasses, snake_case fields, from_json(dict) strict
ProcessIdentity(pid: int, creation_time_utc: str)
ProcessFacts(identity, executable: str, architecture: Literal["x86","x64","arm64","unknown"],
             runtime: Literal["net48","net8","net10"] | None, wpf_loaded: bool,
             session_id: int, user_sid: str, integrity: str)
Session(session_id, process, state, protocol_major, protocol_minor, features: tuple[str, ...],
        runtime_version: str | None, architecture: str | None, agent_version: str | None,
        error: str | None)
TypeInfo, ObjectRef, Member, AttributeInfo, Diagnostic, Mapping, ManagedNode, BindingInfo,
Page[T](items: tuple[T, ...], complete: bool, snapshot_id: str, diagnostics, next_token)
Value(status, kind, declared_type, runtime_type, scalar: object = MISSING, object_ref=None,
      message=None, truncated_at=None, cycle_to=None, numeric_value: str | None = None,
      type_info=None, array_rank=None, array_length=None, failed_segment=None,
      redaction_rule=None)     # MISSING is a module-level sentinel distinct from None (JSON null)
PathValue(path: tuple[PathSegment, ...], value: Value)
CandidateResult(runtime_id: tuple[int, ...], mapping: Mapping, values: tuple[PathValue, ...])

# wintestkit/inspector/paths.py
MANAGED_PREFIXES = ("type:", "clr:", "field:", "dp:")
@dataclass(frozen=True) class PathSegment: kind: Literal["property","field","dependency","type"];
    name: str; declaring_type: str | None = None; member_key: str | None = None;
    owner_type: str | None = None; owner_assembly: str | None = None
    def to_json(self) -> dict[str, object]
@dataclass(frozen=True) class ManagedPath: canonical: str; segments: tuple[PathSegment, ...]
def is_managed_key(key: str) -> bool
def parse_managed_key(key: str) -> ManagedPath     # raises InvalidLocatorError with a clear message

# wintestkit/inspector/client.py
class InspectorClient:   # one authenticated session; all methods take a monotonic deadline (time.monotonic() based)
    session: Session
    def resolve(self, runtime_id: tuple[int, ...], native_window_handle: int | None, *, deadline: float) -> Mapping
    def read_batch(self, candidates: Sequence[tuple[tuple[int, ...], int | None]], paths: Sequence[ManagedPath], *, deadline: float) -> list[CandidateResult]
    def roots(self, *, page_size: int | None = None, page_token: str | None = None, deadline: float) -> Page[ManagedNode]
    def children(self, object_id: str, generation: int, tree: Literal["visual","logical"], *, page_size=None, page_token=None, deadline: float) -> Page[ManagedNode]
    def members(self, object_id: str, generation: int, *, page_size=None, page_token=None, deadline: float) -> Page[Member]
    def read(self, object_id: str, generation: int, paths: Sequence[Sequence[PathSegment]], *, deadline: float) -> tuple[tuple[PathValue, ...], str]
    def bindings(self, object_id: str, generation: int, member_keys: Sequence[str], *, deadline: float) -> tuple[BindingInfo, ...]
    def release(self, object_ids: Sequence[str], *, deadline: float) -> int
    def close(self) -> None

# wintestkit/inspector/probe.py
def identify(pid: int) -> ProcessFacts                      # never loads code into the target
def current_identity(pid: int) -> ProcessIdentity           # raises InspectorUnavailableError(processExited)

# wintestkit/inspector/sessions.py
class SessionRegistry:   # one per runtime context; thread-safe; concurrent attaches to one identity share one attempt
    def __init__(self, payload_loader: Callable[[], Payload] = load_payload) -> None
    def attach(self, identity: ProcessIdentity, *, target_hwnd: int | None, deadline: float) -> InspectorClient
    def get(self, identity: ProcessIdentity) -> InspectorClient | None
    def status(self, identity: ProcessIdentity) -> Session          # detached Session if none
    def detach(self, session_id: str) -> None
    def close_all(self) -> None

# wintestkit/inspector/payload.py (S11)
@dataclass(frozen=True) class Payload:
    root: Path; manifest: Mapping[str, Any]; inspector_version: str; signed: bool
    def launcher_for(self, architecture: Literal["x86","x64"]) -> Path
    def agent_for(self, runtime: Literal["net48","net8","net10"]) -> Path
    def verify(self) -> None        # re-hashes every manifest file; InspectorUnavailableError(payloadMismatch)
def load_payload() -> Payload       # InspectorUnavailableError(payloadMissing | payloadMismatch)
def payload_status() -> dict[str, object]   # for wtk doctor: installed, version, matches, signed, controller_architecture
```

`load_payload` finds the payload through `importlib.resources.files("wintestkit_inspector") /
"payload"`. Until S11 lands, S6 imports it lazily inside `SessionRegistry` so that
`import wintestkit.inspector` never fails.

### 3.6 Payload layout and manifest (S5 produces, S11 packages, S11 `payload.py` reads)

```
inspector-payload/src/wintestkit_inspector/payload/      # generated, git-ignored
  manifest.json
  launcher/x64/...   launcher/x86/...                    # upstream Snoop launcher + native libs, per arch
  agent/net48/WinTestKit.Inspector.Agent.dll (+ Protocol dll)
  agent/net8.0-windows/...   agent/net10.0-windows/...
  notices/THIRD-PARTY-NOTICES.md, notices/snoop-License.txt
```

`manifest.json`: `{"schemaVersion": 1, "inspectorVersion", "protocolMajor": 1,
"protocolMinor": 0, "sourceCommit", "upstreamCommit":
"2bf48f60c2bb1753001f6be9122395def9070fa9", "signed": bool, "cells": [{"runtime": "net10",
"architecture": "x64", "verified": bool}, ...six cells], "launchers": {"x64": "<rel path>",
"x86": "<rel path>"}, "agents": {"net48": "<rel>", "net8": "<rel>", "net10": "<rel>"},
"files": [{"path": "<rel, forward slashes>", "sha256": "<lowercase hex>"}],
"notices": ["notices/THIRD-PARTY-NOTICES.md", ...]}`. Paths are relative to `payload/`.

### 3.7 Launcher invocation (S6 implements; S5 verifies against upstream and reports any difference)

Argument array (no shell): `[<launcher exe>, "--targetPID", "<pid>", "--assembly",
"<absolute agent dll>", "--className", "WinTestKit.Inspector.Agent.EntryPoint",
"--methodName", "Start", "--settingsFile", "<absolute bootstrap file>"]`, hidden window,
working directory = the launcher's directory, no inherited handles. Launcher architecture =
target architecture; agent = target runtime. Amended after S5's source review
(`wpf-inspector/third_party/snoop-loader-notes.md`): no `--targetHwnd`; the loader uses
`CreateRemoteThread`, so `EntryPoint.Start` runs on a loader thread, not a UI thread; the exit
code is not trustworthy, so readiness is only the authenticated handshake. Python keeps the
`target_hwnd` parameter of `SessionRegistry.attach` for compatibility but does not pass it to
the launcher.

### 3.8 Public RPC (S1 schemas, S7 server, S9 Spy)

Methods exactly as plan section 6 plus `inspect.managed.identify {nodeId}`. `process`
parameters are `{pid, creationTimeUtc}`. `initialize` result gains
`capabilities.managedInspector: boolean` (true only when the payload is installed and loads).
S9 must not import generated types for these until integration; define matching interfaces in
`vscode/src/spy/managedTypes.ts`.

### 3.9 Configuration keys (S7)

`inspector.enabled` (bool, false), `inspector.attach` (`manual` | `on-demand`, `manual`),
`inspector.attach_timeout` (float, 0 < x <= 10, 10.0), `inspector.request_timeout` (float,
0 < x <= 2, 2.0), `inspector.redact_names` (list of nonempty str, []). `WtkConfig.inspector:
InspectorConfig`. S8 reads `get_config().inspector`. Managed alias targets in
`property_aliases` are validated by S7 in `config.py` with `wintestkit.inspector.paths.
parse_managed_key`; S8 turns them into managed conditions.

### 3.10 Server-side helpers for locators (S7 provides in `runtime.py`; S8 consumes)

```python
def inspector_sessions() -> SessionRegistry                 # lazily created, closed by reset()/shutdown
def managed_client_for(pid: int, *, deadline: float, target_hwnd: int | None) -> InspectorClient
    # Applies inspector config: disabled -> InspectorUnavailableError(code="notAttached") with an
    # actionable "set inspector.enabled" message; manual + not attached -> InspectorUnavailableError
    # (code="notAttached"); on-demand -> attaches within the deadline (once; failures are cached
    # for this identity until explicit attach so polling never re-injects).
```

### S4b-3 implementation progress (2026-10-29)

Binding metadata reads use WPF binding definitions and expression status without updating targets or sources. Single, multi, and priority bindings, sensitive path omission, relative source metadata, and validation error type names are covered by strict JSON round trips and converter counters. The service continues other paths after a throwing getter. The session advertises `exactUiaMapping` only when the inspection service reports it available.

Verification: member tests passed 71 on each of net10.0-windows and net48; session tests passed 47 with one pre-existing dedicated-account skip; mapping tests passed 82 on each of net10.0-windows and net48; Agent build passed all configured targets. The validation test exposed a zero ancestor level for `RelativeSource Self`; this is now omitted, preserving the strict protocol.

Slow/hanging getter and stuck UI thread integration tests remain deferred to the S10 owned fixture processes. The current unit results do not establish that integration gate or claim that a timed-out getter is stopped.

### S10 fixture progress (2026-10-29)

The shared fixture now builds and publishes all six framework/architecture cells. It includes independent control types and a test-only pipe with counters, dynamic tree and DataContext scenarios, and releasable slow/hanging getter and blocked-dispatcher controls. A validation binding startup crash was corrected. On Windows 10.0.26200, independent UIA runs found the fixture window and control in net48 x86/x64, net8 x86/x64, and net10 x64 (some control lookups were intermittent). SHA-256 hashes were printed before inspection. Net10 x86 did not start: the machine has no x86 .NET 10 runtime. An owned net10 x64 process reported dispatcher.blocked and dispatcher.released after pipe release. This is fixture-control evidence, not injection or inspector timeout evidence. Stage 1 remains partial: repeat reliable UIA smoke and complete the missing runtime cell; integration timeout, isolation, attachment, and matrix gates require S5 and subsequent integration.

### S5 verification status (2026-10-29)

The locked build verifies all 34 pinned Snoop files and applies the reviewed launcher patch only to an artifacts copy. It builds the matching x86/x64 native injectors and launchers, the normal Protocol and Agent projects, and a separately locked `BundledAgent.csproj`. The bundle compiles the existing Agent and Protocol sources into one strong-named Agent DLL per TFM. This is needed because the first real .NET 10 injection could not resolve the adjacent standalone Protocol DLL in the target's default load context; that owned fixture exited before hello. The bundle does not install into the target directory or add a process-wide resolver.

The locked Release and Debug builds each staged a 14-file unsigned development payload and passed `-Suite Package`; the final staging is Release. The manifest is under `inspector-payload/src/wintestkit_inspector/payload/` and all six compatibility cells are explicitly unverified. Package checks cover exact inventory and hashes, the 34 source hashes, source-matching notices including Snoop and CommandLineParser licenses, launcher/native PE architecture and export, the launcher configuration, Agent TFM/version/strong-name signature and dependency allowlist, entry points, and no-argument loader probes. The Python payload consumer also accepted and verified the manifest. Ten isolated negative cases rejected a tampered DLL, missing DLL, traversal path, version drift, duplicate JSON key, unlisted UI file, rehashed wrong-architecture native DLL, rehashed wrong-TFM Agent, modified native export, and unsafe launcher configuration. A rehashed changed notice and `-RequireSigned` against the unsigned development payload were also rejected. Authenticode signing with a real certificate has not been exercised. Third-party inventory owner approval remains a publication gate.

The `OwnedAttach` harness starts the published fixture without startup arguments and terminates only its own fixture and launcher. It verifies the user-only bootstrap directory/file ACLs, reparse points, one-use deletion, server PID and exact creation time before sending a random token; it accepts readiness only after the authenticated hello reports matching version, process, TFM, runtime major and architecture. The following **partial integration checks**, not full matrix gates, passed with Agent version `0.1.1rc2`: net10 x64 (runtime 10.0.11), net8 x64 (8.0.20), net8 x86 (8.0.6), net48 x64 and net48 x86 (4.0.30319.42000). Each completed hello, WPF roots/type read, session.close and a post-detach fixture-dispatcher operation, with pre-start, post-start and post-attach fixture file hashes unchanged. The .NET 10 x64 run returned from a hanging getter in about two seconds, rejected another read on that dispatcher, read the second dispatcher, observed one getter call, and released the fixture. A wrong-token hello was rejected with no response. The Agent session unit suite passed 47 tests and skipped its one dedicated-account case. These results do not claim that running application code was cancelled.

The fixtures execute Newtonsoft.Json and System.Text.Json before opening their control pipe and use System.Text.Json for control responses after inspection. On CoreCLR, the loaded conflict modules were visible before and after. For Framework, the fixture's pinned Newtonsoft.Json 13.0.3, System.Text.Json 8.0.5 and System.Memory 4.5.5 files and configuration remained unchanged and the JSON control pipe still worked; Windows native module enumeration did not expose the managed assemblies, and no post-attach Newtonsoft operation was requested. A dedicated post-attach Newtonsoft/System.Memory operation remains a compatibility gate.

Net10 x86 cannot start here because the x86 .NET 10 core and WindowsDesktop runtimes are absent; no runtime was installed. Stage 1/S10 remains partial, including intermittent independent UIA smoke. Stage 3 remains partial: duplicate/reattach and version-mismatch behavior, target exit, PID reuse, denied integrity, non-WPF and policy-block cases, 100-cycle attach/detach, and independent post-detach UIA interaction remain unverified. Wrong-user/session security, full slow-getter/dispatcher scenarios and the complete matrix remain open. Wheel/sdist validation, signed release artifacts, clean-environment install/CLI/extension tests, CI and release packaging are outside this S5 work. The manifest must not mark a cell verified until its full gate passes.

### S6 Python client verification (2026-10-29)

The Python client now implements strict framing and typed DTOs, matching-bitness hidden
launcher invocation, process-bound pipe verification before token transmission, private
one-use bootstrap creation and cleanup, authenticated readiness, bounded concurrent requests,
late-response discard/cancellation, feature checks, and runtime-owned session management.
The interrupted runs were continued directly on the primary Codex agent, without switching
to Carol's account or changing the primary model.

Fresh validation: all eight `python/tests/unit/test_inspector_*.py` files passed **222 tests**
with `WTK_INSPECTOR_REAL=1`, using `uv run --frozen --directory python pytest` with their
explicit paths. This includes three real .NET 10 x64 owned-fixture cases: attach/read/member
enumeration/detach, duplicate attachment rejection, reattach with a new session ID, target
exit, wrong-token rejection, and client-side hello agent-version mismatch rejection.
Fixture executable/DLL/configuration hashes remained unchanged; the fixture control pipe
worked after detach and rejected hello sessions. Harnesses terminated only their own fixture
processes. This is not the full six-cell compatibility or 100-cycle stress gate, and a
client-side hello version check does not prove incompatible preloaded-agent handling.

The new target-exit check exposed pipe EOF preceding the process becoming signaled. Registry
status now revalidates disconnected identities so a terminal `sessionStale` can become
`processExited` or `processReused`, without attempting another injection. Shutdown regression
tests also cover cancellation racing with I/O submission and authenticated-client cleanup
when launcher or bootstrap cleanup fails. Real overlapped pipe tests prove timeout
cancellation, subsequent pipe usability, and prompt close of a pending read.

Ruff and strict Pyright pass for the S6 source files, additive inspector errors, and the S6
test lint scope. The existing S11 `payload.py` is unchanged: checking the whole inspector
directory additionally reports its seven lint violations and eleven Pyright errors, carried
forward to S11. A broader `uv run --frozen --directory python pytest tests/unit tests/contract
-q` run before the final added regressions produced **1792 passed, 3 skipped, 3 failed**.
The failures are the S7 doctor check-list expectation, missing traceback hiding in S7 runtime
helpers, and missing traceback hiding in S8 query helpers. These remain assigned to their
integration slices rather than being silently repaired during S6.

S6's client slice is verified on the available vertical slice. Full stage 7 remains open
until S7 server/config/CLI integration passes; S5/S10 security, stress, matrix and independent
UIA gates, the absent .NET 10 x86 runtime, and unsigned-development-payload release gates
remain open. No compatibility manifest cell was promoted to verified.

### S7 Python integration progress (2026-10-29)

The S7 server, configuration, runtime, CLI, doctor, and pytest integration now implement the
public managed operations and lifecycle. Focused unit/contract checks passed 436 tests, and
223 S6/S7 tests passed with real-fixture validation enabled: the S7 case exercised actual
.NET 10 x64 UIA mapping, all eleven RPCs including one dependency-property binding metadata
request, built-in password redaction without a getter call, and a separate standalone CLI
attach/read/detach. The broader Python run passed 1863,
skipped 5, and failed only the existing S8 `engine/query.py` traceback-hiding check.

Stage 7 remains partial: the bootstrap/agent factory does not transmit configured extra
redaction names, so S7 refuses managed attachment when they are configured. Agent/protocol
integration and real configured-name redaction evidence are required; signature, security, stress, matrix,
independent-UIA and release gates remain open. No manifest cell was promoted to verified.
Repeated single-page tree requests also exhausted the agent's 16 retained snapshots before
their 30-second expiry; S4a needs to assess reclaiming snapshots with no continuation token.
