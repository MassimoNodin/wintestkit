using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Inspection;
using WinTestKit.Inspector.Protocol;
using Xunit;

namespace WinTestKit.Inspector.Agent.Mapping.Tests
{
    [Trait("Category", "Unit")]
    [Collection("WPF dispatchers")]
    public sealed class DispatcherExecutorTests
    {
        private readonly ApplicationDispatcherFixture application;
        public DispatcherExecutorTests(ApplicationDispatcherFixture application) { this.application = application; }

        [Fact]
        public async Task UsesBackgroundPriorityAndPassesCancellation()
        {
            using (var ui = new DispatcherThread())
            using (var cancellation = new CancellationTokenSource())
            {
                var executor = new DispatcherExecutor();
                var priorities = new List<DispatcherPriority>();
                DispatcherHookEventHandler handler = (_, args) => priorities.Add(args.Operation.Priority);
                ui.Dispatcher.Hooks.OperationStarted += handler;
                try
                {
                    Assert.Equal(42, await executor.ExecuteAsync(ui.Dispatcher, token =>
                    {
                        Assert.True(ui.Dispatcher.CheckAccess());
                        Assert.True(token.CanBeCanceled);
                        Assert.False(token.IsCancellationRequested);
                        return 42;
                    }, cancellation.Token));
                    Assert.Contains(DispatcherPriority.Background, priorities);
                    Assert.DoesNotContain(priorities, priority => priority != DispatcherPriority.Background);
                }
                finally { ui.Dispatcher.Hooks.OperationStarted -= handler; }
            }
        }

        [Fact]
        public async Task QueueWaitAbortsWithoutExecutingAndDispatcherRemainsUsable()
        {
            using (var ui = new DispatcherThread())
            using (var unblock = new ManualResetEventSlim())
            {
                var started = Signal();
                Task blocking = ui.Dispatcher.InvokeAsync(() => { started.SetResult(true); unblock.Wait(TimeSpan.FromSeconds(10)); }).Task;
                await started.Task;
                var executor = new DispatcherExecutor();
                bool ran = false;
                try
                {
                    var error = await Assert.ThrowsAsync<ProtocolException>(() => executor.ExecuteAsync(ui.Dispatcher, () => { ran = true; return 0; }, CancellationToken.None));
                    Assert.Equal(ErrorCodes.Timeout, error.Code);
                    Assert.Contains("Dispatcher queue wait exceeded 500 ms (waited", error.Message);
                    Assert.True(((JsonBoolNode)error.Details!.Get("dispatcherBusy")).Value);
                    Assert.True(((JsonBoolNode)error.Details!.Get("escalated")).Value);
                    Assert.Contains("escalated to Normal priority after 250 ms", error.Message);
                }
                finally { unblock.Set(); await blocking; }
                Assert.Equal(1, await executor.ExecuteAsync(ui.Dispatcher, () => 1, CancellationToken.None));
                Assert.False(ran);
            }
        }

        [Fact]
        public async Task BusyNormalPriorityLoopStarvesBackgroundWorkUntilItIsEscalated()
        {
            using (var ui = new DispatcherThread())
            {
                bool stop = false;
                var priorityChanges = new List<DispatcherPriority>();
                DispatcherHookEventHandler handler = (_, args) => { lock (priorityChanges) priorityChanges.Add(args.Operation.Priority); };
                ui.Dispatcher.Hooks.OperationPriorityChanged += handler;
                Action? pump = null;
                pump = () =>
                {
                    if (Volatile.Read(ref stop)) return;
                    Thread.Sleep(5);
                    _ = ui.Dispatcher.InvokeAsync(pump!, DispatcherPriority.Normal);
                };
                _ = ui.Dispatcher.InvokeAsync(pump, DispatcherPriority.Normal);
                try
                {
                    var watch = System.Diagnostics.Stopwatch.StartNew();
                    int result = await new DispatcherExecutor().ExecuteAsync(ui.Dispatcher, () => 7, CancellationToken.None);
                    watch.Stop();
                    Assert.Equal(7, result);
                    Assert.InRange(watch.ElapsedMilliseconds, ProtocolLimits.DispatcherEscalateMs - 20, ProtocolLimits.DispatcherQueueWaitMs);
                    lock (priorityChanges) Assert.Single(priorityChanges);
                }
                finally
                {
                    Volatile.Write(ref stop, true);
                    ui.Dispatcher.Hooks.OperationPriorityChanged -= handler;
                    await ui.Dispatcher.InvokeAsync(() => { }, DispatcherPriority.Normal).Task;
                }
            }
        }

