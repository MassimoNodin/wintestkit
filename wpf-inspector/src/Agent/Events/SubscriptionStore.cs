using System;
using System.Collections.Generic;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Events
{
    // All methods are thread-safe. Delivery acknowledges an overflow only after its frame is written.
    public sealed class SubscriptionStore
    {
        private sealed class Subscription
        {
            internal readonly HashSet<string> Kinds;
            internal readonly Queue<EventsEventParams> Pending = new Queue<EventsEventParams>();
            internal long NextSequence = 1;
            internal bool Overflow;
            internal Subscription(IEnumerable<string> kinds) { Kinds = new HashSet<string>(kinds, StringComparer.Ordinal); }
        }

        private readonly object gate = new object();
        private readonly Dictionary<string, Subscription> subscriptions = new Dictionary<string, Subscription>(StringComparer.Ordinal);
        public event Action? Available;

        public string Subscribe(IReadOnlyList<string> kinds)
        {
            // Reuse the protocol's strict validation, including duplicate and reserved kinds.
            new EventsSubscribeParams { Kinds = kinds }.ToJson();
            string id = Guid.NewGuid().ToString("N");
            lock (gate) subscriptions.Add(id, new Subscription(kinds));
            return id;
        }

        public bool Unsubscribe(string id) { lock (gate) return subscriptions.Remove(id); }
        public void Clear() { lock (gate) subscriptions.Clear(); }
        public bool Wants(string kind)
        {
            lock (gate) { foreach (var subscription in subscriptions.Values) if (subscription.Kinds.Contains(kind)) return true; return false; }
        }

        public void Publish(string kind, ObjectRef? handle)
        {
            bool available = false;
            lock (gate)
            {
                foreach (var pair in subscriptions)
                {
                    var subscription = pair.Value;
                    if (!subscription.Kinds.Contains(kind) || subscription.Overflow) continue;
                    long sequence = subscription.NextSequence++;
                    if (subscription.Pending.Count == 1024)
                    {
                        subscription.Pending.Clear();
                        subscription.Overflow = true;
                        subscription.Pending.Enqueue(new EventsEventParams { SubscriptionId = pair.Key, Sequence = subscription.NextSequence++, Kind = EventKind.Overflow });
                    }
                    else subscription.Pending.Enqueue(new EventsEventParams { SubscriptionId = pair.Key, Sequence = sequence, Kind = kind, Handle = handle });
                    available = true;
                }
            }
            if (available) Available?.Invoke();
        }

        public EventsEventParams? Take()
        {
            lock (gate)
            {
                foreach (var subscription in subscriptions.Values)
                    if (subscription.Pending.Count != 0) return subscription.Pending.Dequeue();
                return null;
            }
        }

        public void Delivered(EventsEventParams notification)
        {
            if (notification.Kind != EventKind.Overflow) return;
            lock (gate) if (subscriptions.TryGetValue(notification.SubscriptionId, out var subscription)) subscription.Overflow = false;
        }
    }
}
