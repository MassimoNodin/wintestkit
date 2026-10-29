using System;
using System.Collections.Generic;
using System.ComponentModel;

namespace WinTestKit.Inspector.Agent.Inspection.Members
{
    internal sealed class DescriptorEntry
    {
        internal DescriptorEntry(PropertyDescriptor descriptor)
        {
            Descriptor = descriptor;
            Type component = descriptor.ComponentType;
            ComponentType = component;
            Name = descriptor.Name;
            PropertyType = descriptor.PropertyType;
            Key = "descriptorProperty|" + Declaration.AssemblyName(component) + "|" + Declaration.TypeName(component) + "|" + Name + "|" + Declaration.TypeName(PropertyType);
        }
        internal PropertyDescriptor Descriptor { get; }
        internal Type ComponentType { get; }
        internal Type PropertyType { get; }
        internal string Name { get; }
        internal string Key { get; }
        internal bool Ambiguous { get; set; }
        internal Declaration? Declaration { get; set; }
    }

    internal static class DescriptorCatalog
    {
        internal static IReadOnlyList<DescriptorEntry> Discover(object target, IReadOnlyList<Declaration> declarations, Action<Exception> onFailure)
        {
            var result = new List<DescriptorEntry>();
            var byKey = new Dictionary<string, DescriptorEntry>(StringComparer.Ordinal);
            try
            {
                foreach (PropertyDescriptor descriptor in TypeDescriptor.GetProperties(target))
                {
                    try
                    {
                        var entry = new DescriptorEntry(descriptor);
                        foreach (Declaration declaration in declarations)
                        {
                            if (declaration.Property != null && declaration.DeclaringType == entry.ComponentType && declaration.Name == entry.Name && declaration.ValueType == entry.PropertyType)
                            {
                                entry.Declaration = declaration;
                                break;
                            }
                        }
                        if (byKey.TryGetValue(entry.Key, out DescriptorEntry? previous))
                        {
                            previous.Ambiguous = true;
                            entry.Ambiguous = true;
                        }
                        else
                        {
                            byKey.Add(entry.Key, entry);
                            result.Add(entry);
                        }
                    }
                    catch (Exception ex) { onFailure(ex); }
                }
            }
            catch (Exception ex) { onFailure(ex); }
            return result;
        }
    }
}
