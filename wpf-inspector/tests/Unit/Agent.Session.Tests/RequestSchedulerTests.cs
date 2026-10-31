using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using WinTestKit.Inspector.Agent.Session;
using WinTestKit.Inspector.Protocol;
using Xunit;

namespace WinTestKit.Inspector.Agent.Session.Tests;

[Trait("Category", "Unit")]
public class RequestSchedulerTests
{
    [Fact]
    public async Task WaitsLeaveCapacityForReads()
    {
        using var scheduler = new RequestScheduler(2000);
        var release = new TaskCompletionSource<JsonNode>(TaskCreationOptions.RunContinuationsAsynchronously);
        var started = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        int count = 0;
        var waits = Enumerable.Range(1, 4).Select(id => scheduler.ExecuteAsync(new RequestEnvelope { Id = id, Method = PipeMethods.WaitUntil }, async ct =>
        {
            if (Interlocked.Increment(ref count) == 3) started.TrySetResult(true);
            return await release.Task;
        }, default)).ToArray();
        await started.Task.WaitAsync(TimeSpan.FromSeconds(1));
        var read = scheduler.ExecuteAsync(Request(5), ct => Task.FromResult<JsonNode>(JsonNullNode.Instance), default);
        await read.WaitAsync(TimeSpan.FromSeconds(1));
        Assert.Equal(3, count);
        release.SetResult(JsonNullNode.Instance);
        await Task.WhenAll(waits);
    }
    private static RequestEnvelope Request(long id) => new() { Id = id, Method = PipeMethods.Roots };
    private static async Task<string> Error(Task<JsonNode> task) => (await Assert.ThrowsAsync<ProtocolException>(async () => await task)).Code;

    [Fact]
    public async Task QueueIsBoundedAndQueuedCancellationFreesCapacity()
    {
        using var scheduler = new RequestScheduler(2000);
        var release = new TaskCompletionSource<JsonNode>(TaskCreationOptions.RunContinuationsAsynchronously);
        var running = Enumerable.Range(1, ProtocolLimits.MaxActivePerSession).Select(id => scheduler.ExecuteAsync(Request(id), _ => release.Task, default)).ToArray();
        var queued = Enumerable.Range(10, ProtocolLimits.MaxQueuedOps).Select(id => scheduler.ExecuteAsync(Request(id), _ => release.Task, default)).ToArray();
        Assert.Equal(ErrorCodes.Busy, await Error(scheduler.ExecuteAsync(Request(99), _ => release.Task, default)));
        Assert.True(scheduler.Cancel(10));
        Assert.Equal(ErrorCodes.Cancelled, await Error(queued[0]));
        Assert.False(scheduler.Cancel(10));
        release.SetResult(JsonNullNode.Instance);
        await Task.WhenAll(running.Concat(queued.Skip(1)));
    }

    [Fact]
    public async Task RunningCancelAndTimeoutSuppressLateResults()
    {
        using var scheduler = new RequestScheduler(80);
        var started = new TaskCompletionSource<CancellationToken>(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource<JsonNode>(TaskCreationOptions.RunContinuationsAsynchronously);
        var cancelled = scheduler.ExecuteAsync(Request(1), ct => { started.TrySetResult(ct); return release.Task; }, default);
        var token = await started.Task;
        Assert.True(scheduler.Cancel(1));
        Assert.Equal(ErrorCodes.Cancelled, await Error(cancelled));
        Assert.True(SpinWait.SpinUntil(() => token.IsCancellationRequested, 1000));
        var timed = scheduler.ExecuteAsync(Request(2), _ => release.Task, default);
        Assert.Equal(ErrorCodes.Timeout, await Error(timed));
        Assert.False(scheduler.Cancel(2));
        release.SetResult(JsonNullNode.Instance);
        Assert.Equal(ErrorCodes.Cancelled, await Error(cancelled));
        Assert.Equal(ErrorCodes.Timeout, await Error(timed));
    }

    [Fact]
    public async Task DisposeCancelsRunningAndQueued()
    {
        var scheduler = new RequestScheduler(2000);
        var started = new TaskCompletionSource<CancellationToken>(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource<JsonNode>(TaskCreationOptions.RunContinuationsAsynchronously);
        var tasks = Enumerable.Range(1, 5).Select(id => scheduler.ExecuteAsync(Request(id), ct => { started.TrySetResult(ct); return release.Task; }, default)).ToArray();
        var token = await started.Task;
        scheduler.Dispose();
        foreach (var task in tasks) await Assert.ThrowsAnyAsync<OperationCanceledException>(async () => await task);
        Assert.True(SpinWait.SpinUntil(() => token.IsCancellationRequested, 1000));
        release.TrySetResult(JsonNullNode.Instance);
    }

    [Fact]
    public async Task TwoHundredMixedRequestsRespectActiveLimit()
    {
        using var scheduler = new RequestScheduler(2000);
        int active = 0, maximum = 0;
        var tasks = new List<Task>();
        for (int id = 1; id <= 200; id++)
        {
            int current = id;
            var task = scheduler.ExecuteAsync(Request(id), async ct =>
            {
                int count = Interlocked.Increment(ref active);
                int observed;
                do { observed = maximum; if (observed >= count) break; } while (Interlocked.CompareExchange(ref maximum, count, observed) != observed);
                try { await Task.Delay(current % 7 + 1, ct); return JsonNullNode.Instance; }
                finally { Interlocked.Decrement(ref active); }
            }, default);
            if (id % 4 == 0) scheduler.Cancel(id);
            tasks.Add(task.ContinueWith(completed => { _ = completed.Exception; }, TaskScheduler.Default));
            if (id % 10 == 0) await Task.Delay(4);
        }
        await Task.WhenAll(tasks);
        Assert.InRange(maximum, 1, ProtocolLimits.MaxActivePerSession);
    }
}
