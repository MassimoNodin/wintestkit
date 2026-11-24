using System;
using System.Collections.Generic;

namespace WinTestKit.Inspector.Protocol
{
    /// <summary>Limits of the <c>members.events</c> answer.</summary>
    public static class MemberEventLimits
    {
        /// <summary>Handlers or subscribers listed per event.</summary>
        public const int MaxHandlers = 32;
        public const int MaxText = StylingLimits.MaxText;
    }

    public static class MemberEventValues
    {
        public const string Routed = "routed", Clr = "clr";
        public static readonly string[] Kinds = { Routed, Clr };
        public static readonly string[] Strategies = { "bubble", "tunnel", "direct" };
        public static readonly string[] ResourceScopes = { "local", "application" };
    }

    /// <summary>One handler of a routed event, or one subscriber of a CLR event: the method the delegate points at. No handler is invoked to find it.</summary>
    public sealed class MemberEventHandlerDto
    {
        /// <summary>The type that declares the target method; empty for a dynamic method.</summary>
        public string DeclaringType { get; set; } = "";
        public string Method { get; set; } = "";
        /// <summary>Routed handlers only: the handler is also called for events another handler marked handled.</summary>
        public bool? HandledEventsToo { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("declaringType", new JsonStringNode(DeclaringType)); o.Add("method", new JsonStringNode(Method)); if (HandledEventsToo.HasValue) StylingJson.Flag(o, "handledEventsToo", HandledEventsToo.Value); return o; }
        public static MemberEventHandlerDto FromJson(JsonNode node) { var o = DtoHelpers.Object(node, "declaringType", "method", "handledEventsToo"); return new MemberEventHandlerDto { DeclaringType = StylingJson.Text(o, "declaringType"), Method = StylingJson.Text(o, "method"), HandledEventsToo = o.TryGet("handledEventsToo", out var flag) ? DtoHelpers.Boolean(flag) : (bool?)null }; }
    }

    /// <summary>
    /// An event of an object: a routed event that applies to its type, or a CLR event the type declares. A CLR event that only wraps a routed
    /// event of the same name and handler type is not listed twice: the routed entry stands for it. The handler list is named by kind on the wire:
    /// <c>handlersKnown</c>, <c>handlerCount</c>, <c>handlersTruncated</c> and <c>handlers</c> for a routed event,
    /// <c>subscribersKnown</c>, <c>subscriberCount</c>, <c>subscribersTruncated</c> and <c>subscribers</c> for a CLR event.
    /// </summary>
    public sealed class MemberEventDto
    {
        public string Kind { get; set; } = MemberEventValues.Routed;
        public string Name { get; set; } = "";
        /// <summary>The routed event's owner type, or the type that declares the CLR event.</summary>
        public string DeclaringType { get; set; } = "";
        public string HandlerType { get; set; } = "";
        /// <summary>Routed events only.</summary>
        public string? Strategy { get; set; }
        /// <summary>CLR events only.</summary>
        public bool IsStatic { get; set; }
        /// <summary>False when the handlers could not be read: the framework's store or the event's backing field was not found, or the object is protected.</summary>
        public bool Known { get; set; }
        public int Count { get; set; }
        public bool Truncated { get; set; }
        public IReadOnlyList<MemberEventHandlerDto> Handlers { get; set; } = new List<MemberEventHandlerDto>();

        private static readonly string[] Common = { "kind", "name", "declaringType", "handlerType" };
        private static readonly string[] RoutedKeys = { "strategy", "handlersKnown", "handlerCount", "handlersTruncated", "handlers" };
        private static readonly string[] ClrKeys = { "isStatic", "subscribersKnown", "subscriberCount", "subscribersTruncated", "subscribers" };

        public JsonObjectNode ToJson()
        {
            var o = new JsonObjectNode();
            o.Add("kind", new JsonStringNode(Kind)); o.Add("name", new JsonStringNode(Name)); o.Add("declaringType", new JsonStringNode(DeclaringType)); o.Add("handlerType", new JsonStringNode(HandlerType));
            bool routed = Kind == MemberEventValues.Routed;
            if (routed) o.Add("strategy", new JsonStringNode(Strategy ?? throw DtoHelpers.Invalid("Routed event without a strategy"))); else StylingJson.Flag(o, "isStatic", IsStatic);
            string[] keys = routed ? RoutedKeys : ClrKeys;
            StylingJson.Flag(o, keys[1], Known); StylingJson.Number(o, keys[2], Count); StylingJson.Flag(o, keys[3], Truncated); o.Add(keys[4], StylingJson.Array(Handlers, item => item.ToJson()));
            return o;
        }

