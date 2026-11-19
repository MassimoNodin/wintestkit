using System.Collections.Generic;

namespace WinTestKit.Inspector.Protocol
{
    public sealed class SpyInvokeParams
    {
        public ObjectRef Handle { get; set; } = new ObjectRef();
        public string MemberKey { get; set; } = "";
        public IReadOnlyList<JsonNode> Arguments { get; set; } = new List<JsonNode>();
        public int TimeoutMs { get; set; }
        public static SpyInvokeParams FromJson(JsonNode node)
        {
            var obj = DtoHelpers.Object(node, "capability", "handle", "memberKey", "arguments", "timeoutMs");
            DtoHelpers.Required(obj, "capability", 44);
            var arguments = new List<JsonNode>();
            foreach (var argument in DtoHelpers.Array(obj.Get("arguments"), 16).Items) arguments.Add(argument);
            return new SpyInvokeParams { Handle = ObjectRef.FromJson(obj.Get("handle")), MemberKey = DtoHelpers.Required(obj, "memberKey", 8192), Arguments = arguments, TimeoutMs = RemainingHelpers.Timeout(obj) };
        }
    }

    public sealed class MethodParameterDto
    {
        public string Name { get; set; } = "";
        public string Type { get; set; } = "";
        public bool IsOut { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); DtoHelpers.Add(o, "name", Name); DtoHelpers.Add(o, "type", Type); o.Add("isOut", new JsonBoolNode(IsOut)); FromJson(o); return o; }
        public static MethodParameterDto FromJson(JsonNode node) { var o = DtoHelpers.Object(node, "name", "type", "isOut"); return new MethodParameterDto { Name = DtoHelpers.Required(o, "name", 1024, true), Type = DtoHelpers.Required(o, "type", 1024), IsOut = DtoHelpers.Boolean(o.Get("isOut")) }; }
    }

    public sealed class MethodMetadataDto
    {
        public string Key { get; set; } = "";
        public string Name { get; set; } = "";
        public string DeclaringType { get; set; } = "";
        public string ReturnType { get; set; } = "";
        public string Visibility { get; set; } = "";
        public bool IsStatic { get; set; }
        public IReadOnlyList<MethodParameterDto> Parameters { get; set; } = new List<MethodParameterDto>();
        public string? UnsupportedReason { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); DtoHelpers.Add(o, "key", Key); DtoHelpers.Add(o, "name", Name); DtoHelpers.Add(o, "declaringType", DeclaringType); DtoHelpers.Add(o, "returnType", ReturnType); DtoHelpers.Add(o, "visibility", Visibility); o.Add("isStatic", new JsonBoolNode(IsStatic)); var parameters = new JsonArrayNode(); foreach (var p in Parameters) parameters.Add(p.ToJson()); o.Add("parameters", parameters); DtoHelpers.Add(o, "unsupportedReason", UnsupportedReason); FromJson(o); return o; }
        public static MethodMetadataDto FromJson(JsonNode node) { var o = DtoHelpers.Object(node, "key", "name", "declaringType", "returnType", "visibility", "isStatic", "parameters", "unsupportedReason"); var parameters = new List<MethodParameterDto>(); foreach (var p in DtoHelpers.Array(o.Get("parameters"), 128).Items) parameters.Add(MethodParameterDto.FromJson(p)); var x = new MethodMetadataDto { Key = DtoHelpers.Required(o, "key", 8192), Name = DtoHelpers.Required(o, "name", 1024), DeclaringType = DtoHelpers.Required(o, "declaringType", 1024), ReturnType = DtoHelpers.Required(o, "returnType", 1024), Visibility = DtoHelpers.Required(o, "visibility"), IsStatic = DtoHelpers.Boolean(o.Get("isStatic")), Parameters = parameters, UnsupportedReason = DtoHelpers.Optional(o, "unsupportedReason", 1024) }; DtoHelpers.OneOf(x.Visibility, Protocol.Visibility.Public, Protocol.Visibility.Private, Protocol.Visibility.Protected, Protocol.Visibility.Internal, Protocol.Visibility.ProtectedInternal, Protocol.Visibility.PrivateProtected); return x; }
    }
}
