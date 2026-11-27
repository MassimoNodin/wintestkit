using System;
using System.Collections;
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

        /// <summary>
        /// The x:Name of a FrameworkElement or FrameworkContentElement for tree identity, with the protection and redaction
        /// checks a <c>property Name</c> read applies; null when it is empty, protected, redacted or too long to return whole.
        /// Reading the property directly skips building the object's member catalog, which costs about 7 ms per element.
        /// </summary>
        internal string? IdentityName(object target)
        {
            if (!(target is FrameworkElement) && !(target is FrameworkContentElement)) return null;
            if (redaction.Match("Name") != null || RedactionPolicy.IsProtectedIdentity(target)) return null;
            string name = target is FrameworkElement element ? element.Name : ((FrameworkContentElement)target).Name;
            if (string.IsNullOrEmpty(name)) return null;
            ScalarText.Prefix(name, ProtocolLimits.MaxScalarChars, out int length);
            return length > ProtocolLimits.MaxScalarChars ? null : name;
        }
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
                var row = new MemberInfo { MemberKey = d.Key, Name = d.Name, Category = d.Property != null ? (d.IsStatic ? "staticProperty" : "clrProperty") : (d.IsStatic ? "staticField" : "clrField"), DeclaringType = Declaration.TypeName(d.DeclaringType), DeclaredType = Declaration.TypeName(d.ValueType), Visibility = VisibilityOf(d.Field, getter ?? d.Property?.GetSetMethod(true)), Readable = reason == null, Reason = reason,
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
                    var wrapper = (entry.IsAttached || entry.Descriptor?.IsAttached == true) ? null : declarations.FirstOrDefault(d => d.Property != null && d.Name == dp.Name && d.ValueType == dp.PropertyType && (d.DeclaringType == dp.OwnerType || (entry.Descriptor != null && d.DeclaringType == entry.Descriptor.ComponentType) || d.BaseProperties.Any(property => property.DeclaringType == dp.OwnerType)));
                    if (wrapper != null) { MemberInfo? row = rows.FirstOrDefault(r => r.MemberKey == wrapper.Key); if (row != null) row.WrapperKey = entry.Key; }
                    bool unsupported = Declaration.Unsupported(dp.PropertyType);
                    rows.Add(new MemberInfo { MemberKey = entry.Key, Name = dp.Name, Category = (entry.IsAttached || entry.Descriptor?.IsAttached == true) ? "attachedProperty" : "dependencyProperty", DeclaringType = Declaration.TypeName(dp.OwnerType), DeclaredType = Declaration.TypeName(dp.PropertyType), Visibility = "public", Readable = !unsupported, Reason = unsupported ? "unsupportedType" : null, WrapperKey = wrapper?.Key, Dependency = metadata, PathSegment = new PathSegment { Kind = "dependency", Name = dp.Name, OwnerType = Declaration.TypeName(dp.OwnerType), OwnerAssembly = Declaration.AssemblyName(dp.OwnerType) } });
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
            => ReadPathCore(root, path, registry, dispatcher, ct, false, null, null);

        internal ValueDto ReadPath(object root, IReadOnlyList<PathSegment> path, IObjectRegistry registry, Dispatcher dispatcher, CancellationToken ct, bool protectedRoot)
            => ReadPathCore(root, path, registry, dispatcher, ct, false, protectedRoot, null);

        /// <summary>Query evaluation: the path was validated when the query was compiled, and results below an intermediate object are shared through <paramref name="memo"/>.</summary>
        internal ValueDto ReadPath(object root, IReadOnlyList<PathSegment> path, IObjectRegistry registry, Dispatcher dispatcher, CancellationToken ct, bool protectedRoot, PathMemo memo)
            => ReadPathCore(root, path, registry, dispatcher, ct, false, protectedRoot, memo);

        public ValueDto ReadSpyField(object root, IReadOnlyList<PathSegment> path, IObjectRegistry registry, Dispatcher dispatcher, CancellationToken ct)
        {
            if (path.Count != 1 || path[0].Kind != "field" || string.IsNullOrEmpty(path[0].MemberKey) || string.IsNullOrEmpty(path[0].DeclaringType))
                throw new ProtocolException(ErrorCodes.InvalidParams, "Spy field reads require one exact field");
            return ReadPathCore(root, path, registry, dispatcher, ct, true, null, null);
        }

        /// <summary>Largest sequence position reachable by enumerating a collection that has no indexer.</summary>
        internal const int MaxEnumeratedIndex = 10000;
        internal const string IndexOutOfRangeText = "index out of range";

        /// <summary>The runtime type's metadata facet <paramref name="name"/>; read without building the whole type description.</summary>
        internal static object TypeFacet(Type type, string name)
        {
            switch (name)
            {
                case "Name": return type.Name;
                case "FullName": return type.FullName ?? string.Empty;
                case "AssemblyName": return type.Assembly.GetName().Name ?? string.Empty;
                case "AssemblyQualifiedName": return type.AssemblyQualifiedName ?? string.Empty;
                case "BaseTypes": return TypeInfoBuilder.Build(type).BaseTypes.ToArray();
                default: throw new ProtocolException(ErrorCodes.MemberNotFound, "Unknown type metadata");
            }
        }

        /// <summary>Splits <c>Name[3]</c> into its member name and index; the name is unchanged when there is no indexer.</summary>
        internal static bool TryParseIndexer(string text, out string name, out int index)
        {
            name = text; index = 0;
            int bracket = text.IndexOf('[');
            if (bracket < 0) return false;
            if (bracket == 0 || !text.EndsWith("]", StringComparison.Ordinal) ||
                !int.TryParse(text.Substring(bracket + 1, text.Length - bracket - 2), System.Globalization.NumberStyles.AllowLeadingSign, System.Globalization.CultureInfo.InvariantCulture, out index))
                throw new ProtocolException(ErrorCodes.InvalidParams, "Invalid index");
            name = text.Substring(0, bracket);
            return true;
        }

        private ValueDto ReadPathCore(object root, IReadOnlyList<PathSegment> path, IObjectRegistry registry, Dispatcher dispatcher, CancellationToken ct, bool spyField, bool? knownProtectedRoot, PathMemo? memo)
        {
            if (memo == null)
            {
                if (path.Count == 0 || path.Count > ProtocolLimits.MaxPathSegments || (path.Count != 1 && (path.Any(x => x.Kind == "uia") || path.Take(path.Count - 1).Any(x => x.Kind == "type")))) throw new ProtocolException(ErrorCodes.InvalidParams, "Invalid path");
                foreach (PathSegment segment in path) segment.ToJson();
            }
            PathSegment first = path[0];
            if (first.Kind == "property" && ReflectionCatalog.Get(root.GetType()).Any(declaration =>
                declaration.Name == first.Name && RedactionPolicy.IsPasswordIdentity(declaration.DeclaringType, declaration.Name) &&
                (first.MemberKey == null || first.MemberKey == declaration.Key) &&
                (first.DeclaringType == null || first.DeclaringType == Declaration.TypeName(declaration.DeclaringType))))
                return new ValueDto { Status = "redacted", Kind = "unavailable", RedactionRule = "identity" };
            foreach (PathSegment segment in path)
            {
                string? rule = segment.Kind == "uia" && (segment.Name == "is_password" || segment.Name == "supported_patterns") ? null : redaction.Match(segment.Name);
                if (rule != null) return new ValueDto { Status = "redacted", Kind = "unavailable", RedactionRule = rule };
            }
            if (first.Kind == "uia" && WinFormsNative.IsWinFormsObject(root)) return WinFormsNative.ReadUia(root, first.Name, registry, dispatcher);
            if (first.Kind == "uia")
            {
                try { if (!(root is DependencyObject dependency) || (first.Name != "automation_id" && PeerIdentity.GetPeer(dependency) == null)) return new ValueDto { Status = "unavailable", Kind = "unavailable" }; }
                catch (Exception) { return new ValueDto { Status = "exception", Kind = "unavailable", FailedSegment = 0 }; }
                return PeerIdentity.Read(root, first.Name, registry, dispatcher);
            }
            bool protectedRoot = knownProtectedRoot ?? RedactionPolicy.IsProtectedIdentity(root);
            if (protectedRoot && path[0].Kind == "type" && !RedactionPolicy.IsAllowedOnProtected(path, null)) return new ValueDto { Status = "redacted", Kind = "unavailable", RedactionRule = "identity" };
            if (path[0].Kind == "type")
            {
                object value = TypeFacet(root.GetType(), path[0].Name);
                return ValueSerializer.Serialize(value, value.GetType(), registry, dispatcher);
            }
            if (memo == null || path.Count == 1) return ReadPathLoop(root, path, registry, dispatcher, ct, spyField, protectedRoot, null);
            ValueDto result;
            try { result = ReadPathLoop(root, path, registry, dispatcher, ct, spyField, protectedRoot, memo); }
            catch (ProtocolException error) when (error.Code == ErrorCodes.MemberNotFound || error.Code == ErrorCodes.MemberAmbiguous)
            {
                memo.Complete(null, error);
                throw;
            }
            catch (Exception) { memo.Abandon(); throw; }
            memo.Complete(result, null);
            return result;
        }

        private ValueDto ReadPathLoop(object root, IReadOnlyList<PathSegment> path, IObjectRegistry registry, Dispatcher dispatcher, CancellationToken ct, bool spyField, bool protectedRoot, PathMemo? memo)
        {
            object? current = root;
            HashSet<object>? ancestors = null;
            Type declared = root.GetType();
            DependencySourceDto? dependencySource = null;
            for (int i = 0; i < path.Count; i++)
            {
                ct.ThrowIfCancellationRequested();
                if (path[i].Kind == "type")
                {
                    if (RedactionPolicy.IsProtectedIdentity(current!)) return new ValueDto { Status = "redacted", Kind = "unavailable", RedactionRule = "identity" };
                    object value = TypeFacet(current!.GetType(), path[i].Name);
                    return ValueSerializer.Serialize(value, value.GetType(), registry, dispatcher);
                }
                if (memo != null && i > 0 && !(current is string) && !current!.GetType().IsValueType)
                {
                    PathMemo.Entry? cached = memo.Lookup(current, i);
                    if (cached != null)
                    {
                        if (cached.Error != null) throw cached.Error;
                        return cached.Value!;
                    }
                    memo.Track(current, i);
                }
                bool protectedIdentity = i == 0 ? protectedRoot : RedactionPolicy.IsProtectedIdentity(current!);
                if (protectedIdentity && (path.Count != 1 || (path[0].Kind != "property" && path[0].Kind != "dependency"))) return new ValueDto { Status = "redacted", Kind = "unavailable", RedactionRule = "identity" };
                dependencySource = null;
                PathSegment segment = path[i];
                int? index = null;
                if (segment.Name.IndexOf('[') >= 0)
                {
                    TryParseIndexer(segment.Name, out string memberName, out int parsed);
                    index = parsed;
                    segment = new PathSegment { Kind = segment.Kind, Name = memberName, DeclaringType = segment.DeclaringType, MemberKey = segment.MemberKey, OwnerType = segment.OwnerType, OwnerAssembly = segment.OwnerAssembly };
                }
                if (protectedIdentity)
                {
                    Declaration[] candidates = ReflectionCatalog.Get(current!.GetType()).Where(item => item.Name == segment.Name && item.Property != null &&
                        (segment.MemberKey == null || segment.MemberKey == item.Key) &&
                        (segment.DeclaringType == null || segment.DeclaringType == Declaration.TypeName(item.DeclaringType))).ToArray();
                    if (segment.Kind == "property" && (candidates.Length != 1 || !RedactionPolicy.IsAllowedOnProtected(path, candidates[0])) ||
                        segment.Kind == "dependency" && !RedactionPolicy.IsAllowedOnProtected(path, null))
                        return new ValueDto { Status = "redacted", Kind = "unavailable", RedactionRule = "identity" };
                }
                MemberInfo? selected = null;
                Declaration? declaration = null;
                if (!protectedIdentity && !spyField && (segment.Kind == "property" || segment.Kind == "field") && !(current is System.ComponentModel.ICustomTypeDescriptor))
                {
                    StepPlan plan = PlanFor(current!.GetType(), segment);
                    if (plan.Kind == PlanKind.NoMember) throw new ProtocolException(ErrorCodes.MemberNotFound, "Member was not found");
                    if (plan.Kind == PlanKind.Declared) declaration = plan.Declaration;
                }
                if (declaration != null)
                {
                    if (RedactionPolicy.IsPasswordIdentity(declaration.DeclaringType, declaration.Name)) return new ValueDto { Status = "redacted", Kind = "unavailable", RedactionRule = "identity" };
                    string? reason = ReadabilityReason(declaration);
                    if (reason != null) return new ValueDto { Status = reason == "unsupportedType" ? "unsupported" : "notReadable", Kind = "unavailable", DeclaredType = Declaration.TypeName(declaration.ValueType) };
                }
                else
                {
                    var diagnostics = new List<Diagnostic>();
                    IReadOnlyList<MemberInfo> catalog = GetMembers(current!, diagnostics);
                    IEnumerable<MemberInfo> matches = catalog.Where(row => row.Name == segment.Name && ((segment.Kind == "property" && (row.Category == "clrProperty" || row.Category == "staticProperty")) || (segment.Kind == "field" && (row.Category == "clrField" || row.Category == "staticField")) || (segment.Kind == "dependency" && (row.Category == "dependencyProperty" || row.Category == "attachedProperty"))));
                    if (segment.MemberKey != null) matches = matches.Where(row => row.MemberKey == segment.MemberKey);
                    if (segment.DeclaringType != null) matches = matches.Where(row => row.DeclaringType == segment.DeclaringType);
                    if (segment.Kind == "dependency") matches = matches.Where(row => row.PathSegment?.OwnerType == segment.OwnerType && row.PathSegment?.OwnerAssembly == segment.OwnerAssembly);
                    MemberInfo[] found = matches.ToArray();
                    if (found.Length == 0) throw new ProtocolException(ErrorCodes.MemberNotFound, "Member was not found");
                    if (found.Length != 1) throw new ProtocolException(ErrorCodes.MemberAmbiguous, "Member is ambiguous");
                    selected = found[0];
                    declaration = ReflectionCatalog.Get(current!.GetType()).FirstOrDefault(d => d.Key == selected.MemberKey);
                    if (protectedIdentity && !RedactionPolicy.IsAllowedOnProtected(path, declaration)) return new ValueDto { Status = "redacted", Kind = "unavailable", RedactionRule = "identity" };
                    if (declaration != null && RedactionPolicy.IsPasswordIdentity(declaration.DeclaringType, declaration.Name)) return new ValueDto { Status = "redacted", Kind = "unavailable", RedactionRule = "identity" };
                    if (!selected.Readable && !(spyField && (selected.Category == "clrField" || selected.Category == "staticField") && selected.Reason == "nonPublic" && declaration?.Field != null && !Declaration.Unsupported(declaration.ValueType))) return new ValueDto { Status = selected.Reason == "unsupportedType" ? "unsupported" : "notReadable", Kind = "unavailable", DeclaredType = selected.DeclaredType };
                }
                try
                {
                    object? next;
                    if (segment.Kind == "dependency" && current is DependencyObject dep)
                    {
                        DependencyEntry entry = DependencyCatalog.Discover(dep, _ => { }).First(x => x.Key == selected!.MemberKey);
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
                        DescriptorEntry descriptor = DescriptorCatalog.Discover(current!, ReflectionCatalog.Get(current!.GetType()), _ => { }).First(x => x.Key == selected!.MemberKey);
                        declared = descriptor.Descriptor.PropertyType; next = descriptor.Descriptor.GetValue(current);
                    }
                    if (index.HasValue)
                    {
                        // An indexer applies to the member's value: null cannot be indexed, however the path ends.
                        if (next == null) return new ValueDto { Status = "nullIntermediate", Kind = "unavailable", DeclaredType = Declaration.TypeName(declared), FailedSegment = i };
                        next = ReadIndex(next, index.Value, ct);
                        declared = next?.GetType() ?? typeof(object);
                    }
                    if (next == null && i < path.Count - 1) return new ValueDto { Status = "nullIntermediate", Kind = "unavailable", DeclaredType = Declaration.TypeName(declared), FailedSegment = i };
                    current = next;
                    bool typeNext = i + 1 < path.Count && path[i + 1].Kind == "type";
                    if (current != null && !typeNext && !current.GetType().IsValueType && !(current is string))
                    {
                        if (ancestors == null) ancestors = new HashSet<object>(ReferenceComparer.Instance) { root };
                        if (ancestors.Contains(current)) return new ValueDto { Status = "cycle", Kind = "object", DeclaredType = Declaration.TypeName(declared), RuntimeType = Declaration.TypeName(current.GetType()), CycleTo = registry.Register(current, dispatcher, DescribeType(current.GetType())), DependencySource = dependencySource };
                        if (i < path.Count - 1) ancestors.Add(current);
                    }
                }
                catch (OperationCanceledException) { throw; }
                catch (Exception ex)
                {
                    Exception actual = ex is TargetInvocationException invocation && invocation.InnerException != null ? invocation.InnerException : ex;
                    return new ValueDto { Status = "exception", Kind = "unavailable", DeclaredType = Declaration.TypeName(declared), Message = actual.GetType().FullName, ErrorMessage = protectedIdentity ? null : ValueSerializer.ErrorMessage(actual), FailedSegment = i };
                }
            }
            ValueDto result = ValueSerializer.Serialize(current, declared, registry, dispatcher);
            if (result.Status == ValueStatus.Ok || result.Status == ValueStatus.Truncated) result.DependencySource = dependencySource;
            return result;
        }

        /// <summary>Why a declaration cannot be read, or null when it can.</summary>
        private static string? ReadabilityReason(Declaration d)
        {
            MethodInfo? getter = d.Property?.GetGetMethod(true);
            bool isPublic = d.Field != null ? d.Field.IsPublic : getter != null && getter.IsPublic;
            return d.Property != null && d.Property.GetIndexParameters().Length != 0 ? "indexer" : d.Property != null && getter == null ? "writeOnly" : !isPublic ? "nonPublic" : Declaration.Unsupported(d.ValueType) ? "unsupportedType" : null;
        }

        private enum PlanKind { Slow, NoMember, Declared }
        private sealed class StepPlan
        {
            internal StepPlan(PlanKind kind, Declaration? declaration) { Kind = kind; Declaration = declaration; }
            internal PlanKind Kind { get; }
            internal Declaration? Declaration { get; }
        }
        private readonly Dictionary<Tuple<Type, string, string, string?, string?>, StepPlan> plans = new Dictionary<Tuple<Type, string, string, string?, string?>, StepPlan>();

        /// <summary>How one property or field segment resolves on a type; cached so repeated reads skip member discovery.</summary>
        private StepPlan PlanFor(Type type, PathSegment segment)
        {
            var key = Tuple.Create(type, segment.Kind, segment.Name, segment.MemberKey, segment.DeclaringType);
            lock (plans) { if (plans.TryGetValue(key, out StepPlan? cached)) return cached; }
            StepPlan plan = BuildPlan(type, segment);
            lock (plans)
            {
                if (plans.Count >= 4096) plans.Clear();
                plans[key] = plan;
            }
            return plan;
        }

        private static StepPlan BuildPlan(Type type, PathSegment segment)
        {
            Declaration[] found = ReflectionCatalog.Get(type).Where(d => d.Name == segment.Name &&
                (segment.Kind == "property" ? d.Property != null : d.Field != null) &&
                (segment.MemberKey == null || segment.MemberKey == d.Key) &&
                (segment.DeclaringType == null || segment.DeclaringType == Declaration.TypeName(d.DeclaringType))).ToArray();
            if (found.Length == 1) return new StepPlan(PlanKind.Declared, found[0]);
            if (found.Length > 1) return new StepPlan(PlanKind.Slow, null);
            if (segment.Kind == "field") return new StepPlan(PlanKind.NoMember, null);
            try { return System.ComponentModel.TypeDescriptor.GetProperties(type)[segment.Name] == null ? new StepPlan(PlanKind.NoMember, null) : new StepPlan(PlanKind.Slow, null); }
            catch (Exception) { return new StepPlan(PlanKind.Slow, null); }
        }

        /// <summary>The element at <paramref name="index"/> of an array, list, default indexer or (bounded) sequence.</summary>
        private static object? ReadIndex(object value, int index, CancellationToken ct)
        {
            if (index < 0) throw new IndexOutOfRangeException(IndexOutOfRangeText);
            try
            {
                if (value is Array array)
                {
                    if (array.Rank != 1) throw new InvalidOperationException("multidimensional arrays are not indexable");
                    if (index >= array.Length) throw new IndexOutOfRangeException(IndexOutOfRangeText);
                    return array.GetValue(index);
                }
                if (value is IList list)
                {
                    if (index >= list.Count) throw new IndexOutOfRangeException(IndexOutOfRangeText);
                    return list[index];
                }
                PropertyInfo? property = value.GetType().GetDefaultMembers().OfType<PropertyInfo>().FirstOrDefault(p => p.CanRead && p.GetIndexParameters().Length == 1 && p.GetIndexParameters()[0].ParameterType == typeof(int));
                if (property != null) return property.GetValue(value, new object[] { index });
                if (value is IEnumerable sequence)
                {
                    if (index >= MaxEnumeratedIndex) throw new InvalidOperationException("index exceeds the enumeration limit of " + MaxEnumeratedIndex.ToString(System.Globalization.CultureInfo.InvariantCulture));
                    int position = 0;
                    foreach (object? item in sequence) { ct.ThrowIfCancellationRequested(); if (position++ == index) return item; }
                    throw new IndexOutOfRangeException(IndexOutOfRangeText);
                }
                throw new InvalidOperationException("value is not indexable");
            }
            catch (Exception ex) when (ex is ArgumentOutOfRangeException || ex is KeyNotFoundException || ex is TargetInvocationException invocation && (invocation.InnerException is ArgumentOutOfRangeException || invocation.InnerException is IndexOutOfRangeException || invocation.InnerException is KeyNotFoundException))
            { throw new IndexOutOfRangeException(IndexOutOfRangeText); }
        }

        /// <summary>The sub-path memo for one compiled query path: reads below the same intermediate object are evaluated once.</summary>
        internal sealed class PathMemo
        {
            internal sealed class Entry { internal ValueDto? Value; internal ProtocolException? Error; }
            private readonly Dictionary<MemoKey, Entry> entries = new Dictionary<MemoKey, Entry>();
            private readonly List<MemoKey> trail = new List<MemoKey>();
            private const int MaxEntries = 50000;
            private readonly struct MemoKey : IEquatable<MemoKey>
            {
                private readonly object subject; private readonly int step;
                internal MemoKey(object subject, int step) { this.subject = subject; this.step = step; }
                public bool Equals(MemoKey other) => ReferenceEquals(subject, other.subject) && step == other.step;
                public override bool Equals(object? obj) => obj is MemoKey other && Equals(other);
                public override int GetHashCode() => System.Runtime.CompilerServices.RuntimeHelpers.GetHashCode(subject) * 31 + step;
            }
            internal Entry? Lookup(object subject, int step) => entries.TryGetValue(new MemoKey(subject, step), out Entry? entry) ? entry : null;
            internal void Track(object subject, int step) => trail.Add(new MemoKey(subject, step));
            internal void Abandon() => trail.Clear();
            internal void Complete(ValueDto? value, ProtocolException? error)
            {
                if (entries.Count + trail.Count > MaxEntries) entries.Clear();
                var entry = new Entry { Value = value, Error = error };
                foreach (MemoKey key in trail) entries[key] = entry;
                trail.Clear();
            }
        }

        public IReadOnlyList<BindingInfoDto> GetBindings(object target, IReadOnlyList<string> memberKeys, IObjectRegistry registry, Dispatcher dispatcher)
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
                result.Add(ToBinding(key, BindingMetadataReader.Read(dep, entry.Property, redaction, registry, dispatcher)));
            }
            return result;
        }
        private static BindingInfoDto ToBinding(string key, BindingMetadata metadata)
        {
            var result = new BindingInfoDto { MemberKey = key, Kind = metadata.Kind, Status = metadata.Status, Mode = metadata.Mode, UpdateSourceTrigger = metadata.Trigger, Path = metadata.Path, ElementName = metadata.ElementName, SourceType = metadata.SourceType, ConverterType = metadata.ConverterType, StringFormat = metadata.StringFormat, FallbackValue = metadata.FallbackValue, TargetNullValue = metadata.TargetNullValue, ConverterParameter = metadata.ConverterParameter, ConverterCulture = metadata.ConverterCulture, Delay = metadata.Delay, BindingGroupName = metadata.BindingGroupName, XPath = metadata.XPath, IsAsync = metadata.IsAsync, NotifyOnSourceUpdated = metadata.NotifyOnSourceUpdated, NotifyOnTargetUpdated = metadata.NotifyOnTargetUpdated, NotifyOnValidationError = metadata.NotifyOnValidationError, ValidatesOnDataErrors = metadata.ValidatesOnDataErrors, ValidatesOnExceptions = metadata.ValidatesOnExceptions, ValidatesOnNotifyDataErrors = metadata.ValidatesOnNotifyDataErrors, ValidationRules = metadata.ValidationRules, HasUpdateSourceExceptionFilter = metadata.HasUpdateSourceExceptionFilter, ActiveChildIndex = metadata.ActiveChildIndex, DataItem = metadata.DataItem, ResolvedSource = metadata.ResolvedSource, ResolvedSourcePropertyName = metadata.ResolvedSourcePropertyName, HasError = metadata.HasError, HasValidationError = metadata.HasValidationError };
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
