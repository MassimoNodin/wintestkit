using System;
using System.Collections.Generic;

namespace WinTestKit.Inspector.Protocol
{
    internal static class DtoHelpers
    {
        internal static ProtocolException Invalid(string message) => new ProtocolException(ErrorCodes.InvalidParams, message);
        internal static JsonObjectNode Object(JsonNode node, params string[] allowed)
        {
            if (!(node is JsonObjectNode obj)) throw Invalid("Expected object");
            var keys = new HashSet<string>(allowed, StringComparer.Ordinal);
            foreach (var member in obj.Members) if (!keys.Contains(member.Key)) throw Invalid("Unknown field: " + member.Key);
            return obj;
        }
        internal static string String(JsonNode node, int max = ProtocolLimits.MaxIdentifierLength, bool empty = false)
        {
            if (!(node is JsonStringNode value)) throw Invalid("Expected string");
            int length = 0;
            for (int i = 0; i < value.Value.Length; i++) { if (char.IsHighSurrogate(value.Value[i])) { if (++i >= value.Value.Length || !char.IsLowSurrogate(value.Value[i])) throw Invalid("Invalid string"); } else if (char.IsLowSurrogate(value.Value[i])) throw Invalid("Invalid string"); length++; }
            if (length > max || (!empty && length == 0)) throw Invalid("String length out of range");
            return value.Value;
        }
        internal static string Required(JsonObjectNode obj, string key, int max = ProtocolLimits.MaxIdentifierLength, bool empty = false) => String(obj.Get(key), max, empty);
        internal static string? Optional(JsonObjectNode obj, string key, int max = ProtocolLimits.MaxIdentifierLength, bool empty = false) => obj.TryGet(key, out var n) ? String(n, max, empty) : null;
        internal static long Integer(JsonNode node, long min = 0, long max = long.MaxValue) { if (!(node is JsonNumberNode n) || !n.TryGetInt64(out long value) || value < min || value > max) throw Invalid("Integer out of range"); return value; }
        internal static bool Boolean(JsonNode node) => node is JsonBoolNode b ? b.Value : throw Invalid("Expected boolean");
        internal static JsonArrayNode Array(JsonNode node, int max = ProtocolLimits.MaxPageSize) { if (!(node is JsonArrayNode a) || a.Items.Count > max) throw Invalid("Invalid array"); return a; }
        internal static List<string> Strings(JsonNode node, int max = ProtocolLimits.MaxPageSize, int length = ProtocolLimits.MaxKeyLength, bool empty = false) { var result = new List<string>(); foreach (var n in Array(node, max).Items) result.Add(String(n, length, empty)); return result; }
        internal static JsonArrayNode Strings(IEnumerable<string> values) { var a = new JsonArrayNode(); foreach (var value in values) a.Add(new JsonStringNode(value)); return a; }
        internal static void Add(JsonObjectNode obj, string key, string? value) { if (value != null) obj.Add(key, new JsonStringNode(value)); }
        internal static void Add(JsonObjectNode obj, string key, long? value) { if (value.HasValue) obj.Add(key, JsonNumberNode.From(value.Value)); }
        internal static void OneOf(string value, params string[] valid) { foreach (var item in valid) if (item == value) return; throw Invalid("Unknown enum value"); }
        internal static List<string> FeatureList(JsonNode node) { var values = Strings(node); foreach (var value in values) OneOf(value, Features.TypeMetadata, Features.ClrMembers, Features.DependencyProperties, Features.Bindings, Features.ExactUiaMapping, Features.BatchReads, Features.Query, Features.Geometry, Features.Actions, Features.VirtualItems, Features.Writes, Features.HitTest, Features.Waits, Features.Events); return values; }
    }
}
