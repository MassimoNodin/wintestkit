using System;
using System.Globalization;
using System.Text;

namespace WinTestKit.Inspector.Protocol
{
    public static class StrictJson
    {
        private static readonly UTF8Encoding Utf8 = new UTF8Encoding(false, true);
        public static JsonNode Parse(byte[] utf8, int offset, int count)
        {
            try { var parser = new Parser(Utf8.GetString(utf8, offset, count)); var result = parser.Value(0); parser.White(); if (!parser.End) throw Bad(); return result; }
            catch (DecoderFallbackException) { throw Bad(); }
        }
        public static byte[] Serialize(JsonNode node) { var output = new StringBuilder(); Write(output, node, 0); try { return Utf8.GetBytes(output.ToString()); } catch (EncoderFallbackException) { throw Bad(); } }
        private static ProtocolException Bad() => new ProtocolException(ErrorCodes.InvalidParams, "Invalid JSON");
        private static void Write(StringBuilder b, JsonNode n, int depth)
        {
            if (depth > ProtocolLimits.MaxJsonDepth || (depth == ProtocolLimits.MaxJsonDepth && (n is JsonArrayNode || n is JsonObjectNode))) throw Bad();
            if (n is JsonStringNode s) { Quote(b, s.Value); return; }
            if (n is JsonNumberNode number) { var p = new Parser(number.RawText); if (!(p.Value(0) is JsonNumberNode) || !p.End) throw Bad(); b.Append(number.RawText); return; }
            if (n is JsonBoolNode boolean) { b.Append(boolean.Value ? "true" : "false"); return; }
            if (n is JsonNullNode) { b.Append("null"); return; }
            if (n is JsonArrayNode array) { b.Append('['); bool first = true; foreach (var item in array.Items) { if (!first) b.Append(','); first = false; Write(b, item, depth + 1); } b.Append(']'); return; }
            if (n is JsonObjectNode obj) { b.Append('{'); bool first = true; foreach (var item in obj.Members) { if (!first) b.Append(','); first = false; Quote(b, item.Key); b.Append(':'); Write(b, item.Value, depth + 1); } b.Append('}'); return; }
            throw Bad();
        }
        private static void Quote(StringBuilder b, string s) { b.Append('"'); foreach (char c in s) { if (c == '"' || c == '\\') { b.Append('\\'); b.Append(c); } else if (c < 32) { b.Append("\\u"); b.Append(((int)c).ToString("x4", CultureInfo.InvariantCulture)); } else b.Append(c); } b.Append('"'); }
        private sealed class Parser
        {
            private readonly string s; private int i;
            public Parser(string input) { s = input; }
            public bool End => i == s.Length;
            public void White() { while (i < s.Length && (s[i] == ' ' || s[i] == '\t' || s[i] == '\r' || s[i] == '\n')) i++; }
            private bool Take(char c) { if (i < s.Length && s[i] == c) { i++; return true; } return false; }
            public JsonNode Value(int depth)
            {
                White(); if (depth > ProtocolLimits.MaxJsonDepth || End || (depth == ProtocolLimits.MaxJsonDepth && (s[i] == '[' || s[i] == '{'))) throw Bad();
                if (Take('{')) { var o = new JsonObjectNode(); White(); if (Take('}')) return o; do { White(); if (End || s[i] != '"') throw Bad(); string key = String(); White(); if (!Take(':')) throw Bad(); o.Add(key, Value(depth + 1)); White(); if (Take('}')) return o; if (!Take(',')) throw Bad(); } while (true); }
                if (Take('[')) { var a = new JsonArrayNode(); White(); if (Take(']')) return a; do { a.Add(Value(depth + 1)); White(); if (Take(']')) return a; if (!Take(',')) throw Bad(); } while (true); }
                if (s[i] == '"') return new JsonStringNode(String());
                if (Literal("true")) return new JsonBoolNode(true); if (Literal("false")) return new JsonBoolNode(false); if (Literal("null")) return JsonNullNode.Instance;
                int start = i; Take('-'); if (Take('0')) { if (i < s.Length && Digit(s[i])) throw Bad(); } else { if (i >= s.Length || s[i] < '1' || s[i] > '9') throw Bad(); while (i < s.Length && Digit(s[i])) i++; }
                if (Take('.')) { if (i >= s.Length || !Digit(s[i])) throw Bad(); while (i < s.Length && Digit(s[i])) i++; }
                if (Take('e') || Take('E')) { if (!Take('+')) Take('-'); if (i >= s.Length || !Digit(s[i])) throw Bad(); while (i < s.Length && Digit(s[i])) i++; }
                return new JsonNumberNode(s.Substring(start, i - start));
            }
            private static bool Digit(char c) => c >= '0' && c <= '9';
            private bool Literal(string value) { if (i + value.Length > s.Length || string.CompareOrdinal(s, i, value, 0, value.Length) != 0) return false; i += value.Length; return true; }
            private char Hex() { if (i + 4 > s.Length || !ushort.TryParse(s.Substring(i, 4), NumberStyles.AllowHexSpecifier, CultureInfo.InvariantCulture, out ushort v)) throw Bad(); i += 4; return (char)v; }
            private string String()
            {
                if (!Take('"')) throw Bad(); var b = new StringBuilder();
                while (!End) { char c = s[i++]; if (c == '"') return b.ToString(); if (c < 32) throw Bad(); if (c == '\\') { if (End) throw Bad(); c = s[i++]; switch (c) { case '"': case '\\': case '/': break; case 'b': c = '\b'; break; case 'f': c = '\f'; break; case 'n': c = '\n'; break; case 'r': c = '\r'; break; case 't': c = '\t'; break; case 'u': c = Hex(); break; default: throw Bad(); } }
                    if (char.IsHighSurrogate(c)) { char low; if (i + 1 < s.Length && s[i] == '\\' && s[i + 1] == 'u') { i += 2; low = Hex(); } else { if (End) throw Bad(); low = s[i++]; } if (!char.IsLowSurrogate(low)) throw Bad(); b.Append(c); b.Append(low); } else { if (char.IsLowSurrogate(c)) throw Bad(); b.Append(c); }
                } throw Bad();
            }
        }
    }
}
