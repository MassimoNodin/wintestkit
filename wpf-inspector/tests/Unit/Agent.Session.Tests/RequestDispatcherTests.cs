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

    [Theory]
    [InlineData(PipeMethods.QueryFind)][InlineData(PipeMethods.QueryFindAll)][InlineData(PipeMethods.StateGet)]
    [InlineData(PipeMethods.ActFocus)][InlineData(PipeMethods.ActBringIntoView)][InlineData(PipeMethods.ActInvoke)]
    [InlineData(PipeMethods.ActToggle)][InlineData(PipeMethods.ActExpand)][InlineData(PipeMethods.ActCollapse)]
    [InlineData(PipeMethods.ActSelect)][InlineData(PipeMethods.ActScrollIntoView)][InlineData(PipeMethods.ActSetValue)]
    [InlineData(PipeMethods.ActSetRange)][InlineData(PipeMethods.ActScroll)][InlineData(PipeMethods.ActRealizeItem)]
    [InlineData(PipeMethods.WaitUntil)][InlineData(PipeMethods.HitTest)][InlineData(PipeMethods.WriteSetProperty)]
    [InlineData(PipeMethods.WriteCall)][InlineData(PipeMethods.EventsSubscribe)][InlineData(PipeMethods.EventsUnsubscribe)]
    public async Task Protocol2MethodsAreRecognizedButUnavailable(string method)
    {
        var request = new RequestEnvelope { Id = 42, Method = method, Params = new JsonObjectNode() };
        request = RequestEnvelope.FromJson(request.ToJson());
        var response = await new RequestDispatcher(Session, new RecordingService()).HandleAsync(request, CancellationToken.None);
        Assert.Equal(ErrorCodes.UnsupportedTarget, response.Error!.Code);
    }

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

    private static JsonObjectNode QueryParams(string scope = "allRoots", int limit = 200, int depth = 256, int timeout = 1000, string predicates = "[]")
    {
        string json = $"{{\"locator\":{{\"scope\":{{\"kind\":\"{scope}\"}},\"tree\":\"logical\",\"predicates\":{predicates},\"depth\":{depth},\"depthMode\":\"tree\",\"limit\":{limit}}},\"timeoutMs\":{timeout}}}";
        var bytes = System.Text.Encoding.UTF8.GetBytes(json);
        return (JsonObjectNode)StrictJson.Parse(bytes, 0, bytes.Length);
    }

    [Theory]
    [InlineData("bad", 200, 256, 1000, "[]")]
    [InlineData("allRoots", 0, 256, 1000, "[]")]
    [InlineData("allRoots", 200, 257, 1000, "[]")]
    [InlineData("allRoots", 200, 256, 0, "[]")]
    [InlineData("allRoots", 200, 256, 2001, "[]")]
    [InlineData("allRoots", 200, 256, 1000, "[{\"kind\":\"unknown\"}]")]
    public async Task QueryRejectsMalformedParameters(string scope, int limit, int depth, int timeout, string predicates)
    {
        var response = await Dispatch(new RequestDispatcher(Session, new QueryService()), PipeMethods.QueryFind, QueryParams(scope, limit, depth, timeout, predicates));
        Assert.Equal(ErrorCodes.InvalidParams, response.Error!.Code);
    }

    [Fact]
    public async Task QueryResultsAndErrorDetailsAreSerialized()
    {
        var service = new QueryService();
        var dispatcher = new RequestDispatcher(Session, service);
        var response = await Dispatch(dispatcher, PipeMethods.QueryFind, QueryParams());
        Assert.Equal(2, QueryFindResult.FromJson(response.Result!).Warning!.Count);
        response = await Dispatch(dispatcher, PipeMethods.QueryFindAll, QueryParams());
        var all = QueryFindAllResult.FromJson(response.Result!);
        Assert.True(all.Complete); Assert.Equal(1, all.Count); Assert.Single(all.Matches);
        foreach (string code in new[] { ErrorCodes.NotFound, ErrorCodes.ObjectStale, ErrorCodes.ValueUnreadable })
        {
            var details = new JsonObjectNode(); details.Add("status", new JsonStringNode("redacted"));
            service.QueryError = new ProtocolException(code, "sensitive", details);
            response = await Dispatch(dispatcher, PipeMethods.QueryFind, QueryParams());
            var serialized = ResponseEnvelope.FromJson(StrictJson.Parse(StrictJson.Serialize(response.ToJson()), 0, StrictJson.Serialize(response.ToJson()).Length));
            Assert.Equal(code, serialized.Error!.Code);
            if (code == ErrorCodes.ValueUnreadable) Assert.Equal("redacted", ((JsonStringNode)serialized.Error.Details!.Get("status")).Value);
        }
    }

    [Fact]
    public async Task QueryCancellationUsesTheSharedScheduler()
    {
        using var scheduler = new RequestScheduler(2000);
        var service = new QueryService { Block = true };
        var dispatcher = new RequestDispatcher(Session, service, scheduler);
        var pending = dispatcher.HandleAsync(new RequestEnvelope { Id = 1, Method = PipeMethods.QueryFind, Params = QueryParams() }, CancellationToken.None);
        await service.Started.Task.WaitAsync(TimeSpan.FromSeconds(1));
        var cancel = await dispatcher.HandleAsync(new RequestEnvelope { Id = 2, Method = PipeMethods.Cancel, Params = new CancelParams { RequestId = 1 }.ToJson() }, CancellationToken.None);
        Assert.True(CancelResult.FromJson(cancel.Result!).Accepted);
        Assert.Equal(ErrorCodes.Cancelled, (await pending).Error!.Code);
    }

    [Fact]
    public async Task QueryUsesSharedBusyLimit()
    {
        using var scheduler = new RequestScheduler(2000);
        var service = new QueryService { Block = true };
        var dispatcher = new RequestDispatcher(Session, service, scheduler);
        var pending = new List<Task<ResponseEnvelope>>();
        int capacity = ProtocolLimits.MaxActivePerSession + ProtocolLimits.MaxQueuedOps;
        for (int index = 1; index <= capacity; index++)
            pending.Add(dispatcher.HandleAsync(new RequestEnvelope { Id = index, Method = PipeMethods.QueryFind, Params = QueryParams() }, CancellationToken.None));
        var busy = await dispatcher.HandleAsync(new RequestEnvelope { Id = capacity + 1, Method = PipeMethods.QueryFindAll, Params = QueryParams() }, CancellationToken.None);
        Assert.Equal(ErrorCodes.Busy, busy.Error!.Code);
        for (int index = 1; index <= capacity; index++) scheduler.Cancel(index);
        await Task.WhenAll(pending);
    }

    [Theory]
    [InlineData(0)]
    [InlineData(2001)]
    public async Task StateRejectsInvalidTimeout(int timeout)
    {
        var parameters = new JsonObjectNode();
        parameters.Add("handle", StateService.Handle.ToJson());
        parameters.Add("timeoutMs", JsonNumberNode.From(timeout));
        var response = await Dispatch(new RequestDispatcher(Session, new StateService()), PipeMethods.StateGet, parameters);
        Assert.Equal(ErrorCodes.InvalidParams, response.Error!.Code);
    }

    [Fact]
    public async Task StateRoutesAndSerializes()
    {
        var service = new StateService();
        var response = await Dispatch(new RequestDispatcher(Session, service), PipeMethods.StateGet,
            new StateGetParams { Handle = StateService.Handle, TimeoutMs = 500 }.ToJson());
        Assert.Null(response.Error);
        Assert.Equal("object", StateGetResult.FromJson(response.Result!).State.Handle.ObjectId);
        Assert.Equal(500, service.Timeout);
    }

    private sealed class StateService : RecordingService, IStateInspectionService
    {
        public static ObjectRef Handle => new() { SessionId = Session, ObjectId = "object", Generation = 1, DispatcherId = "dispatcher", Type = new TypeInfoDto() };
        public int Timeout { get; private set; }
        public Task<StateGetResult> GetStateAsync(ObjectRef handle, DateTime deadline, int timeoutMs, CancellationToken ct)
        {
            Timeout = timeoutMs;
            return Task.FromResult(new StateGetResult { State = new ElementState { Handle = handle, Dpi = new PointDto { X = 96, Y = 96 } } });
        }
    }

    [Theory]
    [InlineData(0)]
    [InlineData(2001)]
    [InlineData(500)]
    public async Task WaitValidatesAndRoutes(int timeout)
    {
        var parameters = new JsonObjectNode();
        var condition = new JsonObjectNode();
        condition.Add("kind", new JsonStringNode("exists"));
        condition.Add("locator", QueryParams().Get("locator"));
        parameters.Add("condition", condition);
        parameters.Add("timeoutMs", JsonNumberNode.From(timeout));
        var response = await Dispatch(new RequestDispatcher(Session, new WaitService()), PipeMethods.WaitUntil, parameters);
        if (timeout == 500) Assert.False(WaitUntilResult.FromJson(response.Result!).Satisfied);
        else Assert.Equal(ErrorCodes.InvalidParams, response.Error!.Code);
    }

    private sealed class WaitService : RecordingService, IWaitInspectionService
    {
        public Task<WaitUntilResult> WaitUntilAsync(WaitCondition condition, DateTime deadline, int timeoutMs, CancellationToken ct) =>
            Task.FromResult(new WaitUntilResult { Satisfied = false });
    }

    private sealed class QueryService : RecordingService, IQueryInspectionService
    {
        public ProtocolException? QueryError { get; set; }
        public bool Block { get; set; }
        public TaskCompletionSource<bool> Started { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private static ObjectRef Match => new() { SessionId = Session, ObjectId = "object", Generation = 1, DispatcherId = "dispatcher", Type = new TypeInfoDto() };
        public async Task<QueryFindResult> FindAsync(Locator locator, DateTime deadline, int timeoutMs, CancellationToken ct)
        {
            if (QueryError != null) throw QueryError;
            Started.TrySetResult(true);
            if (Block) await Task.Delay(Timeout.Infinite, ct);
            return new QueryFindResult { Match = Match, Warning = new MatchWarning { Count = 2 } };
        }
        public Task<QueryFindAllResult> FindAllAsync(Locator locator, DateTime deadline, int timeoutMs, CancellationToken ct) => Task.FromResult(new QueryFindAllResult { Matches = new[] { Match }, Count = 1, Complete = true });
    }

    private class RecordingService : IInspectionService
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
