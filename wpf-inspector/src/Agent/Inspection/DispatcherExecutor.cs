using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Threading;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Inspection
{
    /// <summary>Serializes work per dispatcher without blocking a pipe or UI thread.</summary>
    public sealed class DispatcherExecutor
    {
        private sealed class State
        {
            internal readonly SemaphoreSlim Admission = new SemaphoreSlim(1, 1);
            internal readonly string Id = Guid.NewGuid().ToString("N");
            internal readonly CancellationTokenSource Unavailable = new CancellationTokenSource();
            internal bool Unresponsive;
        }
        private readonly object gate = new object();
        private readonly Dictionary<Dispatcher, State> states = new Dictionary<Dispatcher, State>();
        private State GetState(Dispatcher dispatcher)
        {
            lock (gate)
            {
                if (!states.TryGetValue(dispatcher, out State? state)) states.Add(dispatcher, state = new State());
                return state;
            }
        }
        public string GetDispatcherId(Dispatcher dispatcher) => GetState(dispatcher).Id;

        public Task<T> ExecuteAsync<T>(Dispatcher dispatcher, Func<T> action, CancellationToken ct) =>
            ExecuteAsync(dispatcher, _ => action(), ct);

        public async Task<T> ExecuteAsync<T>(Dispatcher dispatcher, Func<CancellationToken, T> action, CancellationToken ct)
        {
            ct.ThrowIfCancellationRequested();
            Stopwatch elapsed = Stopwatch.StartNew();
            State state = GetState(dispatcher);
            lock (gate) if (state.Unresponsive) throw Unavailable();
            using (var admissionCancellation = CancellationTokenSource.CreateLinkedTokenSource(ct, state.Unavailable.Token))
            {
                try
                {
                    if (!await state.Admission.WaitAsync(ProtocolLimits.DispatcherQueueWaitMs, admissionCancellation.Token).ConfigureAwait(false))
                        throw QueueTimeout();
                }
                catch (OperationCanceledException) when (state.Unavailable.IsCancellationRequested) { throw Unavailable(); }
            }
            bool release = true;
            var workCancellation = CancellationTokenSource.CreateLinkedTokenSource(ct);
            try
            {
                lock (gate) if (state.Unresponsive) throw Unavailable();
                ct.ThrowIfCancellationRequested();
                if (dispatcher.HasShutdownStarted || dispatcher.HasShutdownFinished) throw Unavailable();
                DispatcherOperation<T> operation = dispatcher.InvokeAsync(() =>
                {
                    ct.ThrowIfCancellationRequested();
                    if (elapsed.ElapsedMilliseconds >= ProtocolLimits.DispatcherQueueWaitMs) throw QueueTimeout();
                    return action(workCancellation.Token);
                }, DispatcherPriority.Background);
                Task completed = await Task.WhenAny(operation.Task,
                    Task.Delay(Remaining(ProtocolLimits.DispatcherQueueWaitMs, elapsed), ct)).ConfigureAwait(false);
                if (completed != operation.Task && operation.Abort())
                {
                    Observe(operation.Task);
                    ct.ThrowIfCancellationRequested();
                    throw QueueTimeout();
                }
                Task deadline = Task.Delay(Remaining(ProtocolLimits.RequestTimeoutMs, elapsed), ct);
                completed = await Task.WhenAny(operation.Task, deadline).ConfigureAwait(false);
                if (completed != operation.Task && !operation.Task.IsCompleted)
                {
                    MarkUnresponsive(state);
                    try { workCancellation.Cancel(); }
                    catch (AggregateException) { }
                    release = false;
                    _ = operation.Task.ContinueWith(task =>
                    {
                        Observe(task);
                        workCancellation.Dispose();
                        state.Admission.Release();
                    }, CancellationToken.None,
                        TaskContinuationOptions.ExecuteSynchronously, TaskScheduler.Default);
                    ct.ThrowIfCancellationRequested();
                    throw new ProtocolException(ErrorCodes.DispatcherUnavailable, "Dispatcher did not complete before the deadline.");
                }
                T result;
                try { result = await operation.Task.ConfigureAwait(false); }
                catch (OperationCanceledException) when (elapsed.ElapsedMilliseconds >= ProtocolLimits.RequestTimeoutMs)
                {
                    MarkUnresponsive(state);
                    ct.ThrowIfCancellationRequested();
                    throw Unavailable();
                }
                if (elapsed.ElapsedMilliseconds >= ProtocolLimits.RequestTimeoutMs)
                {
                    MarkUnresponsive(state);
                    throw Unavailable();
                }
                ct.ThrowIfCancellationRequested();
                return result;
            }
            finally
            {
                if (release) { workCancellation.Dispose(); state.Admission.Release(); }
            }
        }

        public IReadOnlyList<Dispatcher> DiscoverDispatchers()
        {
            var found = new HashSet<Dispatcher>();
            foreach (PresentationSource source in PresentationSource.CurrentSources)
                if (!source.IsDisposed && !source.Dispatcher.HasShutdownStarted && !source.Dispatcher.HasShutdownFinished)
                    found.Add(source.Dispatcher);
            Application? application = Application.Current;
            if (application != null && application.Dispatcher.CheckAccess())
                foreach (Window window in application.Windows)
                    if (!window.Dispatcher.HasShutdownStarted && !window.Dispatcher.HasShutdownFinished) found.Add(window.Dispatcher);
            return new List<Dispatcher>(found).AsReadOnly();
        }

        public async Task<IReadOnlyList<Dispatcher>> DiscoverDispatchersAsync(CancellationToken ct)
        {
            ct.ThrowIfCancellationRequested();
            var found = new HashSet<Dispatcher>(DiscoverDispatchers());
            Application? application = Application.Current;
            if (application != null && !application.Dispatcher.HasShutdownStarted && !application.Dispatcher.HasShutdownFinished)
            {
                IReadOnlyList<Dispatcher> windows = await ExecuteAsync(application.Dispatcher, token =>
                {
                    var owners = new List<Dispatcher>();
                    foreach (Window window in application.Windows)
                    {
                        token.ThrowIfCancellationRequested();
                        if (!window.Dispatcher.HasShutdownStarted && !window.Dispatcher.HasShutdownFinished) owners.Add(window.Dispatcher);
                    }
                    return (IReadOnlyList<Dispatcher>)owners;
                }, ct).ConfigureAwait(false);
                foreach (Dispatcher dispatcher in windows) found.Add(dispatcher);
            }
            return new List<Dispatcher>(found).AsReadOnly();
        }

        public async Task ExecuteSlicedAsync<T>(Dispatcher dispatcher, IReadOnlyList<T> items,
            Action<T, CancellationToken> action, CancellationToken ct)
        {
            ct.ThrowIfCancellationRequested();
            int index = 0;
            bool complete = false;
            while (!complete)
            {
                complete = await ExecuteAsync(dispatcher, token =>
                {
                    Stopwatch slice = Stopwatch.StartNew();
                    for (int count = 0; count < ProtocolLimits.TraversalSliceObjects &&
                        slice.ElapsedMilliseconds < ProtocolLimits.TraversalSliceMs; count++)
                    {
                        token.ThrowIfCancellationRequested();
                        if (index >= items.Count) return true;
                        action(items[index++], token);
                    }
                    return false;
                }, ct).ConfigureAwait(false);
            }
        }

        private static int Remaining(int limit, Stopwatch elapsed) => (int)Math.Max(0, limit - elapsed.ElapsedMilliseconds);
        private void MarkUnresponsive(State state)
        {
            lock (gate) state.Unresponsive = true;
            state.Unavailable.Cancel();
        }
        private static void Observe(Task task) { if (task.IsFaulted) _ = task.Exception; }
        private static ProtocolException QueueTimeout() => new ProtocolException(ErrorCodes.Timeout, "Dispatcher queue wait timed out.");
        private static ProtocolException Unavailable() => new ProtocolException(ErrorCodes.DispatcherUnavailable, "Dispatcher is unavailable.");
    }
}
