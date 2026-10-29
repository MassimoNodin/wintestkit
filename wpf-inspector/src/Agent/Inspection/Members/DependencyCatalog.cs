using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Windows;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Inspection.Members
{
    // This is built on the target Dispatcher for each snapshot. It does not touch the
    // private global dependency-property registry or evaluate property values.
    internal static class DependencyCatalog
    {
        internal static IReadOnlyList<DependencyEntry> Discover(DependencyObject target, Action<Exception> onFailure)
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
            return new List<DependencyEntry>(entries.Values);
        }
    }

    internal sealed class DependencyEntry
    {
        internal DependencyEntry(DependencyProperty property) { Property = property; }
        internal DependencyProperty Property { get; }
        internal bool HasLocalValue { get; set; }
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
            result.Add("isAttached", new JsonStringNode(Descriptor == null ? "unknown" : Descriptor.IsAttached ? "true" : "false"));
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
