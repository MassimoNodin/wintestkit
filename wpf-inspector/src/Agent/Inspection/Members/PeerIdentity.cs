using System;
using System.Windows;
using System.Windows.Automation.Peers;
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
                string? result = name == "class_name" ? peer.GetClassName() :
                    name == "automation_id" ? peer.GetAutomationId() :
                    name == "name" ? peer.GetName() : Enum.GetName(typeof(AutomationControlType), peer.GetAutomationControlType());
                return ValueSerializer.Serialize(result ?? "", typeof(string), registry, dispatcher);
            }
            catch (Exception) { return new ValueDto { Status = "exception", Kind = "unavailable", FailedSegment = 0 }; }
        }
    }
}
