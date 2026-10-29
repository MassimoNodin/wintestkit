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

    public interface IExactMappingCapability
    {
        bool ExactMappingAvailable { get; }
    }

    public interface IInspectionServiceFactory
    {
        IInspectionService Create(string sessionId, IReadOnlyList<string> redactNames);
    }
}