        public static MemberEventDto FromJson(JsonNode node)
        {
            var all = new List<string>(Common); all.AddRange(RoutedKeys); all.AddRange(ClrKeys);
            var o = DtoHelpers.Object(node, all.ToArray());
            var result = new MemberEventDto { Kind = StylingJson.Choice(o, "kind", MemberEventValues.Kinds), Name = StylingJson.Text(o, "name"), DeclaringType = StylingJson.Text(o, "declaringType"), HandlerType = StylingJson.Text(o, "handlerType") };
            bool routed = result.Kind == MemberEventValues.Routed;
            foreach (string foreign in routed ? ClrKeys : RoutedKeys) if (o.TryGet(foreign, out _)) throw DtoHelpers.Invalid("Field does not belong to the event kind");
            if (routed) result.Strategy = StylingJson.Choice(o, "strategy", MemberEventValues.Strategies); else result.IsStatic = DtoHelpers.Boolean(o.Get("isStatic"));
            string[] keys = routed ? RoutedKeys : ClrKeys;
            result.Known = DtoHelpers.Boolean(o.Get(keys[1]));
            result.Count = StylingJson.Count(o, keys[2]);
            result.Truncated = DtoHelpers.Boolean(o.Get(keys[3]));
            result.Handlers = StylingJson.List(o, keys[4], MemberEventLimits.MaxHandlers, MemberEventHandlerDto.FromJson);
            if (!result.Known && (result.Count != 0 || result.Truncated || result.Handlers.Count != 0)) throw DtoHelpers.Invalid("Unknown handlers cannot be listed");
            StylingJson.Check(result.Truncated, result.Count, result.Handlers.Count, MemberEventLimits.MaxHandlers);
            foreach (var handler in result.Handlers) if (routed != handler.HandledEventsToo.HasValue) throw DtoHelpers.Invalid("Handler does not match the event kind");
            return result;
        }
    }

    /// <summary>Parameters of <c>members.resource</c>: one value of a resource dictionary, named by what the <c>members.styling</c> listing returned for it.</summary>
    public sealed class ResourceParams
    {
        public string SessionId { get; set; } = "";
        public string ObjectId { get; set; } = "";
        public long Generation { get; set; }
        /// <summary><c>local</c> for the object's own dictionary, <c>application</c> for Application.Current.Resources.</summary>
        public string Scope { get; set; } = "local";
        public string Key { get; set; } = "";
        public string KeyKind { get; set; } = "string";
        /// <summary>Where the key was in the dictionary's key order when it was listed; a hint that spares a search.</summary>
        public int? Index { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); DtoHelpers.Add(o, "sessionId", SessionId); DtoHelpers.Add(o, "objectId", ObjectId); o.Add("generation", JsonNumberNode.From(Generation)); o.Add("scope", new JsonStringNode(Scope)); o.Add("key", new JsonStringNode(Key)); o.Add("keyKind", new JsonStringNode(KeyKind)); if (Index.HasValue) o.Add("index", JsonNumberNode.From(Index.Value)); FromJson(o); return o; }
        public static ResourceParams FromJson(JsonNode node) { var o = DtoHelpers.Object(node, "sessionId", "objectId", "generation", "scope", "key", "keyKind", "index"); return new ResourceParams { SessionId = DtoHelpers.Required(o, "sessionId"), ObjectId = DtoHelpers.Required(o, "objectId"), Generation = DtoHelpers.Integer(o.Get("generation"), 1), Scope = StylingJson.Choice(o, "scope", MemberEventValues.ResourceScopes), Key = StylingJson.Text(o, "key"), KeyKind = StylingJson.Choice(o, "keyKind", StylingValues.KeyKinds), Index = o.TryGet("index", out var index) ? (int)DtoHelpers.Integer(index, 0, int.MaxValue) : (int?)null }; }
    }

    /// <summary>Result of <c>members.resource</c>. Not found (and empty) when the dictionary no longer has the key, or the object is protected.</summary>
    public sealed class ResourceResult
    {
        public bool Found { get; set; }
        public string ValueType { get; set; } = "";
        public ValueDto? Value { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); StylingJson.Flag(o, "found", Found); if (Found) { o.Add("valueType", new JsonStringNode(ValueType)); o.Add("value", (Value ?? throw DtoHelpers.Invalid("Found resource without a value")).ToJson()); } return o; }
        public static ResourceResult FromJson(JsonNode node)
        {
            var o = DtoHelpers.Object(node, "found", "valueType", "value");
            var result = new ResourceResult { Found = DtoHelpers.Boolean(o.Get("found")) };
            if (result.Found) { result.ValueType = StylingJson.Text(o, "valueType"); result.Value = ValueDto.FromJson(o.Get("value")); }
            else if (o.TryGet("valueType", out _) || o.TryGet("value", out _)) throw DtoHelpers.Invalid("Not found result must be empty");
            return result;
        }
    }
}
