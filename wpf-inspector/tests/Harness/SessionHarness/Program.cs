using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using WinTestKit.Inspector.Agent.Contracts;
using WinTestKit.Inspector.Agent.Session;
using WinTestKit.Inspector.Protocol;

if (args.Length != 2 || args[0] != "--fake") { Console.Error.WriteLine("Usage: SessionHarness --fake <bootstrap-path>"); return 2; }
try
{
    var deadline = DateTime.UtcNow.AddSeconds(10);
    while (!File.Exists(args[1]) && DateTime.UtcNow < deadline) await Task.Delay(20);
    var settings = BootstrapReader.Read(args[1]);
    using var host = new SessionHost(settings, new FakeFactory(settings.Process));
    host.Run();
    return host.State == SessionState.Faulted ? 1 : 0;
}
catch (Exception error) { Console.Error.WriteLine(error.GetType().Name); return 1; }

sealed class FakeFactory : IInspectionServiceFactory
{
    private readonly ProcessIdentity process;
    public FakeFactory(ProcessIdentity process) { this.process = process; }
    public IInspectionService Create(string sessionId) => new FakeService(process);
}

sealed class FakeService : IInspectionService
{
    private readonly ProcessIdentity process;
    public FakeService(ProcessIdentity process) { this.process = process; }
    public void Dispose() { }
    public Task<MappingDto> ResolveAsync(int[] runtimeId, long? nativeWindowHandle, CancellationToken ct) => Task.FromResult(new MappingDto { Status = MappingStatus.NotFound, Process = process, RuntimeId = runtimeId });
    public Task<ReadBatchResult> ReadBatchAsync(IReadOnlyList<CandidateRequest> candidates, IReadOnlyList<IReadOnlyList<PathSegment>> paths, CancellationToken ct) => Task.FromResult(new ReadBatchResult { Candidates = candidates.Select(candidate => new CandidateResult { RuntimeId = candidate.RuntimeId, Mapping = new MappingDto { Status = MappingStatus.NotFound, Process = process, RuntimeId = candidate.RuntimeId } }).ToArray() });
    public Task<PageDto<ManagedNodeDto>> RootsAsync(int? pageSize, string? pageToken, CancellationToken ct) => Task.FromResult(new PageDto<ManagedNodeDto> { Complete = true, SnapshotId = "fake" });
    public Task<PageDto<ManagedNodeDto>> ChildrenAsync(string objectId, long generation, string tree, int? pageSize, string? pageToken, CancellationToken ct) => RootsAsync(pageSize, pageToken, ct);
    public Task<PageDto<WinTestKit.Inspector.Protocol.MemberInfo>> MembersAsync(string objectId, long generation, int? pageSize, string? pageToken, CancellationToken ct) => Task.FromResult(new PageDto<WinTestKit.Inspector.Protocol.MemberInfo> { Complete = true, SnapshotId = "fake" });
    public Task<ReadResult> ReadAsync(string objectId, long generation, IReadOnlyList<IReadOnlyList<PathSegment>> paths, CancellationToken ct) => Task.FromResult(new ReadResult { ReadId = "fake" });
    public Task<IReadOnlyList<BindingInfoDto>> BindingsAsync(string objectId, long generation, IReadOnlyList<string> memberKeys, CancellationToken ct) => Task.FromResult<IReadOnlyList<BindingInfoDto>>(Array.Empty<BindingInfoDto>());
    public Task<int> ReleaseAsync(IReadOnlyList<string> objectIds, CancellationToken ct) => Task.FromResult(objectIds.Count);
}
