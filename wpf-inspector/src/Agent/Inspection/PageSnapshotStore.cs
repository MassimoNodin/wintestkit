using System;
using System.Collections.Generic;
using System.Security.Cryptography;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Inspection
{
    /// <summary>Session-owned bounded, expiring immutable pagination snapshots.</summary>
    public sealed class PageSnapshotStore : IDisposable
    {
        private sealed class Snapshot
        {
            internal string Binding = "";
            internal DateTime Expires;
            internal object Items = null!;
        }
        private readonly object gate = new object();
        private readonly Dictionary<string, Snapshot> snapshots = new Dictionary<string, Snapshot>(StringComparer.Ordinal);
        private readonly Func<DateTime> now;
        private bool disposed;
        public PageSnapshotStore() : this(() => DateTime.UtcNow) { }
        public PageSnapshotStore(Func<DateTime> now) { this.now = now; }

        public string Create<T>(string objectId, long generation, string operation, string tree,
            IReadOnlyList<T> items, IComparer<T>? comparer = null) =>
            Create(Bind(objectId, generation, operation, tree), items, comparer);

        public IReadOnlyList<T> Get<T>(string token, string objectId, long generation, string operation, string tree) =>
            Get<T>(token, Bind(objectId, generation, operation, tree));

        public string Create<T>(string binding, IReadOnlyList<T> items, IComparer<T>? comparer = null)
        {
            lock (gate)
            {
                CheckDisposed();
                Prune();
                if (snapshots.Count >= ProtocolLimits.MaxSnapshots)
                    throw new ProtocolException(ErrorCodes.LimitExceeded, "Snapshot limit reached.");
                byte[] bytes = new byte[32];
                string token;
                do
                {
                    using (RandomNumberGenerator rng = RandomNumberGenerator.Create()) rng.GetBytes(bytes);
                    token = Convert.ToBase64String(bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_');
                } while (snapshots.ContainsKey(token));
                var copy = new T[items.Count];
                for (int i = 0; i < copy.Length; i++) copy[i] = items[i];
                Array.Sort(copy, comparer ?? Comparer<T>.Default);
                snapshots.Add(token, new Snapshot { Binding = binding, Expires = now().AddMilliseconds(ProtocolLimits.PageTokenTtlMs), Items = Array.AsReadOnly(copy) });
                return token;
            }
        }

        public IReadOnlyList<T> Get<T>(string token, string binding)
        {
            lock (gate)
            {
                CheckDisposed();
                Prune();
                if (token == null || !snapshots.TryGetValue(token, out Snapshot? snapshot) || snapshot.Binding != binding || !(snapshot.Items is IReadOnlyList<T> items))
                    throw new ProtocolException(ErrorCodes.InvalidPageToken, "Invalid or expired page token.");
                return items;
            }
        }

        private static string Bind(string objectId, long generation, string operation, string tree) =>
            objectId.Length.ToString(System.Globalization.CultureInfo.InvariantCulture) + ":" + objectId + ":" +
            generation.ToString(System.Globalization.CultureInfo.InvariantCulture) + ":" +
            operation.Length.ToString(System.Globalization.CultureInfo.InvariantCulture) + ":" + operation + ":" + tree;

        public void Remove(string token) { lock (gate) { CheckDisposed(); snapshots.Remove(token); } }
        private void Prune()
        {
            var expired = new List<string>();
            DateTime current = now();
            foreach (var entry in snapshots) if (entry.Value.Expires <= current) expired.Add(entry.Key);
            foreach (string key in expired) snapshots.Remove(key);
        }
        private void CheckDisposed() { if (disposed) throw new ObjectDisposedException(nameof(PageSnapshotStore)); }
        public void Dispose() { lock (gate) { snapshots.Clear(); disposed = true; } }
    }
}
