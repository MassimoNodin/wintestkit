using System;
using System.Collections.Generic;
using System.Windows.Controls;

namespace WinTestKit.Inspector.Agent.Inspection.Members
{
    internal sealed class RedactionPolicy
    {
        private static readonly string[] BuiltIn = { "password", "passwd", "pwd", "secret", "token", "credential", "connectionstring", "apikey", "privatekey" };
        private readonly string[] rules;
        internal RedactionPolicy(IEnumerable<string> additional)
        {
            var all = new List<string>(BuiltIn);
            foreach (string name in additional)
                if (!string.IsNullOrEmpty(name)) all.Add(name);
            rules = all.ToArray();
        }
        internal string? Match(string name)
        {
            foreach (string rule in rules)
                if (name.IndexOf(rule, StringComparison.OrdinalIgnoreCase) >= 0) return rule;
            return null;
        }
        internal static bool IsPasswordIdentity(Type declaringType, string name) =>
            declaringType == typeof(PasswordBox) && (name == "Password" || name == "SecurePassword");
    }
}
