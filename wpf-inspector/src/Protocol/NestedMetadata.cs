namespace WinTestKit.Inspector.Protocol
{
    public sealed class DependencySourceDto
    {
        public string BaseValueSource { get; set; } = "";
        public bool IsExpression { get; set; }
        public bool IsAnimated { get; set; }
        public bool IsCoerced { get; set; }
        public bool IsCurrent { get; set; }

        public JsonObjectNode ToJson()
        {
            var o = new JsonObjectNode();
            DtoHelpers.Add(o, "baseValueSource", BaseValueSource);
            o.Add("isExpression", new JsonBoolNode(IsExpression));
            o.Add("isAnimated", new JsonBoolNode(IsAnimated));
            o.Add("isCoerced", new JsonBoolNode(IsCoerced));
            o.Add("isCurrent", new JsonBoolNode(IsCurrent));
            FromJson(o); return o;
        }
        public static DependencySourceDto FromJson(JsonNode node)
        {
            var o = DtoHelpers.Object(node, "baseValueSource", "isExpression", "isAnimated", "isCoerced", "isCurrent");
            var x = new DependencySourceDto { BaseValueSource = DtoHelpers.Required(o, "baseValueSource"), IsExpression = DtoHelpers.Boolean(o.Get("isExpression")), IsAnimated = DtoHelpers.Boolean(o.Get("isAnimated")), IsCoerced = DtoHelpers.Boolean(o.Get("isCoerced")), IsCurrent = DtoHelpers.Boolean(o.Get("isCurrent")) };
            DtoHelpers.OneOf(x.BaseValueSource, "Unknown", "Default", "Inherited", "DefaultStyle", "DefaultStyleTrigger", "Style", "TemplateTrigger", "StyleTrigger", "ImplicitStyleReference", "ParentTemplate", "ParentTemplateTrigger", "Local");
            return x;
        }
    }

    public static class NestedMetadata
    {
        public static void Dependency(JsonNode node)
        {
            var o = DtoHelpers.Object(node, "ownerType", "ownerAssembly", "propertyType", "readOnly", "isAttached", "hasLocalValue", "metadataFlags");
            DtoHelpers.Required(o, "ownerType", 1024); DtoHelpers.Required(o, "ownerAssembly", 1024); DtoHelpers.Required(o, "propertyType", 1024);
            DtoHelpers.Boolean(o.Get("readOnly")); DtoHelpers.Boolean(o.Get("hasLocalValue"));
            DtoHelpers.OneOf(DtoHelpers.Required(o, "isAttached"), "true", "false", "unknown");
            foreach (var flag in DtoHelpers.Strings(o.Get("metadataFlags"), 32, 128))
                DtoHelpers.OneOf(flag, "None", "AffectsMeasure", "AffectsArrange", "AffectsParentMeasure", "AffectsParentArrange", "AffectsRender", "Inherits", "OverridesInheritanceBehavior", "NotDataBindable", "BindsTwoWayByDefault", "Journal", "SubPropertiesDoNotAffectRender");
        }
        public static void Literal(JsonNode node, bool inArray = false)
        {
            var o = DtoHelpers.Object(node, "kind", "value");
            var kind = DtoHelpers.Required(o, "kind"); var value = o.Get("value");
            switch (kind)
            {
                case "string": DtoHelpers.String(value, ProtocolLimits.MaxScalarChars, true); break;
                case "enum": case "type": DtoHelpers.String(value, ProtocolLimits.MaxKeyLength); break;
                case "boolean": DtoHelpers.Boolean(value); break;
                case "integer": DtoHelpers.Integer(value, long.MinValue); break;
                case "number": if (!(value is JsonNumberNode)) throw DtoHelpers.Invalid("Expected number"); break;
                case "null": if (!(value is JsonNullNode)) throw DtoHelpers.Invalid("Expected null"); break;
                case "array": if (inArray) throw DtoHelpers.Invalid("Nested literal array"); foreach (var item in DtoHelpers.Array(value, 32).Items) Literal(item, true); break;
                default: throw DtoHelpers.Invalid("Unknown literal kind");
            }
        }
        public static void RelativeSource(JsonNode node)
        {
            var o = DtoHelpers.Object(node, "mode", "ancestorType", "ancestorLevel");
            DtoHelpers.OneOf(DtoHelpers.Required(o, "mode"), "FindAncestor", "PreviousData", "TemplatedParent", "Self");
            DtoHelpers.Optional(o, "ancestorType", 1024);
            if (o.TryGet("ancestorLevel", out var level)) DtoHelpers.Integer(level, 1, int.MaxValue);
        }
    }
}
