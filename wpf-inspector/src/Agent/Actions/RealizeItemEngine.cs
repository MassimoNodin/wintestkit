using System;
using System.Collections.Generic;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Media;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Inspection;
using WinTestKit.Inspector.Agent.Inspection.Members;
using WinTestKit.Inspector.Agent.Query;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Actions
{
    internal static class RealizeItemEngine
    {
        internal static async Task<ActRealizeItemResult> ExecuteAsync(DispatcherExecutor executor, Dispatcher dispatcher,
            object target, ItemSearch search, ObjectRegistry registry, ObjectInspector inspector,
            DateTime deadline, int timeoutMs, CancellationToken ct)
        {
            ItemSearch.FromJson(search.ToJson());
            if (timeoutMs < 1 || timeoutMs > 2000) throw new ProtocolException(ErrorCodes.InvalidParams, "Invalid timeout.");
            DateTime end = DateTime.UtcNow.AddMilliseconds(timeoutMs);
            if (deadline < end) end = deadline;
            var context = new QueryPredicateContext(end);
            var match = search.Match;
            ValuePredicate? predicate = match.Kind == "index" ? null : new ValuePredicate(new Predicate
            {
                Kind = match.Kind, Path = match.Path, Value = match.Value, Pattern = match.Pattern, Flags = match.Flags
            }, inspector, registry);
            int visited = 0, first = -1, matches = 0, count = 0;
            bool done = false;
            while (!done)
            {
                ct.ThrowIfCancellationRequested();
                if (context.Remaining <= TimeSpan.Zero)
                {
                    if (first < 0) throw ProtocolException.Deadline("Item search deadline reached.");
                    break;
                }
                done = await executor.ExecuteAsync(dispatcher, token =>
                {
                    if (!(target is ItemsControl control)) throw new ProtocolException(ErrorCodes.ActionUnsupported, "Target is not an ItemsControl.");
                    count = control.Items.Count;
                    int stop = Math.Min(Math.Min(count, search.MaxItems), visited + 64);
                    while (visited < stop && context.Remaining > TimeSpan.Zero &&
                        (first < 0 || context.Remaining > TimeSpan.FromMilliseconds(50)))
                    {
                        token.ThrowIfCancellationRequested();
                        object item = control.Items[visited];
                        bool found;
                        try { found = predicate == null ? visited == match.Index : item != null && predicate.MatchesObject(item, dispatcher, context); }
                        catch (OperationCanceledException) when (context.Remaining <= TimeSpan.Zero && !token.IsCancellationRequested)
                        { throw ProtocolException.Deadline("Item search deadline reached."); }
                        catch (ProtocolException error) when (error.Code == ErrorCodes.RegexTimeout && context.Remaining <= TimeSpan.Zero)
                        { throw ProtocolException.Deadline("Item search deadline reached."); }
                        if (found) { if (first < 0) first = visited; matches++; }
                        visited++;
                        if (predicate == null && found) return true;
                    }
                    return visited >= count || visited >= search.MaxItems ||
                        first >= 0 && context.Remaining <= TimeSpan.FromMilliseconds(50);
                }, ct).ConfigureAwait(false);
            }
            if (first < 0)
            {
                if (visited < count && visited >= search.MaxItems) throw new ProtocolException(ErrorCodes.LimitExceeded, "Item search budget exhausted.");
                throw new ProtocolException(ErrorCodes.NotFound, "No matching item.");
            }
            bool performed = false;
            while (true)
            {
                ct.ThrowIfCancellationRequested();
                if (context.Remaining <= TimeSpan.Zero) throw ProtocolException.Deadline("Item realization deadline reached.");
                ObjectRef? result = await executor.ExecuteAsync(dispatcher, token =>
                {
                    var control = (ItemsControl)target;
                    if (first >= control.Items.Count) throw new ProtocolException(ErrorCodes.NotFound, "Item is no longer available.");
                    var container = control.ItemContainerGenerator.ContainerFromIndex(first);
                    if (container == null)
                    {
                        object item = control.Items[first];
                        if (!performed)
                        {
                            if (control is DataGrid grid) grid.ScrollIntoView(item);
                            else if (control is ListBox list) list.ScrollIntoView(item);
                            else
                            {
                                control.UpdateLayout();
                                BringIndexIntoView(control, first);
                            }
                            performed = true;
                        }
                        control.UpdateLayout();
                        container = control.ItemContainerGenerator.ContainerFromIndex(first);
                    }
                    return container == null ? null : registry.Register(container, dispatcher, inspector.DescribeType(container.GetType()));
                }, ct).ConfigureAwait(false);
                if (result != null) return new ActRealizeItemResult { Outcome = performed ? ActionOutcome.Performed : ActionOutcome.NoChange, Handle = result, Warning = matches > 1 ? new MatchWarning { Count = matches } : null };
                await dispatcher.InvokeAsync(() => { }, DispatcherPriority.Background, ct).Task.ConfigureAwait(false);
            }
        }

        private static void BringIndexIntoView(ItemsControl control, int index)
        {
            var pending = new Stack<DependencyObject>();
            pending.Push(control);
            if (control.Template?.FindName("PART_Popup", control) is Popup popup && popup.Child != null)
                pending.Push(popup.Child);
            int visited = 0;
            while (pending.Count > 0 && visited++ < 4096)
            {
                DependencyObject current = pending.Pop();
                if (current is VirtualizingPanel panel && ItemsControl.GetItemsOwner(panel) == control)
                {
                    MethodInfo? bring = panel.GetType().GetMethod("BringIndexIntoView", BindingFlags.Instance | BindingFlags.NonPublic);
                    bring?.Invoke(panel, new object[] { index });
                    return;
                }
                if (!(current is Visual) && !(current is System.Windows.Media.Media3D.Visual3D)) continue;
                for (int child = VisualTreeHelper.GetChildrenCount(current) - 1; child >= 0; child--)
                    pending.Push(VisualTreeHelper.GetChild(current, child));
            }
        }
    }
}