        [Fact]
        public async Task IdleDispatcherNeverEscalates()
        {
            using (var ui = new DispatcherThread())
            {
                int changes = 0;
                DispatcherHookEventHandler handler = (_, args) => Interlocked.Increment(ref changes);
                ui.Dispatcher.Hooks.OperationPriorityChanged += handler;
                try
                {
                    var executor = new DispatcherExecutor();
                    for (int index = 0; index < 5; index++)
                    {
                        var watch = System.Diagnostics.Stopwatch.StartNew();
                        Assert.Equal(index, await executor.ExecuteAsync(ui.Dispatcher, () => index, CancellationToken.None));
                        Assert.True(watch.ElapsedMilliseconds < ProtocolLimits.DispatcherEscalateMs, "Idle work waited for the escalation delay.");
                    }
                    await Task.Delay(ProtocolLimits.DispatcherEscalateMs + 50);
                    Assert.Equal(0, Volatile.Read(ref changes));
                }
                finally { ui.Dispatcher.Hooks.OperationPriorityChanged -= handler; }
            }
        }

        [Fact]
        public async Task CancellationBeforeEscalationDoesNotRaisePriority()
        {
            using (var ui = new DispatcherThread())
            using (var unblock = new ManualResetEventSlim())
            using (var cancellation = new CancellationTokenSource())
            {
                var started = Signal();
                Task blocking = ui.Dispatcher.InvokeAsync(() => { started.SetResult(true); unblock.Wait(TimeSpan.FromSeconds(10)); }).Task;
                await started.Task;
                int changes = 0;
                DispatcherHookEventHandler handler = (_, args) => Interlocked.Increment(ref changes);
                ui.Dispatcher.Hooks.OperationPriorityChanged += handler;
                try
                {
                    Task operation = new DispatcherExecutor().ExecuteAsync(ui.Dispatcher, () => 0, cancellation.Token);
                    cancellation.Cancel();
                    await Assert.ThrowsAnyAsync<OperationCanceledException>(() => operation);
                    Assert.Equal(0, Volatile.Read(ref changes));
                }
                finally { unblock.Set(); await blocking; ui.Dispatcher.Hooks.OperationPriorityChanged -= handler; }
            }
        }

        [Fact]
        public async Task CancellationWhileQueuedAbortsBeforeStart()
        {
            using (var ui = new DispatcherThread())
            using (var unblock = new ManualResetEventSlim())
            using (var cancellation = new CancellationTokenSource())
            {
                var started = Signal();
                Task blocking = ui.Dispatcher.InvokeAsync(() => { started.SetResult(true); unblock.Wait(TimeSpan.FromSeconds(10)); }).Task;
                await started.Task;
                var executor = new DispatcherExecutor();
                bool ran = false;
                try
                {
                    Task operation = executor.ExecuteAsync(ui.Dispatcher, () => { ran = true; return 0; }, cancellation.Token);
                    cancellation.Cancel();
                    await Assert.ThrowsAnyAsync<OperationCanceledException>(() => operation);
                }
                finally { unblock.Set(); await blocking; }
                await executor.ExecuteAsync(ui.Dispatcher, () => 0, CancellationToken.None);
                Assert.False(ran);
            }
        }

