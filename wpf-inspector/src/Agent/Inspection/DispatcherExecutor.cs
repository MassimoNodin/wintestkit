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
            internal CancellationTokenSource Unavailable = new CancellationTokenSource();
            internal bool Unresponsive;
            internal long WorkStarted;
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
            CancellationToken unavailable;
            long queuedMs = 0;
            lock (gate)
            {
                if (state.Unresponsive) throw Unavailable(state);
                unavailable = state.Unavailable.Token;
            }
            using (var admissionCancellation = CancellationTokenSource.CreateLinkedTokenSource(ct, unavailable))
            {
                try
                {
                    if (!await state.Admission.WaitAsync(ProtocolLimits.DispatcherQueueWaitMs, admissionCancellation.Token).ConfigureAwait(false))
                        throw QueueTimeout(elapsed.ElapsedMilliseconds);
                }
                catch (OperationCanceledException) when (unavailable.IsCancellationRequested) { throw Unavailable(state); }
            }
            bool release = true;
            var workCancellation = CancellationTokenSource.CreateLinkedTokenSource(ct);
            try
            {
                lock (gate) if (state.Unresponsive) throw Unavailable(state);
                ct.ThrowIfCancellationRequested();
                if (dispatcher.HasShutdownStarted || dispatcher.HasShutdownFinished) throw Unavailable(state);
                int escalated = 0;
                DispatcherOperation<T> operation = dispatcher.InvokeAsync(() =>
                {
                    ct.ThrowIfCancellationRequested();
                    if (elapsed.ElapsedMilliseconds >= ProtocolLimits.DispatcherQueueWaitMs) throw QueueTimeout(elapsed.ElapsedMilliseconds, Volatile.Read(ref escalated) != 0);
                    Interlocked.Exchange(ref queuedMs, elapsed.ElapsedMilliseconds);
                    Interlocked.Exchange(ref state.WorkStarted, Stopwatch.GetTimestamp());
                    return action(workCancellation.Token);
                }, DispatcherPriority.Background);
                // Background work starves behind a busy UI thread: after DispatcherEscalateMs still pending, requeue at Normal.
                Task completed = await Task.WhenAny(operation.Task,
                    Task.Delay(Remaining(ProtocolLimits.DispatcherEscalateMs, elapsed), ct)).ConfigureAwait(false);
                if (completed != operation.Task && !ct.IsCancellationRequested && operation.Status == DispatcherOperationStatus.Pending)
                {
                    try
                    {
                        operation.Priority = DispatcherPriority.Normal;
                        Volatile.Write(ref escalated, 1);
                    }
                    catch (InvalidOperationException) { }
                }
                if (completed != operation.Task)
                    completed = await Task.WhenAny(operation.Task,
                        Task.Delay(Remaining(ProtocolLimits.DispatcherQueueWaitMs, elapsed), ct)).ConfigureAwait(false);
                if (completed != operation.Task && operation.Abort())
                {
                    Observe(operation.Task);
                    ct.ThrowIfCancellationRequested();
                    throw QueueTimeout(elapsed.ElapsedMilliseconds, Volatile.Read(ref escalated) != 0);
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
                        lock (gate)
                        {
                            state.Unavailable = new CancellationTokenSource();
                            state.Unresponsive = false;
                            state.Admission.Release();
                        }
                    }, CancellationToken.None,
                        TaskContinuationOptions.ExecuteSynchronously, TaskScheduler.Default);
                    ct.ThrowIfCancellationRequested();
                    throw WorkTimeout(elapsed.ElapsedMilliseconds, Interlocked.Read(ref queuedMs), Volatile.Read(ref escalated) != 0);
                }
                T result;
                try { result = await operation.Task.ConfigureAwait(false); }
                catch (OperationCanceledException) when (elapsed.ElapsedMilliseconds >= ProtocolLimits.RequestTimeoutMs)
                {
                    ct.ThrowIfCancellationRequested();
                    throw Unavailable(state);
                }
                if (elapsed.ElapsedMilliseconds >= ProtocolLimits.RequestTimeoutMs)
                {
                    throw WorkTimeout(elapsed.ElapsedMilliseconds, Interlocked.Read(ref queuedMs), Volatile.Read(ref escalated) != 0);
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
        private static ProtocolException QueueTimeout(long waited, bool escalated = false)
        {
            var details = new JsonObjectNode();
            details.Add("dispatcherBusy", new JsonBoolNode(true)); details.Add("escalated", new JsonBoolNode(escalated));
            return new ProtocolException(ErrorCodes.Timeout, string.Format("Dispatcher queue wait exceeded {0} ms (waited {1} ms{2}; the UI thread is busy with higher-priority work)", ProtocolLimits.DispatcherQueueWaitMs, waited, escalated ? string.Format(", escalated to Normal priority after {0} ms", ProtocolLimits.DispatcherEscalateMs) : ""), details);
        }
        private static ProtocolException WorkTimeout(long elapsed, long queued, bool escalated) =>
            new ProtocolException(ErrorCodes.DispatcherUnavailable, string.Format("Dispatcher work did not finish within {0} ms (queued {1} ms, ran {2} ms{3})", ProtocolLimits.RequestTimeoutMs, queued, Math.Max(0, elapsed - queued), escalated ? ", escalated to Normal priority" : ""));
        private static ProtocolException Unavailable(State state)
        {
            long started = Interlocked.Read(ref state.WorkStarted);
            string message = state.Unresponsive && started != 0
                ? string.Format("Dispatcher is unavailable: earlier work is still running (for {0} ms)", (Stopwatch.GetTimestamp() - started) * 1000 / Stopwatch.Frequency)
                : "Dispatcher is unavailable.";
            return new ProtocolException(ErrorCodes.DispatcherUnavailable, message);
        }
    }
}
