using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Media;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Inspection;
using WinTestKit.Inspector.Agent.Inspection.Members;
using WinTestKit.Inspector.Agent.Mapping;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Query
{
    internal sealed class QueryEngine
    {
        private readonly DispatcherExecutor executor;
        private readonly ObjectRegistry registry;
        private readonly ObjectInspector inspector;
        internal QueryEngine(DispatcherExecutor executor, ObjectRegistry registry, ObjectInspector? inspector = null)
        { this.executor = executor; this.registry = registry; this.inspector = inspector ?? new ObjectInspector(); }

        internal Task<QueryFindResult> FindAsync(Locator locator, DateTime deadline, CancellationToken ct) =>
            FindAsync(locator, deadline, ProtocolLimits.ScanMaxMs, ct);
        internal async Task<QueryFindResult> FindAsync(Locator locator, DateTime deadline, int timeoutMs, CancellationToken ct)
        {
            Search result = await RunAsync(locator, deadline, timeoutMs, true, ct).ConfigureAwait(false);
            if (result.Matches.Count == 0)
                throw new ProtocolException(result.Finished ? ErrorCodes.NotFound : ErrorCodes.LimitExceeded,
                    result.Finished ? "No matching object." : "Traversal budget exhausted.");
            return new QueryFindResult { Match = result.Matches[0], Warning = !locator.Index.HasValue && result.Count > 1 ? new MatchWarning { Count = result.Count } : null };
        }
        internal Task<QueryFindAllResult> FindAllAsync(Locator locator, DateTime deadline, CancellationToken ct) =>
            FindAllAsync(locator, deadline, ProtocolLimits.ScanMaxMs, ct);
        internal async Task<QueryFindAllResult> FindAllAsync(Locator locator, DateTime deadline, int timeoutMs, CancellationToken ct)
        {
            Search result = await RunAsync(locator, deadline, timeoutMs, false, ct).ConfigureAwait(false);
            return new QueryFindAllResult
            {
                Matches = result.Matches,
                Complete = result.Finished && !result.Overflow,
                Count = result.Finished ? (int?)(locator.Index.HasValue ? result.Matches.Count : result.Count) : null
            };
        }
        private sealed class Search
        {
            internal readonly List<ObjectRef> Matches = new List<ObjectRef>();
            internal int Count;
            internal int Visited;
            internal bool Finished;
            internal bool Overflow;
        }
        private sealed class Frame
        {
            internal readonly IEnumerator<DependencyObject> Children;
            internal readonly int Depth;
            internal Frame(IEnumerator<DependencyObject> children, int depth) { Children = children; Depth = depth; }
        }
        private async Task<Search> RunAsync(Locator locator, DateTime deadline, int timeoutMs, bool find, CancellationToken ct)
        {
            Locator.FromJson(locator.ToJson());
            if (timeoutMs < 1 || timeoutMs > ProtocolLimits.ScanMaxMs) throw new ProtocolException(ErrorCodes.InvalidParams, "Invalid timeout.");
            DateTime budgetDeadline = DateTime.UtcNow.AddMilliseconds(timeoutMs);
            if (deadline < budgetDeadline) budgetDeadline = deadline;
            var context = new QueryPredicateContext(budgetDeadline);
            var uiaPredicates = new List<IQueryPredicate>();
            var predicates = new List<IQueryPredicate>();
            foreach (Predicate predicate in locator.Predicates)
            {
                var compiled = PredicateFactory.Create(predicate, inspector, registry);
                if (predicate.Kind == "assignableTo" || predicate.Path != null && predicate.Path.Count == 1 && (predicate.Path[0].Kind == "uia" || predicate.Path[0].Kind == "type")) uiaPredicates.Add(compiled);
                else predicates.Add(compiled);
            }
            var sources = new List<PresentationSource>();
            DependencyObject? scoped = null;
            Dispatcher? scopedDispatcher = null;
            if (locator.Scope.Kind == "allRoots")
            {
                foreach (PresentationSource source in PresentationSource.CurrentSources) sources.Add(source);
            }
            else
            {
                ObjectRef handle = locator.Scope.Handle!;
                if (!registry.TryGet(handle.ObjectId, handle.Generation, out object target, out scopedDispatcher) || !(target is DependencyObject dependencyObject))
                    throw new ProtocolException(ErrorCodes.ObjectStale, "Unknown or stale object handle.");
                ObjectRef actual = registry.Register(target, scopedDispatcher, TypeInfoBuilder.Build(target.GetType()));
                if (actual.SessionId != handle.SessionId) throw new ProtocolException(ErrorCodes.ObjectStale, "Unknown or stale object handle.");
                scoped = dependencyObject;
                if (locator.Scope.Kind == "window" && !(scoped is Window))
                    throw new ProtocolException(ErrorCodes.InvalidParams, "Window scope requires a window root.");
            }
            var result = new Search();
            var seen = new HashSet<object>(ReferenceComparer.Instance);
            int roots = scoped != null ? 1 : sources.Count;
            for (int rootIndex = 0; rootIndex < roots; rootIndex++)
            {
                ct.ThrowIfCancellationRequested();
                if (DateTime.UtcNow >= budgetDeadline) return result;
                PresentationSource? source = scoped == null ? sources[rootIndex] : null;
                Dispatcher dispatcher = scopedDispatcher ?? source!.Dispatcher;
                if (dispatcher.HasShutdownStarted || dispatcher.HasShutdownFinished) continue;
                var stack = new Stack<Frame>();
                bool initialized = false;
                bool done = false;
                while (!done)
                {
                    if (DateTime.UtcNow >= budgetDeadline) return result;
                    done = await executor.ExecuteAsync(dispatcher, token =>
                    {
                        if (!initialized)
                        {
                            DependencyObject? root = scoped ?? (source!.IsDisposed ? null : source.RootVisual as DependencyObject);
                            if (root != null) stack.Push(new Frame(Single(root).GetEnumerator(), 0));
                            initialized = true;
                        }
                        Stopwatch slice = Stopwatch.StartNew();
                        int steps = 0;
                        while (stack.Count > 0 && steps < ProtocolLimits.TraversalSliceObjects && slice.ElapsedMilliseconds < ProtocolLimits.TraversalSliceMs)
                        {
                            token.ThrowIfCancellationRequested();
                            if (DateTime.UtcNow >= budgetDeadline) return true;
                            Frame frame = stack.Peek();
                            if (!frame.Children.MoveNext()) { stack.Pop().Children.Dispose(); continue; }
                            steps++;
                            DependencyObject current = frame.Children.Current;
                            if (current.Dispatcher != dispatcher || !seen.Add(current)) continue;
                            if (result.Visited >= ProtocolLimits.ScanMaxObjects) return true;
                            result.Visited++;
                            bool matches = true;
                            foreach (IQueryPredicate predicate in uiaPredicates)
                                if (!predicate.Matches(current, context)) { matches = false; break; }
                            ProtocolException? unreadable = null;
                            if (matches) foreach (IQueryPredicate predicate in predicates)
                            {
                                try { if (!predicate.Matches(current, context)) matches = false; }
                                catch (ProtocolException error) when (error.Code == ErrorCodes.ValueUnreadable) { unreadable = unreadable ?? error; }
                            }
                            if (unreadable != null) throw unreadable;
                            if (matches)
                            {
                                int matchIndex = result.Count++;
                                if ((!locator.Index.HasValue || locator.Index.Value == matchIndex) && (find ? result.Matches.Count == 0 : result.Matches.Count < locator.Limit))
                                    result.Matches.Add(registry.Register(current, dispatcher, TypeInfoBuilder.Build(current.GetType())));
                                else if (!find && (!locator.Index.HasValue || locator.Index.Value == matchIndex)) result.Overflow = true;
                            }
                            if (frame.Depth < locator.Depth) stack.Push(new Frame(Children(current, locator.Tree).GetEnumerator(), frame.Depth + 1));
                        }
                        return stack.Count == 0 || result.Visited >= ProtocolLimits.ScanMaxObjects || DateTime.UtcNow >= budgetDeadline;
                    }, ct).ConfigureAwait(false);
                }
                if (stack.Count != 0) return result;
            }
            result.Finished = true;
            return result;
        }
        private static IEnumerable<DependencyObject> Single(DependencyObject target) { yield return target; }
        private static IEnumerable<DependencyObject> Children(DependencyObject target, string tree)
        {
            if (tree == "visual" || tree == "combined")
                foreach (DependencyObject child in TreeWalker.EnumerateChildren(target, TreeKind.Visual)) yield return child;
            if (tree == "logical" || tree == "combined")
                foreach (DependencyObject child in TreeWalker.EnumerateChildren(target, TreeKind.Logical)) yield return child;
        }
    }
}