        [Fact]
        public async Task AlreadyCancelledWorkIsNotEnqueued()
        {
            using (var ui = new DispatcherThread())
            {
                bool ran = false;
                await Assert.ThrowsAnyAsync<OperationCanceledException>(() => new DispatcherExecutor().ExecuteAsync(ui.Dispatcher,
                    () => { ran = true; return 0; }, new CancellationToken(true)));
                Assert.False(ran);
            }
        }

        [Fact]
        public async Task OnlyOneOperationIsAdmittedPerDispatcher()
        {
            using (var ui = new DispatcherThread())
            using (var unblock = new ManualResetEventSlim())
            {
                var executor = new DispatcherExecutor();
                var started = Signal();
                int posted = 0;
                DispatcherHookEventHandler handler = (_, args) => Interlocked.Increment(ref posted);
                ui.Dispatcher.Hooks.OperationPosted += handler;
                Task<int> first = executor.ExecuteAsync(ui.Dispatcher, () =>
                {
                    started.SetResult(true);
                    unblock.Wait(TimeSpan.FromSeconds(10));
                    return 1;
                }, CancellationToken.None);
                try
                {
                    await started.Task;
                    Task<int> second = executor.ExecuteAsync(ui.Dispatcher, () => 2, CancellationToken.None);
                    Assert.Equal(1, Volatile.Read(ref posted));
                    unblock.Set();
                    Assert.Equal(1, await first);
                    Assert.Equal(2, await second);
                    Assert.Equal(2, Volatile.Read(ref posted));
                }
                finally { unblock.Set(); await first; ui.Dispatcher.Hooks.OperationPosted -= handler; }
            }
        }

        [Theory]
        [InlineData(false)]
        [InlineData(true)]
        public async Task RunningDeadlineMarksOnlyItsDispatcherUnresponsive(bool cancel)
        {
            using (var ui = new DispatcherThread())
            using (var other = new DispatcherThread())
            using (var unblock = new ManualResetEventSlim())
            using (var cancellation = new CancellationTokenSource())
            {
                var executor = new DispatcherExecutor();
                var started = Signal();
                var finished = Signal();
                CancellationToken workToken = default;
                Task<int> operation = executor.ExecuteAsync(ui.Dispatcher, token =>
                {
                    workToken = token;
                    started.SetResult(true);
                    unblock.Wait(TimeSpan.FromSeconds(10));
                    finished.SetResult(true);
                    return 99;
                }, cancellation.Token);
                try
                {
                    await started.Task;
                    if (cancel)
                    {
                        cancellation.Cancel();
                        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => operation);
                    }
                    else
                    {
                        var timeout = await Assert.ThrowsAsync<ProtocolException>(() => operation);
                        Assert.Equal(ErrorCodes.DispatcherUnavailable, timeout.Code);
                        Assert.Contains("Dispatcher work did not finish within 2000 ms (queued", timeout.Message);
                        Assert.Contains("ran", timeout.Message);
                    }
                    Assert.True(workToken.IsCancellationRequested);
                    int posted = 0;
                    DispatcherHookEventHandler handler = (_, args) => Interlocked.Increment(ref posted);
                    ui.Dispatcher.Hooks.OperationPosted += handler;
                    try
                    {
                        Task<int> rejected = executor.ExecuteAsync(ui.Dispatcher, () => 0, CancellationToken.None);
                        Assert.True(rejected.IsCompleted);
                        var unavailable = await Assert.ThrowsAsync<ProtocolException>(() => rejected);
                        Assert.Equal(ErrorCodes.DispatcherUnavailable, unavailable.Code);
                        Assert.Contains("Dispatcher is unavailable: earlier work is still running (for", unavailable.Message);
                        Assert.Equal(0, posted);
                    }
                    finally { ui.Dispatcher.Hooks.OperationPosted -= handler; }
                    Assert.Equal(7, await executor.ExecuteAsync(other.Dispatcher, () => 7, CancellationToken.None));
                }
                finally { unblock.Set(); await finished.Task; }
                await ui.Dispatcher.InvokeAsync(() => { }).Task;
                var recoveryDeadline = DateTime.UtcNow.AddSeconds(2);
                while (true)
                {
                    try
                    {
                        Assert.Equal(1, await executor.ExecuteAsync(ui.Dispatcher, () => 1, CancellationToken.None));
                        break;
                    }
                    catch (ProtocolException error) when (error.Code == ErrorCodes.DispatcherUnavailable && DateTime.UtcNow < recoveryDeadline)
                    {
                        await Task.Delay(10);
                    }
                }
            }
        }

