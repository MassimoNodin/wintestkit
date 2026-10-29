namespace WinTestKit.Inspector.Protocol
{
    // The schema reuses these shapes for the simple action methods.
    public sealed class StateGetParams
    {
        public ObjectRef Handle { get; set; } = new ObjectRef();
        public int TimeoutMs { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("handle", Handle.ToJson()); o.Add("timeoutMs", JsonNumberNode.From(TimeoutMs)); FromJson(o); return o; }
        public static StateGetParams FromJson(JsonNode node) { var o = DtoHelpers.Object(node, "handle", "timeoutMs"); return new StateGetParams { Handle = ObjectRef.FromJson(o.Get("handle")), TimeoutMs = (int)DtoHelpers.Integer(o.Get("timeoutMs"), 1, ProtocolLimits.RequestTimeoutMs) }; }
    }
    public sealed class ActResult
    {
        public string Outcome { get; set; } = "";
        public ObjectRef Handle { get; set; } = new ObjectRef();
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); DtoHelpers.Add(o, "outcome", Outcome); o.Add("handle", Handle.ToJson()); FromJson(o); return o; }
        public static ActResult FromJson(JsonNode node) { var o = DtoHelpers.Object(node, "outcome", "handle"); var result = new ActResult { Outcome = DtoHelpers.Required(o, "outcome"), Handle = ObjectRef.FromJson(o.Get("handle")) }; DtoHelpers.OneOf(result.Outcome, ActionOutcome.Performed, ActionOutcome.NoChange); return result; }
    }
}
