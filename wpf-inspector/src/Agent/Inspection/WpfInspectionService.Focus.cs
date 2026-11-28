using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Inspection.Members;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Inspection
{
    public sealed partial class WpfInspectionService
    {
        public Task<FocusResult?> FocusedAsync(FocusScope? scope, DateTime deadline, CancellationToken ct) => RunAsync(async token =>
        {
            object? root = null;
            Dispatcher dispatcher;
            if (scope != null) root = GetObject(scope.ObjectId, scope.Generation, out dispatcher);
            else
            {
                var main = Application.Current?.Dispatcher;
                if (main == null)
                {
                    var available = await executor.DiscoverDispatchersAsync(token).ConfigureAwait(false);
                    if (available.Count == 1) main = available[0];
                }
                dispatcher = main ?? throw new ProtocolException(ErrorCodes.DispatcherUnavailable, "No main dispatcher.");
            }
            int remaining = (int)Math.Max(0, (deadline - DateTime.UtcNow).TotalMilliseconds);
            if (remaining == 0) throw new ProtocolException(ErrorCodes.Timeout, "Request deadline elapsed.");
            using (var timed = CancellationTokenSource.CreateLinkedTokenSource(token))
            {
                timed.CancelAfter(remaining);
                try { return await executor.ExecuteAsync(dispatcher, () =>
                {
                    var focused = Keyboard.FocusedElement;
                    if (focused == null) return null;
                    bool password = false, classified = true;
                    try
                    {
                        password = RedactionPolicy.ReadProtectedIdentity(focused);
                        if (!password && focused is DependencyObject dependency)
                        {
                            var peer = PeerIdentity.GetPeer(dependency);
                            if (peer != null) password = peer.IsPassword();
                        }
                    }
                    catch (Exception) { classified = false; }
                    bool within = false;
                    var pending = new Stack<DependencyObject>();
                    var visited = new HashSet<DependencyObject>();
                    if (focused is DependencyObject node) pending.Push(node);
                    while (pending.Count > 0)
                    {
                        var current = pending.Pop();
                        if (!visited.Add(current)) continue;
                        if (ReferenceEquals(current, root)) { within = true; break; }
                        if (current is Visual || current is System.Windows.Media.Media3D.Visual3D)
                        { var parent = VisualTreeHelper.GetParent(current); if (parent != null) pending.Push(parent); }
                        var logical = LogicalTreeHelper.GetParent(current); if (logical != null) pending.Push(logical);
                        if (current is FrameworkElement fe && fe.TemplatedParent is DependencyObject templated) pending.Push(templated);
                        if (current is FrameworkContentElement fce && fce.TemplatedParent is DependencyObject contentParent) pending.Push(contentParent);
                    }
                    return new FocusResult { Ref = registry.Register(focused, dispatcher, inspector.DescribeType(focused.GetType())), IsPassword = password, Classified = classified, WithinScope = within };
                }, timed.Token).ConfigureAwait(false); }
                catch (OperationCanceledException) when (!token.IsCancellationRequested) { throw new ProtocolException(ErrorCodes.Timeout, "Request deadline elapsed."); }
            }
        }, ct);
    }
}