        [Fact]
        public async Task CooperativeCancellationDoesNotPermanentlyQuarantineDispatcher()
        {
            using (var ui = new DispatcherThread())
            using (var cancellation = new CancellationTokenSource())
            {
                var executor = new DispatcherExecutor();
                var started = Signal();
                Task<int> operation = executor.ExecuteAsync(ui.Dispatcher, token =>
                {
                    started.SetResult(true);
                    token.WaitHandle.WaitOne();
                    token.ThrowIfCancellationRequested();
                    return 0;
                }, cancellation.Token);
                await started.Task;
                cancellation.Cancel();
                await Assert.ThrowsAnyAsync<OperationCanceledException>(() => operation);
                await ui.Dispatcher.InvokeAsync(() => { }).Task;
                var deadline = DateTime.UtcNow.AddSeconds(2);
                while (true)
                {
                    try
                    {
                        Assert.Equal(42, await executor.ExecuteAsync(ui.Dispatcher, () => 42, CancellationToken.None));
                        break;
                    }
                    catch (ProtocolException error) when (error.Code == ErrorCodes.DispatcherUnavailable && DateTime.UtcNow < deadline)
                    {
                        await Task.Delay(10);
                    }
                }
            }
        }

        [Fact]
        public void DispatcherIdsAreStableOpaqueAndSessionScoped()
        {
            using (var ui = new DispatcherThread())
            using (var other = new DispatcherThread())
            {
                var executor = new DispatcherExecutor();
                string id = executor.GetDispatcherId(ui.Dispatcher);
                Assert.Equal(id, executor.GetDispatcherId(ui.Dispatcher));
                Assert.NotEqual(id, executor.GetDispatcherId(other.Dispatcher));
                Assert.NotEqual(id, new DispatcherExecutor().GetDispatcherId(ui.Dispatcher));
                Assert.True(Guid.TryParseExact(id, "N", out _));
            }
        }

        [Fact]
        public async Task DiscoversLiveWindowsOnTwoDispatchers()
        {
            using (var ui = new DispatcherThread())
            using (var other = new DispatcherThread())
            {
                Window? first = null;
                Window? second = null;
                try
                {
                    first = await ui.Dispatcher.InvokeAsync(() => { var window = new Window { ShowActivated = false, Width = 50, Height = 50 }; window.Show(); return window; }).Task;
                    second = await other.Dispatcher.InvokeAsync(() => { var window = new Window { ShowActivated = false, Width = 50, Height = 50 }; window.Show(); return window; }).Task;
                    var dispatchers = new DispatcherExecutor().DiscoverDispatchers();
                    Assert.Contains(ui.Dispatcher, dispatchers);
                    Assert.Contains(other.Dispatcher, dispatchers);
                }
                finally
                {
                    if (first != null) await ui.Dispatcher.InvokeAsync(first.Close).Task;
                    if (second != null) await other.Dispatcher.InvokeAsync(second.Close).Task;
                }
            }
        }

