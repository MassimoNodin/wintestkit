namespace WinTestKit.Inspector.Protocol
{
    public sealed class FocusScope
    {
        public string ObjectId { get; set; } = ""; public long Generation { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); DtoHelpers.Add(o, "objectId", ObjectId); o.Add("generation", JsonNumberNode.From(Generation)); FromJson(o); return o; }
        public static FocusScope FromJson(JsonNode n) { var o = DtoHelpers.Object(n, "objectId", "generation"); return new FocusScope { ObjectId = DtoHelpers.Required(o, "objectId"), Generation = DtoHelpers.Integer(o.Get("generation"), 1) }; }
    }
    public sealed class FocusParams
    {
        public string SessionId { get; set; } = ""; public FocusScope? Scope { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); DtoHelpers.Add(o, "sessionId", SessionId); if (Scope != null) o.Add("scope", Scope.ToJson()); FromJson(o); return o; }
        public static FocusParams FromJson(JsonNode n) { var o = DtoHelpers.Object(n, "sessionId", "scope"); return new FocusParams { SessionId = DtoHelpers.Required(o, "sessionId"), Scope = o.TryGet("scope", out var s) ? FocusScope.FromJson(s) : null }; }
    }
    public sealed class FocusResult
    {
        public ObjectRef Ref { get; set; } = new ObjectRef(); public bool IsPassword { get; set; } public bool Classified { get; set; } public bool WithinScope { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("ref", Ref.ToJson()); o.Add("isPassword", new JsonBoolNode(IsPassword)); o.Add("classified", new JsonBoolNode(Classified)); o.Add("withinScope", new JsonBoolNode(WithinScope)); return o; }
        public static FocusResult FromJson(JsonNode n) { var o = DtoHelpers.Object(n, "ref", "isPassword", "classified", "withinScope"); return new FocusResult { Ref = ObjectRef.FromJson(o.Get("ref")), IsPassword = DtoHelpers.Boolean(o.Get("isPassword")), Classified = DtoHelpers.Boolean(o.Get("classified")), WithinScope = DtoHelpers.Boolean(o.Get("withinScope")) }; }
    }
}
