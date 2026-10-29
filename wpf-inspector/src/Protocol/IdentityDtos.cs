using System.Collections.Generic;

namespace WinTestKit.Inspector.Protocol
{
    public sealed class TypeInfoDto
    {
        public string Name { get; set; } = ""; public string FullName { get; set; } = ""; public string AssemblyName { get; set; } = ""; public string AssemblyQualifiedName { get; set; } = ""; public IReadOnlyList<string> BaseTypes { get; set; } = new List<string>();
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); DtoHelpers.Add(o, "name", Name); DtoHelpers.Add(o, "fullName", FullName); DtoHelpers.Add(o, "assemblyName", AssemblyName); DtoHelpers.Add(o, "assemblyQualifiedName", AssemblyQualifiedName); o.Add("baseTypes", DtoHelpers.Strings(BaseTypes)); FromJson(o); return o; }
        public static TypeInfoDto FromJson(JsonNode node) { var o = DtoHelpers.Object(node, "name", "fullName", "assemblyName", "assemblyQualifiedName", "baseTypes"); return new TypeInfoDto { Name = DtoHelpers.Required(o, "name", 1024, true), FullName = DtoHelpers.Required(o, "fullName", 1024, true), AssemblyName = DtoHelpers.Required(o, "assemblyName", 1024, true), AssemblyQualifiedName = DtoHelpers.Required(o, "assemblyQualifiedName", 1024, true), BaseTypes = DtoHelpers.Strings(o.Get("baseTypes"), 1024, 1024, true) }; }
    }
    public sealed class ObjectRef
    {
        public string SessionId { get; set; } = ""; public string ObjectId { get; set; } = ""; public long Generation { get; set; } public TypeInfoDto Type { get; set; } = new TypeInfoDto(); public string DispatcherId { get; set; } = "";
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); DtoHelpers.Add(o, "sessionId", SessionId); DtoHelpers.Add(o, "objectId", ObjectId); o.Add("generation", JsonNumberNode.From(Generation)); o.Add("type", Type.ToJson()); DtoHelpers.Add(o, "dispatcherId", DispatcherId); FromJson(o); return o; }
        public static ObjectRef FromJson(JsonNode node) { var o = DtoHelpers.Object(node, "sessionId", "objectId", "generation", "type", "dispatcherId"); return new ObjectRef { SessionId = DtoHelpers.Required(o, "sessionId"), ObjectId = DtoHelpers.Required(o, "objectId"), Generation = DtoHelpers.Integer(o.Get("generation"), 1), Type = TypeInfoDto.FromJson(o.Get("type")), DispatcherId = DtoHelpers.Required(o, "dispatcherId") }; }
    }
    public sealed class PathSegment
    {
        public string Kind { get; set; } = ""; public string Name { get; set; } = ""; public string? DeclaringType { get; set; } public string? MemberKey { get; set; } public string? OwnerType { get; set; } public string? OwnerAssembly { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); DtoHelpers.Add(o, "kind", Kind); DtoHelpers.Add(o, "name", Name); DtoHelpers.Add(o, "declaringType", DeclaringType); DtoHelpers.Add(o, "memberKey", MemberKey); DtoHelpers.Add(o, "ownerType", OwnerType); DtoHelpers.Add(o, "ownerAssembly", OwnerAssembly); FromJson(o); return o; }
        public static PathSegment FromJson(JsonNode node)
        {
            var o = DtoHelpers.Object(node, "kind", "name", "declaringType", "memberKey", "ownerType", "ownerAssembly"); var p = new PathSegment { Kind = DtoHelpers.Required(o, "kind"), Name = DtoHelpers.Required(o, "name", 1024), DeclaringType = DtoHelpers.Optional(o, "declaringType", 1024), MemberKey = DtoHelpers.Optional(o, "memberKey", 1024), OwnerType = DtoHelpers.Optional(o, "ownerType", 1024), OwnerAssembly = DtoHelpers.Optional(o, "ownerAssembly", 1024) };
            DtoHelpers.OneOf(p.Kind, SegmentKind.Property, SegmentKind.Field, SegmentKind.Dependency, SegmentKind.Type, "uia");
            if (p.Kind == SegmentKind.Dependency) { if (p.OwnerType == null || p.OwnerAssembly == null || p.DeclaringType != null || p.MemberKey != null) throw DtoHelpers.Invalid("Invalid dependency segment"); }
            else if (p.OwnerType != null || p.OwnerAssembly != null) throw DtoHelpers.Invalid("Invalid segment owner");
            if (p.Kind == "uia") { if (p.DeclaringType != null || p.MemberKey != null) throw DtoHelpers.Invalid("Invalid uia segment"); DtoHelpers.OneOf(p.Name, "automation_id", "name", "class_name", "control_type"); }
            if (p.Kind == SegmentKind.Type) { if (p.DeclaringType != null || p.MemberKey != null) throw DtoHelpers.Invalid("Invalid type segment"); DtoHelpers.OneOf(p.Name, "Name", "FullName", "AssemblyName", "AssemblyQualifiedName", "BaseTypes"); }
            return p;
        }
    }
}
