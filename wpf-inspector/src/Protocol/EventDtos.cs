using System.Collections.Generic;

namespace WinTestKit.Inspector.Protocol
{
    public sealed class EventsSubscribeParams
    {
        public IReadOnlyList<string> Kinds { get; set; } = new List<string>();
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("kinds", DtoHelpers.Strings(Kinds)); FromJson(o); return o; }
        public static EventsSubscribeParams FromJson(JsonNode node) { var o = DtoHelpers.Object(node, "kinds"); var kinds = DtoHelpers.Strings(o.Get("kinds"), 3); var seen = new HashSet<string>(); foreach (var kind in kinds) { DtoHelpers.OneOf(kind, EventKind.WindowOpened, EventKind.WindowClosed, EventKind.TreeChanged); if (!seen.Add(kind)) throw DtoHelpers.Invalid("Duplicate event kind"); } if (kinds.Count == 0) throw DtoHelpers.Invalid("No event kinds"); return new EventsSubscribeParams { Kinds = kinds }; }
    }
    public sealed class EventsSubscription
    {
        public string SubscriptionId { get; set; } = "";
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); DtoHelpers.Add(o, "subscriptionId", SubscriptionId); FromJson(o); return o; }
        public static EventsSubscription FromJson(JsonNode node) { var o = DtoHelpers.Object(node, "subscriptionId"); return new EventsSubscription { SubscriptionId = DtoHelpers.Required(o, "subscriptionId") }; }
    }
    public sealed class EventsUnsubscribeResult
    {
        public bool Unsubscribed { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("unsubscribed", new JsonBoolNode(Unsubscribed)); return o; }
        public static EventsUnsubscribeResult FromJson(JsonNode node) { var o = DtoHelpers.Object(node, "unsubscribed"); return new EventsUnsubscribeResult { Unsubscribed = DtoHelpers.Boolean(o.Get("unsubscribed")) }; }
    }
    public sealed class EventsEventParams
    {
        public string SubscriptionId { get; set; } = ""; public long Sequence { get; set; } public string Kind { get; set; } = ""; public ObjectRef? Handle { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); DtoHelpers.Add(o, "subscriptionId", SubscriptionId); o.Add("sequence", JsonNumberNode.From(Sequence)); DtoHelpers.Add(o, "kind", Kind); if (Handle != null) o.Add("handle", Handle.ToJson()); FromJson(o); return o; }
        public static EventsEventParams FromJson(JsonNode node) { var o = DtoHelpers.Object(node, "subscriptionId", "sequence", "kind", "handle"); var result = new EventsEventParams { SubscriptionId = DtoHelpers.Required(o, "subscriptionId"), Sequence = DtoHelpers.Integer(o.Get("sequence"), 1), Kind = DtoHelpers.Required(o, "kind"), Handle = o.TryGet("handle", out var handle) ? ObjectRef.FromJson(handle) : null }; DtoHelpers.OneOf(result.Kind, EventKind.WindowOpened, EventKind.WindowClosed, EventKind.TreeChanged, EventKind.Overflow); if (result.Kind == EventKind.Overflow && result.Handle != null) throw DtoHelpers.Invalid("Overflow cannot contain a handle"); return result; }
    }
    public sealed class EventsNotification
    {
        public EventsEventParams Params { get; set; } = new EventsEventParams();
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("method", new JsonStringNode("events.event")); o.Add("params", Params.ToJson()); return o; }
        public static EventsNotification FromJson(JsonNode node) { var o = DtoHelpers.Object(node, "method", "params"); DtoHelpers.OneOf(DtoHelpers.Required(o, "method"), "events.event"); return new EventsNotification { Params = EventsEventParams.FromJson(o.Get("params")) }; }
    }
}
