using System;
using System.Collections.Generic;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Contracts;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Inspection
{
    public sealed class ObjectRegistry : IObjectRegistry, IDisposable
    {
        private sealed class Entry
        {
            internal WeakReference Target = null!;
            internal object? Lease;
            internal DateTime LastUse;
            internal Dispatcher Dispatcher = null!;
            internal ObjectRef Reference = null!;
        }
        private readonly object gate = new object();
        private readonly Dictionary<string, Entry> entries = new Dictionary<string, Entry>(StringComparer.Ordinal);
        private readonly string sessionId;
        private readonly DispatcherExecutor executor;
        private readonly Func<DateTime> now;
        private long nextId;
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
                        return entry.Reference;
                    }
                if (entries.Count >= ProtocolLimits.MaxWeakEntries) throw Limit();
                long id = checked(++nextId);
                var reference = new ObjectRef { SessionId = sessionId, ObjectId = sessionId + ":" + id.ToString(System.Globalization.CultureInfo.InvariantCulture) + ":" + id.ToString(System.Globalization.CultureInfo.InvariantCulture), Generation = id, Type = type, DispatcherId = executor.GetDispatcherId(dispatcher) };
                var created = new Entry { Target = new WeakReference(target), Dispatcher = dispatcher, Reference = reference };
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
        public int Release(IEnumerable<string> objectIds)
        {
            lock (gate) { CheckDisposed(); int count = 0; foreach (string id in objectIds) if (entries.Remove(id)) count++; return count; }
        }
        private void Lease(Entry entry, object target)
        {
            if (entry.Lease == null)
            {
                int count = 0;
                foreach (Entry item in entries.Values) if (item.Lease != null) count++;
                if (count >= ProtocolLimits.MaxStrongHandles) throw Limit();
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
        }
        private static ProtocolException Limit() => new ProtocolException(ErrorCodes.LimitExceeded, "Object registry limit reached.");
        private void CheckDisposed() { if (disposed) throw new ObjectDisposedException(nameof(ObjectRegistry)); }
        public void Dispose() { lock (gate) { entries.Clear(); disposed = true; } }
    }
}
