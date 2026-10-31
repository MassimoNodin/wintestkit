using System.Collections.Generic;
using System.Globalization;
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
        public static Predicate FromJson(JsonNode n) { var o = DtoHelpers.Object(n,"kind","path","value","pattern","flags","fullName"); var x = new Predicate { Kind = DtoHelpers.Required(o,"kind") }; DtoHelpers.OneOf(x.Kind,"equals","regex","assignableTo"); if (x.Kind == "assignableTo") { DtoHelpers.Object(n,"kind","fullName"); x.FullName = DtoHelpers.Required(o,"fullName",1024); } else { x.Path = ResultHelpers.Path(o.Get("path")); if (x.Kind == "equals") { DtoHelpers.Object(n,"kind","path","value"); x.Value = o.Get("value"); QueryHelpers.Scalar(x.Value); } else { DtoHelpers.Object(n,"kind","path","pattern","flags"); x.Pattern = DtoHelpers.Required(o,"pattern",1024,true); var flags = DtoHelpers.Strings(o.Get("flags"),3); var seen = new HashSet<string>(); foreach (var f in flags) { DtoHelpers.OneOf(f,"ignoreCase","multiline","singleline"); if (!seen.Add(f)) throw DtoHelpers.Invalid("Duplicate flag"); } x.Flags = flags; } } return x; }
    }
    public sealed class Locator
    {
        public Scope Scope { get; set; } = new Scope(); public string Tree { get; set; } = ""; public IReadOnlyList<Predicate> Predicates { get; set; } = new List<Predicate>(); public int Depth { get; set; } public string DepthMode { get; set; } = ""; public int? Index { get; set; } public int Limit { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("scope",Scope.ToJson()); DtoHelpers.Add(o,"tree",Tree); var a = new JsonArrayNode(); foreach (var p in Predicates) a.Add(p.ToJson()); o.Add("predicates",a); o.Add("depth",JsonNumberNode.From(Depth)); DtoHelpers.Add(o,"depthMode",DepthMode); DtoHelpers.Add(o,"index",Index); o.Add("limit",JsonNumberNode.From(Limit)); FromJson(o); return o; }
        public static Locator FromJson(JsonNode n) { var o = DtoHelpers.Object(n,"scope","tree","predicates","depth","depthMode","index","limit"); var ps = new List<Predicate>(); foreach (var p in DtoHelpers.Array(o.Get("predicates"),32).Items) ps.Add(Predicate.FromJson(p)); var x = new Locator { Scope = Scope.FromJson(o.Get("scope")), Tree = DtoHelpers.Required(o,"tree"), Predicates = ps, Depth = (int)DtoHelpers.Integer(o.Get("depth"),0,256), DepthMode = DtoHelpers.Required(o,"depthMode"), Limit = (int)DtoHelpers.Integer(o.Get("limit"),1,200) }; DtoHelpers.OneOf(x.Tree,"visual","logical","combined"); DtoHelpers.OneOf(x.DepthMode,"tree","peers"); if (o.TryGet("index",out var i)) x.Index = (int)DtoHelpers.Integer(i,0,9999); return x; }
    }
    public sealed class QueryFindParams
    {
        public Locator Locator { get; set; } = new Locator(); public int TimeoutMs { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("locator",Locator.ToJson()); o.Add("timeoutMs",JsonNumberNode.From(TimeoutMs)); FromJson(o); return o; }
        public static QueryFindParams FromJson(JsonNode n) { var o = DtoHelpers.Object(n,"locator","timeoutMs"); return new QueryFindParams { Locator = Locator.FromJson(o.Get("locator")), TimeoutMs = (int)DtoHelpers.Integer(o.Get("timeoutMs"),1,2000) }; }
    }
    public sealed class QueryFindAllParams
    {
        public Locator Locator { get; set; } = new Locator(); public int TimeoutMs { get; set; }
        public JsonObjectNode ToJson() => new QueryFindParams { Locator = Locator, TimeoutMs = TimeoutMs }.ToJson();
        public static QueryFindAllParams FromJson(JsonNode n) { var x = QueryFindParams.FromJson(n); return new QueryFindAllParams { Locator = x.Locator, TimeoutMs = x.TimeoutMs }; }
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
    public sealed class QueryFindAllResult
    {
        public IReadOnlyList<ObjectRef> Matches { get; set; } = new List<ObjectRef>(); public int? Count { get; set; } public bool Complete { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); var a = new JsonArrayNode(); foreach (var m in Matches) a.Add(m.ToJson()); o.Add("matches",a); DtoHelpers.Add(o,"count",Count); o.Add("complete",new JsonBoolNode(Complete)); FromJson(o); return o; }
        public static QueryFindAllResult FromJson(JsonNode n) { var o = DtoHelpers.Object(n,"matches","count","complete"); var ms = new List<ObjectRef>(); foreach (var m in DtoHelpers.Array(o.Get("matches"),200).Items) ms.Add(ObjectRef.FromJson(m)); var x = new QueryFindAllResult { Matches = ms, Complete = DtoHelpers.Boolean(o.Get("complete")) }; if (o.TryGet("count",out var c)) x.Count = (int)DtoHelpers.Integer(c,0,10000); if (x.Complete && x.Count.HasValue && x.Count.Value != ms.Count || x.Count.HasValue && x.Count.Value < ms.Count) throw DtoHelpers.Invalid("Invalid count"); return x; }
    }
}
