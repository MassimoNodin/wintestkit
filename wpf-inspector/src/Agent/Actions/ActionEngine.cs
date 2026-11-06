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

namespace WinTestKit.Inspector.Agent.Actions
{
    public static class ActionEngine
    {
        public static async Task<ActResult> ExecuteAsync(DispatcherExecutor executor, Dispatcher dispatcher, object target, ObjectRef handle, string method, DateTime deadline, int timeoutMs, CancellationToken ct)
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
                    string outcome = await executor.ExecuteAsync(dispatcher, token => Perform(target, method, token), timed.Token).ConfigureAwait(false);
                    return new ActResult { Outcome = outcome, Handle = handle };
                }
                catch (OperationCanceledException) when (!ct.IsCancellationRequested) { throw ProtocolException.Deadline("Action deadline elapsed."); }
                catch (ProtocolException error) when (error.Code == ErrorCodes.Timeout && DateTime.UtcNow >= end) { throw ProtocolException.Deadline("Action deadline elapsed."); }
            }
            finally { timed.Dispose(); }
        }

        private static string Perform(object target, string method, CancellationToken ct)
        {
            ct.ThrowIfCancellationRequested();
            if (!(target is UIElement element) || !element.IsEnabled) throw Unsupported();
            AutomationPeer? peer = UIElementAutomationPeer.FromElement(element) ?? UIElementAutomationPeer.CreatePeerForElement(element);
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

        private static ProtocolException Unsupported() => new ProtocolException(ErrorCodes.ActionUnsupported, "Action is unsupported.");
    }
}
