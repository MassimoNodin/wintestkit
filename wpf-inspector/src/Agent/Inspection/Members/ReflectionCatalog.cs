using System;
using System.Collections.Generic;
using System.Reflection;
using System.Runtime.CompilerServices;

namespace WinTestKit.Inspector.Agent.Inspection.Members
{
    // Only immutable reflection declarations are cached. Descriptor and dependency-property
    // discovery are deliberately per instance and must never enter this cache.
    internal static class ReflectionCatalog
    {
        private static readonly ConditionalWeakTable<Type, Declaration[]> Cache = new ConditionalWeakTable<Type, Declaration[]>();

        internal static Declaration[] Get(Type type) => Cache.GetValue(type, Build);

        private static Declaration[] Build(Type type)
        {
            var result = new List<Declaration>();
            var overrides = new Dictionary<MethodInfo, int>();
            for (Type? current = type; current != null; current = current.BaseType)
            {
                const BindingFlags flags = BindingFlags.DeclaredOnly | BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
                foreach (PropertyInfo property in current.GetProperties(flags))
                {
                    MethodInfo? accessor = property.GetGetMethod(true) ?? property.GetSetMethod(true);
                    if (accessor != null && accessor.IsVirtual)
                    {
                        MethodInfo baseDefinition = accessor.GetBaseDefinition();
                        if (overrides.TryGetValue(baseDefinition, out int index))
                        {
                            Declaration effective = result[index];
                            var bases = new List<PropertyInfo>(effective.BaseProperties) { property };
                            result[index] = new Declaration(effective.Property!, bases.ToArray());
                            continue;
                        }
                        overrides.Add(baseDefinition, result.Count);
                    }
                    result.Add(new Declaration(property));
                }
                foreach (FieldInfo field in current.GetFields(flags)) result.Add(new Declaration(field));
            }
            return result.ToArray();
        }
    }

    internal sealed class Declaration
    {
        internal Declaration(PropertyInfo property, PropertyInfo[]? baseProperties = null)
        {
            BaseProperties = Array.AsReadOnly(baseProperties ?? Array.Empty<PropertyInfo>());
            Property = property;
            DeclaringType = property.DeclaringType!;
            Name = property.Name;
            ValueType = property.PropertyType;
            var parameters = property.GetIndexParameters();
            var names = new string[parameters.Length];
            for (int i = 0; i < parameters.Length; i++) names[i] = TypeName(parameters[i].ParameterType);
            Key = "clrProperty|" + AssemblyName(DeclaringType) + "|" + TypeName(DeclaringType) + "|" + Name + "|" + string.Join(",", names);
        }
        internal Declaration(FieldInfo field)
        {
            BaseProperties = Array.Empty<PropertyInfo>();
            Field = field;
            DeclaringType = field.DeclaringType!;
            Name = field.Name;
            ValueType = field.FieldType;
            Key = "clrField|" + AssemblyName(DeclaringType) + "|" + TypeName(DeclaringType) + "|" + Name;
        }
        internal PropertyInfo? Property { get; }
        internal FieldInfo? Field { get; }
        internal IReadOnlyList<PropertyInfo> BaseProperties { get; }
        internal Type DeclaringType { get; }
        internal Type ValueType { get; }
        internal string Name { get; }
        internal string Key { get; }
        internal static string TypeName(Type type) => type.FullName ?? string.Empty;
        internal static string AssemblyName(Type type) => type.Assembly.GetName().Name ?? string.Empty;
        internal static bool Unsupported(Type type)
        {
            if (type.IsPointer || type.IsByRef || type == typeof(TypedReference) || type == typeof(ArgIterator) || type == typeof(RuntimeArgumentHandle)) return true;
#if NET48
            foreach (CustomAttributeData attribute in CustomAttributeData.GetCustomAttributes(type))
                if (attribute.AttributeType.FullName == "System.Runtime.CompilerServices.IsByRefLikeAttribute") return true;
            return false;
#else
            return type.IsByRefLike || type.IsFunctionPointer;
#endif
        }
    }
}
