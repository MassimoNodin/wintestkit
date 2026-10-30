using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Query
{
    // Translate the shared grammar instead of using RegexOptions.IgnoreCase, whose
    // Unicode case folding differs from the protocol's ASCII-only semantics.
    internal sealed class QueryRegex
    {
        private readonly string pattern;
        private readonly RegexOptions options;
        private readonly Dictionary<int, Regex> cache = new Dictionary<int, Regex>();

        internal QueryRegex(string source, IReadOnlyList<string> flags)
        {
            bool fold = false;
            var seen = new HashSet<string>(StringComparer.Ordinal);
            options = RegexOptions.CultureInvariant;
            foreach (string flag in flags)
            {
                if (!seen.Add(flag)) throw Invalid();
                switch (flag)
                {
                    case "ignoreCase": fold = true; break;
                    case "multiline": options |= RegexOptions.Multiline; break;
                    case "singleline": options |= RegexOptions.Singleline; break;
                    default: throw Invalid();
                }
            }
            if (source.Length > 1024) throw Invalid();
            pattern = new Parser(source, fold).Parse();
            // Compile even if the traversal has no candidates, so malformed input
            // always fails validation before searching.
            try { cache.Add(50, new Regex(pattern, options, TimeSpan.FromMilliseconds(50))); }
            catch (ArgumentException) { throw Invalid(); }
        }

        internal bool IsMatch(string input, int remainingMilliseconds)
        {
            if (remainingMilliseconds < 1) throw new ProtocolException(ErrorCodes.LimitExceeded, "Query deadline reached.");
            int timeout = Math.Min(50, remainingMilliseconds);
            if (!cache.TryGetValue(timeout, out Regex? regex))
                cache.Add(timeout, regex = new Regex(pattern, options, TimeSpan.FromMilliseconds(timeout)));
            try { return regex.IsMatch(input); }
            catch (RegexMatchTimeoutException) { throw new ProtocolException(ErrorCodes.RegexTimeout, "Regular expression timed out."); }
        }

        private static ProtocolException Invalid() => new ProtocolException(ErrorCodes.InvalidParams, "Invalid regular expression.");

        private sealed class Parser
        {
            private const string Meta = @"\.^$|?*+()[]{}-";
            private readonly string source;
            private readonly bool fold;
            private int pos;
            private readonly StringBuilder result = new StringBuilder();
            internal Parser(string source, bool fold) { this.source = source; this.fold = fold; }
            internal string Parse()
            {
                Expression(false);
                if (pos != source.Length) throw Invalid();
                return result.ToString();
            }
            private void Expression(bool group)
            {
                while (pos < source.Length && source[pos] != ')')
                {
                    char c = source[pos++];
                    if (c == '|') { result.Append(c); continue; }
                    bool quantifiable = true;
                    if (c == '(')
                    {
                        result.Append('(');
                        if (pos < source.Length && source[pos] == '?')
                        {
                            if (pos + 1 >= source.Length || source[pos + 1] != ':') throw Invalid();
                            pos += 2; result.Append("?:");
                        }
                        Expression(true);
                        if (pos == source.Length || source[pos++] != ')') throw Invalid();
                        result.Append(')');
                    }
                    else if (c == '[') CharacterClass();
                    else if (c == '\\') Literal(Escape());
                    else if (c == '.' || c == '^' || c == '$') { result.Append(c); quantifiable = c == '.'; }
                    else if (c == '*' || c == '+' || c == '?' || c == '{' || c == '}' || c == ']') throw Invalid();
                    else { CheckAscii(c); Literal(c); }
                    if (pos < source.Length && IsQuantifier(source[pos]))
                    {
                        if (!quantifiable) throw Invalid();
                        Quantifier();
                    }
                }
                if (!group && pos < source.Length) throw Invalid();
            }
            private void Quantifier()
            {
                char c = source[pos++]; result.Append(c);
                if (c == '{')
                {
                    int min = Bound(); int max = min;
                    if (pos < source.Length && source[pos] == ',')
                    {
                        result.Append(','); pos++;
                        max = pos < source.Length && char.IsDigit(source[pos]) ? Bound() : 10000;
                    }
                    if (max < min || pos >= source.Length || source[pos++] != '}') throw Invalid();
                    result.Append('}');
                }
                if (pos < source.Length && source[pos] == '?') { result.Append('?'); pos++; }
                if (pos < source.Length && IsQuantifier(source[pos])) throw Invalid();
            }
            private int Bound()
            {
                int start = pos, value = 0;
                while (pos < source.Length && source[pos] >= '0' && source[pos] <= '9')
                {
                    value = value * 10 + source[pos] - '0';
                    if (value > 10000) throw Invalid();
                    result.Append(source[pos++]);
                }
                if (pos == start) throw Invalid();
                return value;
            }
            private void CharacterClass()
            {
                bool negated = pos < source.Length && source[pos] == '^';
                if (negated) pos++;
                var chars = new SortedSet<char>();
                bool any = false;
                while (pos < source.Length && source[pos] != ']')
                {
                    char first = ClassChar(); any = true;
                    if (pos < source.Length && source[pos] == '-' && pos + 1 < source.Length && source[pos + 1] != ']')
                    {
                        pos++; char last = ClassChar();
                        if (first > last) throw Invalid();
                        for (int i = first; i <= last; i++) Add(chars, (char)i);
                    }
                    else Add(chars, first);
                }
                if (!any || pos >= source.Length || source[pos++] != ']') throw Invalid();
                result.Append(negated ? "[^" : "[");
                foreach (char ch in chars) result.Append("\\u").Append(((int)ch).ToString("X4", CultureInfo.InvariantCulture));
                result.Append(']');
            }
            private char ClassChar()
            {
                if (pos >= source.Length) throw Invalid();
                char c = source[pos++];
                if (c == '\\') return Escape();
                CheckAscii(c);
                return c;
            }
            private char Escape()
            {
                if (pos >= source.Length) throw Invalid();
                char c = source[pos++];
                if (Meta.IndexOf(c) < 0) throw Invalid();
                return c;
            }
            private void Literal(char c)
            {
                if (fold && IsLetter(c))
                    result.Append('[').Append(char.ToUpperInvariant(c)).Append(char.ToLowerInvariant(c)).Append(']');
                else result.Append(Regex.Escape(c.ToString()));
            }
            private void Add(SortedSet<char> chars, char c)
            {
                chars.Add(c);
                if (fold && IsLetter(c)) { chars.Add(char.ToUpperInvariant(c)); chars.Add(char.ToLowerInvariant(c)); }
            }
            private static bool IsLetter(char c) => c >= 'A' && c <= 'Z' || c >= 'a' && c <= 'z';
            private static void CheckAscii(char c) { if (c > 127) throw Invalid(); }
            private static bool IsQuantifier(char c) => c == '*' || c == '+' || c == '?' || c == '{';
        }
    }
}
