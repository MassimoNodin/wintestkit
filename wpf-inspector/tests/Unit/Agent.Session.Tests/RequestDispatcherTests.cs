using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using WinTestKit.Inspector.Agent.Contracts;
using WinTestKit.Inspector.Agent.Session;
using WinTestKit.Inspector.Protocol;
using Xunit;

namespace WinTestKit.Inspector.Agent.Session.Tests;

[Trait("Category", "Unit")]
public class RequestDispatcherTests
{
    private const string Session = "session";
    private static readonly IReadOnlyList<IReadOnlyList<PathSegment>> Paths = new[] { new[] { new PathSegment { Kind = SegmentKind.Type, Name = "Name" } } };
    private static Task<ResponseEnvelope> Dispatch(RequestDispatcher dispatcher, string method, JsonObjectNode parameters) => dispatcher.HandleAsync(new RequestEnvelope { Id = 42, Method = method, Params = parameters }, CancellationToken.None);

    [Fact]
    public async Task RoutesAllMethodsAndConvertsArguments()
    {
        var service = new RecordingService();
        var dispatcher = new RequestDispatcher(Session, service);
        var response = await Dispatch(dispatcher, PipeMethods.Resolve, new ResolveParams { RuntimeId = new[] { 3, 4 }, NativeWindowHandle = 99 }.ToJson());
        Assert.Equal(42, response.Id); Assert.Null(response.Error); Assert.Equal(MappingStatus.NotFound, MappingDto.FromJson(response.Result!).Status);
        Assert.Equal("resolve:3,4:99", service.Call);
        response = await Dispatch(dispatcher, PipeMethods.ReadBatch, new ReadBatchParams { Candidates = new[] { new CandidateRequestDto { RuntimeId = new[] { 3, 4 }, NativeWindowHandle = 99 } }, Paths = Paths }.ToJson());
        Assert.Single(ReadBatchResult.FromJson(response.Result!).Candidates); Assert.Equal("batch:3,4:99:Name", service.Call);
        response = await Dispatch(dispatcher, PipeMethods.Roots, new RootsParams { SessionId = Session, PageSize = 7, PageToken = "token" }.ToJson());
        Assert.True(PageDto<ManagedNodeDto>.FromJson(response.Result!, ManagedNodeDto.FromJson).Complete); Assert.Equal("roots:7:token", service.Call);
        response = await Dispatch(dispatcher, PipeMethods.Children, new ChildrenParams { SessionId = Session, ObjectId = "object", Generation = 2, Tree = "visual", PageSize = 7, PageToken = "token" }.ToJson());
        Assert.True(PageDto<ManagedNodeDto>.FromJson(response.Result!, ManagedNodeDto.FromJson).Complete); Assert.Equal("children:object:2:visual:7:token", service.Call);
        response = await Dispatch(dispatcher, PipeMethods.Members, new MembersParams { SessionId = Session, ObjectId = "object", Generation = 2, PageSize = 7, PageToken = "token" }.ToJson());
        Assert.True(PageDto<WinTestKit.Inspector.Protocol.MemberInfo>.FromJson(response.Result!, WinTestKit.Inspector.Protocol.MemberInfo.FromJson).Complete); Assert.Equal("members:object:2:7:token", service.Call);
        response = await Dispatch(dispatcher, PipeMethods.Read, new ReadParams { SessionId = Session, ObjectId = "object", Generation = 2, Paths = Paths }.ToJson());
        Assert.Empty(ReadResult.FromJson(response.Result!).Values); Assert.Equal("read:object:2:Name", service.Call);
        response = await Dispatch(dispatcher, PipeMethods.Bindings, new BindingsParams { SessionId = Session, ObjectId = "object", Generation = 2, MemberKeys = new[] { "key" } }.ToJson());
        Assert.Empty(BindingsResult.FromJson(response.Result!).Bindings); Assert.Equal("bindings:object:2:key", service.Call);
        response = await Dispatch(dispatcher, PipeMethods.Release, new ReleaseParams { SessionId = Session, ObjectIds = new[] { "object" } }.ToJson());
        Assert.Equal(1, ReleaseResult.FromJson(response.Result!).ReleasedCount); Assert.Equal("release:object", service.Call);
        response = await Dispatch(dispatcher, PipeMethods.Close, new CloseParams().ToJson());
        Assert.True(CloseResult.FromJson(response.Result!).Closed);
    }

    [Theory]
    [InlineData(PipeMethods.Resolve)][InlineData(PipeMethods.ReadBatch)][InlineData(PipeMethods.Roots)][InlineData(PipeMethods.Children)]
    [InlineData(PipeMethods.Members)][InlineData(PipeMethods.Read)][InlineData(PipeMethods.Bindings)][InlineData(PipeMethods.Release)][InlineData(PipeMethods.Close)]
    public async Task RejectsMalformedParams(string method)
    {
        var parameters = new JsonObjectNode(); parameters.Add("unexpected", new JsonStringNode("secret"));
        var service = new RecordingService();
        var response = await Dispatch(new RequestDispatcher(Session, service), method, parameters);
        Assert.Equal(ErrorCodes.InvalidParams, response.Error!.Code); Assert.Null(service.Call);
    }

    [Fact]
    public async Task UnknownMethodAndSessionMismatchAreRejected()
    {
        var dispatcher = new RequestDispatcher(Session, new RecordingService());
        Assert.Equal(ErrorCodes.InvalidParams, (await Dispatch(dispatcher, "unknown", new JsonObjectNode())).Error!.Code);
        Assert.Equal(ErrorCodes.SessionStale, (await Dispatch(dispatcher, PipeMethods.Roots, new RootsParams { SessionId = "other" }.ToJson())).Error!.Code);
    }

