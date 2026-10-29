using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Contracts;
using WinTestKit.Inspector.Agent.Mapping;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Inspection
{
    public sealed class WpfInspectionService : IInspectionService, IExactMappingCapability
    {
        private readonly DispatcherExecutor executor;
        private readonly ObjectRegistry registry;
        private readonly PageSnapshotStore snapshots;
        private readonly IPeerRuntimeIdAdapter adapter;
        private readonly ElementMapper mapper;
        private readonly IObjectInspector inspector;
        private readonly TreeWalker walker;
        private readonly CancellationTokenSource lifetime = new CancellationTokenSource();
        private int disposed;

        internal WpfInspectionService(string sessionId, IObjectInspector inspector,
            PageSnapshotStore? snapshots = null, IPeerRuntimeIdAdapter? adapter = null)
        {
            this.inspector = inspector ?? throw new ArgumentNullException(nameof(inspector));
            executor = new DispatcherExecutor();
            registry = new ObjectRegistry(sessionId, executor);
            this.snapshots = snapshots ?? new PageSnapshotStore();
            this.adapter = adapter ?? new PeerRuntimeIdAdapter();
            walker = new TreeWalker(executor);
            mapper = new ElementMapper(executor, this.adapter, registry, walker);
        }

        public bool ExactMappingAvailable => mapper.IsAvailable;

        public Task<MappingDto> ResolveAsync(int[] runtimeId, long? nativeWindowHandle, CancellationToken ct) =>
            RunAsync(token => mapper.ResolveAsync(runtimeId, nativeWindowHandle, token), ct);

        public Task<ReadBatchResult> ReadBatchAsync(IReadOnlyList<CandidateRequest> candidates,
            IReadOnlyList<IReadOnlyList<PathSegment>> paths, CancellationToken ct) => RunAsync(async token =>
        {
            CheckCount(candidates.Count, ProtocolLimits.MaxBatchCandidates);
            CheckPaths(paths);
            IReadOnlyList<MappingDto> mappings = await mapper.ResolveBatchAsync(candidates, token).ConfigureAwait(false);
            var results = new List<CandidateResult>();
            foreach (MappingDto mapping in mappings)
            {
                token.ThrowIfCancellationRequested();
                IReadOnlyList<PathValue> values = Array.Empty<PathValue>();
                if (mapping.Status == MappingStatus.Exact && mapping.Object != null)
                    values = await ReadValuesAsync(mapping.Object.ObjectId, mapping.Object.Generation, paths, token).ConfigureAwait(false);
                results.Add(new CandidateResult { RuntimeId = mapping.RuntimeId, Mapping = mapping, Values = values });
            }
            return new ReadBatchResult { Candidates = results };
        }, ct);

        public Task<PageDto<ManagedNodeDto>> RootsAsync(int? pageSize, string? pageToken, CancellationToken ct) => RunAsync(async token =>
        {
            int size = PageSize(pageSize);
            if (pageToken != null) return Page<ManagedNodeDto>("", 0, "roots", "", size, pageToken);
            var nodes = new List<ManagedNodeDto>();
            var seen = new HashSet<object>(ReferenceComparer.Instance);
            IReadOnlyList<Dispatcher> dispatchers = await executor.DiscoverDispatchersAsync(token).ConfigureAwait(false);
            ScanBudget budget = walker.NewBudget();
            foreach (Dispatcher dispatcher in dispatchers)
                await CollectNodesAsync(dispatcher, () => TreeWalker.EnumerateRoots(dispatcher), nodes, seen, budget, token).ConfigureAwait(false);
            nodes.Sort(CompareNodes);
            return NewPage("", 0, "roots", "", nodes, Array.Empty<Diagnostic>(), size, token);
        }, ct);

        public Task<PageDto<ManagedNodeDto>> ChildrenAsync(string objectId, long generation, string tree,
            int? pageSize, string? pageToken, CancellationToken ct) => RunAsync(async token =>
        {
            int size = PageSize(pageSize);
            if (tree != TreeKind.Visual && tree != TreeKind.Logical)
                throw new ProtocolException(ErrorCodes.InvalidParams, "Unknown tree kind.");
            object target = GetObject(objectId, generation, out Dispatcher dispatcher);
            if (pageToken != null) return Page<ManagedNodeDto>(objectId, generation, "children", tree, size, pageToken);
            var nodes = new List<ManagedNodeDto>();
            if (target is DependencyObject dependencyObject)
                await CollectNodesAsync(dispatcher, () => TreeWalker.EnumerateChildren(dependencyObject, tree),
                    nodes, new HashSet<object>(ReferenceComparer.Instance), walker.NewBudget(), token).ConfigureAwait(false);
            nodes.Sort(CompareNodes);
            return NewPage(objectId, generation, "children", tree, nodes, Array.Empty<Diagnostic>(), size, token);
        }, ct);

        public Task<PageDto<MemberInfo>> MembersAsync(string objectId, long generation, int? pageSize,
            string? pageToken, CancellationToken ct) => RunAsync(async token =>
        {
            int size = PageSize(pageSize);
            object target = GetObject(objectId, generation, out Dispatcher dispatcher);
            if (pageToken != null) return Page<MemberInfo>(objectId, generation, "members", "", size, pageToken);
            var diagnostics = new List<Diagnostic>();
            IReadOnlyList<MemberInfo> members = await executor.ExecuteAsync(dispatcher,
                () => inspector.GetMembers(target, diagnostics), token).ConfigureAwait(false);
            var sorted = members.OrderBy(member => member.Category, StringComparer.Ordinal)
                .ThenBy(member => member.Name, StringComparer.Ordinal)
                .ThenBy(member => member.DeclaringType, StringComparer.Ordinal)
                .ThenBy(member => member.MemberKey, StringComparer.Ordinal).ToArray();
            return NewPage(objectId, generation, "members", "", sorted, diagnostics.ToArray(), size, token);
        }, ct);

        public Task<ReadResult> ReadAsync(string objectId, long generation,
            IReadOnlyList<IReadOnlyList<PathSegment>> paths, CancellationToken ct) => RunAsync(async token =>
        {
            CheckPaths(paths);
            return new ReadResult
            {
                Values = await ReadValuesAsync(objectId, generation, paths, token).ConfigureAwait(false),
                ReadId = Guid.NewGuid().ToString("N")
            };
        }, ct);

        public Task<IReadOnlyList<BindingInfoDto>> BindingsAsync(string objectId, long generation,
            IReadOnlyList<string> memberKeys, CancellationToken ct) => RunAsync(async token =>
        {
            CheckCount(memberKeys.Count, ProtocolLimits.MaxBindingKeys, true);
            object target = GetObject(objectId, generation, out Dispatcher dispatcher);
            return await executor.ExecuteAsync(dispatcher, () => inspector.GetBindings(target, memberKeys), token).ConfigureAwait(false);
        }, ct);

        public Task<int> ReleaseAsync(IReadOnlyList<string> objectIds, CancellationToken ct) => RunAsync(token =>
        {
            CheckCount(objectIds.Count, ProtocolLimits.MaxReleaseIds, true);
            token.ThrowIfCancellationRequested();
            return Task.FromResult(registry.Release(objectIds));
        }, ct);

        private async Task<IReadOnlyList<PathValue>> ReadValuesAsync(string objectId, long generation,
            IReadOnlyList<IReadOnlyList<PathSegment>> paths, CancellationToken ct)
        {
            object target = GetObject(objectId, generation, out Dispatcher dispatcher);
            var values = new List<PathValue>();
            foreach (IReadOnlyList<PathSegment> path in paths)
            {
                ValueDto value = await executor.ExecuteAsync(dispatcher,
                    token => inspector.ReadPath(target, path, registry, dispatcher, token), ct).ConfigureAwait(false);
                values.Add(new PathValue { Path = path, Value = value });
            }
            return values;
        }

        private object GetObject(string objectId, long generation, out Dispatcher dispatcher)
        {
            if (!registry.TryGet(objectId, generation, out object target, out dispatcher))
                throw new ProtocolException(ErrorCodes.ObjectStale, "Unknown or stale object handle.");
            return target;
        }

        private void AddNode(List<ManagedNodeDto> nodes, DependencyObject target)
        {
            if (nodes.Count >= ProtocolLimits.ScanMaxObjects)
                throw new ProtocolException(ErrorCodes.LimitExceeded, "Tree scan limit reached.");
            var peer = PeerRuntimeIdAdapter.ExistingPeer(target);
            int[]? runtimeId = peer == null || !adapter.IsAvailable ? null : adapter.GetRuntimeId(peer);
            nodes.Add(new ManagedNodeDto
            {
                Object = registry.Register(target, target.Dispatcher, inspector.DescribeType(target.GetType())),
                Label = target.GetType().Name,
                HasVisualChildren = TreeWalker.EnumerateChildren(target, TreeKind.Visual).Any(),
                HasLogicalChildren = TreeWalker.EnumerateChildren(target, TreeKind.Logical).Any(),
                RuntimeId = runtimeId == null ? null : (int[])runtimeId.Clone()
            });
        }

        private async Task CollectNodesAsync(Dispatcher dispatcher, Func<IEnumerable<DependencyObject>> enumerate,
            List<ManagedNodeDto> nodes, HashSet<object> seen, ScanBudget budget, CancellationToken ct)
        {
            IEnumerator<DependencyObject> iterator = await executor.ExecuteAsync(dispatcher, () => enumerate().GetEnumerator(), ct).ConfigureAwait(false);
            try
            {
                bool complete;
                do
                {
                    complete = await executor.ExecuteAsync(dispatcher, token =>
                    {
                        Stopwatch slice = Stopwatch.StartNew();
                        for (int count = 0; count < ProtocolLimits.TraversalSliceObjects &&
                            slice.ElapsedMilliseconds < ProtocolLimits.TraversalSliceMs; count++)
                        {
                            token.ThrowIfCancellationRequested();
                            if (budget.Expired) throw new ProtocolException(ErrorCodes.LimitExceeded, "Tree scan limit reached.");
                            if (!iterator.MoveNext()) return true;
                            DependencyObject current = iterator.Current;
                            if (!seen.Add(current)) continue;
                            if (!budget.Take()) throw new ProtocolException(ErrorCodes.LimitExceeded, "Tree scan limit reached.");
                            AddNode(nodes, current);
                        }
                        return false;
                    }, ct).ConfigureAwait(false);
                } while (!complete);
            }
            finally
            {
                if (!dispatcher.HasShutdownStarted)
                    await executor.ExecuteAsync(dispatcher, () => { iterator.Dispose(); return true; }, CancellationToken.None).ConfigureAwait(false);
            }
        }

        private static int CompareNodes(ManagedNodeDto first, ManagedNodeDto second)
        {
            int label = StringComparer.Ordinal.Compare(first.Label, second.Label);
            return label != 0 ? label : StringComparer.Ordinal.Compare(first.Object.ObjectId, second.Object.ObjectId);
        }

        private sealed class Snapshot<T>
        {
            internal IReadOnlyList<T> Items = Array.Empty<T>();
            internal IReadOnlyList<Diagnostic> Diagnostics = Array.Empty<Diagnostic>();
            internal readonly Dictionary<string, int> Offsets = new Dictionary<string, int>(StringComparer.Ordinal);
            internal readonly Dictionary<int, string> Tokens = new Dictionary<int, string>();
        }

        private PageDto<T> NewPage<T>(string objectId, long generation, string operation, string tree,
            IReadOnlyList<T> items, IReadOnlyList<Diagnostic> diagnostics, int size, CancellationToken ct)
        {
            ct.ThrowIfCancellationRequested();
            var snapshot = new Snapshot<T> { Items = items.ToArray(), Diagnostics = diagnostics };
            if (items.Count <= size)
                return Slice(snapshot, Guid.NewGuid().ToString("N"), 0, size);
            string id = snapshots.Create(objectId, generation, operation, tree, new[] { snapshot },
                Comparer<Snapshot<T>>.Create((first, second) => 0));
            return Slice(snapshot, id, 0, size);
        }

        private PageDto<T> Page<T>(string objectId, long generation, string operation, string tree, int size, string token)
        {
            int separator = token.IndexOf('.');
            if (separator <= 0) throw InvalidPage();
            string id = token.Substring(0, separator);
            Snapshot<T> snapshot = snapshots.Get<Snapshot<T>>(id, objectId, generation, operation, tree)[0];
            lock (snapshot)
            {
                snapshots.Get<Snapshot<T>>(id, objectId, generation, operation, tree);
                if (!snapshot.Offsets.TryGetValue(token.Substring(separator + 1), out int offset)) throw InvalidPage();
                PageDto<T> page = Slice(snapshot, id, offset, size);
                if (page.NextToken == null) snapshots.Remove(id);
                return page;
            }
        }

        private static PageDto<T> Slice<T>(Snapshot<T> snapshot, string id, int offset, int size)
        {
            var items = new List<T>();
            int end = Math.Min(snapshot.Items.Count, offset + size);
            for (int index = offset; index < end; index++) items.Add(snapshot.Items[index]);
            string? nextToken = null;
            lock (snapshot)
            {
                if (end < snapshot.Items.Count)
                {
                    if (!snapshot.Tokens.TryGetValue(end, out string? cursor))
                    {
                        cursor = Guid.NewGuid().ToString("N");
                        snapshot.Tokens.Add(end, cursor);
                        snapshot.Offsets.Add(cursor, end);
                    }
                    nextToken = id + "." + cursor;
                }
            }
            return new PageDto<T>
            {
                Items = items, SnapshotId = id, Diagnostics = snapshot.Diagnostics,
                Complete = end == snapshot.Items.Count && snapshot.Diagnostics.Count == 0,
                NextToken = nextToken
            };
        }

        private static int PageSize(int? size)
        {
            int result = size ?? ProtocolLimits.DefaultPageSize;
            CheckCount(result, ProtocolLimits.MaxPageSize);
            return result;
        }

        private static void CheckPaths(IReadOnlyList<IReadOnlyList<PathSegment>> paths)
        {
            CheckCount(paths.Count, ProtocolLimits.MaxBatchPaths);
            foreach (IReadOnlyList<PathSegment> path in paths)
            {
                CheckCount(path.Count, ProtocolLimits.MaxPathSegments);
                var json = new JsonArrayNode();
                foreach (PathSegment segment in path) json.Add(segment.ToJson());
                if (StrictJson.Serialize(json).Length > ProtocolLimits.MaxPathBytes)
                    throw new ProtocolException(ErrorCodes.LimitExceeded, "Path byte limit reached.");
                if (path.Count > 1 && path.Any(segment => segment.Kind == SegmentKind.Type))
                    throw new ProtocolException(ErrorCodes.InvalidParams, "Type path must contain one segment.");
            }
        }

        private static void CheckCount(int count, int maximum, bool allowEmpty = false)
        {
            if (count > maximum) throw new ProtocolException(ErrorCodes.LimitExceeded, "Request limit reached.");
            if (!allowEmpty && count < 1) throw new ProtocolException(ErrorCodes.InvalidParams, "Empty request.");
        }

        private static ProtocolException InvalidPage() => new ProtocolException(ErrorCodes.InvalidPageToken, "Invalid or expired page token.");

        private async Task<T> RunAsync<T>(Func<CancellationToken, Task<T>> action, CancellationToken ct)
        {
            CancellationTokenSource cancellation;
            lock (lifetime)
            {
                if (Volatile.Read(ref disposed) != 0) throw new ObjectDisposedException(nameof(WpfInspectionService));
                cancellation = CancellationTokenSource.CreateLinkedTokenSource(ct, lifetime.Token);
            }
            using (cancellation)
            {
                cancellation.Token.ThrowIfCancellationRequested();
                T result = await action(cancellation.Token).ConfigureAwait(false);
                cancellation.Token.ThrowIfCancellationRequested();
                return result;
            }
        }

        public void Dispose()
        {
            if (Interlocked.Exchange(ref disposed, 1) != 0) return;
            lock (lifetime) { lifetime.Cancel(); lifetime.Dispose(); }
            mapper.Invalidate();
            snapshots.Dispose();
            registry.Dispose();
        }
    }
}
