using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Runtime.CompilerServices;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Media3D;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Inspection;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Mapping
{
    internal sealed class ReferenceComparer : IEqualityComparer<object>
    {
        internal static readonly ReferenceComparer Instance = new ReferenceComparer();
        public new bool Equals(object? first, object? second) => ReferenceEquals(first, second);
        public int GetHashCode(object value) => RuntimeHelpers.GetHashCode(value);
    }

    internal sealed class ScanBudget
    {
        private readonly Stopwatch timer = Stopwatch.StartNew();
        private readonly int maxObjects;
        private readonly int maxMilliseconds;
        private int count;
        internal ScanBudget(int maxObjects, int maxMilliseconds)
        { this.maxObjects = maxObjects; this.maxMilliseconds = maxMilliseconds; }
        internal bool Expired => timer.ElapsedMilliseconds >= maxMilliseconds;
        internal bool Take() => !Expired && count++ < maxObjects;
    }

    public sealed class TreeScanResult
    {
        internal TreeScanResult(List<DependencyObject> objects, bool limitExceeded)
        { Objects = objects.AsReadOnly(); LimitExceeded = limitExceeded; }
        public IReadOnlyList<DependencyObject> Objects { get; }
        public bool LimitExceeded { get; }
    }

    public sealed class TreeWalker
    {
        private readonly DispatcherExecutor executor;
        private readonly int maxObjects;
        private readonly int maxMilliseconds;
        private int traversalCount;
        public TreeWalker(DispatcherExecutor executor, int maxObjects = ProtocolLimits.ScanMaxObjects,
            int maxMilliseconds = ProtocolLimits.ScanMaxMs)
        {
            if (maxObjects < 1 || maxObjects > ProtocolLimits.ScanMaxObjects ||
                maxMilliseconds < 1 || maxMilliseconds > ProtocolLimits.ScanMaxMs)
                throw new ArgumentOutOfRangeException(nameof(maxObjects));
            this.executor = executor;
            this.maxObjects = maxObjects;
            this.maxMilliseconds = maxMilliseconds;
        }
        public int TraversalCount => Volatile.Read(ref traversalCount);
        internal ScanBudget NewBudget() => new ScanBudget(maxObjects, maxMilliseconds);
        public Task<TreeScanResult> WalkAsync(Dispatcher dispatcher, CancellationToken ct) =>
            WalkAsync(dispatcher, NewBudget(), ct);

        internal async Task<TreeScanResult> WalkAsync(Dispatcher dispatcher, ScanBudget budget, CancellationToken ct)
        {
            Interlocked.Increment(ref traversalCount);
            var pending = new Queue<IEnumerator<DependencyObject>>();
            var seen = new HashSet<object>(ReferenceComparer.Instance);
            var found = new List<DependencyObject>();
            bool initialized = false;
            bool limited = false;
            try
            {
                while (true)
                {
                    bool complete = await executor.ExecuteAsync(dispatcher, token =>
                    {
                        if (!initialized)
                        {
                            pending.Enqueue(EnumerateRoots(dispatcher).GetEnumerator());
                            initialized = true;
                        }
                        Stopwatch slice = Stopwatch.StartNew();
                        int steps = 0;
                        while (pending.Count != 0 && steps++ < ProtocolLimits.TraversalSliceObjects &&
                            slice.ElapsedMilliseconds < ProtocolLimits.TraversalSliceMs)
                        {
                            token.ThrowIfCancellationRequested();
                            if (budget.Expired) { limited = true; return true; }
                            IEnumerator<DependencyObject> children = pending.Peek();
                            if (!children.MoveNext()) { pending.Dequeue().Dispose(); continue; }
                            DependencyObject current = children.Current;
                            if (current.Dispatcher != dispatcher || !seen.Add(current)) continue;
                            if (!budget.Take()) { limited = true; return true; }
                            found.Add(current);
                            pending.Enqueue(EnumerateChildren(current, TreeKind.Visual).GetEnumerator());
                            pending.Enqueue(EnumerateChildren(current, TreeKind.Logical).GetEnumerator());
                        }
                        return pending.Count == 0;
                    }, ct).ConfigureAwait(false);
                    if (complete) return new TreeScanResult(found, limited);
                }
            }
            finally
            {
                if (pending.Count != 0 && !dispatcher.HasShutdownStarted)
                    await executor.ExecuteAsync(dispatcher, () =>
                    { while (pending.Count != 0) pending.Dequeue().Dispose(); return true; }, CancellationToken.None).ConfigureAwait(false);
            }
        }

        public static IEnumerable<DependencyObject> EnumerateRoots(Dispatcher dispatcher)
        {
            dispatcher.VerifyAccess();
            foreach (PresentationSource source in PresentationSource.CurrentSources)
                if (source.Dispatcher == dispatcher && !source.IsDisposed && source.RootVisual is DependencyObject root)
                    yield return root;
        }

        public static IEnumerable<DependencyObject> EnumerateChildren(DependencyObject target, string tree)
        {
            target.VerifyAccess();
            if (tree == TreeKind.Visual)
            {
                if (target is Visual || target is Visual3D)
                    for (int index = 0; index < VisualTreeHelper.GetChildrenCount(target); index++)
                        yield return VisualTreeHelper.GetChild(target, index);
            }
            else if (tree == TreeKind.Logical)
            {
                foreach (object child in LogicalTreeHelper.GetChildren(target))
                    if (child is DependencyObject dependencyObject) yield return dependencyObject;
            }
            else throw new ProtocolException(ErrorCodes.InvalidParams, "Unknown tree kind.");
        }
    }
}
