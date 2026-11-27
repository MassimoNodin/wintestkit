using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Security.Cryptography;
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
        private readonly object gate = new object();
        private readonly Dictionary<string, Scan> suspended = new Dictionary<string, Scan>(StringComparer.Ordinal);
        internal QueryEngine(DispatcherExecutor executor, ObjectRegistry registry, ObjectInspector? inspector = null)
        { this.executor = executor; this.registry = registry; this.inspector = inspector ?? new ObjectInspector(); }

        /// <summary>Number of traversals waiting for a continuation request.</summary>
        internal int SuspendedCount { get { lock (gate) { Prune(); return suspended.Count; } } }

        internal Task<QueryFindResult> FindAsync(Locator locator, DateTime deadline, CancellationToken ct) =>
            FindAsync(locator, deadline, ProtocolLimits.ScanMaxMs, ct);
        internal async Task<QueryFindResult> FindAsync(Locator locator, DateTime deadline, int timeoutMs, CancellationToken ct)
        {
            Search result = await RunAsync(locator, deadline, timeoutMs, true, null, ct).ConfigureAwait(false);
            if (result.Matches.Count == 0)
                throw result.Finished ? new ProtocolException(ErrorCodes.NotFound, "No matching object.") :
                    result.Visited >= ProtocolLimits.ScanMaxObjects ? new ProtocolException(ErrorCodes.LimitExceeded, "Traversal budget exhausted.") :
                    ProtocolException.Deadline("Traversal budget exhausted.");
            return new QueryFindResult { Match = result.Matches[0], Warning = !locator.Index.HasValue && result.Count > 1 ? new MatchWarning { Count = result.Count } : null };
        }
        internal Task<QueryFindAllResult> FindAllAsync(Locator locator, DateTime deadline, CancellationToken ct) =>
            FindAllAsync(locator, deadline, ProtocolLimits.ScanMaxMs, ct);
        internal Task<QueryFindAllResult> FindAllAsync(Locator locator, DateTime deadline, int timeoutMs, CancellationToken ct) =>
            FindAllAsync(locator, deadline, timeoutMs, null, ct);

        /// <summary>
        /// Searches for every match. A traversal that cannot finish inside one request's time or object budget is suspended and
        /// returned as an incomplete result with a continuation token; presenting the token with the same locator resumes it
        /// where it stopped. A result is either complete, ends at the 200-match limit, or carries a continuation; running out of
        /// the total object budget is a limit error.
        /// </summary>
        internal async Task<QueryFindAllResult> FindAllAsync(Locator locator, DateTime deadline, int timeoutMs, string? continuation, CancellationToken ct)
        {
            Search result = await RunAsync(locator, deadline, timeoutMs, false, continuation, ct).ConfigureAwait(false);
            if (result.Continuation != null)
                return new QueryFindAllResult { Matches = new List<ObjectRef>(), Complete = false, Continuation = result.Continuation };
            if (!result.Finished && result.Visited >= ProtocolLimits.ScanMaxObjects && result.Matches.Count < locator.Limit)
                throw new ProtocolException(ErrorCodes.LimitExceeded, "Traversal budget exhausted.");
            return new QueryFindAllResult
            {
                Matches = result.Matches,
                Complete = result.Finished && !result.Overflow,
                Count = result.Finished ? (int?)Math.Min(locator.Index.HasValue ? result.Matches.Count : result.Count, 10000) : null
            };
        }
        private sealed class Search
        {
            internal readonly List<ObjectRef> Matches = new List<ObjectRef>();
            internal int Count;
            internal int Visited;
            internal bool Finished;
            internal bool Overflow;
            internal string? Continuation;
        }
        private sealed class Frame
        {
            internal readonly IEnumerator<DependencyObject> Children;
            internal readonly int Depth;
            internal Frame(IEnumerator<DependencyObject> children, int depth) { Children = children; Depth = depth; }
        }
        /// <summary>The state of one traversal, kept between the requests that make it up.</summary>
        private sealed class Scan
        {
            internal string Binding = "";
            internal DateTime Expires;
            internal readonly Search Result = new Search();
            internal readonly List<IQueryPredicate> Cheap = new List<IQueryPredicate>();
            internal readonly List<IQueryPredicate> Deferred = new List<IQueryPredicate>();
            internal readonly List<PresentationSource> Sources = new List<PresentationSource>();
            internal DependencyObject? Scoped;
            internal Dispatcher? ScopedDispatcher;
            internal readonly HashSet<object> Seen = new HashSet<object>(ReferenceComparer.Instance);
            internal Stack<Frame> Stack = new Stack<Frame>();
            internal int RootIndex;
            internal bool Initialized;
            internal int RequestVisited;
            internal int Roots => Scoped != null ? 1 : Sources.Count;
        }

        private static string Binding(Locator locator) => Convert.ToBase64String(StrictJson.Serialize(locator.ToJson()));

        private Scan Begin(Locator locator)
        {
            var scan = new Scan { Binding = Binding(locator) };
            var deferred = new List<IQueryPredicate>();
            foreach (Predicate predicate in locator.Predicates)
            {
                IQueryPredicate compiled = PredicateFactory.Create(predicate, inspector, registry);
                // Type and identity predicates cannot be unreadable, so a mismatch rejects an element before any member is read.
                if (predicate.Kind == "assignableTo" || predicate.Path != null && predicate.Path.Count == 1 && (predicate.Path[0].Kind == "uia" || predicate.Path[0].Kind == "type")) scan.Cheap.Add(compiled);
                else deferred.Add(compiled);
            }
            // Cheaper member reads first; an unreadable value is still reported whatever the other predicates say.
            scan.Deferred.AddRange(deferred.Select((predicate, position) => new { predicate, position }).OrderBy(x => x.predicate.Cost).ThenBy(x => x.position).Select(x => x.predicate));
            if (locator.Scope.Kind == "allRoots")
            {
                foreach (PresentationSource source in PresentationSource.CurrentSources) scan.Sources.Add(source);
            }
            else
            {
                ObjectRef handle = locator.Scope.Handle!;
                Dispatcher? scopedDispatcher = null;
                if (!registry.TryGet(handle.ObjectId, handle.Generation, out object target, out scopedDispatcher) || !(target is DependencyObject dependencyObject))
                    throw new ProtocolException(ErrorCodes.ObjectStale, "Unknown or stale object handle.");
                ObjectRef actual = registry.Register(target, scopedDispatcher, TypeInfoBuilder.Build(target.GetType()));
                if (actual.SessionId != handle.SessionId) throw new ProtocolException(ErrorCodes.ObjectStale, "Unknown or stale object handle.");
                scan.Scoped = dependencyObject;
                scan.ScopedDispatcher = scopedDispatcher;
                if (locator.Scope.Kind == "window" && !(scan.Scoped is Window))
                    throw new ProtocolException(ErrorCodes.InvalidParams, "Window scope requires a window root.");
            }
            return scan;
        }

        private Scan Resume(string token, Locator locator)
        {
            string binding = Binding(locator);
            lock (gate)
            {
                Prune();
                if (!suspended.TryGetValue(token, out Scan? scan) || scan.Binding != binding)
                    throw new ProtocolException(ErrorCodes.InvalidPageToken, "Invalid or expired continuation.");
                suspended.Remove(token);
                return scan;
            }
        }

        private string Suspend(Scan scan)
        {
            lock (gate)
            {
                Prune();
                while (suspended.Count >= ProtocolLimits.MaxContinuations)
                {
                    string oldest = suspended.OrderBy(entry => entry.Value.Expires).First().Key;
                    suspended.Remove(oldest);
                }
                byte[] bytes = new byte[24];
                string token;
                do
                {
                    using (RandomNumberGenerator rng = RandomNumberGenerator.Create()) rng.GetBytes(bytes);
                    token = Convert.ToBase64String(bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_');
                } while (suspended.ContainsKey(token));
                scan.Expires = DateTime.UtcNow.AddMilliseconds(ProtocolLimits.PageTokenTtlMs);
                suspended.Add(token, scan);
                return token;
            }
        }

        private void Prune()
        {
            DateTime now = DateTime.UtcNow;
            foreach (string key in suspended.Where(entry => entry.Value.Expires <= now).Select(entry => entry.Key).ToList()) suspended.Remove(key);
        }

        private async Task<Search> RunAsync(Locator locator, DateTime deadline, int timeoutMs, bool find, string? continuation, CancellationToken ct)
        {
            Locator.FromJson(locator.ToJson());
            if (timeoutMs < 1 || timeoutMs > ProtocolLimits.ScanMaxMs) throw new ProtocolException(ErrorCodes.InvalidParams, "Invalid timeout.");
            if (continuation != null && find) throw new ProtocolException(ErrorCodes.InvalidParams, "Only findAll continues.");
            lock (gate) Prune();
            DateTime budgetDeadline = DateTime.UtcNow.AddMilliseconds(timeoutMs);
            if (deadline < budgetDeadline) budgetDeadline = deadline;
            using (var context = new QueryPredicateContext(budgetDeadline))
            {
                Scan scan = continuation != null ? Resume(continuation, locator) : Begin(locator);
                Search result = scan.Result;
                scan.RequestVisited = 0;
                result.Continuation = null;
                bool resumable = await TraverseAsync(scan, locator, find, context, budgetDeadline, ct).ConfigureAwait(false);
                if (resumable && !find && result.Matches.Count < locator.Limit) result.Continuation = Suspend(scan);
                return result;
            }
        }

        /// <summary>Runs the traversal until it finishes or the request budget ends; true when it stopped early and can be resumed.</summary>
        private async Task<bool> TraverseAsync(Scan scan, Locator locator, bool find, QueryPredicateContext context, DateTime budgetDeadline, CancellationToken ct)
        {
            Search result = scan.Result;
            int roots = scan.Roots;
            while (scan.RootIndex < roots)
            {
                ct.ThrowIfCancellationRequested();
                if (DateTime.UtcNow >= budgetDeadline) return true;
                PresentationSource? source = scan.Scoped == null ? scan.Sources[scan.RootIndex] : null;
                Dispatcher dispatcher = scan.ScopedDispatcher ?? source!.Dispatcher;
                if (dispatcher.HasShutdownStarted || dispatcher.HasShutdownFinished) { scan.RootIndex++; scan.Initialized = false; continue; }
                bool done = false;
                while (!done)
                {
                    if (DateTime.UtcNow >= budgetDeadline) return true;
                    done = await executor.ExecuteAsync(dispatcher, token =>
                    {
                        if (!scan.Initialized)
                        {
                            DependencyObject? root = scan.Scoped ?? (source!.IsDisposed ? null : source.RootVisual as DependencyObject);
                            if (root != null) scan.Stack.Push(new Frame(Single(root).GetEnumerator(), 0));
                            scan.Initialized = true;
                        }
                        Stopwatch slice = Stopwatch.StartNew();
                        int steps = 0;
                        while (scan.Stack.Count > 0 && steps < ProtocolLimits.TraversalSliceObjects && slice.ElapsedMilliseconds < ProtocolLimits.TraversalSliceMs)
                        {
                            token.ThrowIfCancellationRequested();
                            if (DateTime.UtcNow >= budgetDeadline || scan.RequestVisited >= ProtocolLimits.ScanMaxObjects) return true;
                            if (result.Visited >= ProtocolLimits.ScanTotalMaxObjects)
                                throw new ProtocolException(ErrorCodes.LimitExceeded, "Traversal budget exhausted.");
                            Frame frame = scan.Stack.Peek();
                            if (!frame.Children.MoveNext()) { scan.Stack.Pop().Children.Dispose(); continue; }
                            steps++;
                            DependencyObject current = frame.Children.Current;
                            if (current.Dispatcher != dispatcher || !scan.Seen.Add(current)) continue;
                            result.Visited++;
                            scan.RequestVisited++;
                            bool hasPeer = locator.DepthMode == "peers" && frame.Depth > 0 && PeerIdentity.GetPeer(current) != null;
                            int currentDepth = locator.DepthMode == "peers" && frame.Depth > 0 ? frame.Depth - 1 + (hasPeer ? 1 : 0) : frame.Depth;
                            if (currentDepth > locator.Depth) continue;
                            bool matches = true;
                            foreach (IQueryPredicate predicate in scan.Cheap)
                                if (!predicate.Matches(current, context)) { matches = false; break; }
                            ProtocolException? unreadable = null;
                            if (matches) foreach (IQueryPredicate predicate in scan.Deferred)
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
                            if (locator.DepthMode == "tree" ? currentDepth < locator.Depth : !(hasPeer && currentDepth == locator.Depth))
                                scan.Stack.Push(new Frame(Children(current, locator.Tree).GetEnumerator(), currentDepth + 1));
                        }
                        return scan.Stack.Count == 0 || scan.RequestVisited >= ProtocolLimits.ScanMaxObjects || DateTime.UtcNow >= budgetDeadline;
                    }, ct).ConfigureAwait(false);
                }
                if (scan.Stack.Count != 0) return true;
                scan.RootIndex++;
                scan.Initialized = false;
            }
            result.Finished = true;
            return false;
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
