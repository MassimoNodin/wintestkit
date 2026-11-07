using System;
using System.Windows;
using System.Windows.Automation.Peers;
using System.Windows.Automation.Provider;
using System.Collections.Generic;
using System.Windows.Threading;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Reflection;
using WinTestKit.Inspector.Agent.Contracts;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Inspection.Members
{
    internal static class PeerIdentity
    {
        // Test hook and diagnostic are thread-local so concurrent inspector reads are unaffected.
        [ThreadStatic] private static bool disablePeerFromProvider;
        internal static bool DisablePeerFromProvider { get => disablePeerFromProvider; set => disablePeerFromProvider = value; }
        [ThreadStatic] internal static string? SelectionNameRoute;

        private static AutomationPeer? SelectedPeer(AutomationPeer owner, IRawElementProviderSimple provider)
        {
            SelectionNameRoute = "unavailable";
            if (!DisablePeerFromProvider)
            {
                try
                {
                    var method = typeof(AutomationPeer).GetMethod("PeerFromProvider", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic);
                    if (method?.Invoke(owner, new object[] { provider }) is AutomationPeer peer)
                    {
                        SelectionNameRoute = "PeerFromProvider";
                        return peer;
                    }
                }
                catch (Exception) { /* Try the WPF proxy below. */ }
            }

            // WPF's ElementProxy holds the exact peer used by UIA, even for virtualized
            // items. Reading it preserves GetSelection order and never realizes a container.
            // Restrict reflection to WPF's own type and tolerate changes in its internals.
            try
            {
                Type type = provider.GetType();
                if (type.Assembly == typeof(AutomationPeer).Assembly && type.FullName == "MS.Internal.Automation.ElementProxy")
                {
                    var property = type.GetProperty("Peer", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic);
                    if (property?.GetValue(provider, null) is AutomationPeer peer)
                    {
                        SelectionNameRoute = "ElementProxy.Peer";
                        return peer;
                    }
                }
            }
            catch (Exception) { /* An unsupported proxy remains unavailable. */ }
            return null;
        }

        private static List<object>? SelectedItems(object target, AutomationPeer peer)
        {
            if (!(peer is ItemsControlAutomationPeer)) return null;
            var items = new List<object>();
            if (target is DataGrid grid && grid.SelectionUnit != DataGridSelectionUnit.FullRow) return null;
            if (target is MultiSelector multi)
            {
                foreach (object item in multi.SelectedItems) items.Add(item);
            }
            else if (target is ListBox list)
            {
                foreach (object item in list.SelectedItems) items.Add(item);
            }
            else if (target is Selector selector)
            {
                if (selector.SelectedIndex >= 0) items.Add(selector.SelectedItem);
            }
            else if (target is TreeView tree)
            {
                if (tree.SelectedItem != null) items.Add(tree.SelectedItem);
            }
            else return null;
            return items;
        }

        private static ItemAutomationPeer? FindChildItemPeer(AutomationPeer peer, object item)
        {
            var children = peer.GetChildren();
            if (children == null) return null;
            foreach (AutomationPeer child in children)
            {
                if (child is ItemAutomationPeer itemPeer && Equals(itemPeer.Item, item)) return itemPeer;
                // TreeView item peers own nested items rather than the root peer.
                if (child is TreeViewItemAutomationPeer)
                {
                    var nested = FindChildItemPeer(child, item);
                    if (nested != null) return nested;
                }
            }
            return null;
        }

        private static ItemAutomationPeer? SelectedItemPeer(ItemsControlAutomationPeer peer, object item)
        {
            SelectionNameRoute = "ItemsControl.GetChildren";
            var child = FindChildItemPeer(peer, item);
            if (child != null) return child;
            // This WPF method looks up or creates an item peer without realizing a container.
            SelectionNameRoute = "ItemsControl.FindOrCreateItemAutomationPeer";
            try
            {
                var method = typeof(ItemsControlAutomationPeer).GetMethod("FindOrCreateItemAutomationPeer",
                    BindingFlags.Instance | BindingFlags.NonPublic, null, new[] { typeof(object) }, null);
                return method?.Invoke(peer, new[] { item }) as ItemAutomationPeer;
            }
            catch (Exception) { return null; }
        }

        internal static AutomationPeer? GetPeer(DependencyObject target)
        {
            if (target is UIElement element)
            {
                var owner = ItemsControl.ItemsControlFromItemContainer(element);
                if (owner != null)
                {
                    object item = owner.ItemContainerGenerator.ItemFromContainer(element);
                    if (item != DependencyProperty.UnsetValue &&
                        (UIElementAutomationPeer.FromElement(owner) ?? UIElementAutomationPeer.CreatePeerForElement(owner)) is ItemsControlAutomationPeer ownerPeer)
                    {
                        var itemPeer = SelectedItemPeer(ownerPeer, item);
                        if (itemPeer != null) return itemPeer;
                    }
                }
                return UIElementAutomationPeer.FromElement(element) ?? UIElementAutomationPeer.CreatePeerForElement(element);
            }
            return target is ContentElement content ? ContentElementAutomationPeer.FromElement(content) ?? ContentElementAutomationPeer.CreatePeerForElement(content) : null;
        }

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
                if (target is ItemsControl itemControl && peer is ItemsControlAutomationPeer itemPeer)
                {
                    if (name == "item_count") result = itemControl.Items.Count;
                    else if (name.StartsWith("item_name_", StringComparison.Ordinal) &&
                        int.TryParse(name.Substring("item_name_".Length), out int itemIndex) &&
                        itemIndex >= 0 && itemIndex < itemControl.Items.Count)
                        result = SelectedItemPeer(itemPeer, itemControl.Items[itemIndex])?.GetName();
                }
                if ((name == "selection_count" || name.StartsWith("selection_name_", StringComparison.Ordinal)) && peer.GetPattern(PatternInterface.Selection) is ISelectionProvider provider)
                {
                    var items = SelectedItems(target, peer);
                    if (items != null && peer is ItemsControlAutomationPeer itemsPeer)
                    {
                        if (name == "selection_count") result = items.Count;
                        else if (int.TryParse(name.Substring("selection_name_".Length), out int index) && index >= 0 && index < items.Count)
                            result = SelectedItemPeer(itemsPeer, items[index])?.GetName();
                    }
                    else
                    {
                        if (peer is ItemsControlAutomationPeer) peer.GetChildren();
                        IRawElementProviderSimple[] selected = provider.GetSelection() ?? Array.Empty<IRawElementProviderSimple>();
                        if (name == "selection_count") result = selected.Length;
                        else if (int.TryParse(name.Substring("selection_name_".Length), out int index) && index >= 0 && index < selected.Length)
                            result = SelectedPeer(peer, selected[index])?.GetName();
                    }
                }
                if (result == null) return new ValueDto { Status = "unavailable", Kind = "unavailable" };
                return ValueSerializer.Serialize(result, result.GetType(), registry, dispatcher);
            }
            catch (Exception) { return new ValueDto { Status = "exception", Kind = "unavailable", FailedSegment = 0 }; }
        }
    }
}
