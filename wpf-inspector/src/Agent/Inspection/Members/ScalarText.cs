using System;

namespace WinTestKit.Inspector.Agent.Inspection.Members
{
    internal static class ScalarText
    {
        // Count Unicode scalar values, preserving surrogate pairs in the bounded prefix.
        internal static string Prefix(string value, int limit, out int scalarLength)
        {
            int count = 0, boundary = value.Length;
            for (int i = 0; i < value.Length; i++)
            {
                if (count == limit) boundary = i;
                count++;
                if (char.IsHighSurrogate(value[i]) && i + 1 < value.Length && char.IsLowSurrogate(value[i + 1])) i++;
            }
            scalarLength = count;
            return boundary == value.Length ? value : value.Substring(0, boundary);
        }
    }
}