    [Theory]
    [InlineData(true)][InlineData(false)]
    public async Task ExceptionsAreSanitized(bool protocol)
    {
        var service = new RecordingService { Error = protocol ? new ProtocolException(ErrorCodes.ObjectStale, "secret path value") : new Exception("secret path value") };
        var response = await Dispatch(new RequestDispatcher(Session, service), PipeMethods.Roots, new RootsParams { SessionId = Session }.ToJson());
        Assert.Equal(protocol ? ErrorCodes.ObjectStale : ErrorCodes.InternalError, response.Error!.Code);
        Assert.Equal("Request failed.", response.Error.Message); Assert.Null(response.Error.Details);
        Assert.DoesNotContain("secret", System.Text.Encoding.UTF8.GetString(StrictJson.Serialize(response.ToJson())));
    }

    [Fact]
    public async Task CancelBypassesQueueAndReportsKnownAndUnknownIds()
    {
        using var scheduler = new RequestScheduler(2000);
        var release = new TaskCompletionSource<JsonNode>(TaskCreationOptions.RunContinuationsAsynchronously);
        var request = scheduler.ExecuteAsync(new RequestEnvelope { Id = 1 }, _ => release.Task, default);
        var dispatcher = new RequestDispatcher(Session, new RecordingService(), scheduler);
        var response = await dispatcher.HandleAsync(new RequestEnvelope { Id = 2, Method = PipeMethods.Cancel, Params = new CancelParams { RequestId = 1 }.ToJson() }, default);
        Assert.True(CancelResult.FromJson(response.Result!).Accepted);
        Assert.Equal(ErrorCodes.Cancelled, (await Assert.ThrowsAsync<ProtocolException>(async () => await request)).Code);
        response = await dispatcher.HandleAsync(new RequestEnvelope { Id = 3, Method = PipeMethods.Cancel, Params = new CancelParams { RequestId = 1 }.ToJson() }, default);
        Assert.False(CancelResult.FromJson(response.Result!).Accepted);
        release.SetResult(JsonNullNode.Instance);
    }

    private sealed class RecordingService : IInspectionService
    {
        public string? Call { get; private set; }
        public Exception? Error { get; set; }
        public void Dispose() { }
        private static MappingDto Mapping(int[] id) => new() { Status = MappingStatus.NotFound, RuntimeId = id, Process = new ProcessIdentity { Pid = 1, CreationTimeUtc = "2026-01-01T00:00:00Z" } };
        private static PageDto<T> Page<T>() => new() { Complete = true, SnapshotId = "snapshot" };
        public Task<MappingDto> ResolveAsync(int[] runtimeId, long? nativeWindowHandle, CancellationToken ct) { Call = $"resolve:{string.Join(",", runtimeId)}:{nativeWindowHandle}"; return Task.FromResult(Mapping(runtimeId)); }
        public Task<ReadBatchResult> ReadBatchAsync(IReadOnlyList<CandidateRequest> candidates, IReadOnlyList<IReadOnlyList<PathSegment>> paths, CancellationToken ct) { var candidate = candidates.Single(); Call = $"batch:{string.Join(",", candidate.RuntimeId)}:{candidate.NativeWindowHandle}:{paths[0][0].Name}"; return Task.FromResult(new ReadBatchResult { Candidates = new[] { new CandidateResult { RuntimeId = candidate.RuntimeId, Mapping = Mapping(candidate.RuntimeId) } } }); }
        public Task<PageDto<ManagedNodeDto>> RootsAsync(int? pageSize, string? pageToken, CancellationToken ct) { if (Error != null) throw Error; Call = $"roots:{pageSize}:{pageToken}"; return Task.FromResult(Page<ManagedNodeDto>()); }
        public Task<PageDto<ManagedNodeDto>> ChildrenAsync(string objectId, long generation, string tree, int? pageSize, string? pageToken, CancellationToken ct) { Call = $"children:{objectId}:{generation}:{tree}:{pageSize}:{pageToken}"; return Task.FromResult(Page<ManagedNodeDto>()); }
        public Task<PageDto<WinTestKit.Inspector.Protocol.MemberInfo>> MembersAsync(string objectId, long generation, int? pageSize, string? pageToken, CancellationToken ct) { Call = $"members:{objectId}:{generation}:{pageSize}:{pageToken}"; return Task.FromResult(Page<WinTestKit.Inspector.Protocol.MemberInfo>()); }
        public Task<ReadResult> ReadAsync(string objectId, long generation, IReadOnlyList<IReadOnlyList<PathSegment>> paths, CancellationToken ct) { Call = $"read:{objectId}:{generation}:{paths[0][0].Name}"; return Task.FromResult(new ReadResult { ReadId = "read" }); }
        public Task<IReadOnlyList<BindingInfoDto>> BindingsAsync(string objectId, long generation, IReadOnlyList<string> memberKeys, CancellationToken ct) { Call = $"bindings:{objectId}:{generation}:{string.Join(",", memberKeys)}"; return Task.FromResult<IReadOnlyList<BindingInfoDto>>(Array.Empty<BindingInfoDto>()); }
        public Task<int> ReleaseAsync(IReadOnlyList<string> objectIds, CancellationToken ct) { Call = $"release:{string.Join(",", objectIds)}"; return Task.FromResult(objectIds.Count); }
    }
}
