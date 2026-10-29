using System.Collections.Generic;

namespace WinTestKit.Inspector.Protocol
{
    public sealed class PathValue
    {
        public IReadOnlyList<PathSegment> Path { get; set; } = new List<PathSegment>(); public ValueDto Value { get; set; } = new ValueDto();
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("path", ResultHelpers.Path(Path)); o.Add("value", Value.ToJson()); FromJson(o); return o; }
        public static PathValue FromJson(JsonNode node) { var o = DtoHelpers.Object(node, "path", "value"); return new PathValue { Path = ResultHelpers.Path(o.Get("path")), Value = ValueDto.FromJson(o.Get("value")) }; }
    }
    public sealed class ReadResult
    {
        public IReadOnlyList<PathValue> Values { get; set; } = new List<PathValue>(); public string ReadId { get; set; } = "";
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); var a = new JsonArrayNode(); foreach (var v in Values) a.Add(v.ToJson()); o.Add("values", a); DtoHelpers.Add(o, "readId", ReadId); FromJson(o); return o; }
        public static ReadResult FromJson(JsonNode node) { var o = DtoHelpers.Object(node, "values", "readId"); var values = new List<PathValue>(); foreach (var v in DtoHelpers.Array(o.Get("values"), ProtocolLimits.MaxBatchPaths).Items) values.Add(PathValue.FromJson(v)); return new ReadResult { Values = values, ReadId = DtoHelpers.Required(o, "readId") }; }
    }
    public sealed class CandidateResult
    {
        public IReadOnlyList<int> RuntimeId { get; set; } = new List<int>(); public MappingDto Mapping { get; set; } = new MappingDto(); public IReadOnlyList<PathValue> Values { get; set; } = new List<PathValue>();
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("runtimeId", ResultHelpers.RuntimeId(RuntimeId)); o.Add("mapping", Mapping.ToJson()); var a = new JsonArrayNode(); foreach (var v in Values) a.Add(v.ToJson()); o.Add("values", a); FromJson(o); return o; }
        public static CandidateResult FromJson(JsonNode node) { var o = DtoHelpers.Object(node, "runtimeId", "mapping", "values"); var values = new List<PathValue>(); foreach (var v in DtoHelpers.Array(o.Get("values"), ProtocolLimits.MaxBatchPaths).Items) values.Add(PathValue.FromJson(v)); var x = new CandidateResult { RuntimeId = ResultHelpers.RuntimeId(o.Get("runtimeId")), Mapping = MappingDto.FromJson(o.Get("mapping")), Values = values }; if (x.Mapping.Status != MappingStatus.Exact && values.Count != 0) throw DtoHelpers.Invalid("Non-exact candidate has values"); return x; }
    }
    public sealed class ReadBatchResult
    {
        public IReadOnlyList<CandidateResult> Candidates { get; set; } = new List<CandidateResult>();
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); var a = new JsonArrayNode(); foreach (var c in Candidates) a.Add(c.ToJson()); o.Add("candidates", a); FromJson(o); return o; }
        public static ReadBatchResult FromJson(JsonNode node) { var o = DtoHelpers.Object(node, "candidates"); var candidates = new List<CandidateResult>(); foreach (var c in DtoHelpers.Array(o.Get("candidates"), ProtocolLimits.MaxBatchCandidates).Items) candidates.Add(CandidateResult.FromJson(c)); if (candidates.Count == 0) throw DtoHelpers.Invalid("Empty candidate result"); return new ReadBatchResult { Candidates = candidates }; }
    }
}
