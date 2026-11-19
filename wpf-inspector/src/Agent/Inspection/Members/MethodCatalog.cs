using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;

namespace WinTestKit.Inspector.Agent.Inspection.Members
{
    internal static class MethodCatalog
    {
        internal static IReadOnlyList<MethodMetadata> Get(Type type)
        {
            if (type == null) throw new ArgumentNullException(nameof(type));
            var methods = new List<MethodMetadata>();
            const BindingFlags flags = BindingFlags.DeclaredOnly | BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
            for (Type? current = type; current != null; current = current.BaseType)
                methods.AddRange(current.GetMethods(flags)
                    .Select(method => new MethodMetadata(method, type))
                    .OrderBy(method => method.Key, StringComparer.Ordinal));
            return methods.AsReadOnly();
        }

        internal static string TypeKey(Type type)
        {
            if (type.IsByRef) return TypeKey(type.GetElementType()!) + "&";
            if (type.IsPointer) return TypeKey(type.GetElementType()!) + "*";
            if (type.IsArray) return TypeKey(type.GetElementType()!) + (type.GetArrayRank() == 1 && type == type.GetElementType()!.MakeArrayType() ? "[]" : "[" + new string(',', type.GetArrayRank() - 1) + "*]");
            if (type.IsGenericParameter) return (type.DeclaringMethod == null ? "!" : "!!") + type.GenericParameterPosition;
            if (type.IsGenericType)
            {
                Type definition = type.GetGenericTypeDefinition();
                Type[] arguments = type.GetGenericArguments();
                var keys = new string[arguments.Length];
                for (int index = 0; index < arguments.Length; index++) keys[index] = TypeKey(arguments[index]);
                return NamedTypeKey(definition) + "<" + string.Join(",", keys) + ">";
            }
            return NamedTypeKey(type);
        }

        private static string NamedTypeKey(Type type) => (type.Assembly.FullName ?? string.Empty) + ":" + (type.FullName ?? type.Name);
    }

    internal sealed class MethodMetadata
    {
        internal MethodMetadata(MethodInfo method, Type? targetType = null)
        {
            Method = method;
            Name = method.Name;
            DeclaringType = method.DeclaringType!;
            ReturnType = method.ReturnType;
            IsStatic = method.IsStatic;
            Visibility = method.IsPublic ? "public" : method.IsPrivate ? "private" : method.IsFamily ? "protected" : method.IsAssembly ? "internal" : method.IsFamilyOrAssembly ? "protected internal" : "private protected";
            ParameterInfo[] parameters = method.GetParameters();
            var metadata = new MethodParameterMetadata[parameters.Length];
            var parameterKeys = new string[parameters.Length];
            for (int index = 0; index < parameters.Length; index++)
            {
                metadata[index] = new MethodParameterMetadata(parameters[index]);
                parameterKeys[index] = MethodCatalog.TypeKey(parameters[index].ParameterType);
            }
            Parameters = Array.AsReadOnly(metadata);
            Key = "method|" + MethodCatalog.TypeKey(DeclaringType) + "|" + Name + "`" + method.GetGenericArguments().Length + "(" + string.Join(",", parameterKeys) + ")->" + MethodCatalog.TypeKey(ReturnType);
            if (method.ContainsGenericParameters) UnsupportedReason = "Open generic methods or declaring types are not supported.";
            else if (Declaration.Unsupported(ReturnType) || ReturnType.IsGenericParameter) UnsupportedReason = "The return type is not supported.";
            else if ((method.CallingConvention & CallingConventions.VarArgs) != 0 || parameters.Length > 16) UnsupportedReason = "The method signature is not supported.";
            else if (targetType != null && DispatchesElsewhere(method, targetType)) UnsupportedReason = "The virtual declaration dispatches to another method.";
            else
                foreach (ParameterInfo parameter in parameters)
                    if (parameter.IsOut || parameter.IsDefined(typeof(ParamArrayAttribute), false) || !SupportsArgument(parameter.ParameterType))
                    {
                        UnsupportedReason = "A parameter type is not supported.";
                        break;
                    }
        }

        internal static bool SupportsArgument(Type type) => type == typeof(string) || type == typeof(bool) || type == typeof(int) || type == typeof(long) || type == typeof(float) || type == typeof(double) || type == typeof(decimal) || type.IsEnum;

        private static bool DispatchesElsewhere(MethodInfo method, Type targetType)
        {
            if (!method.IsVirtual || method.IsFinal || method.IsStatic) return false;
            MethodInfo root = method.GetBaseDefinition();
            const BindingFlags flags = BindingFlags.DeclaredOnly | BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
            for (Type? current = targetType; current != null && current != method.DeclaringType; current = current.BaseType)
                foreach (MethodInfo candidate in current.GetMethods(flags))
                    if (candidate.IsVirtual && candidate.GetBaseDefinition() == root) return true;
            return false;
        }

        internal MethodInfo Method { get; }
        internal string Key { get; }
        internal string Name { get; }
        internal Type DeclaringType { get; }
        internal Type ReturnType { get; }
        internal string Visibility { get; }
        internal bool IsStatic { get; }
        internal IReadOnlyList<MethodParameterMetadata> Parameters { get; }
        internal string? UnsupportedReason { get; }
    }

    internal sealed class MethodParameterMetadata
    {
        internal MethodParameterMetadata(ParameterInfo parameter)
        {
            Name = parameter.Name ?? string.Empty;
            ParameterType = parameter.ParameterType;
            IsOut = parameter.IsOut;
        }

        internal string Name { get; }
        internal Type ParameterType { get; }
        internal bool IsOut { get; }
    }
}
