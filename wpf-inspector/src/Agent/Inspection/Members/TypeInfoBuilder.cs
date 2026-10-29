using System;
using System.Collections.Generic;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Inspection.Members
{
    internal static class TypeInfoBuilder
    {
        internal static TypeInfoDto Build(Type type)
        {
            var bases = new List<string>();
            for (Type? current = type.BaseType; current != null; current = current.BaseType)
                bases.Add(current.FullName ?? string.Empty);
            return new TypeInfoDto
            {
                Name = type.Name,
                FullName = type.FullName ?? string.Empty,
                AssemblyName = type.Assembly.GetName().Name ?? string.Empty,
                AssemblyQualifiedName = type.AssemblyQualifiedName ?? string.Empty,
                BaseTypes = bases
            };
        }
    }
}
