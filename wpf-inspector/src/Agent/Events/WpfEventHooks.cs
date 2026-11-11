using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Runtime.CompilerServices;
using System.Threading;
using System.Windows;
using System.Windows.Media;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Contracts;
using WinTestKit.Inspector.Agent.Inspection;
using WinTestKit.Inspector.Agent.Inspection.Members;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Events
{
    internal sealed class WpfEventHooks : IDisposable
    {
        private sealed class WindowState
        {
            internal WeakReference Window = null!;
            internal ObjectRef Handle = null!;
            internal long? Fingerprint;
            internal long LastChange;
            internal EventHandler Closed = null!;
        }
        private sealed class DispatcherState
        {
            internal readonly List<WindowState> Windows = new List<WindowState>();
            internal bool Pending;
        }
        private readonly object gate = new object();
        private readonly SubscriptionStore subscriptions;
        private readonly DispatcherExecutor executor;
        private readonly ObjectRegistry registry;
        private readonly IObjectInspector inspector;
        private readonly Dictionary<Dispatcher, DispatcherState> dispatchers = new Dictionary<Dispatcher, DispatcherState>();
        private Timer? timer;
        private bool disposed;
        private int handlerCount;
        internal int HandlerCount => Volatile.Read(ref handlerCount);

        internal WpfEventHooks(SubscriptionStore subscriptions, DispatcherExecutor executor, ObjectRegistry registry, IObjectInspector inspector)
        {
            this.subscriptions = subscriptions; this.executor = executor; this.registry = registry; this.inspector = inspector;
            subscriptions.Changed += Update;
            Update();
        }

        private void Update()
        {
            lock (gate)
            {
                if (disposed) return;
                bool wanted = subscriptions.Wants(EventKind.WindowOpened) || subscriptions.Wants(EventKind.WindowClosed) || subscriptions.Wants(EventKind.TreeChanged);
                if (!subscriptions.Wants(EventKind.TreeChanged))
                    foreach (var state in dispatchers.Values)
                        foreach (var window in state.Windows) { window.Fingerprint = null; window.LastChange = 0; }
                if (wanted && timer == null) timer = new Timer(Scan, null, 0, 100);
                else if (!wanted && timer != null) { timer.Dispose(); timer = null; DetachAll(); }
            }
        }

        // A single background discovery timer finds dispatchers from PresentationSource; each
        // dispatcher compares its own roots at Background priority. Snapshots contain only weak
        // window references and registered handles, so neither polling nor close detection roots a window.
        private void Scan(object? unused)
        {
            lock (gate)
            {
                if (disposed || timer == null) return;
                try
                {
                    foreach (var dispatcher in executor.DiscoverDispatchers())
                        if (!dispatchers.ContainsKey(dispatcher)) dispatchers.Add(dispatcher, new DispatcherState());
                    foreach (var pair in dispatchers)
                    {
                        var dispatcher = pair.Key; var state = pair.Value;
                        if (state.Pending || dispatcher.HasShutdownStarted || dispatcher.HasShutdownFinished) continue;
                        state.Pending = true;
                        dispatcher.BeginInvoke(DispatcherPriority.Background, new Action(() =>
                        {
                            // Event observation must never propagate an inspection failure into the host application.
                            try { Check(dispatcher, state); }
                            catch (Exception) { lock (gate) state.Pending = false; }
                        }));
                    }
                }
                catch (InvalidOperationException) { }
            }
        }

        private void Check(Dispatcher dispatcher, DispatcherState state)
        {
            lock (gate)
            {
                state.Pending = false;
                if (disposed || timer == null || !dispatchers.TryGetValue(dispatcher, out var current) || current != state) return;
                var present = new List<Window>();
                foreach (PresentationSource source in PresentationSource.CurrentSources)
                    if (!source.IsDisposed && source.Dispatcher == dispatcher && source.RootVisual is Window window) present.Add(window);
                for (int i = state.Windows.Count - 1; i >= 0; i--)
                {
                    var old = state.Windows[i];
                    var window = old.Window.Target as Window;
                    if (window == null || !present.Contains(window))
                    {
                        subscriptions.Publish(EventKind.WindowClosed, old.Handle);
                        if (window != null) window.Closed -= old.Closed;
                        Interlocked.Decrement(ref handlerCount);
                        state.Windows.RemoveAt(i);
                    }
                }
                foreach (var window in present)
                {
                    WindowState? found = state.Windows.Find(item => ReferenceEquals(item.Window.Target, window));
                    if (found == null)
                    {
                        found = new WindowState { Window = new WeakReference(window), Handle = registry.Register(window, dispatcher, inspector.DescribeType(window.GetType())), Fingerprint = subscriptions.Wants(EventKind.TreeChanged) ? Fingerprint(window) : (long?)null };
                        var entry = found;
                        found.Closed = (sender, args) => Closed(state, entry, sender);
                        window.Closed += found.Closed;
                        Interlocked.Increment(ref handlerCount);
                        state.Windows.Add(found);
                        subscriptions.Publish(EventKind.WindowOpened, found.Handle);
                    }
                    else if (subscriptions.Wants(EventKind.TreeChanged))
                    {
                        long fingerprint = Fingerprint(window);
                        long now = Stopwatch.GetTimestamp();
                        if (found.Fingerprint == null) found.Fingerprint = fingerprint;
                        else if (fingerprint != found.Fingerprint && (found.LastChange == 0 || now - found.LastChange >= Stopwatch.Frequency / 10))
                        {
                            found.Fingerprint = fingerprint; found.LastChange = now;
                            subscriptions.Publish(EventKind.TreeChanged, found.Handle);
                        }
                    }
                }
            }
        }

        private void Closed(DispatcherState state, WindowState entry, object? sender)
        {
            lock (gate)
            {
                if (sender is Window window) window.Closed -= entry.Closed;
                if (state.Windows.Remove(entry))
                {
                    Interlocked.Decrement(ref handlerCount);
                    if (!disposed && timer != null) subscriptions.Publish(EventKind.WindowClosed, entry.Handle);
                }
            }
        }

        private void DetachAll()
        {
            foreach (var pair in dispatchers)
            {
                var dispatcher = pair.Key;
                foreach (var entry in pair.Value.Windows)
                {
                    var weak = entry.Window; var handler = entry.Closed;
                    if (!dispatcher.HasShutdownStarted && !dispatcher.HasShutdownFinished)
                        dispatcher.BeginInvoke(DispatcherPriority.Send, new Action(() => { if (weak.Target is Window window) window.Closed -= handler; Interlocked.Decrement(ref handlerCount); }));
                    else Interlocked.Decrement(ref handlerCount);
                }
                pair.Value.Windows.Clear();
            }
            dispatchers.Clear();
        }

        // Hash at most 512 visual nodes, including identity and child counts. This bounds work
        // and detects replacement as well as addition/removal; changes beyond the cap may be missed.
        private static long Fingerprint(DependencyObject root)
        {
            unchecked
            {
                long hash = 17; int visited = 0;
                var stack = new Stack<DependencyObject>(); stack.Push(root);
                while (stack.Count != 0 && visited++ < 512)
                {
                    var node = stack.Pop(); int count = VisualTreeHelper.GetChildrenCount(node);
                    hash = hash * 31 + RuntimeHelpers.GetHashCode(node); hash = hash * 31 + count;
                    for (int i = Math.Min(count, Math.Max(0, 512 - visited - stack.Count)) - 1; i >= 0; i--) stack.Push(VisualTreeHelper.GetChild(node, i));
                }
                return hash;
            }
        }

        public void Dispose()
        {
            subscriptions.Changed -= Update;
            lock (gate) { disposed = true; timer?.Dispose(); timer = null; DetachAll(); }
        }
    }
}
