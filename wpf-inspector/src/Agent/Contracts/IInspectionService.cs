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
        Task<ReleaseResult> ReleaseAsync(IReadOnlyList<ReleaseItem> objects, CancellationToken ct);
    }

    public interface IItemsInspectionService
    {
        Task<ItemsResult> ItemsAsync(string objectId, long generation, int? pageSize, string? pageToken, CancellationToken ct);
    }

    public interface IStylingInspectionService
    {
        Task<StylingResult> StylingAsync(string objectId, long generation, CancellationToken ct);
    }

    /// <summary>One value of a resource dictionary, read on demand: the listing in <c>members.styling</c> never creates a resource.</summary>
    public interface IResourceInspectionService
    {
        Task<ResourceResult> ResourceAsync(string objectId, long generation, string scope, string key, string keyKind, int? index, CancellationToken ct);
    }

    /// <summary>The events of an object and who handles them.</summary>
    public interface IMemberEventsInspectionService
    {
        Task<PageDto<MemberEventDto>> EventsAsync(string objectId, long generation, int? pageSize, string? pageToken, CancellationToken ct);
    }

    public interface IParentInspectionService
    {
        Task<ParentResult> ParentAsync(string objectId, long generation, string? tree, CancellationToken ct);
    }

    public interface ISpyFieldInspectionService
    {
        Task<ReadResult> ReadSpyFieldAsync(string objectId, long generation, IReadOnlyList<IReadOnlyList<PathSegment>> paths, CancellationToken ct);
    }

    public interface ISpyMethodInspectionService
    {
        Task<PageDto<MethodMetadataDto>> SpyMethodsAsync(string objectId, long generation, int? pageSize, string? pageToken, CancellationToken ct);
    }

    public sealed class CandidateRequest
    {
        public CandidateRequest(int[] runtimeId, long? nativeWindowHandle) { RuntimeId = runtimeId; NativeWindowHandle = nativeWindowHandle; }
        public int[] RuntimeId { get; }
        public long? NativeWindowHandle { get; }
    }

    public interface IQueryInspectionService
    {
        Task<QueryFindResult> FindAsync(Locator locator, DateTime deadline, int timeoutMs, CancellationToken ct);
        Task<QueryFindAllResult> FindAllAsync(Locator locator, DateTime deadline, int timeoutMs, string? continuation, CancellationToken ct);
    }

    public interface IStateInspectionService
    {
        Task<StateGetResult> GetStateAsync(ObjectRef handle, DateTime deadline, int timeoutMs, CancellationToken ct);
    }

    public interface IHitTestInspectionService
    {
        Task<HitTestResult> HitTestAsync(long nativeWindowHandle, PointDto point, DateTime deadline, int timeoutMs, CancellationToken ct, bool includePath = false, string? tree = null);
    }

    public interface IActionInspectionService
    {
        Task<ActResult> ActAsync(string method, ObjectRef handle, DateTime deadline, int timeoutMs, CancellationToken ct, object? parameters = null);
    }

    public interface ISpyInvokeInspectionService
    {
        Task<WriteCallResult> InvokeAsync(ObjectRef handle, string memberKey, IReadOnlyList<JsonNode> values, DateTime deadline, CancellationToken ct);
    }

    public interface IWriteInspectionService
    {
        Task<WriteCallResult> WriteAsync(string operation, ObjectRef handle, string memberKey, IReadOnlyList<JsonNode> values, DateTime deadline, int timeoutMs, CancellationToken ct);
    }

    public interface IWriteInspectionServiceFactory
    {
        IInspectionService Create(string sessionId, IReadOnlyList<string> redactNames, WriteAllowlist allowlist);
    }

    public interface IRealizeInspectionService
    {
        Task<ActRealizeItemResult> RealizeItemAsync(ItemSearch search, DateTime deadline, int timeoutMs, CancellationToken ct);
    }

    public interface IExactMappingCapability
    {
        bool ExactMappingAvailable { get; }
    }

    public interface IWaitInspectionService
    {
        Task<WaitUntilResult> WaitUntilAsync(WaitCondition condition, DateTime deadline, int timeoutMs, CancellationToken ct);
    }

    public interface IInspectionServiceFactory
    {
        IInspectionService Create(string sessionId, IReadOnlyList<string> redactNames);
    }
}
