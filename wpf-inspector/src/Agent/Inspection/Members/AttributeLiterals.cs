using System;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Inspection.Members
{
    internal static class AttributeLiterals
    {
        internal static JsonNode Convert(CustomAttributeTypedArgument argument, int depth = 0)
        {
            string kind;
            JsonNode value;
            if (argument.Value == null) { kind = "null"; value = JsonNullNode.Instance; }
            else if (argument.Value is IList<CustomAttributeTypedArgument> array)
            {
                if (depth != 0) throw new NotSupportedException("Nested attribute arrays are unsupported.");
                kind = "array";
                var items = new JsonArrayNode();
                for (int index = 0; index < Math.Min(array.Count, 32); index++) items.Add(Convert(array[index], depth + 1));
                value = items;
            }
            else if (argument.Value is Type type) { kind = "type"; value = new JsonStringNode(type.AssemblyQualifiedName ?? type.FullName ?? string.Empty); }
            else if (argument.ArgumentType.IsEnum)
            {
                kind = "enum";
                value = new JsonStringNode(Declaration.TypeName(argument.ArgumentType) + "." + (Enum.GetName(argument.ArgumentType, argument.Value) ?? System.Convert.ToString(argument.Value, CultureInfo.InvariantCulture)));
            }
            else if (argument.Value is string text) { kind = "string"; value = new JsonStringNode(ScalarText.Prefix(text, ProtocolLimits.MaxScalarChars, out _)); }
            else if (argument.Value is char character) { kind = "string"; value = new JsonStringNode(character.ToString()); }
            else if (argument.Value is bool boolean) { kind = "boolean"; value = new JsonBoolNode(boolean); }
            else if (argument.Value is float || argument.Value is double)
            {
                double number = System.Convert.ToDouble(argument.Value, CultureInfo.InvariantCulture);
                if (double.IsNaN(number) || double.IsInfinity(number)) throw new NotSupportedException("Nonfinite attribute numbers are unsupported.");
                kind = "number"; value = JsonNumberNode.From(number);
            }
            else
            {
                kind = "integer";
                value = new JsonNumberNode(System.Convert.ToInt64(argument.Value, CultureInfo.InvariantCulture).ToString(CultureInfo.InvariantCulture));
            }
            var result = new JsonObjectNode();
            result.Add("kind", new JsonStringNode(kind));
            result.Add("value", value);
            return result;
        }
    }
}
