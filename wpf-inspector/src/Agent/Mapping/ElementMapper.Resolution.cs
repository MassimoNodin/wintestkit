using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Automation.Peers;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Media.Media3D;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Contracts;
using WinTestKit.Inspector.Agent.Inspection;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Mapping
{
    public sealed partial class ElementMapper
    {
        private readonly IObjectRegistry registry;
        private readonly ProcessIdentity process;
        private readonly SemaphoreSlim resolutionGate = new SemaphoreSlim(1, 1);
        private readonly object cacheGate = new object();
        private readonly Dictionary<string, CacheEntry> cache = new Dictionary<string, CacheEntry>(StringComparer.Ordinal);
        private List<SourceStamp> observedSources = new List<SourceStamp>();
        private long generation;

        public ElementMapper(DispatcherExecutor executor, IPeerRuntimeIdAdapter adapter, IObjectRegistry registry,
            int maxObjects = ProtocolLimits.ScanMaxObjects, int maxMilliseconds = ProtocolLimits.ScanMaxMs)
            : this(executor, adapter, registry, new TreeWalker(executor, maxObjects, maxMilliseconds)) { }

        public ElementMapper(DispatcherExecutor executor, IPeerRuntimeIdAdapter adapter, IObjectRegistry registry, TreeWalker walker)
        {
            this.executor = executor;
            this.adapter = adapter;
            this.registry = registry;
            this.walker = walker;
            using (Process current = Process.GetCurrentProcess())
                process = new ProcessIdentity { Pid = current.Id, CreationTimeUtc = current.StartTime.ToUniversalTime().ToString("O", System.Globalization.CultureInfo.InvariantCulture) };
        }

        public long TreeGeneration { get { lock (cacheGate) return generation; } }
        public int CacheCount { get { lock (cacheGate) return cache.Count; } }

        private sealed class CacheEntry
        {
            internal WeakReference Target = null!;
            internal WeakReference Peer = null!;
            internal DateTime Expires;
        }

        private sealed class SourceStamp
        {
            internal WeakReference Source = null!;
            internal WeakReference Root = null!;
        }

        public void Invalidate()
        {
            lock (cacheGate) { generation++; cache.Clear(); }
        }

        public Task<MappingDto> Resolve(int[] runtimeId, long? nativeWindowHandle) =>
            ResolveAsync(runtimeId, nativeWindowHandle, CancellationToken.None);

        public async Task<MappingDto> ResolveAsync(int[] runtimeId, long? nativeWindowHandle, CancellationToken ct)
        {
            ValidateRuntimeId(runtimeId);
            runtimeId = (int[])runtimeId.Clone();
            await resolutionGate.WaitAsync(ct).ConfigureAwait(false);
            try
            {
                IReadOnlyList<Dispatcher> dispatchers = await ObserveSourcesAsync(ct).ConfigureAwait(false);
                MappingDto? window = await ResolveWindowAsync(runtimeId, nativeWindowHandle, dispatchers, ct).ConfigureAwait(false);
                if (window != null) return window;
                if (!adapter.IsAvailable) return Result(runtimeId, MappingStatus.UnsupportedPeer);
                long scanGeneration = TreeGeneration;
                string key = CacheKey(runtimeId, scanGeneration);
                CacheEntry? entry;
                lock (cacheGate) cache.TryGetValue(key, out entry);
                if (entry != null)
                {
                    if (entry.Expires > DateTime.UtcNow && entry.Target.Target is DependencyObject target && entry.Peer.Target is AutomationPeer peer)
                        return await ValidateMatchAsync(runtimeId, target, peer, scanGeneration, ct).ConfigureAwait(false);
                    lock (cacheGate) cache.Remove(key);
                }
                ScanBudget budget = walker.NewBudget();
                var indexes = new List<PeerIndex>();
                foreach (Dispatcher dispatcher in dispatchers)
                    indexes.Add(await BuildIndexAsync(dispatcher, budget, false, ct).ConfigureAwait(false));
                if (!indexes.Any(index => index.LimitExceeded || index.Find(runtimeId).Count != 0 || index.UnsupportedPeer))
                {
                    indexes.Clear();
                    foreach (Dispatcher dispatcher in dispatchers)
                        indexes.Add(await BuildIndexAsync(dispatcher, budget, true, ct).ConfigureAwait(false));
                }
                return await ResolveIndexedAsync(runtimeId, indexes, scanGeneration, ct).ConfigureAwait(false);
            }
            finally { resolutionGate.Release(); }
        }

        public Task<IReadOnlyList<MappingDto>> ResolveBatch(IReadOnlyList<CandidateRequest> candidates) =>
            ResolveBatchAsync(candidates, CancellationToken.None);

        public async Task<IReadOnlyList<MappingDto>> ResolveBatchAsync(IReadOnlyList<CandidateRequest> candidates, CancellationToken ct)
        {
            if (candidates == null || candidates.Count < 1 || candidates.Count > ProtocolLimits.MaxBatchCandidates)
                throw new ProtocolException(ErrorCodes.InvalidParams, "A batch requires 1 to 32 candidates.");
            var requests = new List<CandidateRequest>();
            foreach (CandidateRequest candidate in candidates)
            {
                if (candidate == null) throw new ProtocolException(ErrorCodes.InvalidParams, "Invalid candidate.");
                ValidateRuntimeId(candidate.RuntimeId);
                requests.Add(new CandidateRequest((int[])candidate.RuntimeId.Clone(), candidate.NativeWindowHandle));
            }
            await resolutionGate.WaitAsync(ct).ConfigureAwait(false);
            try
            {
                IReadOnlyList<Dispatcher> dispatchers = await ObserveSourcesAsync(ct).ConfigureAwait(false);
                long scanGeneration = TreeGeneration;
                ScanBudget budget = walker.NewBudget();
                var indexes = new List<PeerIndex>();
                foreach (Dispatcher dispatcher in dispatchers)
                    indexes.Add(await BuildIndexAsync(dispatcher, budget, false, ct).ConfigureAwait(false));
                var results = new List<MappingDto>();
                foreach (CandidateRequest candidate in requests)
                {
                    MappingDto? window = await ResolveWindowAsync(candidate.RuntimeId, candidate.NativeWindowHandle, dispatchers, ct).ConfigureAwait(false);
                    results.Add(window ?? await ResolveIndexedAsync(candidate.RuntimeId, indexes, scanGeneration, ct).ConfigureAwait(false));
                }
                return results.AsReadOnly();
            }
            finally { resolutionGate.Release(); }
        }

        private async Task<IReadOnlyList<Dispatcher>> ObserveSourcesAsync(CancellationToken ct)
        {
            var sources = new List<PresentationSource>();
            foreach (PresentationSource source in PresentationSource.CurrentSources) sources.Add(source);
            var dispatchers = sources.Select(source => source.Dispatcher).Distinct().Where(dispatcher => !dispatcher.HasShutdownStarted).ToList();
            var stamps = new List<SourceStamp>();
            foreach (Dispatcher dispatcher in dispatchers)
                stamps.AddRange(await executor.ExecuteAsync(dispatcher, () =>
                {
                    var current = new List<SourceStamp>();
                    foreach (PresentationSource source in sources)
                        if (source.Dispatcher == dispatcher && !source.IsDisposed && source.RootVisual is DependencyObject root)
                            current.Add(new SourceStamp { Source = new WeakReference(source), Root = new WeakReference(root) });
                    return current;
                }, ct).ConfigureAwait(false));
            lock (cacheGate)
            {
                if (stamps.Count != observedSources.Count || stamps.Any(stamp => !observedSources.Any(previous =>
                    ReferenceEquals(stamp.Source.Target, previous.Source.Target) && ReferenceEquals(stamp.Root.Target, previous.Root.Target))))
                {
                    generation++;
                    cache.Clear();
                }
                observedSources = stamps;
            }
            return dispatchers;
        }

        private async Task<MappingDto> ResolveIndexedAsync(int[] runtimeId, IReadOnlyList<PeerIndex> indexes, long scanGeneration, CancellationToken ct)
        {
            if (!adapter.IsAvailable || indexes.Any(index => !index.IsAvailable)) return Result(runtimeId, MappingStatus.UnsupportedPeer);
            if (indexes.Any(index => index.LimitExceeded)) return Result(runtimeId, MappingStatus.LimitExceeded);
            if (indexes.Any(index => index.UnsupportedPeer)) return Result(runtimeId, MappingStatus.UnsupportedPeer);
            var matches = new Dictionary<DependencyObject, AutomationPeer>(ReferenceComparer.Instance);
            bool unowned = false;
            foreach (AutomationPeer peer in indexes.SelectMany(index => index.Find(runtimeId)))
            {
                DependencyObject? owner = await executor.ExecuteAsync(peer.Dispatcher, () => Owner(peer), ct).ConfigureAwait(false);
                if (owner == null) unowned = true;
                else matches[owner] = peer;
            }
            if (matches.Count > 1) return Result(runtimeId, MappingStatus.Ambiguous);
            if (unowned) return Result(runtimeId, MappingStatus.UnsupportedPeer);
            if (matches.Count == 0) return Result(runtimeId, MappingStatus.NotFound);
            var match = matches.Single();
            return await ValidateMatchAsync(runtimeId, match.Key, match.Value, scanGeneration, ct).ConfigureAwait(false);
        }

        private Task<MappingDto> ValidateMatchAsync(int[] runtimeId, DependencyObject target, AutomationPeer peer, long scanGeneration, CancellationToken ct) =>
            executor.ExecuteAsync(target.Dispatcher, () =>
            {
                int[]? current = adapter.GetRuntimeId(peer);
                if (current == null) return Result(runtimeId, MappingStatus.UnsupportedPeer);
                if (!runtimeId.SequenceEqual(current) || !ReferenceEquals(Owner(peer), target) || !IsLive(target))
                    return Result(runtimeId, MappingStatus.Stale);
                MappingDto result = Exact(runtimeId, target);
                lock (cacheGate)
                {
                    if (generation == scanGeneration)
                    {
                        foreach (string expired in cache.Where(pair => pair.Value.Expires <= DateTime.UtcNow || !pair.Value.Target.IsAlive || !pair.Value.Peer.IsAlive).Select(pair => pair.Key).ToArray()) cache.Remove(expired);
                        if (cache.Count < ProtocolLimits.MaxWeakEntries)
                            cache[CacheKey(runtimeId, scanGeneration)] = new CacheEntry { Target = new WeakReference(target), Peer = new WeakReference(peer), Expires = DateTime.UtcNow.AddSeconds(1) };
                    }
                }
                return result;
            }, ct);

        private static DependencyObject? Owner(AutomationPeer peer) => peer is UIElementAutomationPeer ui ? ui.Owner :
            peer is ContentElementAutomationPeer content ? content.Owner : null;

        private static bool IsLive(DependencyObject target)
        {
            var pending = new Queue<DependencyObject>();
            var seen = new HashSet<object>(ReferenceComparer.Instance);
            pending.Enqueue(target);
            while (pending.Count != 0 && seen.Count < ProtocolLimits.ScanMaxObjects)
            {
                DependencyObject current = pending.Dequeue();
                if (!seen.Add(current)) continue;
                if (current is Visual visual)
                {
                    PresentationSource? source = PresentationSource.FromVisual(visual);
                    if (source != null && !source.IsDisposed && source.RootVisual != null) return true;
                }
                DependencyObject? parent = current is Visual || current is Visual3D ? VisualTreeHelper.GetParent(current) : null;
                if (parent != null) pending.Enqueue(parent);
                parent = LogicalTreeHelper.GetParent(current);
                if (parent != null) pending.Enqueue(parent);
                if (current is ContentElement content)
                {
                    parent = ContentOperations.GetParent(content);
                    if (parent != null) pending.Enqueue(parent);
                }
            }
            return false;
        }

        private async Task<MappingDto?> ResolveWindowAsync(int[] runtimeId, long? hwnd, IReadOnlyList<Dispatcher> dispatchers, CancellationToken ct)
        {
            if (!hwnd.HasValue || hwnd.Value == 0) return null;
            if (!TryGetHandle(hwnd.Value, out IntPtr handle)) return Result(runtimeId, MappingStatus.NotFound);
            uint thread = GetWindowThreadProcessId(handle, out uint pid);
            if (!IsWindow(handle) || pid != process.Pid || thread == 0) return Result(runtimeId, MappingStatus.NotFound);
            foreach (Dispatcher dispatcher in dispatchers)
            {
                MappingDto? result = await executor.ExecuteAsync(dispatcher, () =>
                {
                    HwndSource? source = HwndSource.FromHwnd(handle);
                    if (source == null || source.Dispatcher != dispatcher) return null;
                    if (source.IsDisposed || source.RootVisual == null || !IsWindow(handle) ||
                        GetWindowThreadProcessId(handle, out uint secondPid) != thread || secondPid != pid)
                        return Result(runtimeId, MappingStatus.Stale);
                    return Exact(runtimeId, source.RootVisual);
                }, ct).ConfigureAwait(false);
                if (result != null) return result;
            }
            return null;
        }

        private MappingDto Result(int[] runtimeId, string status) => new MappingDto
        {
            Status = status, RuntimeId = (int[])runtimeId.Clone(),
            Process = new ProcessIdentity { Pid = process.Pid, CreationTimeUtc = process.CreationTimeUtc }
        };

        private MappingDto Exact(int[] runtimeId, DependencyObject target)
        {
            Type type = target.GetType();
            var bases = new List<string>();
            for (Type? baseType = type.BaseType; baseType != null; baseType = baseType.BaseType) bases.Add(baseType.FullName ?? baseType.Name);
            MappingDto result = Result(runtimeId, MappingStatus.Exact);
            result.Object = registry.Register(target, target.Dispatcher, new TypeInfoDto
            {
                Name = type.Name, FullName = type.FullName ?? type.Name, AssemblyName = type.Assembly.GetName().Name ?? "",
                AssemblyQualifiedName = type.AssemblyQualifiedName ?? type.Name, BaseTypes = bases
            });
            return result;
        }

        private static void ValidateRuntimeId(int[] runtimeId)
        {
            if (runtimeId == null || runtimeId.Length == 0 || runtimeId.Length > 1024)
                throw new ProtocolException(ErrorCodes.InvalidParams, "Invalid runtime ID.");
        }

        private static string CacheKey(int[] runtimeId, long treeGeneration) => treeGeneration.ToString(System.Globalization.CultureInfo.InvariantCulture) + ":" + PeerIndex.Key(runtimeId);

        private static bool TryGetHandle(long value, out IntPtr handle)
        {
            if (IntPtr.Size == 4 && (value < int.MinValue || value > uint.MaxValue)) { handle = IntPtr.Zero; return false; }
            handle = IntPtr.Size == 4 ? new IntPtr(unchecked((int)value)) : new IntPtr(value);
            return true;
        }
    }
}
