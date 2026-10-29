using System;
using System.Collections.Generic;
using System.Text.RegularExpressions;

namespace WinTestKit.Inspector.Protocol
{
    public sealed class AllowEntry
    {
        public AllowEntry(string typeFullName, string memberKey) { TypeFullName = typeFullName; MemberKey = memberKey; }
        public string TypeFullName { get; }
        public string MemberKey { get; }
        public JsonObjectNode ToJson() { var obj = new JsonObjectNode(); DtoHelpers.Add(obj, "typeFullName", TypeFullName); DtoHelpers.Add(obj, "memberKey", MemberKey); return obj; }
        public static AllowEntry FromJson(JsonNode node) { var obj = DtoHelpers.Object(node, "typeFullName", "memberKey"); return new AllowEntry(DtoHelpers.Required(obj, "typeFullName", 1024), DtoHelpers.Required(obj, "memberKey", 1024)); }
    }
    public sealed class WriteAllowlist
    {
        public WriteAllowlist() : this(Array.Empty<AllowEntry>(), Array.Empty<AllowEntry>()) { }
        public WriteAllowlist(IEnumerable<AllowEntry> properties, IEnumerable<AllowEntry> methods) { Properties = new List<AllowEntry>(properties).AsReadOnly(); Methods = new List<AllowEntry>(methods).AsReadOnly(); }
        public IReadOnlyList<AllowEntry> Properties { get; }
        public IReadOnlyList<AllowEntry> Methods { get; }
        public JsonObjectNode ToJson() { var obj = new JsonObjectNode(); obj.Add("properties", Serialize(Properties)); obj.Add("methods", Serialize(Methods)); FromJson(obj); return obj; }
        private static JsonArrayNode Serialize(IEnumerable<AllowEntry> entries) { var array = new JsonArrayNode(); foreach (var entry in entries) array.Add(entry.ToJson()); return array; }
        private static IReadOnlyList<AllowEntry> Read(JsonNode node, bool methods)
        {
            var entries = new List<AllowEntry>(); var seen = new HashSet<string>(StringComparer.Ordinal);
            foreach (var item in DtoHelpers.Array(node, 128).Items)
            {
                var entry = AllowEntry.FromJson(item);
                string pattern = methods ? @"^[^\s(),\[\]&*?]+\((?:[^\s(),\[\]&*?]+(?:,[^\s(),\[\]&*?]+)*)?\)$" : @"^[^\s(),\[\]&*?]+$";
                if (!Regex.IsMatch(entry.MemberKey, pattern) || entry.MemberKey.IndexOf((char)96) >= 0 || entry.TypeFullName.IndexOf('*') >= 0 || !seen.Add(entry.TypeFullName + "\0" + entry.MemberKey)) throw DtoHelpers.Invalid("Invalid allowlist entry");
                entries.Add(entry);
            }
            return entries.AsReadOnly();
        }
        public static WriteAllowlist FromJson(JsonNode node) { var obj = DtoHelpers.Object(node, "properties", "methods"); return new WriteAllowlist(Read(obj.Get("properties"), false), Read(obj.Get("methods"), true)); }
    }
}
