using System;
using System.Globalization;
using System.Runtime.InteropServices;
using System.Security;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Contracts;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Inspection.Members
{
    internal static class ValueSerializer
    {
        internal static ValueDto Serialize(object? value, Type declared, IObjectRegistry registry, Dispatcher dispatcher)
        {
            string declaredName = Declaration.TypeName(declared);
            var result = new ValueDto { Status = ValueStatus.Ok, DeclaredType = declaredName, RuntimeType = value == null ? "" : Declaration.TypeName(value.GetType()) };
            if (value == null) { result.Kind = ValueKind.Null; result.Scalar = JsonNullNode.Instance; return result; }
            Type type = value.GetType();
            if (value is Exception || value is SecureString || value is SafeHandle || value is IntPtr || value is UIntPtr || value is System.Reflection.Pointer || type.IsPointer || type.Assembly == typeof(Dispatcher).Assembly && type.Namespace == typeof(Dispatcher).Namespace || Marshal.IsComObject(value))
            { result.Status = ValueStatus.Unsupported; result.Kind = ValueKind.Unavailable; return result; }
            if (value is Type described) { result.Kind = ValueKind.Type; result.TypeInfo = TypeInfoBuilder.Build(described); return result; }
            if (value is string text) return String(result, text);
            if (value is char ch) return String(result, ch.ToString());
            if (value is bool boolean) { result.Kind = ValueKind.Boolean; result.Scalar = new JsonBoolNode(boolean); return result; }
            if (type.IsEnum)
            {
                result.Kind = ValueKind.Enum;
                result.Scalar = new JsonStringNode(Enum.Format(type, value, "G"));
                result.NumericValue = Convert.ToString(Convert.ChangeType(value, Enum.GetUnderlyingType(type), CultureInfo.InvariantCulture), CultureInfo.InvariantCulture);
                return result;
            }
            switch (Type.GetTypeCode(type))
            {
                case TypeCode.SByte: case TypeCode.Byte: case TypeCode.Int16: case TypeCode.UInt16: case TypeCode.Int32: case TypeCode.UInt32: case TypeCode.Int64: case TypeCode.UInt64:
                    string integer = Convert.ToString(value, CultureInfo.InvariantCulture)!;
                    decimal n = Convert.ToDecimal(value, CultureInfo.InvariantCulture);
                    result.Kind = ValueKind.Integer;
                    result.Scalar = n >= -9007199254740991m && n <= 9007199254740991m ? (JsonNode)new JsonNumberNode(integer) : new JsonStringNode(integer);
                    if (n < -9007199254740991m || n > 9007199254740991m) result.NumericValue = integer;
                    return result;
                case TypeCode.Decimal:
                    result.Kind = ValueKind.Number; string number = ((decimal)value).ToString(CultureInfo.InvariantCulture); result.Scalar = new JsonStringNode(number); result.NumericValue = number; return result;
                case TypeCode.Single: case TypeCode.Double:
                    double floating = Convert.ToDouble(value, CultureInfo.InvariantCulture); result.Kind = ValueKind.Number;
                    result.Scalar = double.IsNaN(floating) ? (JsonNode)new JsonStringNode("NaN") : double.IsPositiveInfinity(floating) ? new JsonStringNode("Infinity") : double.IsNegativeInfinity(floating) ? new JsonStringNode("-Infinity") : JsonNumberNode.From(floating); return result;
                case TypeCode.DateTime: return String(result, ((DateTime)value).ToString("O", CultureInfo.InvariantCulture));
            }
            if (value is DateTimeOffset offset) return String(result, offset.ToString("O", CultureInfo.InvariantCulture));
            if (value is TimeSpan span) return String(result, span.ToString("c", CultureInfo.InvariantCulture));
            if (value is Guid guid) return String(result, guid.ToString("D"));
            result.Kind = value is Array ? ValueKind.Array : ValueKind.Object;
            result.TypeInfo = TypeInfoBuilder.Build(type);
            result.Object = registry.Register(value, dispatcher, result.TypeInfo);
            if (value is Array array) { result.ArrayRank = array.Rank; result.ArrayLength = array.LongLength; }
            return result;
        }
        private static ValueDto String(ValueDto result, string text)
        {
            for (int index = 0; index < text.Length; index++)
            {
                if (!char.IsSurrogate(text[index])) continue;
                if (char.IsHighSurrogate(text[index]) && index + 1 < text.Length && char.IsLowSurrogate(text[index + 1])) { index++; continue; }
                result.Status = ValueStatus.Unsupported;
                result.Kind = ValueKind.Unavailable;
                return result;
            }
            string prefix = ScalarText.Prefix(text, ProtocolLimits.MaxScalarChars, out int length);
            result.Kind = ValueKind.String; result.Scalar = new JsonStringNode(prefix);
            if (length > ProtocolLimits.MaxScalarChars) { result.Status = ValueStatus.Truncated; result.TruncatedAt = length; }
            return result;
        }
    }
}
