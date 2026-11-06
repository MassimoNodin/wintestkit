using System;
using System.Windows;
using System.Windows.Automation.Peers;
using System.Windows.Automation.Provider;
using System.Collections.Generic;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Contracts;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Inspection.Members
{
    internal static class PeerIdentity
    {
        internal static AutomationPeer? GetPeer(DependencyObject target) =>
            target is UIElement element ? UIElementAutomationPeer.FromElement(element) ?? UIElementAutomationPeer.CreatePeerForElement(element) :
            target is ContentElement content ? ContentElementAutomationPeer.FromElement(content) ?? ContentElementAutomationPeer.CreatePeerForElement(content) : null;

        internal static ValueDto Read(object target, string name, IObjectRegistry registry, Dispatcher dispatcher)
        {
            try
            {
                AutomationPeer? peer = target is DependencyObject dependency ? GetPeer(dependency) : null;
                if (peer == null) return new ValueDto { Status = "unavailable", Kind = "unavailable" };
                if ((name == "value" || name == "document_text") && (RedactionPolicy.IsProtectedIdentity(target) || peer.IsPassword()))
                    return new ValueDto { Status = "redacted", Kind = "unavailable", RedactionRule = "identity" };
                object? result = null;
                switch (name)
                {
                    case "class_name": result = peer.GetClassName(); break;
                    case "automation_id": result = peer.GetAutomationId(); break;
                    case "name": result = peer.GetName(); break;
                    case "control_type": result = Enum.GetName(typeof(AutomationControlType), peer.GetAutomationControlType()); break;
                    case "is_password": result = peer.IsPassword(); break;
                    case "supported_patterns":
                        var names = new List<string>();
                        foreach (PatternInterface pattern in new[] { PatternInterface.Invoke, PatternInterface.Toggle, PatternInterface.SelectionItem, PatternInterface.Selection, PatternInterface.ExpandCollapse, PatternInterface.Value, PatternInterface.RangeValue, PatternInterface.Scroll, PatternInterface.ScrollItem, PatternInterface.Text })
                            if (peer.GetPattern(pattern) != null) names.Add(pattern.ToString());
                        result = string.Join(",", names); break;
                    case "value": if (peer.GetPattern(PatternInterface.Value) is IValueProvider value) result = value.Value; break;
                    case "is_read_only":
                        if (peer.GetPattern(PatternInterface.Value) is IValueProvider v) result = v.IsReadOnly;
                        else if (peer.GetPattern(PatternInterface.RangeValue) is IRangeValueProvider r) result = r.IsReadOnly;
                        break;
                    case "toggle_state": if (peer.GetPattern(PatternInterface.Toggle) is IToggleProvider toggle) result = toggle.ToggleState.ToString(); break;
                    case "is_selected": if (peer.GetPattern(PatternInterface.SelectionItem) is ISelectionItemProvider selection) result = selection.IsSelected; break;
                    case "expand_state": if (peer.GetPattern(PatternInterface.ExpandCollapse) is IExpandCollapseProvider expand) result = expand.ExpandCollapseState.ToString(); break;
                    case "range_value": if (peer.GetPattern(PatternInterface.RangeValue) is IRangeValueProvider range) result = range.Value; break;
                    case "document_text": if (peer.GetPattern(PatternInterface.Text) is ITextProvider text) result = text.DocumentRange.GetText(ProtocolLimits.MaxScalarChars); break;
                }
                if ((name == "selection_count" || name.StartsWith("selection_name_", StringComparison.Ordinal)) && peer.GetPattern(PatternInterface.Selection) is ISelectionProvider provider)
                {
                    IRawElementProviderSimple[] selected = provider.GetSelection() ?? Array.Empty<IRawElementProviderSimple>();
                    if (name == "selection_count") result = selected.Length;
                    else if (int.TryParse(name.Substring("selection_name_".Length), out int index) && index >= 0 && index < selected.Length)
                        result = (typeof(AutomationPeer).GetMethod("PeerFromProvider", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!.Invoke(peer, new object[] { selected[index] }) as AutomationPeer)?.GetName();
                }
                if (result == null) return new ValueDto { Status = "unavailable", Kind = "unavailable" };
                return ValueSerializer.Serialize(result, result.GetType(), registry, dispatcher);
            }
            catch (Exception) { return new ValueDto { Status = "exception", Kind = "unavailable", FailedSegment = 0 }; }
        }
    }
}
