using System;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Automation.Peers;
using System.Windows.Automation.Provider;
using System.Windows.Input;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Inspection;
using WinTestKit.Inspector.Protocol;
using WinTestKit.Inspector.Agent.Inspection.Members;

namespace WinTestKit.Inspector.Agent.Actions
{
    public static class ActionEngine
    {
        public static async Task<ActResult> ExecuteAsync(DispatcherExecutor executor, Dispatcher dispatcher, object target, ObjectRef handle, string method, DateTime deadline, int timeoutMs, CancellationToken ct, object? parameters = null)
        {
            DateTime end = DateTime.UtcNow.AddMilliseconds(timeoutMs);
            if (deadline < end) end = deadline;
            int remaining = (int)Math.Max(0, (end - DateTime.UtcNow).TotalMilliseconds);
            if (remaining == 0) throw ProtocolException.Deadline("Action deadline elapsed.");
            var timed = CancellationTokenSource.CreateLinkedTokenSource(ct);
            try
            {
                timed.CancelAfter(remaining);
                try
                {
                    string outcome = await executor.ExecuteAsync(dispatcher, token => Perform(target, method, token, parameters), timed.Token).ConfigureAwait(false);
                    return new ActResult { Outcome = outcome, Handle = handle };
                }
                catch (OperationCanceledException) when (!ct.IsCancellationRequested) { throw ProtocolException.Deadline("Action deadline elapsed."); }
                catch (ProtocolException error) when (error.Code == ErrorCodes.Timeout && DateTime.UtcNow >= end &&
                    (error.Details == null || !error.Details.TryGet("dispatcherBusy", out var marker) || !(marker is JsonBoolNode busy) || !busy.Value))
                { throw ProtocolException.Deadline("Action deadline elapsed."); }
            }
            finally { timed.Dispose(); }
        }

        private static string Perform(object target, string method, CancellationToken ct, object? parameters)
        {
            ct.ThrowIfCancellationRequested();
            if (!(target is UIElement element) || !element.IsEnabled) throw Unsupported();
            AutomationPeer? peer = PeerIdentity.GetPeer(element);
            if (peer == null) throw Unsupported();
            if (method == PipeMethods.ActFocus)
            {
                if (element.IsKeyboardFocused) return ActionOutcome.NoChange;
                if (!element.Focus() && Keyboard.Focus(element) != element) throw Unsupported();
                return ActionOutcome.Performed;
            }
            if (method == PipeMethods.ActBringIntoView)
            {
                if (!(element is FrameworkElement framework)) throw Unsupported();
                framework.BringIntoView();
                return ActionOutcome.Performed;
            }
            if (method == PipeMethods.ActScrollIntoView)
            {
                if (peer.GetPattern(PatternInterface.ScrollItem) is IScrollItemProvider scrollItem) scrollItem.ScrollIntoView();
                else if (element is FrameworkElement framework) framework.BringIntoView();
                else throw Unsupported();
                return ActionOutcome.Performed;
            }
            switch (method)
            {
                case PipeMethods.ActSetValue:
                    if (RedactionPolicy.IsProtectedIdentity(target) || !(parameters is ActSetValueParams text) || !(peer.GetPattern(PatternInterface.Value) is IValueProvider value) || value.IsReadOnly) throw Unsupported();
                    if (value.Value == text.Value) return ActionOutcome.NoChange;
                    value.SetValue(text.Value);
                    break;
                case PipeMethods.ActSetRange:
                    if (!(parameters is ActSetRangeParams rangeParams) || !(peer.GetPattern(PatternInterface.RangeValue) is IRangeValueProvider range) || range.IsReadOnly) throw Unsupported();
                    if (double.IsNaN(rangeParams.Value) || double.IsInfinity(rangeParams.Value) || rangeParams.Value < range.Minimum || rangeParams.Value > range.Maximum) throw new ProtocolException(ErrorCodes.InvalidParams, "Range value is invalid.");
                    if (range.Value == rangeParams.Value) return ActionOutcome.NoChange;
                    range.SetValue(rangeParams.Value);
                    break;
                case PipeMethods.ActScroll:
                    if (!(parameters is ActScrollParams scrollParams) || !(peer.GetPattern(PatternInterface.Scroll) is IScrollProvider scroll)) throw Unsupported();
                    var horizontal = ParseScroll(scrollParams.Horizontal);
                    var vertical = ParseScroll(scrollParams.Vertical);
                    if (horizontal == System.Windows.Automation.ScrollAmount.NoAmount && vertical == System.Windows.Automation.ScrollAmount.NoAmount) return ActionOutcome.NoChange;
                    if ((horizontal != System.Windows.Automation.ScrollAmount.NoAmount && !scroll.HorizontallyScrollable) || (vertical != System.Windows.Automation.ScrollAmount.NoAmount && !scroll.VerticallyScrollable)) throw Unsupported();
                    scroll.Scroll(horizontal, vertical);
                    break;
                case PipeMethods.ActInvoke:
                    if (!(peer.GetPattern(PatternInterface.Invoke) is IInvokeProvider invoke)) throw Unsupported();
                    // Normal priority runs promptly after validation without retaining executor admission during modal loops.
                    element.Dispatcher.BeginInvoke(DispatcherPriority.Normal, new Action(() =>
                    {
                        // Catch provider failures here, not exceptions from separately dispatched application handlers.
                        try { invoke.Invoke(); }
                        catch (Exception) { }
                    }));
                    break;
                case PipeMethods.ActToggle:
                    if (!(peer.GetPattern(PatternInterface.Toggle) is IToggleProvider toggle)) throw Unsupported();
                    toggle.Toggle();
                    break;
                case PipeMethods.ActExpand:
                case PipeMethods.ActCollapse:
                    if (!(peer.GetPattern(PatternInterface.ExpandCollapse) is IExpandCollapseProvider expand)) throw Unsupported();
                    bool expanding = method == PipeMethods.ActExpand;
                    if (expand.ExpandCollapseState == (expanding ? System.Windows.Automation.ExpandCollapseState.Expanded : System.Windows.Automation.ExpandCollapseState.Collapsed)) return ActionOutcome.NoChange;
                    if (expanding) expand.Expand(); else expand.Collapse();
                    break;
                case PipeMethods.ActSelect:
                    if (!(peer.GetPattern(PatternInterface.SelectionItem) is ISelectionItemProvider select)) throw Unsupported();
                    if (select.IsSelected) return ActionOutcome.NoChange;
                    select.Select();
                    break;
                default: throw Unsupported();
            }
            return ActionOutcome.Performed;
        }

        private static System.Windows.Automation.ScrollAmount ParseScroll(string amount)
        {
            switch (amount)
            {
                case ScrollAmount.None: return System.Windows.Automation.ScrollAmount.NoAmount;
                case ScrollAmount.SmallIncrement: return System.Windows.Automation.ScrollAmount.SmallIncrement;
                case ScrollAmount.SmallDecrement: return System.Windows.Automation.ScrollAmount.SmallDecrement;
                case ScrollAmount.LargeIncrement: return System.Windows.Automation.ScrollAmount.LargeIncrement;
                case ScrollAmount.LargeDecrement: return System.Windows.Automation.ScrollAmount.LargeDecrement;
                default: throw new ProtocolException(ErrorCodes.InvalidParams, "Invalid scroll amount.");
            }
        }

        private static ProtocolException Unsupported() => new ProtocolException(ErrorCodes.ActionUnsupported, "Action is unsupported.");
    }
}
