using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text.RegularExpressions;
namespace WinTestKit.Inspector.Protocol
{
    internal static class RemainingHelpers
    {
        internal static int Timeout(JsonObjectNode o) => (int)DtoHelpers.Integer(o.Get("timeoutMs"), 1, 2000);
        internal static void WriteScalar(JsonNode n) { QueryHelpers.Scalar(n); if (n is JsonNumberNode number && number.RawText.IndexOfAny(new[] {'.','e','E'}) < 0 && !number.TryGetInt64(out _)) throw DtoHelpers.Invalid("Integer out of range"); }
        internal static string Key(JsonObjectNode o, bool method) { var key = DtoHelpers.Required(o,"memberKey",1024); var pattern = method ? @"^[^\s(),\[\]&*?`]+\((?:[^\s(),\[\]&*?`]+(?:,[^\s(),\[\]&*?`]+)*)?\)$" : @"^[^\s(),\[\]&*?`]+$"; if (!Regex.IsMatch(key,pattern)) throw DtoHelpers.Invalid("Invalid member key"); return key; }
    }
    public static class ScrollAmount { public const string None = "none", SmallIncrement = "smallIncrement", SmallDecrement = "smallDecrement", LargeIncrement = "largeIncrement", LargeDecrement = "largeDecrement"; internal static string Read(JsonNode n) { var s = DtoHelpers.String(n); DtoHelpers.OneOf(s,None,SmallIncrement,SmallDecrement,LargeIncrement,LargeDecrement); return s; } }
    public sealed class ItemMatch
    {
        public string Kind { get; set; } = ""; public int? Index { get; set; } public IReadOnlyList<PathSegment>? Path { get; set; } public JsonNode? Value { get; set; } public string? Pattern { get; set; } public IReadOnlyList<string>? Flags { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); DtoHelpers.Add(o,"kind",Kind); DtoHelpers.Add(o,"index",Index); if (Path != null) o.Add("path",ResultHelpers.Path(Path)); if (Value != null) o.Add("value",Value); DtoHelpers.Add(o,"pattern",Pattern); if (Flags != null) o.Add("flags",DtoHelpers.Strings(Flags)); FromJson(o); return o; }
        public static ItemMatch FromJson(JsonNode n) { var o = DtoHelpers.Object(n,"kind","index","path","value","pattern","flags"); var x = new ItemMatch { Kind = DtoHelpers.Required(o,"kind") }; if (x.Kind == "index") { DtoHelpers.Object(n,"kind","index"); x.Index = (int)DtoHelpers.Integer(o.Get("index"),0,9999); } else if (x.Kind == "equals" || x.Kind == "regex") { var p = Predicate.FromJson(n); x.Path = p.Path; x.Value = p.Value; x.Pattern = p.Pattern; x.Flags = p.Flags; } else throw DtoHelpers.Invalid("Unknown item match"); return x; }
    }
    public sealed class ItemSearch
    {
        public ObjectRef Container { get; set; } = new ObjectRef(); public ItemMatch Match { get; set; } = new ItemMatch(); public int MaxItems { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("container",Container.ToJson()); o.Add("match",Match.ToJson()); o.Add("maxItems",JsonNumberNode.From(MaxItems)); FromJson(o); return o; }
        public static ItemSearch FromJson(JsonNode n) { var o = DtoHelpers.Object(n,"container","match","maxItems"); return new ItemSearch { Container = ObjectRef.FromJson(o.Get("container")), Match = ItemMatch.FromJson(o.Get("match")), MaxItems = (int)DtoHelpers.Integer(o.Get("maxItems"),1,10000) }; }
    }
    public sealed class ActRealizeItemParams
    {
        public ItemSearch Search { get; set; } = new ItemSearch(); public int TimeoutMs { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("search",Search.ToJson()); o.Add("timeoutMs",JsonNumberNode.From(TimeoutMs)); FromJson(o); return o; }
        public static ActRealizeItemParams FromJson(JsonNode n) { var o = DtoHelpers.Object(n,"search","timeoutMs"); return new ActRealizeItemParams { Search = ItemSearch.FromJson(o.Get("search")), TimeoutMs = RemainingHelpers.Timeout(o) }; }
    }
    public sealed class ActRealizeItemResult
    {
        public string Outcome { get; set; } = ""; public ObjectRef Handle { get; set; } = new ObjectRef(); public MatchWarning? Warning { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); DtoHelpers.Add(o,"outcome",Outcome); o.Add("handle",Handle.ToJson()); if (Warning != null) o.Add("warning",Warning.ToJson()); FromJson(o); return o; }
        public static ActRealizeItemResult FromJson(JsonNode n) { var o = DtoHelpers.Object(n,"outcome","handle","warning"); var x = new ActRealizeItemResult { Outcome = DtoHelpers.Required(o,"outcome"), Handle = ObjectRef.FromJson(o.Get("handle")), Warning = o.TryGet("warning",out var w) ? MatchWarning.FromJson(w) : null }; DtoHelpers.OneOf(x.Outcome,"performed","noChange"); return x; }
    }
    public sealed class ActScrollParams
    {
        public ObjectRef Handle { get; set; } = new ObjectRef(); public string Horizontal { get; set; } = ""; public string Vertical { get; set; } = ""; public int TimeoutMs { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("handle",Handle.ToJson()); DtoHelpers.Add(o,"horizontal",Horizontal); DtoHelpers.Add(o,"vertical",Vertical); o.Add("timeoutMs",JsonNumberNode.From(TimeoutMs)); FromJson(o); return o; }
        public static ActScrollParams FromJson(JsonNode n) { var o = DtoHelpers.Object(n,"handle","horizontal","vertical","timeoutMs"); return new ActScrollParams { Handle = ObjectRef.FromJson(o.Get("handle")), Horizontal = ScrollAmount.Read(o.Get("horizontal")), Vertical = ScrollAmount.Read(o.Get("vertical")), TimeoutMs = RemainingHelpers.Timeout(o) }; }
    }
    public sealed class ActSetRangeParams
    {
        public ObjectRef Handle { get; set; } = new ObjectRef(); public double Value { get; set; } public int TimeoutMs { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("handle",Handle.ToJson()); o.Add("value",JsonNumberNode.From(Value)); o.Add("timeoutMs",JsonNumberNode.From(TimeoutMs)); FromJson(o); return o; }
        public static ActSetRangeParams FromJson(JsonNode n) { var o = DtoHelpers.Object(n,"handle","value","timeoutMs"); return new ActSetRangeParams { Handle = ObjectRef.FromJson(o.Get("handle")), Value = QueryHelpers.Number(o.Get("value")), TimeoutMs = RemainingHelpers.Timeout(o) }; }
    }
    public sealed class ActSetValueParams
    {
        public ObjectRef Handle { get; set; } = new ObjectRef(); public string Value { get; set; } = ""; public int TimeoutMs { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("handle",Handle.ToJson()); DtoHelpers.Add(o,"value",Value); o.Add("timeoutMs",JsonNumberNode.From(TimeoutMs)); FromJson(o); return o; }
        public static ActSetValueParams FromJson(JsonNode n) { var o = DtoHelpers.Object(n,"handle","value","timeoutMs"); return new ActSetValueParams { Handle = ObjectRef.FromJson(o.Get("handle")), Value = DtoHelpers.Required(o,"value",4096,true), TimeoutMs = RemainingHelpers.Timeout(o) }; }
    }
    public sealed class WaitCondition
    {
        public string Kind { get; set; } = ""; public Locator Locator { get; set; } = new Locator(); public IReadOnlyList<PathSegment>? Path { get; set; } public JsonNode? Value { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); DtoHelpers.Add(o,"kind",Kind); o.Add("locator",Locator.ToJson()); if (Path != null) o.Add("path",ResultHelpers.Path(Path)); if (Value != null) o.Add("value",Value); FromJson(o); return o; }
        public static WaitCondition FromJson(JsonNode n) { var o = DtoHelpers.Object(n,"kind","locator","path","value"); var x = new WaitCondition { Kind = DtoHelpers.Required(o,"kind"), Locator = Locator.FromJson(o.Get("locator")) }; DtoHelpers.OneOf(x.Kind,"exists","visible","enabled","propertyEquals"); if (x.Kind == "propertyEquals") { x.Path = ResultHelpers.Path(o.Get("path")); x.Value = o.Get("value"); QueryHelpers.Scalar(x.Value); } else DtoHelpers.Object(n,"kind","locator"); return x; }
    }
    public sealed class WaitUntilParams
    {
        public WaitCondition Condition { get; set; } = new WaitCondition(); public int TimeoutMs { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("condition",Condition.ToJson()); o.Add("timeoutMs",JsonNumberNode.From(TimeoutMs)); FromJson(o); return o; }
        public static WaitUntilParams FromJson(JsonNode n) { var o = DtoHelpers.Object(n,"condition","timeoutMs"); return new WaitUntilParams { Condition = WaitCondition.FromJson(o.Get("condition")), TimeoutMs = RemainingHelpers.Timeout(o) }; }
    }
    public sealed class WaitUntilResult
    {
        public bool Satisfied { get; set; } public ObjectRef? Handle { get; set; } public ElementState? State { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("satisfied",new JsonBoolNode(Satisfied)); if (Handle != null) o.Add("handle",Handle.ToJson()); if (State != null) o.Add("state",State.ToJson()); FromJson(o); return o; }
        public static WaitUntilResult FromJson(JsonNode n) { var o = DtoHelpers.Object(n,"satisfied","handle","state"); var x = new WaitUntilResult { Satisfied = DtoHelpers.Boolean(o.Get("satisfied")), Handle = o.TryGet("handle",out var h) ? ObjectRef.FromJson(h) : null, State = o.TryGet("state",out var s) ? ElementState.FromJson(s) : null }; if (x.Satisfied ? x.Handle == null || x.State == null : x.Handle != null || x.State != null) throw DtoHelpers.Invalid("Invalid wait result"); return x; }
    }
    public sealed class WriteAudit
    {
        public string Operation { get; set; } = ""; public string TypeFullName { get; set; } = ""; public string MemberKey { get; set; } = ""; public string Outcome { get; set; } = ""; public string TimestampUtc { get; set; } = ""; public string? Reason { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); DtoHelpers.Add(o,"operation",Operation); DtoHelpers.Add(o,"typeFullName",TypeFullName); DtoHelpers.Add(o,"memberKey",MemberKey); DtoHelpers.Add(o,"outcome",Outcome); DtoHelpers.Add(o,"timestampUtc",TimestampUtc); DtoHelpers.Add(o,"reason",Reason); FromJson(o); return o; }
        public static WriteAudit FromJson(JsonNode n) { var o = DtoHelpers.Object(n,"operation","typeFullName","memberKey","outcome","timestampUtc","reason"); var x = new WriteAudit { Operation = DtoHelpers.Required(o,"operation"), TypeFullName = DtoHelpers.Required(o,"typeFullName",1024), MemberKey = DtoHelpers.Required(o,"memberKey",1024), Outcome = DtoHelpers.Required(o,"outcome"), TimestampUtc = DtoHelpers.Required(o,"timestampUtc",128), Reason = DtoHelpers.Optional(o,"reason",1024,true) }; DtoHelpers.OneOf(x.Operation,"setProperty","call"); DtoHelpers.OneOf(x.Outcome,"performed","denied","failed"); if (!Regex.IsMatch(x.TimestampUtc,@"^\d{4}-\d\d-\d\d[Tt]\d\d:\d\d:\d\d(?:\.\d+)?(?:[Zz]|[+-]\d\d:\d\d)$") || !DateTimeOffset.TryParse(x.TimestampUtc,CultureInfo.InvariantCulture,DateTimeStyles.None,out _)) throw DtoHelpers.Invalid("Invalid timestamp"); if (x.Reason == "timeout" && x.Outcome != "failed") throw DtoHelpers.Invalid("Invalid timeout audit"); return x; }
    }
    public sealed class WriteSetPropertyParams
    {
        public ObjectRef Handle { get; set; } = new ObjectRef(); public string MemberKey { get; set; } = ""; public JsonNode Value { get; set; } = JsonNullNode.Instance; public int TimeoutMs { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("handle",Handle.ToJson()); DtoHelpers.Add(o,"memberKey",MemberKey); o.Add("value",Value); o.Add("timeoutMs",JsonNumberNode.From(TimeoutMs)); FromJson(o); return o; }
        public static WriteSetPropertyParams FromJson(JsonNode n) { var o = DtoHelpers.Object(n,"handle","memberKey","value","timeoutMs"); var x = new WriteSetPropertyParams { Handle = ObjectRef.FromJson(o.Get("handle")), MemberKey = RemainingHelpers.Key(o,false), Value = o.Get("value"), TimeoutMs = RemainingHelpers.Timeout(o) }; RemainingHelpers.WriteScalar(x.Value); return x; }
    }
    public sealed class WriteCallParams
    {
        public ObjectRef Handle { get; set; } = new ObjectRef(); public string MemberKey { get; set; } = ""; public IReadOnlyList<JsonNode> Arguments { get; set; } = new List<JsonNode>(); public int TimeoutMs { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("handle",Handle.ToJson()); DtoHelpers.Add(o,"memberKey",MemberKey); var a = new JsonArrayNode(); foreach (var v in Arguments) a.Add(v); o.Add("arguments",a); o.Add("timeoutMs",JsonNumberNode.From(TimeoutMs)); FromJson(o); return o; }
        public static WriteCallParams FromJson(JsonNode n) { var o = DtoHelpers.Object(n,"handle","memberKey","arguments","timeoutMs"); var a = new List<JsonNode>(); foreach (var v in DtoHelpers.Array(o.Get("arguments"),16).Items) { RemainingHelpers.WriteScalar(v); a.Add(v); } return new WriteCallParams { Handle = ObjectRef.FromJson(o.Get("handle")), MemberKey = RemainingHelpers.Key(o,true), Arguments = a, TimeoutMs = RemainingHelpers.Timeout(o) }; }
    }
    public sealed class WriteCallResult
    {
        public WriteAudit Audit { get; set; } = new WriteAudit(); public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("audit",Audit.ToJson()); FromJson(o); return o; } public static WriteCallResult FromJson(JsonNode n) { var o = DtoHelpers.Object(n,"audit"); return new WriteCallResult { Audit = WriteAudit.FromJson(o.Get("audit")) }; }
    }
    public sealed class WriteSetPropertyResult
    {
        public WriteAudit Audit { get; set; } = new WriteAudit(); public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("audit",Audit.ToJson()); FromJson(o); return o; } public static WriteSetPropertyResult FromJson(JsonNode n) { var o = DtoHelpers.Object(n,"audit"); return new WriteSetPropertyResult { Audit = WriteAudit.FromJson(o.Get("audit")) }; }
    }
}
