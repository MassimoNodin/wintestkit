using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Automation.Peers;
using System.Windows.Interop;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Inspection;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Mapping
{
    public sealed partial class ElementMapper
    {
        private readonly DispatcherExecutor executor;
        private readonly TreeWalker walker;
        private readonly IPeerRuntimeIdAdapter adapter;
        private int indexBuildCount;
        public ElementMapper(DispatcherExecutor executor, IPeerRuntimeIdAdapter adapter)
            : this(executor, adapter, new ObjectRegistry(Guid.NewGuid().ToString(), executor)) { }
        public bool IsAvailable => adapter.IsAvailable;
        public int IndexBuildCount => Volatile.Read(ref indexBuildCount);

        public Task<PeerIndex> BuildIndexAsync(Dispatcher dispatcher, CancellationToken ct) =>
            BuildIndexAsync(dispatcher, walker.NewBudget(), false, ct);

        private async Task<PeerIndex> BuildIndexAsync(Dispatcher dispatcher, ScanBudget budget, bool createMissing, CancellationToken ct)
        {
            Interlocked.Increment(ref indexBuildCount);
            if (!adapter.IsAvailable) return new PeerIndex(false);
            TreeScanResult scan = await walker.WalkAsync(dispatcher, budget, ct).ConfigureAwait(false);
            IReadOnlyList<DependencyObject> objects = scan.Objects;
            var index = new PeerIndex(true) { LimitExceeded = scan.LimitExceeded };
            if (scan.LimitExceeded) return index;
            var queue = new Queue<AutomationPeer>();
            var seen = new HashSet<object>(ReferenceComparer.Instance);
            int offset = 0;
            while (offset < objects.Count || queue.Count != 0)
            {
                await executor.ExecuteAsync(dispatcher, () =>
                {
                    Stopwatch slice = Stopwatch.StartNew();
                    int processed = 0;
                    while (processed < ProtocolLimits.TraversalSliceObjects && slice.ElapsedMilliseconds < ProtocolLimits.TraversalSliceMs && (offset < objects.Count || queue.Count != 0))
                    {
                        ct.ThrowIfCancellationRequested();
                        if (budget.Expired) { index.LimitExceeded = true; return true; }
                        AutomationPeer? peer;
                        if (offset < objects.Count)
                        {
                            DependencyObject obj = objects[offset++];
                            try { peer = createMissing ? PeerRuntimeIdAdapter.ResolveSingleElement(obj) : PeerRuntimeIdAdapter.ExistingPeer(obj); }
                            catch (Exception exception) when (!(exception is OperationCanceledException))
                            {
                                index.UnsupportedPeer = true;
                                continue;
                            }
                        }
                        else peer = queue.Dequeue();
                        if (peer == null || !seen.Add(peer)) continue;
                        if (!budget.Take()) { index.LimitExceeded = true; return true; }
                        processed++;
                        int[]? id = adapter.GetRuntimeId(peer);
                        if (id != null) index.Add(id, peer);
                        else index.UnsupportedPeer = true;
                        try
                        {
                            List<AutomationPeer>? children = peer.GetChildren();
                            if (children != null)
                                foreach (AutomationPeer child in children)
                                {
                                    if (queue.Count >= ProtocolLimits.ScanMaxObjects) { index.LimitExceeded = true; return true; }
                                    queue.Enqueue(child);
                                }
                        }
                        catch (Exception exception) when (!(exception is OperationCanceledException)) { index.UnsupportedPeer = true; }
                    }
                    return true;
                }, ct).ConfigureAwait(false);
                if (index.LimitExceeded) break;
            }
            if (budget.Expired) index.LimitExceeded = true;
            return index;
        }

        public Task<DependencyObject?> ResolveWindowRootAsync(Dispatcher dispatcher, long hwnd, CancellationToken ct) =>
            executor.ExecuteAsync(dispatcher, () =>
            {
                if (!TryGetHandle(hwnd, out IntPtr handle)) return null;
                uint thread = GetWindowThreadProcessId(handle, out uint pid);
                if (!IsWindow(handle) || pid != (uint)process.Pid || thread == 0) return null;
                HwndSource? source = HwndSource.FromHwnd(handle);
                if (source == null || source.Dispatcher != dispatcher || source.IsDisposed) return null;
                DependencyObject? root = source.RootVisual;
                return IsWindow(handle) && GetWindowThreadProcessId(handle, out uint secondPid) == thread && secondPid == pid ? root : null;
            }, ct);

        [DllImport("user32.dll")] private static extern bool IsWindow(IntPtr hwnd);
        [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint processId);
    }

    public sealed class PeerIndex
    {
        private readonly Dictionary<string, List<AutomationPeer>> peers = new Dictionary<string, List<AutomationPeer>>(StringComparer.Ordinal);
        internal PeerIndex(bool available) { IsAvailable = available; }
        public bool IsAvailable { get; }
        public bool LimitExceeded { get; internal set; }
        internal bool UnsupportedPeer { get; set; }
        internal void Add(int[] id, AutomationPeer peer)
        {
            string key = Key(id);
            if (!peers.TryGetValue(key, out List<AutomationPeer>? matches)) peers.Add(key, matches = new List<AutomationPeer>());
            matches.Add(peer);
        }
        public IReadOnlyList<AutomationPeer> Find(int[] id) => peers.TryGetValue(Key(id), out List<AutomationPeer>? matches) ? matches : Array.Empty<AutomationPeer>();
        internal static string Key(int[] id) => string.Join(",", Array.ConvertAll(id, component => component.ToString(System.Globalization.CultureInfo.InvariantCulture)));
    }
}
