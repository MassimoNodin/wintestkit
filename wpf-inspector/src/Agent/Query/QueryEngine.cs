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
                Count = result.Finished ? (int?)Math.Min(locator.Index.HasValue ? result.Matches.Count : result.Count, 10000) : null,
                Unreadable = result.Summary
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
            /// <summary>Candidates a predicate could not read, by reason; they are non-matches, never failures.</summary>
            internal int Unreadable;
            internal readonly SortedDictionary<string, int> Reasons = new SortedDictionary<string, int>(StringComparer.Ordinal);
            internal QueryUnreadable? Summary => Unreadable == 0 ? null : new QueryUnreadable { Count = Unreadable, Reasons = new Dictionary<string, int>(Reasons) };
            internal void NoteUnreadable(string reason)
            {
                Unreadable++;
                Reasons.TryGetValue(reason, out int seen);
                Reasons[reason] = seen + 1;
            }
        }

        /// <summary>
        /// The reason a predicate could not read an element, or null when the error is something else. A search treats these
        /// as a non-match: a window holds elements of every type, and one of them failing a read must not hide the others.
        /// </summary>
        private static string? UnreadableReason(ProtocolException error)
        {
            if (error.Code == ErrorCodes.MemberAmbiguous) return "ambiguous";
            if (error.Code != ErrorCodes.ValueUnreadable) return null;
            string status = error.Details != null && error.Details.TryGet("status", out JsonNode? node) && node is JsonStringNode text ? text.Value : "other";
            return Array.IndexOf(QueryUnreadable.KnownReasons, status) >= 0 ? status : "other";
        }
        private sealed class Frame
        {
            internal readonly IEnumerator<object> Children;
            internal readonly int Depth;
            internal Frame(IEnumerator<object> children, int depth) { Children = children; Depth = depth; }
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
            internal object? Scoped;
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
                if (!registry.TryGet(handle.ObjectId, handle.Generation, out object target, out scopedDispatcher) || !(target is DependencyObject || WinFormsNative.IsWinFormsObject(target)))
                    throw new ProtocolException(ErrorCodes.ObjectStale, "Unknown or stale object handle.");
                ObjectRef actual = registry.Register(target, scopedDispatcher, TypeInfoBuilder.Build(target.GetType()));
                if (actual.SessionId != handle.SessionId) throw new ProtocolException(ErrorCodes.ObjectStale, "Unknown or stale object handle.");
                scan.Scoped = target;
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
            bool objectTree = locator.Tree == "objects";
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
                            object? root = scan.Scoped ?? (source!.IsDisposed ? null : source.RootVisual as DependencyObject);
                            if (root != null) scan.Stack.Push(new Frame(Single(root).GetEnumerator(), 0));
                            scan.Initialized = true;
                        }
                        context.Objects.Clear();
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
                            object current = frame.Children.Current;
                            // A WinForms control hosted in WPF lives on its host's thread, and a form's controls on the form's: only WPF objects can belong to another dispatcher.
                            if (current is DependencyObject owned && owned.Dispatcher != dispatcher || !scan.Seen.Add(current)) continue;
                            result.Visited++;
                            scan.RequestVisited++;
                            // The object tree counts its own levels; peers and tree depth modes apply to the visual and logical trees.
                            bool peerDepth = !objectTree && locator.DepthMode == "peers";
                            // A WinForms object has no peer, but it is a level of its own tree.
                            bool hasPeer = peerDepth && frame.Depth > 0 && (current is DependencyObject peered ? PeerIdentity.GetPeer(peered) != null : true);
                            int currentDepth = peerDepth && frame.Depth > 0 ? frame.Depth - 1 + (hasPeer ? 1 : 0) : frame.Depth;
                            if (currentDepth > locator.Depth) continue;
                            // Predicates run cheapest first and stop at the first one that rejects the element: a mismatch, or a value
                            // that cannot be read (never compared, so a redacted value cannot leak). The latter is counted for the result.
                            bool matches = true;
                            string? unreadable = null;
                            foreach (IQueryPredicate predicate in scan.Cheap.Concat(scan.Deferred))
                            {
                                try { if (!predicate.Matches(current, dispatcher, context)) { matches = false; break; } }
                                catch (ProtocolException error) when (UnreadableReason(error) != null) { matches = false; unreadable = UnreadableReason(error); break; }
                            }
                            if (unreadable != null) result.NoteUnreadable(unreadable);
                            if (matches)
                            {
                                int matchIndex = result.Count++;
                                if ((!locator.Index.HasValue || locator.Index.Value == matchIndex) && (find ? result.Matches.Count == 0 : result.Matches.Count < locator.Limit))
                                    result.Matches.Add(registry.Register(current, dispatcher, TypeInfoBuilder.Build(current.GetType())));
                                else if (!find && (!locator.Index.HasValue || locator.Index.Value == matchIndex)) result.Overflow = true;
                            }
                            if ((objectTree || locator.DepthMode == "tree") ? currentDepth < locator.Depth : !(hasPeer && currentDepth == locator.Depth))
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
        private static IEnumerable<object> Single(object target) { yield return target; }

        /// <summary>
        /// The children of a searched object. A WinForms control or tool strip item has its Controls or items whatever the tree kind;
        /// a WPF WindowsFormsHost has, besides its WPF children, the WinForms control it hosts, so a query reaches it from a WPF window.
        /// </summary>
        private static IEnumerable<object> Children(object target, string tree)
        {
            if (!(target is DependencyObject element))
            {
                // A snapshot: the traversal pauses between slices, and the control may add or remove children meanwhile.
                foreach (object child in new List<object>(WinFormsNative.Children(target))) yield return child;
                yield break;
            }
            if (tree == "objects")
            {
                element.VerifyAccess();
                foreach (DependencyObject child in ObjectTree.Children(element)) yield return child;
            }
            if (tree == "visual" || tree == "combined")
                foreach (DependencyObject child in TreeWalker.EnumerateChildren(element, TreeKind.Visual)) yield return child;
            if (tree == "logical" || tree == "combined")
                foreach (DependencyObject child in TreeWalker.EnumerateChildren(element, TreeKind.Logical)) yield return child;
            object? hosted = WinFormsNative.HostedChild(element);
            if (hosted != null) yield return hosted;
        }
    }
}
