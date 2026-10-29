using System;
using System.Reflection;
using System.Windows;
using System.Windows.Automation.Peers;

namespace WinTestKit.Inspector.Agent.Mapping
{
    public interface IPeerRuntimeIdAdapter
    {
        bool IsAvailable { get; }
        int[]? GetRuntimeId(AutomationPeer peer);
    }

    public sealed class PeerRuntimeIdAdapter : IPeerRuntimeIdAdapter
    {
        private static readonly MethodInfo? RuntimeIdMethod = FindMethod(typeof(AutomationPeer));
        private readonly MethodInfo? method;

        public PeerRuntimeIdAdapter() : this(RuntimeIdMethod) { }

        public PeerRuntimeIdAdapter(Type peerBaseType) : this(FindMethod(peerBaseType)) { }

        private PeerRuntimeIdAdapter(MethodInfo? method) { this.method = method; }

        public bool IsAvailable => method != null;

        public int[]? GetRuntimeId(AutomationPeer peer)
        {
            peer.Dispatcher.VerifyAccess();
            if (method == null) return null;
            try { return method.Invoke(peer, null) as int[]; }
            catch (TargetInvocationException) { return null; }
            catch (ArgumentException) { return null; }
            catch (MethodAccessException) { return null; }
        }

        private static MethodInfo? FindMethod(Type type)
        {
            MethodInfo? candidate = type.GetMethod("GetRuntimeId", BindingFlags.Instance | BindingFlags.NonPublic,
                null, Type.EmptyTypes, null);
            return candidate != null && !candidate.IsStatic && !candidate.ContainsGenericParameters &&
                candidate.ReturnType == typeof(int[]) ? candidate : null;
        }

        public static AutomationPeer? ExistingPeer(DependencyObject target)
        {
            target.VerifyAccess();
            return target is UIElement element ? UIElementAutomationPeer.FromElement(element) :
                target is ContentElement content ? ContentElementAutomationPeer.FromElement(content) : null;
        }

        public static AutomationPeer? ResolveSingleElement(DependencyObject target)
        {
            target.VerifyAccess();
            return ExistingPeer(target) ?? (target is UIElement element ? UIElementAutomationPeer.CreatePeerForElement(element) :
                target is ContentElement content ? ContentElementAutomationPeer.CreatePeerForElement(content) : null);
        }
    }
}
