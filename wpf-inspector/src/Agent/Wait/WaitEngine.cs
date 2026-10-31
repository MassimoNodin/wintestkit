using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Media;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Inspection;
using WinTestKit.Inspector.Agent.Inspection.Members;
using WinTestKit.Inspector.Agent.Mapping;
using WinTestKit.Inspector.Agent.Query;
using WinTestKit.Inspector.Agent.State;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Wait
{
    internal sealed class WaitEngine
    {
        private readonly QueryEngine query;
        private readonly DispatcherExecutor executor;
        private readonly ObjectRegistry registry;
        private readonly ObjectInspector inspector;
        private readonly IPeerRuntimeIdAdapter adapter;

        internal WaitEngine(QueryEngine query, DispatcherExecutor executor, ObjectRegistry registry, ObjectInspector inspector, IPeerRuntimeIdAdapter adapter)
        { this.query = query; this.executor = executor; this.registry = registry; this.inspector = inspector; this.adapter = adapter; }

        internal async Task<WaitUntilResult> UntilAsync(WaitCondition condition, DateTime deadline, int timeoutMs, CancellationToken ct)
        {
            WaitCondition.FromJson(condition.ToJson());
            if (timeoutMs < 1 || timeoutMs > ProtocolLimits.RequestTimeoutMs) throw new ProtocolException(ErrorCodes.InvalidParams, "Invalid timeout.");
            DateTime end = DateTime.UtcNow.AddMilliseconds(timeoutMs);
            if (deadline < end) end = deadline;
            var signal = new SemaphoreSlim(0, 1);
            var roots = new List<(UIElement Element, Dispatcher Dispatcher)>();
            EventHandler changed = (sender, args) => { if (signal.CurrentCount == 0) { try { signal.Release(); } catch (SemaphoreFullException) { } } };
            try
            {
                ObjectRef? scope = condition.Locator.Scope.Handle;
                if (scope != null && registry.TryGet(scope.ObjectId, scope.Generation, out object scoped, out Dispatcher scopeDispatcher) && scoped is UIElement element)
                {
                    await executor.ExecuteAsync(scopeDispatcher, () => { element.LayoutUpdated += changed; return true; }, ct).ConfigureAwait(false);
                    roots.Add((element, scopeDispatcher));
                }
                else if (scope == null)
                {
                    var sources = new List<PresentationSource>();
                    foreach (PresentationSource source in PresentationSource.CurrentSources) sources.Add(source);
                    foreach (PresentationSource source in sources)
                    {
                        Dispatcher dispatcher = source.Dispatcher;
                        if (dispatcher.HasShutdownStarted || dispatcher.HasShutdownFinished) continue;
                        UIElement? sourceRoot = await executor.ExecuteAsync(dispatcher, () =>
                        {
                            var visual = source.IsDisposed ? null : source.RootVisual as UIElement;
                            if (visual != null) visual.LayoutUpdated += changed;
                            return visual;
                        }, ct).ConfigureAwait(false);
                        if (sourceRoot != null) roots.Add((sourceRoot, dispatcher));
                    }
                }
                ValuePredicate? predicate = condition.Kind == "propertyEquals" ? new ValuePredicate(new Predicate { Kind = "equals", Path = condition.Path, Value = condition.Value }, inspector, registry) : null;
                bool first = true;
                while (first || DateTime.UtcNow < end)
                {
                    first = false;
                    ct.ThrowIfCancellationRequested();
                    int remaining = (int)Math.Ceiling((end - DateTime.UtcNow).TotalMilliseconds);
                    if (remaining <= 0) break;
                    QueryFindResult match;
                    try { match = await query.FindAsync(condition.Locator, end, Math.Min(remaining, ProtocolLimits.RequestTimeoutMs), ct).ConfigureAwait(false); }
                    catch (ProtocolException error) when (error.Code == ErrorCodes.NotFound) { match = null!; }
                    if (match != null)
                    {
                        if (!registry.TryGet(match.Match.ObjectId, match.Match.Generation, out object target, out Dispatcher dispatcher))
                            throw new ProtocolException(ErrorCodes.ObjectStale, "Unknown or stale object handle.");
                        var result = await executor.ExecuteAsync(dispatcher, () =>
                        {
                            var state = StateReader.Read(target, match.Match, adapter);
                            bool satisfied = condition.Kind == "exists" || condition.Kind == "visible" && state.Visible || condition.Kind == "enabled" && state.Enabled ||
                                predicate != null && predicate.Matches((DependencyObject)target, new QueryPredicateContext(end));
                            return satisfied ? new WaitUntilResult { Satisfied = true, Handle = match.Match, State = state } : null;
                        }, ct).ConfigureAwait(false);
                        if (result != null) return result;
                    }
                    remaining = (int)Math.Ceiling((end - DateTime.UtcNow).TotalMilliseconds);
                    if (remaining <= 0) break;
                    await signal.WaitAsync(Math.Min(100, remaining), ct).ConfigureAwait(false);
                    remaining = (int)Math.Ceiling((end - DateTime.UtcNow).TotalMilliseconds);
                    if (remaining > 0) await Task.Delay(Math.Min(15, remaining), ct).ConfigureAwait(false);
                }
                ct.ThrowIfCancellationRequested();
                return new WaitUntilResult { Satisfied = false };
            }
            finally
            {
                foreach (var root in roots)
                    if (!root.Dispatcher.HasShutdownStarted)
                        _ = root.Dispatcher.BeginInvoke(new Action(() => root.Element.LayoutUpdated -= changed), DispatcherPriority.Send);
            }
        }
    }
}
