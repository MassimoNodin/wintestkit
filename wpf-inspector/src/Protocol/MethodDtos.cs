using System.Collections.Generic;

namespace WinTestKit.Inspector.Protocol
{
    public sealed class ResolveParams
    {
        public IReadOnlyList<int> RuntimeId { get; set; } = new List<int>();
        public long? NativeWindowHandle { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("runtimeId", ResultHelpers.RuntimeId(RuntimeId)); DtoHelpers.Add(o, "nativeWindowHandle", NativeWindowHandle); FromJson(o); return o; }
        public static ResolveParams FromJson(JsonNode node) { var o = DtoHelpers.Object(node, "runtimeId", "nativeWindowHandle"); return new ResolveParams { RuntimeId = ResultHelpers.RuntimeId(o.Get("runtimeId")), NativeWindowHandle = o.TryGet("nativeWindowHandle", out var native) ? DtoHelpers.Integer(native, long.MinValue) : (long?)null }; }
    }
    public sealed class CandidateRequestDto
    {
        public IReadOnlyList<int> RuntimeId { get; set; } = new List<int>();
        public long? NativeWindowHandle { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("runtimeId", ResultHelpers.RuntimeId(RuntimeId)); DtoHelpers.Add(o, "nativeWindowHandle", NativeWindowHandle); FromJson(o); return o; }
        public static CandidateRequestDto FromJson(JsonNode node) { var o = DtoHelpers.Object(node, "runtimeId", "nativeWindowHandle"); return new CandidateRequestDto { RuntimeId = ResultHelpers.RuntimeId(o.Get("runtimeId")), NativeWindowHandle = o.TryGet("nativeWindowHandle", out var native) ? DtoHelpers.Integer(native, long.MinValue) : (long?)null }; }
    }
    public sealed class ReadBatchParams
    {
        public IReadOnlyList<CandidateRequestDto> Candidates { get; set; } = new List<CandidateRequestDto>();
        public IReadOnlyList<IReadOnlyList<PathSegment>> Paths { get; set; } = new List<IReadOnlyList<PathSegment>>();
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("candidates", MethodDtoHelpers.Candidates(Candidates)); o.Add("paths", MethodDtoHelpers.Paths(Paths)); FromJson(o); return o; }
        public static ReadBatchParams FromJson(JsonNode node) { var o = DtoHelpers.Object(node, "candidates", "paths"); return new ReadBatchParams { Candidates = MethodDtoHelpers.Candidates(o.Get("candidates")), Paths = MethodDtoHelpers.Paths(o.Get("paths")) }; }
    }
    public sealed class RootsParams
    {
        public string SessionId { get; set; } = "";
        public int? PageSize { get; set; }
        public string? PageToken { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); DtoHelpers.Add(o, "sessionId", SessionId); DtoHelpers.Add(o, "pageSize", PageSize); DtoHelpers.Add(o, "pageToken", PageToken); FromJson(o); return o; }
        public static RootsParams FromJson(JsonNode node) { var o = DtoHelpers.Object(node, "sessionId", "pageSize", "pageToken"); return new RootsParams { SessionId = DtoHelpers.Required(o, "sessionId"), PageSize = o.TryGet("pageSize", out var page) ? (int)DtoHelpers.Integer(page, 1, ProtocolLimits.MaxPageSize) : (int?)null, PageToken = DtoHelpers.Optional(o, "pageToken") }; }
    }
    public sealed class ParentParams
    {
        public string SessionId { get; set; } = ""; public string ObjectId { get; set; } = ""; public long Generation { get; set; }
        /// <summary>Null asks for the visual (else logical) parent; "objects" for the parent in the object tree of the migration model.</summary>
        public string? Tree { get; set; }
        public static ParentParams FromJson(JsonNode n)
        {
            var o = DtoHelpers.Object(n, "sessionId", "objectId", "generation", "tree");
            string? tree = null;
            if (o.TryGet("tree", out var node)) { tree = DtoHelpers.String(node); DtoHelpers.OneOf(tree, "objects"); }
            return new ParentParams { SessionId = DtoHelpers.Required(o, "sessionId"), ObjectId = DtoHelpers.Required(o, "objectId"), Generation = DtoHelpers.Integer(o.Get("generation"), 1), Tree = tree };
        }
    }
    public sealed class ParentResult
    {
        public ObjectRef? Handle { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("handle", (JsonNode?)Handle?.ToJson() ?? JsonNullNode.Instance); return o; }
        public static ParentResult FromJson(JsonNode n) { var o = DtoHelpers.Object(n, "handle"); var h = o.Get("handle"); return new ParentResult { Handle = h is JsonNullNode ? null : ObjectRef.FromJson(h) }; }
    }
    public sealed class ChildrenParams
    {
        public string SessionId { get; set; } = "";
        public string ObjectId { get; set; } = "";
        public long Generation { get; set; }
        public string Tree { get; set; } = "";
        public int? PageSize { get; set; }
        public string? PageToken { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); DtoHelpers.Add(o, "sessionId", SessionId); DtoHelpers.Add(o, "objectId", ObjectId); o.Add("generation", JsonNumberNode.From(Generation)); DtoHelpers.Add(o, "tree", Tree); DtoHelpers.Add(o, "pageSize", PageSize); DtoHelpers.Add(o, "pageToken", PageToken); FromJson(o); return o; }
        public static ChildrenParams FromJson(JsonNode node) { var o = DtoHelpers.Object(node, "sessionId", "objectId", "generation", "tree", "pageSize", "pageToken"); return new ChildrenParams { SessionId = DtoHelpers.Required(o, "sessionId"), ObjectId = DtoHelpers.Required(o, "objectId"), Generation = DtoHelpers.Integer(o.Get("generation"), 1), Tree = MethodDtoHelpers.Tree(o.Get("tree")), PageSize = o.TryGet("pageSize", out var page) ? (int)DtoHelpers.Integer(page, 1, ProtocolLimits.MaxPageSize) : (int?)null, PageToken = DtoHelpers.Optional(o, "pageToken") }; }
    }
    public sealed class MembersParams
    {
        public string SessionId { get; set; } = "";
        public string ObjectId { get; set; } = "";
        public long Generation { get; set; }
        public int? PageSize { get; set; }
        public string? PageToken { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); DtoHelpers.Add(o, "sessionId", SessionId); DtoHelpers.Add(o, "objectId", ObjectId); o.Add("generation", JsonNumberNode.From(Generation)); DtoHelpers.Add(o, "pageSize", PageSize); DtoHelpers.Add(o, "pageToken", PageToken); FromJson(o); return o; }
        public static MembersParams FromJson(JsonNode node) { var o = DtoHelpers.Object(node, "sessionId", "objectId", "generation", "pageSize", "pageToken"); return new MembersParams { SessionId = DtoHelpers.Required(o, "sessionId"), ObjectId = DtoHelpers.Required(o, "objectId"), Generation = DtoHelpers.Integer(o.Get("generation"), 1), PageSize = o.TryGet("pageSize", out var page) ? (int)DtoHelpers.Integer(page, 1, ProtocolLimits.MaxPageSize) : (int?)null, PageToken = DtoHelpers.Optional(o, "pageToken") }; }
    }
    public sealed class ReadParams
    {
        public string SessionId { get; set; } = "";
        public string ObjectId { get; set; } = "";
        public long Generation { get; set; }
        public IReadOnlyList<IReadOnlyList<PathSegment>> Paths { get; set; } = new List<IReadOnlyList<PathSegment>>();
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); DtoHelpers.Add(o, "sessionId", SessionId); DtoHelpers.Add(o, "objectId", ObjectId); o.Add("generation", JsonNumberNode.From(Generation)); o.Add("paths", MethodDtoHelpers.Paths(Paths)); FromJson(o); return o; }
        public static ReadParams FromJson(JsonNode node) { var o = DtoHelpers.Object(node, "sessionId", "objectId", "generation", "paths"); return new ReadParams { SessionId = DtoHelpers.Required(o, "sessionId"), ObjectId = DtoHelpers.Required(o, "objectId"), Generation = DtoHelpers.Integer(o.Get("generation"), 1), Paths = MethodDtoHelpers.Paths(o.Get("paths")) }; }
    }
    public sealed class BindingsParams
    {
        public string SessionId { get; set; } = "";
        public string ObjectId { get; set; } = "";
        public long Generation { get; set; }
        public IReadOnlyList<string> MemberKeys { get; set; } = new List<string>();
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); DtoHelpers.Add(o, "sessionId", SessionId); DtoHelpers.Add(o, "objectId", ObjectId); o.Add("generation", JsonNumberNode.From(Generation)); o.Add("memberKeys", DtoHelpers.Strings(MemberKeys)); FromJson(o); return o; }
        public static BindingsParams FromJson(JsonNode node) { var o = DtoHelpers.Object(node, "sessionId", "objectId", "generation", "memberKeys"); return new BindingsParams { SessionId = DtoHelpers.Required(o, "sessionId"), ObjectId = DtoHelpers.Required(o, "objectId"), Generation = DtoHelpers.Integer(o.Get("generation"), 1), MemberKeys = DtoHelpers.Strings(o.Get("memberKeys"), ProtocolLimits.MaxBindingKeys) }; }
    }
    public sealed class BindingsResult
    {
        public IReadOnlyList<BindingInfoDto> Bindings { get; set; } = new List<BindingInfoDto>();
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("bindings", MethodDtoHelpers.Bindings(Bindings)); FromJson(o); return o; }
        public static BindingsResult FromJson(JsonNode node) { var o = DtoHelpers.Object(node, "bindings"); return new BindingsResult { Bindings = MethodDtoHelpers.Bindings(o.Get("bindings")) }; }
    }
    /// <summary>One object to release: the number of hand-outs of the object the client no longer holds.</summary>
    public sealed class ReleaseItem
    {
        public string ObjectId { get; set; } = "";
        public int Count { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); DtoHelpers.Add(o, "objectId", ObjectId); o.Add("count", JsonNumberNode.From(Count)); FromJson(o); return o; }
        public static ReleaseItem FromJson(JsonNode node) { var o = DtoHelpers.Object(node, "objectId", "count"); return new ReleaseItem { ObjectId = DtoHelpers.Required(o, "objectId"), Count = (int)DtoHelpers.Integer(o.Get("count"), 1, ProtocolLimits.MaxReleaseCount) }; }
    }
    public sealed class ReleaseParams
    {
        public string SessionId { get; set; } = "";
        public IReadOnlyList<ReleaseItem> Objects { get; set; } = new List<ReleaseItem>();
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); DtoHelpers.Add(o, "sessionId", SessionId); var items = new JsonArrayNode(); foreach (var item in Objects) items.Add(item.ToJson()); o.Add("objects", items); FromJson(o); return o; }
        public static ReleaseParams FromJson(JsonNode node) { var o = DtoHelpers.Object(node, "sessionId", "objects"); var items = new List<ReleaseItem>(); foreach (var item in DtoHelpers.Array(o.Get("objects"), ProtocolLimits.MaxReleaseIds).Items) items.Add(ReleaseItem.FromJson(item)); return new ReleaseParams { SessionId = DtoHelpers.Required(o, "sessionId"), Objects = items }; }
    }
    public sealed class ReleaseResult
    {
        /// <summary>Objects whose last hand-out was released, which ended their lease.</summary>
        public int ReleasedCount { get; set; }
        /// <summary>Objects for which more hand-outs were released than were outstanding (or that were unknown); the excess was ignored.</summary>
        public int OverReleasedCount { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("releasedCount", JsonNumberNode.From(ReleasedCount)); o.Add("overReleasedCount", JsonNumberNode.From(OverReleasedCount)); FromJson(o); return o; }
        public static ReleaseResult FromJson(JsonNode node) { var o = DtoHelpers.Object(node, "releasedCount", "overReleasedCount"); return new ReleaseResult { ReleasedCount = (int)DtoHelpers.Integer(o.Get("releasedCount"), 0, ProtocolLimits.MaxReleaseIds), OverReleasedCount = (int)DtoHelpers.Integer(o.Get("overReleasedCount"), 0, ProtocolLimits.MaxReleaseIds) }; }
    }
    public sealed class CancelParams
    {
        public long RequestId { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("requestId", JsonNumberNode.From(RequestId)); FromJson(o); return o; }
        public static CancelParams FromJson(JsonNode node) { var o = DtoHelpers.Object(node, "requestId"); return new CancelParams { RequestId = DtoHelpers.Integer(o.Get("requestId"), 1) }; }
    }
    public sealed class CancelResult
    {
        public bool Accepted { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("accepted", new JsonBoolNode(Accepted)); FromJson(o); return o; }
        public static CancelResult FromJson(JsonNode node) { var o = DtoHelpers.Object(node, "accepted"); return new CancelResult { Accepted = DtoHelpers.Boolean(o.Get("accepted")) }; }
    }
    public sealed class CloseParams
    {
        public JsonObjectNode ToJson() { var o = new JsonObjectNode();  FromJson(o); return o; }
        public static CloseParams FromJson(JsonNode node) { var o = DtoHelpers.Object(node); return new CloseParams {  }; }
    }
    public sealed class CloseResult
    {
        public bool Closed { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("closed", new JsonBoolNode(Closed)); FromJson(o); return o; }
        public static CloseResult FromJson(JsonNode node) { var o = DtoHelpers.Object(node, "closed"); return new CloseResult { Closed = MethodDtoHelpers.True(o.Get("closed")) }; }
    }
    internal static class MethodDtoHelpers
    {
        internal static string Tree(JsonNode node) { var value = DtoHelpers.String(node); DtoHelpers.OneOf(value, "visual", "logical", "objects"); return value; }
        internal static bool True(JsonNode node) { if (!DtoHelpers.Boolean(node)) throw DtoHelpers.Invalid("Expected true"); return true; }
        internal static IReadOnlyList<CandidateRequestDto> Candidates(JsonNode node) { var values = new List<CandidateRequestDto>(); foreach (var item in DtoHelpers.Array(node, ProtocolLimits.MaxBatchCandidates).Items) values.Add(CandidateRequestDto.FromJson(item)); if (values.Count == 0) throw DtoHelpers.Invalid("Empty candidates"); return values; }
        internal static JsonArrayNode Candidates(IEnumerable<CandidateRequestDto> values) { var result = new JsonArrayNode(); foreach (var value in values) result.Add(value.ToJson()); return result; }
        internal static IReadOnlyList<IReadOnlyList<PathSegment>> Paths(JsonNode node) { var values = new List<IReadOnlyList<PathSegment>>(); foreach (var item in DtoHelpers.Array(node, ProtocolLimits.MaxBatchPaths).Items) values.Add(ResultHelpers.Path(item)); if (values.Count == 0) throw DtoHelpers.Invalid("Empty paths"); return values; }
        internal static JsonArrayNode Paths(IEnumerable<IReadOnlyList<PathSegment>> values) { var result = new JsonArrayNode(); foreach (var value in values) result.Add(ResultHelpers.Path(value)); return result; }
        internal static IReadOnlyList<BindingInfoDto> Bindings(JsonNode node) { var values = new List<BindingInfoDto>(); foreach (var item in DtoHelpers.Array(node, ProtocolLimits.MaxBindingEntries).Items) values.Add(BindingInfoDto.FromJson(item)); return values; }
        internal static JsonArrayNode Bindings(IEnumerable<BindingInfoDto> values) { var result = new JsonArrayNode(); foreach (var value in values) result.Add(value.ToJson()); return result; }
    }
}
