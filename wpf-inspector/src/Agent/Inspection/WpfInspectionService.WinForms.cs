using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.Runtime.InteropServices;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Inspection.Members;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Inspection
{
    /// <summary>
    /// WinForms support. A WinForms control is mapped by its window handle, walked through Control.Controls (and the
    /// items of a ToolStrip), and inspected, read and invoked exactly like a WPF object. Its UI thread is addressed through
    /// the thread's WPF Dispatcher (the WinForms message loop pumps it), so the executor, registry, member catalog,
    /// redaction and invocation code are shared with WPF. No WinForms type is named here: they stay in WinFormsNative.
    /// </summary>
    public sealed partial class WpfInspectionService
    {
        private readonly object winFormsGate = new object();
        private readonly Dictionary<uint, Dispatcher> winFormsDispatchers = new Dictionary<uint, Dispatcher>();
        private ProcessIdentity? winFormsProcess;

        [DllImport("user32.dll")] private static extern bool IsWindow(IntPtr hwnd);

        private static bool TryGetHandle(long value, out IntPtr handle)
        {
            if (IntPtr.Size == 4 && (value < int.MinValue || value > uint.MaxValue)) { handle = IntPtr.Zero; return false; }
            handle = IntPtr.Size == 4 ? new IntPtr(unchecked((int)value)) : new IntPtr(value);
            return true;
        }

        private ProcessIdentity CurrentProcess()
        {
            lock (winFormsGate)
            {
                if (winFormsProcess == null)
                    using (Process current = Process.GetCurrentProcess())
                        winFormsProcess = new ProcessIdentity { Pid = current.Id, CreationTimeUtc = current.StartTime.ToUniversalTime().ToString("O", CultureInfo.InvariantCulture) };
                return new ProcessIdentity { Pid = winFormsProcess.Pid, CreationTimeUtc = winFormsProcess.CreationTimeUtc };
            }
        }

        /// <summary>The Dispatcher of the thread that owns <paramref name="control"/>, created on first use and then reused.</summary>
        private async Task<Dispatcher> WinFormsDispatcherAsync(object control, CancellationToken ct)
        {
            uint thread = WinFormsNative.ThreadOf(control);
            if (thread == 0) throw new ProtocolException(ErrorCodes.MappingFailed, "The control has no window.");
            lock (winFormsGate)
                if (winFormsDispatchers.TryGetValue(thread, out Dispatcher? known) && known.Thread.IsAlive && !known.HasShutdownStarted && !known.HasShutdownFinished)
                    return known;
            Dispatcher created = await WinFormsNative.GetDispatcherAsync(control, ProtocolLimits.DispatcherQueueWaitMs, ct).ConfigureAwait(false);
            lock (winFormsGate) winFormsDispatchers[thread] = created;
            return created;
        }

        private async Task<MappingDto?> TryResolveWinFormsAsync(int[] runtimeId, long? nativeWindowHandle, CancellationToken ct)
        {
            if (!nativeWindowHandle.HasValue || nativeWindowHandle.Value == 0 || !WinFormsNative.IsLoaded) return null;
            if (!TryGetHandle(nativeWindowHandle.Value, out IntPtr handle)) return null;
            object? control = WinFormsNative.FromHandle(handle);
            if (control == null) return null;
            Dispatcher dispatcher = await WinFormsDispatcherAsync(control, ct).ConfigureAwait(false);
            return await executor.ExecuteAsync(dispatcher, () =>
            {
                var result = new MappingDto { RuntimeId = (int[])runtimeId.Clone(), Process = CurrentProcess() };
                if (!IsWindow(handle) || !ReferenceEquals(WinFormsNative.FromHandle(handle), control))
                {
                    result.Status = MappingStatus.Stale;
                    return result;
                }
                result.Status = MappingStatus.Exact;
                result.Object = registry.Register(control, dispatcher, inspector.DescribeType(control.GetType()));
                return result;
            }, ct).ConfigureAwait(false);
        }

        private async Task CollectWinFormsRootsAsync(List<ManagedNodeDto> nodes, CancellationToken ct)
        {
            if (!WinFormsNative.IsLoaded) return;
            foreach (object form in WinFormsNative.OpenForms())
            {
                ct.ThrowIfCancellationRequested();
                Dispatcher dispatcher;
                try { dispatcher = await WinFormsDispatcherAsync(form, ct).ConfigureAwait(false); }
                catch (ProtocolException) { continue; }
                await executor.ExecuteAsync(dispatcher, () => { AddWinFormsNode(nodes, form, dispatcher); return true; }, ct).ConfigureAwait(false);
            }
        }

        /// <summary>The children of a WinForms node in their natural order, without sorting.</summary>
        private async Task CollectWinFormsChildrenAsync(object target, Dispatcher dispatcher, List<ManagedNodeDto> nodes, CancellationToken ct)
        {
            List<object> children = await executor.ExecuteAsync(dispatcher, () =>
            {
                var found = new List<object>();
                foreach (object child in WinFormsNative.Children(target))
                {
                    if (found.Count >= ProtocolLimits.ScanMaxObjects) throw new ProtocolException(ErrorCodes.LimitExceeded, "Tree scan limit reached.");
                    found.Add(child);
                }
                return found;
            }, ct).ConfigureAwait(false);
            int index = 0;
            while (index < children.Count)
                await executor.ExecuteAsync(dispatcher, token =>
                {
                    Stopwatch slice = Stopwatch.StartNew();
                    for (int count = 0; index < children.Count && count < ProtocolLimits.TraversalSliceObjects &&
                        slice.ElapsedMilliseconds < ProtocolLimits.TraversalSliceMs; count++, index++)
                    {
                        token.ThrowIfCancellationRequested();
                        AddWinFormsNode(nodes, children[index], dispatcher);
                    }
                    return true;
                }, ct).ConfigureAwait(false);
        }

        private void AddWinFormsNode(List<ManagedNodeDto> nodes, object target, Dispatcher dispatcher)
        {
            if (nodes.Count >= ProtocolLimits.ScanMaxObjects)
                throw new ProtocolException(ErrorCodes.LimitExceeded, "Tree scan limit reached.");
            bool children = WinFormsNative.HasChildren(target);
            nodes.Add(new ManagedNodeDto
            {
                Object = registry.Register(target, dispatcher, inspector.DescribeType(target.GetType())),
                Label = target.GetType().Name,
                HasVisualChildren = children,
                HasLogicalChildren = children
            });
        }

        /// <summary>The control's Name, which UI Automation also exposes as the AutomationId. Not given for a password box.</summary>
        private static NodeIdentityDto? WinFormsIdentity(object target)
        {
            if (RedactionPolicy.IsProtectedIdentity(target)) return null;
            string name = WinFormsNative.Name(target);
            return name.Length == 0 ? null : new NodeIdentityDto { XName = name, AutomationId = name };
        }

        private async Task<Protocol.HitTestResult> HitTestWinFormsAsync(IntPtr hwnd, PointDto point, DateTime deadline, int timeoutMs, bool includePath, CancellationToken token)
        {
            object? root = WinFormsNative.IsLoaded ? WinFormsNative.FromHandle(hwnd) : null;
            if (root == null) throw new ProtocolException(ErrorCodes.MappingFailed, "Window is not a WPF or WinForms source.");
            Dispatcher dispatcher = await WinFormsDispatcherAsync(root, token).ConfigureAwait(false);
            DateTime end = DateTime.UtcNow.AddMilliseconds(timeoutMs);
            if (deadline < end) end = deadline;
            int remaining = (int)Math.Max(0, (end - DateTime.UtcNow).TotalMilliseconds);
            if (remaining == 0) throw new ProtocolException(ErrorCodes.Timeout, "Request deadline elapsed.");
            using (var timed = CancellationTokenSource.CreateLinkedTokenSource(token))
            {
                timed.CancelAfter(remaining);
                try
                {
                    return await executor.ExecuteAsync(dispatcher, () =>
                    {
                        object? target = WinFormsNative.HitTest(hwnd, (int)Math.Round(point.X), (int)Math.Round(point.Y));
                        if (target == null) throw new ProtocolException(ErrorCodes.NotFound, "No hit.");
                        var hit = new Protocol.HitTestResult { Handle = registry.Register(target, dispatcher, inspector.DescribeType(target.GetType())) };
                        if (includePath)
                        {
                            var path = new List<ManagedNodeDto>();
                            for (object? current = target; current != null; current = WinFormsNative.ParentOf(current))
                            {
                                timed.Token.ThrowIfCancellationRequested();
                                if (path.Count >= 256) throw new ProtocolException(ErrorCodes.LimitExceeded, "Hit test path limit reached.");
                                AddWinFormsNode(path, current, dispatcher);
                                path[path.Count - 1].Identity = WinFormsIdentity(current);
                            }
                            path.Reverse();
                            hit.Path = path;
                        }
                        return hit;
                    }, timed.Token).ConfigureAwait(false);
                }
                catch (OperationCanceledException) when (!token.IsCancellationRequested) { throw new ProtocolException(ErrorCodes.Timeout, "Request deadline elapsed."); }
            }
        }
    }
}
