using System;
using System.Collections.Generic;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Contracts;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Inspection
{
    public sealed class ObjectRegistry : IObjectRegistry, IHandOutLedger, IDisposable
    {
        private sealed class Entry
        {
            internal WeakReference Target = null!;
            internal object? Lease;
            internal DateTime LastUse;
            internal Dispatcher Dispatcher = null!;
            internal ObjectRef Reference = null!;
            /// <summary>How many times this ID was handed out and not yet released. The lease ends when it returns to zero.</summary>
            internal long HandOuts;
            /// <summary>Position in the register order of the last <see cref="Register"/> that returned this entry.</summary>
            internal long LastRegister;
            internal bool ZeroPending;
        }
        private readonly object gate = new object();
        private readonly Dictionary<string, Entry> entries = new Dictionary<string, Entry>(StringComparer.Ordinal);
        private readonly string sessionId;
        private readonly DispatcherExecutor executor;
        private readonly Func<DateTime> now;
        private readonly Dictionary<long, int> activeRequests = new Dictionary<long, int>();
        private readonly List<string> zeroPending = new List<string>();
        private long nextId;
        private long registerClock;
        private bool disposed;
        public ObjectRegistry(string sessionId, DispatcherExecutor executor) : this(sessionId, executor, () => DateTime.UtcNow) { }
        public ObjectRegistry(string sessionId, DispatcherExecutor executor, Func<DateTime> now) { this.sessionId = sessionId; this.executor = executor; this.now = now; }

        public ObjectRef Register(object target, Dispatcher traversalDispatcher, TypeInfoDto type)
        {
            if (target == null) throw new ArgumentNullException(nameof(target));
            Dispatcher dispatcher = target is DispatcherObject dispatcherObject ? (dispatcherObject.Dispatcher ?? traversalDispatcher) : traversalDispatcher;
            lock (gate)
            {
                CheckDisposed();
                Prune();
                foreach (Entry entry in entries.Values)
                    if (ReferenceEquals(entry.Target.Target, target))
                    {
                        if (entry.Lease != null) entry.LastUse = now();
                        entry.LastRegister = ++registerClock;
                        return entry.Reference;
                    }
                if (entries.Count >= ProtocolLimits.MaxWeakEntries) throw Limit();
                long id = checked(++nextId);
                var reference = new ObjectRef { SessionId = sessionId, ObjectId = sessionId + ":" + id.ToString(System.Globalization.CultureInfo.InvariantCulture) + ":" + id.ToString(System.Globalization.CultureInfo.InvariantCulture), Generation = id, Type = type, DispatcherId = executor.GetDispatcherId(dispatcher) };
                var created = new Entry { Target = new WeakReference(target), Dispatcher = dispatcher, Reference = reference, LastRegister = ++registerClock };
                entries.Add(reference.ObjectId, created);
                return reference;
            }
        }
        public bool TryGet(string objectId, long generation, out object target, out Dispatcher dispatcher)
        {
            lock (gate)
            {
                CheckDisposed();
                Prune();
                if (entries.TryGetValue(objectId, out Entry? entry) && entry.Reference.Generation == generation && entry.Target.Target is object value)
                {
                    Lease(entry, value); target = value; dispatcher = entry.Dispatcher; return true;
                }
                target = null!; dispatcher = null!; return false;
            }
        }
        internal bool TryGetWeak(string objectId, long generation, out object target)
        {
            lock (gate)
            {
                CheckDisposed();
                Prune();
                if (entries.TryGetValue(objectId, out Entry? entry) && entry.Reference.Generation == generation && entry.Target.Target is object value)
                {
                    target = value; return true;
                }
                target = null!; return false;
            }
        }
        /// <summary>
        /// Counts handles that are being sent to the client, once per occurrence. The count is what keeps a release
        /// that was decided before this hand-out (and reaches the agent after it) from ending the lease.
        /// </summary>
        public void CountHandOuts(IReadOnlyList<KeyValuePair<string, long>> handles)
        {
            if (handles.Count == 0) return;
            lock (gate)
            {
                if (disposed) return;
                foreach (var handle in handles)
                    if (entries.TryGetValue(handle.Key, out Entry? entry) && entry.Reference.Generation == handle.Value)
                    {
                        if (entry.HandOuts < long.MaxValue) entry.HandOuts++;
                        entry.ZeroPending = false;
                    }
            }
        }

        /// <summary>
        /// Takes back hand-outs. An entry is freed only when its count reaches zero; asking for more than is outstanding
        /// is clamped and counted as an over-release, so a miscounting client can never free a live object early.
        /// </summary>
        public ReleaseResult Release(IReadOnlyList<ReleaseItem> items)
        {
            lock (gate)
            {
                CheckDisposed();
                var result = new ReleaseResult();
                var requested = new Dictionary<string, long>(StringComparer.Ordinal);
                foreach (ReleaseItem item in items)
                {
                    requested.TryGetValue(item.ObjectId, out long total);
                    requested[item.ObjectId] = total + item.Count;
                }
                foreach (var request in requested)
                {
                    if (!entries.TryGetValue(request.Key, out Entry? entry)) { result.OverReleasedCount++; continue; }
                    long outstanding = entry.HandOuts;
                    if (request.Value > outstanding) result.OverReleasedCount++;
                    if (outstanding == 0) continue;
                    entry.HandOuts = outstanding - Math.Min(request.Value, outstanding);
                    if (entry.HandOuts > 0) continue;
                    result.ReleasedCount++;
                    entry.Lease = null;
                    if (CanRemove(entry)) entries.Remove(request.Key);
                    else if (!entry.ZeroPending) { entry.ZeroPending = true; zeroPending.Add(request.Key); }
                }
                return result;
            }
        }

        /// <summary>
        /// Marks the start of a request. An entry that a request registered is handed out only once that request's response
        /// has been counted, so until the request ends a release that brings the count to zero keeps the entry (weak)
        /// instead of removing it; <see cref="EndRequest"/> removes it if the response did not hand it out after all.
        /// </summary>
        public long BeginRequest()
        {
            lock (gate)
            {
                long start = registerClock;
                activeRequests.TryGetValue(start, out int running);
                activeRequests[start] = running + 1;
                return start;
            }
        }

        public void EndRequest(long token)
        {
            lock (gate)
            {
                if (activeRequests.TryGetValue(token, out int running))
                {
                    if (running <= 1) activeRequests.Remove(token); else activeRequests[token] = running - 1;
                }
                if (!disposed) SweepZeroPending();
            }
        }

        private bool CanRemove(Entry entry)
        {
            if (activeRequests.Count == 0) return true;
            long oldest = long.MaxValue;
            foreach (long start in activeRequests.Keys) if (start < oldest) oldest = start;
            return entry.LastRegister <= oldest;
        }

        private void SweepZeroPending()
        {
            for (int i = zeroPending.Count - 1; i >= 0; i--)
            {
                string id = zeroPending[i];
                if (!entries.TryGetValue(id, out Entry? entry) || !entry.ZeroPending) zeroPending.RemoveAt(i);
                else if (entry.HandOuts > 0) { entry.ZeroPending = false; zeroPending.RemoveAt(i); }
                else if (CanRemove(entry)) { entries.Remove(id); zeroPending.RemoveAt(i); }
            }
        }

        private void Lease(Entry entry, object target)
        {
            if (entry.Lease == null)
            {
                Prune();
                int count = 0;
                Entry? oldest = null;
                foreach (Entry item in entries.Values)
                    if (item.Lease != null)
                    {
                        count++;
                        if (oldest == null || item.LastUse < oldest.LastUse) oldest = item;
                    }
                if (count >= ProtocolLimits.MaxStrongHandles && oldest != null) oldest.Lease = null;
            }
            entry.Lease = target; entry.LastUse = now();
        }
        private void Prune()
        {
            DateTime expiry = now().AddMilliseconds(-ProtocolLimits.LeaseInactivityMs);
            var dead = new List<string>();
            foreach (var pair in entries)
            {
                if (pair.Value.LastUse <= expiry) pair.Value.Lease = null;
                if (!pair.Value.Target.IsAlive) dead.Add(pair.Key);
            }
            foreach (string key in dead) entries.Remove(key);
            SweepZeroPending();
        }
        private static ProtocolException Limit() => new ProtocolException(ErrorCodes.LimitExceeded, "Object registry limit reached.");
        private void CheckDisposed() { if (disposed) throw new ObjectDisposedException(nameof(ObjectRegistry)); }
        public void Dispose() { lock (gate) { entries.Clear(); zeroPending.Clear(); activeRequests.Clear(); disposed = true; } }
    }
}
