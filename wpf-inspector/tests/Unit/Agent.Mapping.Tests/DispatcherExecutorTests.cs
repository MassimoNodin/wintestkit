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
                }
                finally { unblock.Set(); await blocking; }
                Assert.Equal(1, await executor.ExecuteAsync(ui.Dispatcher, () => 1, CancellationToken.None));
                Assert.False(ran);
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
                        Assert.Equal(ErrorCodes.DispatcherUnavailable, (await Assert.ThrowsAsync<ProtocolException>(() => operation)).Code);
                    }
                    Assert.True(workToken.IsCancellationRequested);
                    int posted = 0;
                    DispatcherHookEventHandler handler = (_, args) => Interlocked.Increment(ref posted);
                    ui.Dispatcher.Hooks.OperationPosted += handler;
                    try
                    {
                        Task<int> rejected = executor.ExecuteAsync(ui.Dispatcher, () => 0, CancellationToken.None);
                        Assert.True(rejected.IsCompleted);
                        Assert.Equal(ErrorCodes.DispatcherUnavailable, (await Assert.ThrowsAsync<ProtocolException>(() => rejected)).Code);
                        Assert.Equal(0, posted);
                    }
                    finally { ui.Dispatcher.Hooks.OperationPosted -= handler; }
                    Assert.Equal(7, await executor.ExecuteAsync(other.Dispatcher, () => 7, CancellationToken.None));
                }
                finally { unblock.Set(); await finished.Task; }
                Assert.Equal(ErrorCodes.DispatcherUnavailable,
                    (await Assert.ThrowsAsync<ProtocolException>(() => executor.ExecuteAsync(ui.Dispatcher, () => 0, CancellationToken.None))).Code);
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
