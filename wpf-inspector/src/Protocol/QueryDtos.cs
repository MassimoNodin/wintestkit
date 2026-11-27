using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
namespace WinTestKit.Inspector.Protocol
{
    internal static class QueryHelpers
    {
        internal static double Number(JsonNode n) { if (!(n is JsonNumberNode x) || !double.TryParse(x.RawText, NumberStyles.Float, CultureInfo.InvariantCulture, out var v) || double.IsNaN(v) || double.IsInfinity(v)) throw DtoHelpers.Invalid("Expected finite number"); return v; }
        internal static void Scalar(JsonNode n) { if (n is JsonNumberNode) Number(n); else if (n is JsonStringNode s) DtoHelpers.String(s, int.MaxValue, true); else if (!(n is JsonBoolNode)) throw DtoHelpers.Invalid("Expected scalar"); }
    }
    public sealed class Scope
    {
        public string Kind { get; set; } = ""; public ObjectRef? Handle { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); DtoHelpers.Add(o,"kind",Kind); if (Handle != null) o.Add("handle",Handle.ToJson()); FromJson(o); return o; }
        public static Scope FromJson(JsonNode n) { var o = DtoHelpers.Object(n,"kind","handle"); var x = new Scope { Kind = DtoHelpers.Required(o,"kind") }; DtoHelpers.OneOf(x.Kind,"allRoots","window","object"); if (x.Kind == "allRoots") { if (o.TryGet("handle",out _)) throw DtoHelpers.Invalid("Unexpected handle"); } else x.Handle = ObjectRef.FromJson(o.Get("handle")); return x; }
    }
    public sealed class Predicate
    {
        public string Kind { get; set; } = ""; public IReadOnlyList<PathSegment>? Path { get; set; } public JsonNode? Value { get; set; } public string? Pattern { get; set; } public IReadOnlyList<string>? Flags { get; set; } public string? FullName { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); DtoHelpers.Add(o,"kind",Kind); if (Path != null) o.Add("path",ResultHelpers.Path(Path)); if (Value != null) o.Add("value",Value); DtoHelpers.Add(o,"pattern",Pattern); if (Flags != null) o.Add("flags",DtoHelpers.Strings(Flags)); DtoHelpers.Add(o,"fullName",FullName); FromJson(o); return o; }
        public static Predicate FromJson(JsonNode n) { var o = DtoHelpers.Object(n,"kind","path","value","pattern","flags","fullName"); var x = new Predicate { Kind = DtoHelpers.Required(o,"kind") }; DtoHelpers.OneOf(x.Kind,"equals","equalsText","regex","assignableTo"); if (x.Kind == "assignableTo") { DtoHelpers.Object(n,"kind","fullName"); x.FullName = DtoHelpers.Required(o,"fullName",1024); } else { x.Path = ResultHelpers.Path(o.Get("path")); if (x.Kind == "equals" || x.Kind == "equalsText") { DtoHelpers.Object(n,"kind","path","value"); x.Value = o.Get("value"); QueryHelpers.Scalar(x.Value); if (x.Kind == "equalsText" && !(x.Value is JsonStringNode)) throw DtoHelpers.Invalid("equalsText requires a string value"); } else { DtoHelpers.Object(n,"kind","path","pattern","flags"); x.Pattern = DtoHelpers.Required(o,"pattern",1024,true); var flags = DtoHelpers.Strings(o.Get("flags"),3); var seen = new HashSet<string>(); foreach (var f in flags) { DtoHelpers.OneOf(f,"ignoreCase","multiline","singleline"); if (!seen.Add(f)) throw DtoHelpers.Invalid("Duplicate flag"); } x.Flags = flags; } } return x; }
    }
    public sealed class Locator
    {
        public Scope Scope { get; set; } = new Scope(); public string Tree { get; set; } = ""; public IReadOnlyList<Predicate> Predicates { get; set; } = new List<Predicate>(); public int Depth { get; set; } public string DepthMode { get; set; } = ""; public int? Index { get; set; } public int Limit { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("scope",Scope.ToJson()); DtoHelpers.Add(o,"tree",Tree); var a = new JsonArrayNode(); foreach (var p in Predicates) a.Add(p.ToJson()); o.Add("predicates",a); o.Add("depth",JsonNumberNode.From(Depth)); DtoHelpers.Add(o,"depthMode",DepthMode); DtoHelpers.Add(o,"index",Index); o.Add("limit",JsonNumberNode.From(Limit)); FromJson(o); return o; }
        public static Locator FromJson(JsonNode n) { var o = DtoHelpers.Object(n,"scope","tree","predicates","depth","depthMode","index","limit"); var ps = new List<Predicate>(); foreach (var p in DtoHelpers.Array(o.Get("predicates"),32).Items) ps.Add(Predicate.FromJson(p)); var x = new Locator { Scope = Scope.FromJson(o.Get("scope")), Tree = DtoHelpers.Required(o,"tree"), Predicates = ps, Depth = (int)DtoHelpers.Integer(o.Get("depth"),0,256), DepthMode = DtoHelpers.Required(o,"depthMode"), Limit = (int)DtoHelpers.Integer(o.Get("limit"),1,200) }; DtoHelpers.OneOf(x.Tree,"visual","logical","combined","objects"); DtoHelpers.OneOf(x.DepthMode,"tree","peers"); if (o.TryGet("index",out var i)) x.Index = (int)DtoHelpers.Integer(i,0,9999); return x; }
    }
    public sealed class QueryFindParams
    {
        public Locator Locator { get; set; } = new Locator(); public int TimeoutMs { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("locator",Locator.ToJson()); o.Add("timeoutMs",JsonNumberNode.From(TimeoutMs)); FromJson(o); return o; }
        public static QueryFindParams FromJson(JsonNode n) { var o = DtoHelpers.Object(n,"locator","timeoutMs"); return new QueryFindParams { Locator = Locator.FromJson(o.Get("locator")), TimeoutMs = (int)DtoHelpers.Integer(o.Get("timeoutMs"),1,2000) }; }
    }
    public sealed class QueryFindAllParams
    {
        public Locator Locator { get; set; } = new Locator(); public int TimeoutMs { get; set; } public string? Continuation { get; set; }
        public JsonObjectNode ToJson() { var o = new QueryFindParams { Locator = Locator, TimeoutMs = TimeoutMs }.ToJson(); DtoHelpers.Add(o,"continuation",Continuation); FromJson(o); return o; }
        public static QueryFindAllParams FromJson(JsonNode n) { var o = DtoHelpers.Object(n,"locator","timeoutMs","continuation"); var x = QueryFindParams.FromJson(Without(o,"continuation")); return new QueryFindAllParams { Locator = x.Locator, TimeoutMs = x.TimeoutMs, Continuation = DtoHelpers.Optional(o,"continuation",ProtocolLimits.MaxContinuationLength) }; }
        private static JsonObjectNode Without(JsonObjectNode source, string key) { var copy = new JsonObjectNode(); foreach (var name in new[] { "locator", "timeoutMs" }) if (name != key && source.TryGet(name, out var value)) copy.Add(name, value); return copy; }
    }
    public sealed class MatchWarning
    {
        public string Code { get; set; } = "multipleMatches"; public int Count { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); DtoHelpers.Add(o,"code",Code); o.Add("count",JsonNumberNode.From(Count)); FromJson(o); return o; }
        public static MatchWarning FromJson(JsonNode n) { var o = DtoHelpers.Object(n,"code","count"); var x = new MatchWarning { Code = DtoHelpers.Required(o,"code"), Count = (int)DtoHelpers.Integer(o.Get("count"),2,10000) }; DtoHelpers.OneOf(x.Code,"multipleMatches"); return x; }
    }
    public sealed class QueryFindResult
    {
        public ObjectRef Match { get; set; } = new ObjectRef(); public MatchWarning? Warning { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("match",Match.ToJson()); if (Warning != null) o.Add("warning",Warning.ToJson()); FromJson(o); return o; }
        public static QueryFindResult FromJson(JsonNode n) { var o = DtoHelpers.Object(n,"match","warning"); return new QueryFindResult { Match = ObjectRef.FromJson(o.Get("match")), Warning = o.TryGet("warning",out var w) ? MatchWarning.FromJson(w) : null }; }
    }
    /// <summary>Candidates whose value a search could not read; each counted as a non-match, by reason.</summary>
    public sealed class QueryUnreadable
    {
        public static readonly string[] KnownReasons = { "unavailable", "notRead", "notReadable", "exception", "redacted", "truncated", "cycle", "timeout", "unsupported", "ambiguous", "other" };
        public int Count { get; set; } public IReadOnlyDictionary<string, int> Reasons { get; set; } = new Dictionary<string, int>();
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("count",JsonNumberNode.From(Count)); var r = new JsonObjectNode(); foreach (var item in Reasons.OrderBy(x => x.Key, StringComparer.Ordinal)) r.Add(item.Key,JsonNumberNode.From(item.Value)); o.Add("reasons",r); FromJson(o); return o; }
        public static QueryUnreadable FromJson(JsonNode n)
        {
            var o = DtoHelpers.Object(n,"count","reasons"); var x = new QueryUnreadable { Count = (int)DtoHelpers.Integer(o.Get("count"),1,int.MaxValue) };
            if (!(o.Get("reasons") is JsonObjectNode reasons) || reasons.Members.Count == 0) throw DtoHelpers.Invalid("Invalid unreadable reasons");
            var map = new Dictionary<string, int>(StringComparer.Ordinal); long total = 0;
            foreach (var item in reasons.Members) { DtoHelpers.OneOf(item.Key,KnownReasons); int value = (int)DtoHelpers.Integer(item.Value,1,int.MaxValue); map.Add(item.Key,value); total += value; }
            if (total != x.Count) throw DtoHelpers.Invalid("Unreadable reasons do not add up");
            x.Reasons = map; return x;
        }
    }
    public sealed class QueryFindAllResult
    {
        public IReadOnlyList<ObjectRef> Matches { get; set; } = new List<ObjectRef>(); public int? Count { get; set; } public bool Complete { get; set; } public string? Continuation { get; set; } public QueryUnreadable? Unreadable { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); var a = new JsonArrayNode(); foreach (var m in Matches) a.Add(m.ToJson()); o.Add("matches",a); DtoHelpers.Add(o,"count",Count); o.Add("complete",new JsonBoolNode(Complete)); DtoHelpers.Add(o,"continuation",Continuation); if (Unreadable != null) o.Add("unreadable",Unreadable.ToJson()); FromJson(o); return o; }
        public static QueryFindAllResult FromJson(JsonNode n) { var o = DtoHelpers.Object(n,"matches","count","complete","continuation","unreadable"); var ms = new List<ObjectRef>(); foreach (var m in DtoHelpers.Array(o.Get("matches"),200).Items) ms.Add(ObjectRef.FromJson(m)); var x = new QueryFindAllResult { Matches = ms, Complete = DtoHelpers.Boolean(o.Get("complete")), Continuation = DtoHelpers.Optional(o,"continuation",ProtocolLimits.MaxContinuationLength) }; if (x.Complete && x.Continuation != null) throw DtoHelpers.Invalid("A complete result has no continuation"); if (o.TryGet("count",out var c)) x.Count = (int)DtoHelpers.Integer(c,0,10000); if (x.Complete && x.Count.HasValue && x.Count.Value != ms.Count || x.Count.HasValue && x.Count.Value < ms.Count) throw DtoHelpers.Invalid("Invalid count"); if (o.TryGet("unreadable",out var u)) x.Unreadable = QueryUnreadable.FromJson(u); return x; }
    }
}
