using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Threading;
using System.Windows;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Contracts;
using WinTestKit.Inspector.Protocol;
using MemberInfo = WinTestKit.Inspector.Protocol.MemberInfo;

namespace WinTestKit.Inspector.Agent.Inspection.Members
{
    public sealed class ObjectInspector : IObjectInspector
    {
        private readonly RedactionPolicy redaction;
        public ObjectInspector() : this(Array.Empty<string>()) { }
        public ObjectInspector(IEnumerable<string> extraRedactNames) { redaction = new RedactionPolicy(extraRedactNames ?? throw new ArgumentNullException(nameof(extraRedactNames))); }
        internal bool IsPathRedacted(IReadOnlyList<PathSegment> path) => path.Any(segment => redaction.Match(segment.Name) != null);
        public TypeInfoDto DescribeType(Type type) => TypeInfoBuilder.Build(type);

        public IReadOnlyList<MemberInfo> GetMembers(object target, List<Diagnostic> diagnostics)
        {
            var rows = new List<MemberInfo>();
            Type runtimeType = target.GetType();
            IReadOnlyList<AttributeInfo> typeAttributes = Attributes(new System.Reflection.MemberInfo[] { runtimeType }, diagnostics);
            foreach (string name in new[] { "Name", "FullName", "AssemblyName", "AssemblyQualifiedName", "BaseTypes" })
                rows.Add(new MemberInfo { MemberKey = "type:" + name, Name = name, Category = "typeMetadata", DeclaringType = Declaration.TypeName(runtimeType), DeclaredType = Declaration.TypeName(name == "BaseTypes" ? typeof(string[]) : typeof(string)), Visibility = "public", Readable = true, CompatibilityAlias = name == "FullName" ? "ClrFullClassName" : null, PathSegment = new PathSegment { Kind = "type", Name = name }, Attributes = typeAttributes });
            if (target.GetType().FullName == null) diagnostics.Add(new Diagnostic { Code = "missingFullName", Message = "The runtime type has no CLR full name.", Category = "type" });
            Declaration[] declarations = ReflectionCatalog.Get(target.GetType());
            foreach (Declaration d in declarations)
            {
                var getter = d.Property?.GetGetMethod(true);
                bool isPublic = d.Field != null ? d.Field.IsPublic : getter != null && getter.IsPublic;
                string? reason = d.Property != null && d.Property.GetIndexParameters().Length != 0 ? "indexer" : d.Property != null && getter == null ? "writeOnly" : !isPublic ? "nonPublic" : Declaration.Unsupported(d.ValueType) ? "unsupportedType" : null;
                var row = new MemberInfo { MemberKey = d.Key, Name = d.Name, Category = d.Property != null ? "clrProperty" : "clrField", DeclaringType = Declaration.TypeName(d.DeclaringType), DeclaredType = Declaration.TypeName(d.ValueType), Visibility = VisibilityOf(d.Field, getter ?? d.Property?.GetSetMethod(true)), Readable = reason == null, Reason = reason,
                    PathSegment = new PathSegment { Kind = d.Property != null ? "property" : "field", Name = d.Name, DeclaringType = Declaration.TypeName(d.DeclaringType), MemberKey = d.Key }, Attributes = Attributes(d, diagnostics) };
                rows.Add(row);
            }
            Action<Exception> failure = ex => diagnostics.Add(new Diagnostic { Code = "discoveryFailed", Message = ex.GetType().FullName ?? "Exception", Category = "descriptor" });
            foreach (DescriptorEntry descriptor in DescriptorCatalog.Discover(target, declarations, failure))
            {
                if (descriptor.Declaration != null)
                {
                    if (descriptor.Ambiguous)
                    {
                        MemberInfo row = rows.First(member => member.MemberKey == descriptor.Declaration.Key);
                        row.Readable = false;
                        row.Reason = "ambiguous";
                    }
                    continue;
                }
                string? reason = descriptor.Ambiguous ? "ambiguous" : Declaration.Unsupported(descriptor.PropertyType) ? "unsupportedType" : null;
                rows.Add(new MemberInfo { MemberKey = descriptor.Key, Name = descriptor.Name, Category = "clrProperty", DeclaringType = Declaration.TypeName(descriptor.ComponentType), DeclaredType = Declaration.TypeName(descriptor.PropertyType), Visibility = "public", Readable = reason == null, Reason = reason, PathSegment = new PathSegment { Kind = "property", Name = descriptor.Name, DeclaringType = Declaration.TypeName(descriptor.ComponentType), MemberKey = descriptor.Key } });
                diagnostics.Add(new Diagnostic { Code = "descriptorAttributesUnavailable", Message = "Descriptor-only attributes are not materialized.", Category = "attribute" });
            }
            if (target is DependencyObject dependencyObject)
                foreach (DependencyEntry entry in DependencyCatalog.Discover(dependencyObject, ex => diagnostics.Add(new Diagnostic { Code = "discoveryFailed", Message = ex.GetType().FullName ?? "Exception", Category = "dependency" })))
                {
                    try
                    {
                    DependencyProperty dp = entry.Property;
                    JsonObjectNode metadata = entry.Metadata(dependencyObject.GetType());
                    var wrapper = entry.Descriptor?.IsAttached == true ? null : declarations.FirstOrDefault(d => d.Property != null && d.Name == dp.Name && d.ValueType == dp.PropertyType && (d.DeclaringType == dp.OwnerType || (entry.Descriptor != null && d.DeclaringType == entry.Descriptor.ComponentType) || d.BaseProperties.Any(property => property.DeclaringType == dp.OwnerType)));
                    if (wrapper != null) { MemberInfo? row = rows.FirstOrDefault(r => r.MemberKey == wrapper.Key); if (row != null) row.WrapperKey = entry.Key; }
                    bool unsupported = Declaration.Unsupported(dp.PropertyType);
                    rows.Add(new MemberInfo { MemberKey = entry.Key, Name = dp.Name, Category = entry.Descriptor?.IsAttached == true ? "attachedProperty" : "dependencyProperty", DeclaringType = Declaration.TypeName(dp.OwnerType), DeclaredType = Declaration.TypeName(dp.PropertyType), Visibility = "public", Readable = !unsupported, Reason = unsupported ? "unsupportedType" : null, WrapperKey = wrapper?.Key, Dependency = metadata, PathSegment = new PathSegment { Kind = "dependency", Name = dp.Name, OwnerType = Declaration.TypeName(dp.OwnerType), OwnerAssembly = Declaration.AssemblyName(dp.OwnerType) } });
                    }
                    catch (Exception ex) { diagnostics.Add(new Diagnostic { Code = "discoveryFailed", Message = ex.GetType().FullName ?? "Exception", Category = "dependency" }); }
                }
            return rows.OrderBy(x => x.Category, StringComparer.Ordinal).ThenBy(x => x.Name, StringComparer.Ordinal).ThenBy(x => x.DeclaringType, StringComparer.Ordinal).ThenBy(x => x.MemberKey, StringComparer.Ordinal).ToArray();
        }
        private static IReadOnlyList<AttributeInfo> Attributes(Declaration d, List<Diagnostic> diagnostics)
        {
            var sources = new List<System.Reflection.MemberInfo> { (System.Reflection.MemberInfo?)d.Property ?? d.Field! };
            sources.AddRange(d.BaseProperties);
            return Attributes(sources, diagnostics);
        }
        private static IReadOnlyList<AttributeInfo> Attributes(IEnumerable<System.Reflection.MemberInfo> sources, List<Diagnostic> diagnostics)
        {
            var result = new List<AttributeInfo>();
            foreach (System.Reflection.MemberInfo source in sources)
            try
            {
                IList<CustomAttributeData> data = CustomAttributeData.GetCustomAttributes(source);
                foreach (CustomAttributeData attribute in data.Take(32 - result.Count))
                {
                    try
                    {
                    var args = new List<JsonNode>(); foreach (var arg in attribute.ConstructorArguments.Take(32)) args.Add(AttributeLiterals.Convert(arg));
                    var named = new JsonObjectNode(); foreach (var arg in attribute.NamedArguments.Take(32)) named.Add(arg.MemberName, AttributeLiterals.Convert(arg.TypedValue));
                    result.Add(new AttributeInfo { TypeName = Declaration.TypeName(attribute.AttributeType), ConstructorArguments = args, NamedArguments = named });
                    }
                    catch (Exception ex) { diagnostics.Add(new Diagnostic { Code = "attributeFailed", Message = ex.GetType().FullName ?? "Exception", Category = "attribute" }); }
                }
            }
            catch (Exception ex) { diagnostics.Add(new Diagnostic { Code = "attributeFailed", Message = ex.GetType().FullName ?? "Exception", Category = "attribute" }); }
            return result;
        }
        private static string VisibilityOf(FieldInfo? field, MethodInfo? method)
        {
            if (field != null) return field.IsPublic ? "public" : field.IsFamilyOrAssembly ? "protectedInternal" : field.IsFamilyAndAssembly ? "privateProtected" : field.IsFamily ? "protected" : field.IsAssembly ? "internal" : "private";
            if (method == null) return "private";
            return method.IsPublic ? "public" : method.IsFamilyOrAssembly ? "protectedInternal" : method.IsFamilyAndAssembly ? "privateProtected" : method.IsFamily ? "protected" : method.IsAssembly ? "internal" : "private";
        }
        public ValueDto ReadPath(object root, IReadOnlyList<PathSegment> path, IObjectRegistry registry, Dispatcher dispatcher, CancellationToken ct)
        {
            if (path.Count == 0 || path.Count > ProtocolLimits.MaxPathSegments || (path.Count != 1 && path.Any(x => x.Kind == "type"))) throw new ProtocolException(ErrorCodes.InvalidParams, "Invalid path");
            foreach (PathSegment segment in path) segment.ToJson();
            PathSegment first = path[0];
            if (first.Kind == "property" && ReflectionCatalog.Get(root.GetType()).Any(declaration =>
                declaration.Name == first.Name && RedactionPolicy.IsPasswordIdentity(declaration.DeclaringType, declaration.Name) &&
                (first.MemberKey == null || first.MemberKey == declaration.Key) &&
                (first.DeclaringType == null || first.DeclaringType == Declaration.TypeName(declaration.DeclaringType))))
                return new ValueDto { Status = "redacted", Kind = "unavailable", RedactionRule = "identity" };
            foreach (PathSegment segment in path)
            {
                string? rule = redaction.Match(segment.Name);
                if (rule != null) return new ValueDto { Status = "redacted", Kind = "unavailable", RedactionRule = rule };
            }
            if (RedactionPolicy.IsProtectedIdentity(root)) return new ValueDto { Status = "redacted", Kind = "unavailable", RedactionRule = "identity" };
            if (path[0].Kind == "type")
            {
                TypeInfoDto t = DescribeType(root.GetType());
                object value = path[0].Name == "Name" ? t.Name : path[0].Name == "FullName" ? t.FullName : path[0].Name == "AssemblyName" ? t.AssemblyName : path[0].Name == "AssemblyQualifiedName" ? t.AssemblyQualifiedName : path[0].Name == "BaseTypes" ? (object)t.BaseTypes.ToArray() : throw new ProtocolException(ErrorCodes.MemberNotFound, "Unknown type metadata");
                return ValueSerializer.Serialize(value, value.GetType(), registry, dispatcher);
            }
            object? current = root;
            var ancestors = new HashSet<object>(ReferenceComparer.Instance) { root };
            Type declared = root.GetType();
            DependencySourceDto? dependencySource = null;
            for (int i = 0; i < path.Count; i++)
            {
                ct.ThrowIfCancellationRequested();
                if (RedactionPolicy.IsProtectedIdentity(current!)) return new ValueDto { Status = "redacted", Kind = "unavailable", RedactionRule = "identity" };
                dependencySource = null;
                PathSegment segment = path[i];
                var diagnostics = new List<Diagnostic>();
                IReadOnlyList<MemberInfo> catalog = GetMembers(current!, diagnostics);
                IEnumerable<MemberInfo> matches = catalog.Where(row => row.Name == segment.Name && ((segment.Kind == "property" && row.Category == "clrProperty") || (segment.Kind == "field" && row.Category == "clrField") || (segment.Kind == "dependency" && (row.Category == "dependencyProperty" || row.Category == "attachedProperty"))));
                if (segment.MemberKey != null) matches = matches.Where(row => row.MemberKey == segment.MemberKey);
                if (segment.DeclaringType != null) matches = matches.Where(row => row.DeclaringType == segment.DeclaringType);
                if (segment.Kind == "dependency") matches = matches.Where(row => row.PathSegment?.OwnerType == segment.OwnerType && row.PathSegment?.OwnerAssembly == segment.OwnerAssembly);
                MemberInfo[] found = matches.ToArray();
                if (found.Length == 0) throw new ProtocolException(ErrorCodes.MemberNotFound, "Member was not found");
                if (found.Length != 1) throw new ProtocolException(ErrorCodes.MemberAmbiguous, "Member is ambiguous");
                MemberInfo selected = found[0];
                Declaration? declaration = ReflectionCatalog.Get(current!.GetType()).FirstOrDefault(d => d.Key == selected.MemberKey);
                if (declaration != null && RedactionPolicy.IsPasswordIdentity(declaration.DeclaringType, declaration.Name)) return new ValueDto { Status = "redacted", Kind = "unavailable", RedactionRule = "identity" };
                if (!selected.Readable) return new ValueDto { Status = selected.Reason == "unsupportedType" ? "unsupported" : "notReadable", Kind = "unavailable", DeclaredType = selected.DeclaredType };
                try
                {
                    object? next;
                    if (segment.Kind == "dependency" && current is DependencyObject dep)
                    {
                        DependencyEntry entry = DependencyCatalog.Discover(dep, _ => { }).First(x => x.Key == selected.MemberKey);
                        declared = entry.Property.PropertyType; next = dep.GetValue(entry.Property);
                        ValueSource source = DependencyPropertyHelper.GetValueSource(dep, entry.Property);
                        dependencySource = new DependencySourceDto { BaseValueSource = Enum.GetName(typeof(BaseValueSource), source.BaseValueSource)!, IsExpression = source.IsExpression, IsAnimated = source.IsAnimated, IsCoerced = source.IsCoerced, IsCurrent = source.IsCurrent };
                    }
                    else if (declaration != null)
                    {
                        declared = declaration.ValueType;
                        next = declaration.Property != null ? declaration.Property.GetValue(current, null) : declaration.Field!.GetValue(current);
                    }
                    else
                    {
                        DescriptorEntry descriptor = DescriptorCatalog.Discover(current, ReflectionCatalog.Get(current.GetType()), _ => { }).First(x => x.Key == selected.MemberKey);
                        declared = descriptor.Descriptor.PropertyType; next = descriptor.Descriptor.GetValue(current);
                    }
                    if (next == null && i < path.Count - 1) return new ValueDto { Status = "nullIntermediate", Kind = "unavailable", DeclaredType = Declaration.TypeName(declared), FailedSegment = i };
                    current = next;
                    if (current != null && !current.GetType().IsValueType && !(current is string))
                    {
                        if (ancestors.Contains(current)) return new ValueDto { Status = "cycle", Kind = "object", DeclaredType = Declaration.TypeName(declared), RuntimeType = Declaration.TypeName(current.GetType()), CycleTo = registry.Register(current, dispatcher, DescribeType(current.GetType())), DependencySource = dependencySource };
                        if (i < path.Count - 1) ancestors.Add(current);
                    }
                }
                catch (Exception ex)
                {
                    Exception actual = ex is TargetInvocationException invocation && invocation.InnerException != null ? invocation.InnerException : ex;
                    return new ValueDto { Status = "exception", Kind = "unavailable", DeclaredType = Declaration.TypeName(declared), Message = actual.GetType().FullName, FailedSegment = i };
                }
            }
            ValueDto result = ValueSerializer.Serialize(current, declared, registry, dispatcher);
            if (result.Status == ValueStatus.Ok || result.Status == ValueStatus.Truncated) result.DependencySource = dependencySource;
            return result;
        }
        public IReadOnlyList<BindingInfoDto> GetBindings(object target, IReadOnlyList<string> memberKeys)
        {
            var result = new List<BindingInfoDto>();
            if (memberKeys.Count != 0 && RedactionPolicy.IsProtectedIdentity(target))
                throw new ProtocolException(ErrorCodes.AccessDenied, "Binding metadata is unavailable under the redaction policy");
            if (!(target is DependencyObject dep))
            {
                if (memberKeys.Count != 0) throw new ProtocolException(ErrorCodes.MemberNotFound, "Dependency property was not found");
                return result;
            }
            var entries = DependencyCatalog.Discover(dep, _ => { });
            foreach (string key in memberKeys)
            {
                DependencyEntry? entry = entries.FirstOrDefault(x => x.Key == key);
                if (entry == null) throw new ProtocolException(ErrorCodes.MemberNotFound, "Dependency property was not found");
                if (redaction.Match(entry.Property.Name) != null)
                    throw new ProtocolException(ErrorCodes.AccessDenied, "Binding metadata is unavailable under the redaction policy");
                result.Add(ToBinding(key, BindingMetadataReader.Read(dep, entry.Property, redaction)));
            }
            return result;
        }
        private static BindingInfoDto ToBinding(string key, BindingMetadata metadata)
        {
            var result = new BindingInfoDto { MemberKey = key, Kind = metadata.Kind, Status = metadata.Status, Mode = metadata.Mode, UpdateSourceTrigger = metadata.Trigger, Path = metadata.Path, ElementName = metadata.ElementName, SourceType = metadata.SourceType, ConverterType = metadata.ConverterType };
            if (metadata.RelativeMode != null)
            {
                var relative = new JsonObjectNode(); relative.Add("mode", new JsonStringNode(metadata.RelativeMode));
                if (metadata.AncestorType != null) relative.Add("ancestorType", new JsonStringNode(metadata.AncestorType));
                if (metadata.AncestorLevel.HasValue) relative.Add("ancestorLevel", JsonNumberNode.From(metadata.AncestorLevel.Value));
                result.RelativeSource = relative;
            }
            if (metadata.ValidationErrors.Count != 0) result.ValidationErrors = metadata.ValidationErrors.ToArray();
            if (metadata.Children.Count != 0) result.Children = metadata.Children.Select(x => ToBinding(key, x)).ToArray();
            return result;
        }
        private sealed class ReferenceComparer : IEqualityComparer<object>
        {
            internal static readonly ReferenceComparer Instance = new ReferenceComparer();
            public new bool Equals(object? x, object? y) => ReferenceEquals(x, y);
            public int GetHashCode(object obj) => System.Runtime.CompilerServices.RuntimeHelpers.GetHashCode(obj);
        }
    }
}
