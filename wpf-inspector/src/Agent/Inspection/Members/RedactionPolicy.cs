using System;
using System.Collections.Generic;
using System.Windows;
using System.Windows.Automation.Peers;
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
            int count = 0;
            foreach (string name in additional)
            {
                if (++count > 32 || string.IsNullOrEmpty(name)) throw new ArgumentException("Invalid redaction policy");
                int length = 0;
                for (int index = 0; index < name.Length; index++)
                {
                    if (char.IsHighSurrogate(name[index]))
                    {
                        if (++index >= name.Length || !char.IsLowSurrogate(name[index])) throw new ArgumentException("Invalid redaction policy");
                    }
                    else if (char.IsLowSurrogate(name[index])) throw new ArgumentException("Invalid redaction policy");
                    length++;
                }
                if (length > 128) throw new ArgumentException("Invalid redaction policy");
                all.Add(name);
            }
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

        internal static bool IsProtectedIdentity(object target)
        {
            if (!(target is DependencyObject dependency)) return false;
            try
            {
                dependency.VerifyAccess();
                AutomationPeer? peer = dependency is UIElement element ?
                    UIElementAutomationPeer.FromElement(element) ?? UIElementAutomationPeer.CreatePeerForElement(element) :
                    dependency is ContentElement contentElement ?
                    ContentElementAutomationPeer.FromElement(contentElement) ?? ContentElementAutomationPeer.CreatePeerForElement(contentElement) : null;
                bool owned = peer is UIElementAutomationPeer ui && ReferenceEquals(ui.Owner, dependency) ||
                    peer is ContentElementAutomationPeer content && ReferenceEquals(content.Owner, dependency);
                return !owned || peer!.IsPassword();
            }
            catch (Exception) { return true; }
        }
    }
}
