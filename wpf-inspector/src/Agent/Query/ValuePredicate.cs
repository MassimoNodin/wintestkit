using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Reflection;
using System.Threading;
using System.Windows;
using System.Windows.Automation.Peers;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Inspection;
using WinTestKit.Inspector.Agent.Inspection.Members;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Query
{
    internal sealed class ValuePredicate : IQueryPredicate
    {
        private readonly IReadOnlyList<PathSegment> path;
        private readonly JsonNode? expected;
        private readonly QueryRegex? regex;
        private readonly ObjectInspector inspector;
        private readonly ObjectRegistry registry;
        private readonly Dictionary<Type, Declaration[]> declarations = new Dictionary<Type, Declaration[]>();
        private readonly Dictionary<Type, bool> descriptorNames = new Dictionary<Type, bool>();
        private readonly bool loose;
        private readonly ObjectInspector.PathMemo? memo;

        internal ValuePredicate(Predicate predicate, ObjectInspector inspector, ObjectRegistry registry)
        {
            path = predicate.Path!;
            expected = predicate.Value;
            regex = predicate.Kind == "regex" ? new QueryRegex(predicate.Pattern!, predicate.Flags!) : null;
            loose = predicate.Kind == "equalsText";
            memo = path.Count > 1 ? new ObjectInspector.PathMemo() : null;
            this.inspector = inspector;
            this.registry = registry;
        }

        /// <summary>Cheapest first: type metadata, then one member, then paths through intermediate objects (indexers and regular expressions cost more).</summary>
        public int Cost => (path[0].Kind == "type" ? 1 : path[0].Kind == "uia" ? 1 : path[0].Kind == "object" ? 2 : 2 + path.Count) + (path.Any(segment => segment.Name.IndexOf('[') >= 0) ? 1 : 0) + (regex != null ? 1 : 0);

        public bool Matches(DependencyObject target, QueryPredicateContext context) => MatchesObject(target, target.Dispatcher, context);

        public bool Matches(object target, Dispatcher dispatcher, QueryPredicateContext context) => MatchesObject(target, dispatcher, context);

        internal bool MatchesObject(object target, Dispatcher dispatcher, QueryPredicateContext context)
        {
            if (context.Remaining <= TimeSpan.Zero) throw ProtocolException.Deadline("Query deadline reached.");
            if (path.Count == 1 && path[0].Kind == "type" && path[0].Name == "FullName" && regex == null)
            {
                if (!(expected is JsonStringNode typeName) || target.GetType().FullName != typeName.Value) return false;
                if (inspector.IsPathRedacted(path) || RedactionPolicy.IsProtectedIdentity(target) && !RedactionPolicy.IsAllowedOnProtected(path, null)) throw Unreadable("redacted");
                return true;
            }
            PathSegment first = path[0];
            if (first.Kind == "object")
            {
                ValueDto objectValue;
                try { objectValue = inspector.ReadObjectKey(target, first, registry, dispatcher, context.Token, context.Objects); }
                catch (OperationCanceledException) { throw ProtocolException.Deadline("Query deadline reached."); }
                // A password field has no text to compare; it never matches instead of failing the whole search.
                if (objectValue.Status == "redacted" && objectValue.RedactionRule == "identity") return false;
                if (context.Remaining <= TimeSpan.Zero) throw ProtocolException.Deadline("Query deadline reached.");
                return MatchesValue(objectValue, context);
            }
            if ((first.Kind == "property" || first.Kind == "field") && first.Name.IndexOf('[') < 0)
            {
                Type type = target.GetType();
                if (!declarations.TryGetValue(type, out Declaration[]? found))
                {
                    found = ReflectionCatalog.Get(type).Where(d => d.Name == first.Name &&
                        (first.Kind == "property" ? d.Property != null : d.Field != null) &&
                        (first.MemberKey == null || first.MemberKey == d.Key) &&
                        (first.DeclaringType == null || first.DeclaringType == Declaration.TypeName(d.DeclaringType))).ToArray();
                    declarations.Add(type, found);
                }
                if (found.Length == 0 && first.Kind == "field") return false;
                if (found.Length == 0 && first.Kind == "property")
                {
                    if (target is System.ComponentModel.ICustomTypeDescriptor)
                    {
                        if (System.ComponentModel.TypeDescriptor.GetProperties(target)[first.Name] == null) return false;
                    }
                    else
                    {
                        if (!descriptorNames.TryGetValue(type, out bool present))
                        {
                            present = System.ComponentModel.TypeDescriptor.GetProperties(type)[first.Name] != null;
                            descriptorNames.Add(type, present);
                        }
                        if (!present) return false;
                    }
                }
                if (found.Length > 1) throw new ProtocolException(ErrorCodes.MemberAmbiguous, "Member is ambiguous");
                if (found.Length == 1 && path.Count == 1 && !(target is System.ComponentModel.ICustomTypeDescriptor))
                {
                    Declaration d = found[0];
                    if (inspector.IsPathRedacted(path) || RedactionPolicy.IsPasswordIdentity(d.DeclaringType, d.Name) || RedactionPolicy.IsProtectedIdentity(target) && !RedactionPolicy.IsAllowedOnProtected(path, d))
                        throw Unreadable("redacted");
                    MethodInfo? getter = d.Property?.GetGetMethod(true);
                    if (d.Property != null && (getter == null || !getter.IsPublic || d.Property.GetIndexParameters().Length != 0) || d.Field != null && !d.Field.IsPublic)
                        throw Unreadable("notReadable");
                    if (Declaration.Unsupported(d.ValueType)) throw Unreadable("unsupported");
                    object? raw;
                    try { raw = d.Property != null ? d.Property.GetValue(target, null) : d.Field!.GetValue(target); }
                    catch (Exception) { throw Unreadable("exception"); }
                    if (context.Remaining <= TimeSpan.Zero) throw ProtocolException.Deadline("Query deadline reached.");
                    return MatchesValue(ValueSerializer.Serialize(raw, d.ValueType, registry, dispatcher), context);
                }
            }
            if (first.Kind == "dependency" && (!(target is DependencyObject dependency) || !DependencyCatalog.Discover(dependency, _ => { }).Any(entry =>
                entry.Property.Name == first.Name && Declaration.TypeName(entry.Property.OwnerType) == first.OwnerType &&
                Declaration.AssemblyName(entry.Property.OwnerType) == first.OwnerAssembly &&
                (first.MemberKey == null || entry.Key == first.MemberKey)))) return false;
            // A WinForms control reads its identity itself (WinFormsNative.ReadUia); only a WPF element needs a peer.
            if (first.Kind == "uia" && first.Name != "automation_id" && !WinFormsNative.IsWinFormsObject(target))
            {
                try { if (!(target is DependencyObject element) || PeerIdentity.GetPeer(element) == null) return false; }
                catch (Exception) { throw Unreadable("exception"); }
            }
            {
                ValueDto? value;
                try { value = memo != null ? inspector.ReadPath(target, path, registry, dispatcher, context.Token, ProtectedRoot(target, context), memo) : inspector.ReadPath(target, path, registry, dispatcher, context.Token, ProtectedRoot(target, context)); }
                catch (ProtocolException error) when (error.Code == ErrorCodes.MemberNotFound) { return false; }
                catch (OperationCanceledException) { throw ProtocolException.Deadline("Query deadline reached."); }
                if (path.Count == 1 && path[0].Kind == "uia" && path[0].Name == "automation_id" &&
                    (value.Status == "unavailable" || value.Status == "ok" && value.Kind == "string" && value.Scalar is JsonStringNode id && id.Value.Length == 0) &&
                    (target is FrameworkElement || target is FrameworkContentElement))
                {
                    var namePath = new[] { new PathSegment { Kind = "property", Name = "Name" } };
                    if (inspector.IsPathRedacted(namePath))
                        throw Unreadable("redacted");
                    string name = target is FrameworkElement frameworkElement ? frameworkElement.Name : ((FrameworkContentElement)target).Name;
                    value = new ValueDto { Status = "ok", Kind = "string", Scalar = new JsonStringNode(name) };
                }
                if (path[0].Kind == "uia" && value.Status == "unavailable") return false;
                if (value.Status == "exception" && value.Message == "System.IndexOutOfRangeException" && value.ErrorMessage == ObjectInspector.IndexOutOfRangeText) return false;
                return value != null && MatchesValue(value, context);
            }
        }

        internal bool MatchesValue(ValueDto value, QueryPredicateContext context)
        {
            if (value.Status == "nullIntermediate" || value.Status == "ok" && value.Kind == "null") return false;
            // Python skips stale elements rather than failing the query.
            if (value.Status == "stale") return false;
            if (value.Status != "ok") throw Unreadable(value.Status);
            if (value.Kind != "string" && value.Kind != "boolean" && value.Kind != "integer" && value.Kind != "number" && value.Kind != "enum")
                throw Unreadable("unsupported");
            if (regex != null)
                return (value.Kind == "string" || value.Kind == "enum") && value.Scalar is JsonStringNode text &&
                    regex.IsMatch(text.Value, (int)Math.Max(0, Math.Min(int.MaxValue, context.Remaining.TotalMilliseconds)));
            if (loose) return LooseEquals(value);
            if (value.Kind == "enum")
            {
                if (expected is JsonStringNode enumName && value.Scalar is JsonStringNode name) return enumName.Value == name.Value;
                if (expected is JsonNumberNode integer && integer.RawText.IndexOfAny(new[] { '.', 'e', 'E' }) < 0) return NumbersEqual(value.NumericValue, integer.RawText);
                return false;
            }
            if (value.Kind == "string") return expected is JsonStringNode wanted && value.Scalar is JsonStringNode actual && wanted.Value == actual.Value;
            if (value.Kind == "boolean") return expected is JsonBoolNode wantedBool && value.Scalar is JsonBoolNode actualBool && wantedBool.Value == actualBool.Value;
            return expected is JsonNumberNode number && NumbersEqual(value.NumericValue ?? NumberText(value.Scalar), number.RawText);
        }

        /// <summary>Compares the value's invariant text with the expected text: "15" matches 15 and "True" matches true; a decimal or double also matches the same number written with other trailing zeros ("1.5" matches 1.50m).</summary>
        private bool LooseEquals(ValueDto value)
        {
            if (!(expected is JsonStringNode wanted)) return false;
            string? text = value.Kind == "boolean" ? (value.Scalar is JsonBoolNode flag ? (flag.Value ? "True" : "False") : null) :
                value.Kind == "string" || value.Kind == "enum" ? (value.Scalar as JsonStringNode)?.Value :
                value.NumericValue ?? NumberText(value.Scalar);
            if (text == null) return false;
            if (value.Kind == "boolean") return string.Equals(text, wanted.Value, StringComparison.OrdinalIgnoreCase);
            if (text == wanted.Value) return true;
            if (value.Kind == "enum") return value.NumericValue != null && value.NumericValue == wanted.Value;
            return value.Kind == "number" && NumbersEqual(text, wanted.Value);
        }

        // Identity reads and type metadata never depend on whether the element is protected, so they skip the (costly) peer check.
        private static bool ProtectedRootNeeded(IReadOnlyList<PathSegment> path) => path[0].Kind != "uia" && path[0].Kind != "object" && !(path.Count == 1 && path[0].Kind == "type" && path[0].Name != "BaseTypes");
        private bool ProtectedRoot(object target, QueryPredicateContext context) => ProtectedRootNeeded(path) && context.IsProtected(target);

        private static string? NumberText(JsonNode? value) => value is JsonNumberNode number ? number.RawText : (value as JsonStringNode)?.Value;
        private static bool NumbersEqual(string? left, string right)
        {
            if (left == null) return false;
            if (decimal.TryParse(left, NumberStyles.Float, CultureInfo.InvariantCulture, out decimal leftDecimal) &&
                decimal.TryParse(right, NumberStyles.Float, CultureInfo.InvariantCulture, out decimal rightDecimal)) return leftDecimal == rightDecimal;
            return double.TryParse(left, NumberStyles.Float, CultureInfo.InvariantCulture, out double leftDouble) &&
                double.TryParse(right, NumberStyles.Float, CultureInfo.InvariantCulture, out double rightDouble) && leftDouble == rightDouble;
        }

        private ProtocolException Unreadable(string status)
        {
            var details = new JsonObjectNode();
            details.Add("status", new JsonStringNode(status));
            if (!inspector.IsPathRedacted(path))
            {
                var segments = new JsonArrayNode();
                foreach (PathSegment segment in path) segments.Add(segment.ToJson());
                details.Add("path", segments);
            }
            return new ProtocolException(ErrorCodes.ValueUnreadable, "Predicate value is unreadable.", details);
        }

        internal static string ControlTypeName(AutomationControlType controlType) => Enum.GetName(typeof(AutomationControlType), controlType) ?? throw new InvalidOperationException();
    }
}
