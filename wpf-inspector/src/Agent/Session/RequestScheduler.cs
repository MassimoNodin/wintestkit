using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Session
{
    public sealed class RequestScheduler : IRequestScheduler, IDisposable
    {
        private sealed class Work
        {
            public long Id;
            public Func<CancellationToken, Task<JsonNode>> Operation = null!;
            public readonly CancellationTokenSource Cancellation = new CancellationTokenSource();
            public readonly TaskCompletionSource<JsonNode> Completion = new TaskCompletionSource<JsonNode>(TaskCreationOptions.RunContinuationsAsynchronously);
            public LinkedListNode<Work>? Node;
        }

        private readonly object gate = new object();
        private readonly Dictionary<long, Work> pending = new Dictionary<long, Work>();
        private readonly LinkedList<Work> queue = new LinkedList<Work>();
        private readonly int timeout;
        private int active;
        private bool disposed;

        public RequestScheduler(int timeoutMs) { timeout = Math.Min(ProtocolLimits.RequestTimeoutMs, Math.Max(1, timeoutMs)); }

        internal int TimeoutMs => timeout;

        public Task<JsonNode> ExecuteAsync(RequestEnvelope request, Func<CancellationToken, Task<JsonNode>> operation, CancellationToken ct)
        {
            var work = new Work { Id = request.Id, Operation = operation };
            lock (gate)
            {
                if (disposed || ct.IsCancellationRequested) return Task.FromCanceled<JsonNode>(new CancellationToken(true));
                if (active >= ProtocolLimits.MaxActivePerSession && queue.Count >= ProtocolLimits.MaxQueuedOps)
                    return Task.FromException<JsonNode>(new ProtocolException(ErrorCodes.Busy, "Queue full."));
                pending.Add(work.Id, work);
                if (active < ProtocolLimits.MaxActivePerSession) Start(work);
                else work.Node = queue.AddLast(work);
            }
            _ = ExpireAsync(work, ct);
            return work.Completion.Task;
        }

        public bool Cancel(long id) => Finish(id, ErrorCodes.Cancelled);

        private bool Finish(long id, string code)
        {
            Work work;
            lock (gate)
            {
                if (!pending.TryGetValue(id, out work!)) return false;
                pending.Remove(id);
                if (work.Node != null) { queue.Remove(work.Node); work.Node = null; }
                work.Completion.TrySetException(new ProtocolException(code, "Request ended."));
            }
            _ = Task.Run(() => work.Cancellation.Cancel());
            return true;
        }

        private async Task ExpireAsync(Work work, CancellationToken ct)
        {
            using (var registration = ct.Register(() => Finish(work.Id, ErrorCodes.Cancelled)))
            {
                var delay = Task.Delay(timeout);
                if (await Task.WhenAny(work.Completion.Task, delay).ConfigureAwait(false) == delay)
                    Finish(work.Id, ErrorCodes.Timeout);
            }
        }

        private void Start(Work work)
        {
            active++;
            _ = Task.Run(async () =>
            {
                try
                {
                    var result = await work.Operation(work.Cancellation.Token).ConfigureAwait(false);
                    lock (gate) { if (pending.Remove(work.Id)) work.Completion.TrySetResult(result); }
                }
                catch (Exception error)
                {
                    lock (gate) { if (pending.Remove(work.Id)) work.Completion.TrySetException(error); }
                }
                finally
                {
                    lock (gate)
                    {
                        active--;
                        if (!disposed && queue.First != null)
                        {
                            var next = queue.First.Value;
                            queue.RemoveFirst(); next.Node = null; Start(next);
                        }
                    }
                }
            });
        }

        public void Dispose()
        {
            Work[] work;
            lock (gate)
            {
                if (disposed) return;
                disposed = true;
                work = new Work[pending.Count]; pending.Values.CopyTo(work, 0);
                pending.Clear(); queue.Clear();
                foreach (var item in work) item.Completion.TrySetCanceled();
            }
            foreach (var item in work) _ = Task.Run(() => item.Cancellation.Cancel());
        }
    }
}
