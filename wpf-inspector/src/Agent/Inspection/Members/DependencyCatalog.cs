using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Reflection;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Automation;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Inspection.Members
{
    // Snapshots use public static dependency-property fields and descriptors; the private
    // global dependency-property registry is never accessed.
    internal static class DependencyCatalog
    {
        private static readonly object Gate = new object();
        private static readonly Queue<Assembly> Pending = new Queue<Assembly>();
        private static readonly HashSet<Assembly> Seen = new HashSet<Assembly>();
        private static readonly Dictionary<DependencyProperty, DependencyPropertyDescriptor?> Attached = new Dictionary<DependencyProperty, DependencyPropertyDescriptor?>();
        private static bool incomplete;

        static DependencyCatalog()
        {
            foreach (Type owner in new[] { typeof(Grid), typeof(Canvas), typeof(DockPanel), typeof(Panel), typeof(AutomationProperties), typeof(KeyboardNavigation), typeof(ToolTipService), typeof(ContextMenuService), typeof(ScrollViewer), typeof(Validation), typeof(TextOptions), typeof(RenderOptions), typeof(VirtualizingPanel), typeof(VirtualizingStackPanel), typeof(FocusManager), typeof(InputMethod), typeof(SpellCheck), typeof(TextSearch), typeof(Selector), typeof(Stylus), typeof(NameScope), typeof(Storyboard) })
                ScanType(owner, _ => { });
            AppDomain.CurrentDomain.AssemblyLoad += (_, args) => { lock (Gate) Pending.Enqueue(args.LoadedAssembly); };
            foreach (Assembly assembly in AppDomain.CurrentDomain.GetAssemblies()) Pending.Enqueue(assembly);
        }

        private static bool IsFramework(Assembly assembly)
        {
            byte[]? token = assembly.GetName().GetPublicKeyToken();
            string key = token == null ? "" : BitConverter.ToString(token).Replace("-", "");
            return key == "B77A5C561934E089" || key == "B03F5F7F11D50A3A" || key == "31BF3856AD364E35" || key == "7CEC85D7BEA7798E" || key == "CC7B13FFCD2DDD51";
        }

        internal static int ScanAssembly(Assembly assembly, Action<Exception> onFailure, int maxObjects, int maxMilliseconds)
        {
            var watch = Stopwatch.StartNew();
            Type?[] types;
            try { types = assembly.GetTypes(); }
            catch (ReflectionTypeLoadException ex) { types = ex.Types; onFailure(ex); }
            catch (Exception ex) { onFailure(ex); return 0; }
            int count = 0;
            foreach (Type? type in types)
            {
                if (count++ >= maxObjects || watch.ElapsedMilliseconds >= maxMilliseconds)
                {
                    incomplete = true;
                    onFailure(new TimeoutException("Attached-property discovery scan limit reached."));
                    return count;
                }
                if (type != null) ScanType(type, onFailure);
            }
            return count;
        }

        private static void ScanType(Type owner, Action<Exception> onFailure)
        {
            try
            {
                foreach (FieldInfo field in owner.GetFields(BindingFlags.Public | BindingFlags.Static | BindingFlags.DeclaredOnly))
                {
                    if (field.FieldType != typeof(DependencyProperty)) continue;
                    try
                    {
                        if (!(field.GetValue(null) is DependencyProperty property)) continue;
                        DependencyPropertyDescriptor? descriptor = null;
                        try { descriptor = DependencyPropertyDescriptor.FromProperty(property, owner); }
                        catch (ArgumentException) { }
                        string name = property.Name;
                        MethodInfo? getter = owner.GetMethod("Get" + name, BindingFlags.Public | BindingFlags.Static, null, new[] { typeof(DependencyObject) }, null);
                        MethodInfo? setter = owner.GetMethod("Set" + name, BindingFlags.Public | BindingFlags.Static, null, new[] { typeof(DependencyObject), property.PropertyType }, null);
                        if (descriptor?.IsAttached == true || (getter != null && setter != null)) Attached[property] = descriptor;
                    }
                    catch (Exception ex) { onFailure(ex); }
                }
            }
            catch (Exception ex) { onFailure(ex); }
        }

        internal static IReadOnlyList<DependencyEntry> Discover(DependencyObject target, Action<Exception> onFailure, bool includeNonLocalAttached = true)
        {
            var entries = new Dictionary<DependencyProperty, DependencyEntry>();
            try
            {
                LocalValueEnumerator local = target.GetLocalValueEnumerator();
                while (local.MoveNext())
                {
                    DependencyProperty property = local.Current.Property;
                    entries[property] = new DependencyEntry(property) { HasLocalValue = true };
                }
            }
            catch (Exception ex) { onFailure(ex); }
            try
            {
                foreach (PropertyDescriptor descriptor in TypeDescriptor.GetProperties(target))
                {
                    try
                    {
                        DependencyPropertyDescriptor? dpd = DependencyPropertyDescriptor.FromProperty(descriptor);
                        if (dpd == null) continue;
                        if (!entries.TryGetValue(dpd.DependencyProperty, out DependencyEntry? entry))
                        {
                            entry = new DependencyEntry(dpd.DependencyProperty);
                            entries.Add(dpd.DependencyProperty, entry);
                        }
                        entry.Descriptor = dpd;
                        entry.PropertyDescriptor = descriptor;
                    }
                    catch (Exception ex) { onFailure(ex); }
                }
            }
            catch (Exception ex) { onFailure(ex); }
            lock (Gate)
            {
                var watch = Stopwatch.StartNew();
                int remaining = ProtocolLimits.ScanMaxObjects;
                while (Pending.Count > 0 && remaining > 0 && watch.ElapsedMilliseconds < ProtocolLimits.ScanMaxMs)
                {
                    Assembly assembly = Pending.Dequeue();
                    if (!Seen.Add(assembly) || IsFramework(assembly) || assembly.IsDynamic) continue;
                    remaining -= ScanAssembly(assembly, onFailure, remaining, Math.Max(1, ProtocolLimits.ScanMaxMs - (int)watch.ElapsedMilliseconds));
                }
                if (Pending.Count > 0 || incomplete) onFailure(new TimeoutException("Attached-property discovery scan limit reached."));
                foreach (var pair in Attached)
                {
                    try
                    {
                        if (entries.TryGetValue(pair.Key, out DependencyEntry? existing))
                        {
                            existing.IsAttached = true;
                            if (existing.Descriptor == null) existing.Descriptor = pair.Value;
                        }
                        else if (includeNonLocalAttached && DependencyPropertyHelper.GetValueSource(target, pair.Key).BaseValueSource != BaseValueSource.Default)
                            entries.Add(pair.Key, new DependencyEntry(pair.Key) { Descriptor = pair.Value, IsAttached = true });
                    }
                    catch (Exception ex) { onFailure(ex); }
                }
            }
            return new List<DependencyEntry>(entries.Values);
        }
    }

    internal sealed class DependencyEntry
    {
        internal DependencyEntry(DependencyProperty property) { Property = property; }
        internal DependencyProperty Property { get; }
        internal bool HasLocalValue { get; set; }
        internal bool IsAttached { get; set; }
        internal DependencyPropertyDescriptor? Descriptor { get; set; }
        internal PropertyDescriptor? PropertyDescriptor { get; set; }
        internal JsonObjectNode Metadata(Type targetType)
        {
            var result = new JsonObjectNode();
            result.Add("ownerType", new JsonStringNode(Declaration.TypeName(Property.OwnerType)));
            result.Add("ownerAssembly", new JsonStringNode(Declaration.AssemblyName(Property.OwnerType)));
            result.Add("propertyType", new JsonStringNode(Declaration.TypeName(Property.PropertyType)));
            result.Add("readOnly", new JsonBoolNode(Property.ReadOnly));
            result.Add("hasLocalValue", new JsonBoolNode(HasLocalValue));
            result.Add("isAttached", new JsonStringNode(IsAttached || Descriptor?.IsAttached == true ? "true" : Descriptor == null ? "unknown" : "false"));
            var flags = new JsonArrayNode();
            if (Property.GetMetadata(targetType) is FrameworkPropertyMetadata metadata)
            {
                if (metadata.AffectsMeasure) flags.Add(new JsonStringNode("AffectsMeasure"));
                if (metadata.AffectsArrange) flags.Add(new JsonStringNode("AffectsArrange"));
                if (metadata.AffectsParentMeasure) flags.Add(new JsonStringNode("AffectsParentMeasure"));
                if (metadata.AffectsParentArrange) flags.Add(new JsonStringNode("AffectsParentArrange"));
                if (metadata.AffectsRender) flags.Add(new JsonStringNode("AffectsRender"));
                if (metadata.Inherits) flags.Add(new JsonStringNode("Inherits"));
                if (metadata.OverridesInheritanceBehavior) flags.Add(new JsonStringNode("OverridesInheritanceBehavior"));
                if (!metadata.IsDataBindingAllowed) flags.Add(new JsonStringNode("NotDataBindable"));
                if (metadata.BindsTwoWayByDefault) flags.Add(new JsonStringNode("BindsTwoWayByDefault"));
                if (metadata.Journal) flags.Add(new JsonStringNode("Journal"));
                if (metadata.SubPropertiesDoNotAffectRender) flags.Add(new JsonStringNode("SubPropertiesDoNotAffectRender"));
            }
            result.Add("metadataFlags", flags);
            return result;
        }
        internal string Key => "dependencyProperty|" + Declaration.AssemblyName(Property.OwnerType) + "|" + Declaration.TypeName(Property.OwnerType) + "|" + Property.Name;
    }
}