        [Theory]
        [InlineData(false)]
        [InlineData(true)]
        public async Task SlicesYieldByObjectCountAndElapsedTime(bool slow)
        {
            using (var ui = new DispatcherThread())
            {
                int visited = 0;
                int atYield = -1;
                var yielded = Signal();
                await new DispatcherExecutor().ExecuteSlicedAsync(ui.Dispatcher,
                    Enumerable.Range(0, ProtocolLimits.TraversalSliceObjects + 10).ToArray(), (item, token) =>
                    {
                        Assert.True(ui.Dispatcher.CheckAccess());
                        visited++;
                        if (item == 0)
                        {
                            _ = ui.Dispatcher.InvokeAsync(() => { atYield = visited; yielded.SetResult(true); }, DispatcherPriority.Normal);
                            if (slow) Thread.Sleep(ProtocolLimits.TraversalSliceMs + 5);
                        }
                    }, CancellationToken.None);
                await yielded.Task;
                Assert.InRange(atYield, 1, ProtocolLimits.TraversalSliceObjects);
                if (slow) Assert.Equal(1, atYield);
                Assert.Equal(ProtocolLimits.TraversalSliceObjects + 10, visited);
            }
        }

        [Fact]
        public async Task SlicingChecksCancellationBetweenItems()
        {
            using (var ui = new DispatcherThread())
            using (var cancellation = new CancellationTokenSource())
            {
                int visited = 0;
                await Assert.ThrowsAnyAsync<OperationCanceledException>(() => new DispatcherExecutor().ExecuteSlicedAsync(ui.Dispatcher,
                    Enumerable.Range(0, 500).ToArray(), (item, token) => { visited++; cancellation.Cancel(); }, cancellation.Token));
                Assert.Equal(1, visited);
            }
        }

        private static TaskCompletionSource<bool> Signal() => new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);

        [Fact]
        public async Task AdmissionWaitTimesOutWithoutPostingReplacement()
        {
            using (var ui = new DispatcherThread())
            using (var unblock = new ManualResetEventSlim())
            {
                var executor = new DispatcherExecutor();
                var started = Signal();
                Task<int> first = executor.ExecuteAsync(ui.Dispatcher, () =>
                {
                    started.SetResult(true);
                    unblock.Wait(TimeSpan.FromSeconds(10));
                    return 1;
                }, CancellationToken.None);
                try
                {
                    await started.Task;
                    bool ran = false;
                    Assert.Equal(ErrorCodes.Timeout, (await Assert.ThrowsAsync<ProtocolException>(() =>
                        executor.ExecuteAsync(ui.Dispatcher, () => { ran = true; return 2; }, CancellationToken.None))).Code);
                    Assert.False(ran);
                }
                finally { unblock.Set(); await first; }
                Assert.Equal(3, await executor.ExecuteAsync(ui.Dispatcher, () => 3, CancellationToken.None));
            }
        }

        [Fact]
        public async Task ActionFailureReleasesAdmission()
        {
            using (var ui = new DispatcherThread())
            {
                var executor = new DispatcherExecutor();
                await Assert.ThrowsAsync<InvalidOperationException>(() => executor.ExecuteAsync<int>(ui.Dispatcher,
                    () => throw new InvalidOperationException("Expected failure."), CancellationToken.None));
                Assert.Equal(3, await executor.ExecuteAsync(ui.Dispatcher, () => 3, CancellationToken.None));
            }
        }

        [Fact]
        public async Task ShutdownDispatcherIsUnavailableAndNotDiscovered()
        {
            Dispatcher dispatcher;
            using (var ui = new DispatcherThread()) dispatcher = ui.Dispatcher;
            var executor = new DispatcherExecutor();
            Assert.DoesNotContain(dispatcher, executor.DiscoverDispatchers());
            Assert.Equal(ErrorCodes.DispatcherUnavailable, (await Assert.ThrowsAsync<ProtocolException>(() =>
                executor.ExecuteAsync(dispatcher, () => 0, CancellationToken.None))).Code);
        }

        [Fact]
        public async Task AsyncDiscoveryIncludesUnshownApplicationWindows()
        {
            Window? window = null;
            try
            {
                window = await application.Dispatcher.InvokeAsync(() => new Window { ShowActivated = false }).Task;
                Assert.Contains(application.Dispatcher, await new DispatcherExecutor().DiscoverDispatchersAsync(CancellationToken.None));
            }
            finally { if (window != null) await application.Dispatcher.InvokeAsync(window.Close).Task; }
        }
    }
}
