using System;
using System.Collections.Generic;
using System.Globalization;
using System.Threading;
using System.Windows;
using System.Windows.Automation.Peers;
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

        internal ValuePredicate(Predicate predicate, ObjectInspector inspector, ObjectRegistry registry)
        {
            path = predicate.Path!;
            expected = predicate.Value;
            regex = predicate.Kind == "regex" ? new QueryRegex(predicate.Pattern!, predicate.Flags!) : null;
            this.inspector = inspector;
            this.registry = registry;
        }

        public bool Matches(DependencyObject target, QueryPredicateContext context)
        {
            ValueDto? value = path.Count == 1 && path[0].Kind == "uia" ? ReadUia(target) :
                inspector.ReadPath(target, path, registry, target.Dispatcher, CancellationToken.None);
            return value != null && MatchesValue(value, context);
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

        private ValueDto? ReadUia(DependencyObject target)
        {
            string name = path[0].Name;
            try
            {
                AutomationPeer? peer = null;
                if (name == "name" || name == "control_type")
                {
                    peer = target is UIElement element ? UIElementAutomationPeer.FromElement(element) ?? UIElementAutomationPeer.CreatePeerForElement(element) :
                        target is ContentElement content ? ContentElementAutomationPeer.FromElement(content) ?? ContentElementAutomationPeer.CreatePeerForElement(content) : null;
                    if (peer == null) return null;
                }
                if (inspector.IsPathRedacted(path)) throw Unreadable("redacted");
                string? result;
                if (name == "class_name") result = target.GetType().Name;
                else if (name == "automation_id")
                {
                    result = System.Windows.Automation.AutomationProperties.GetAutomationId(target);
                    if (string.IsNullOrEmpty(result)) result = target is FrameworkElement element ? element.Name : target is FrameworkContentElement content ? content.Name : "";
                }
                else
                {
                    result = name == "name" ? peer!.GetName() : ControlTypeName(peer!.GetAutomationControlType());
                }
                return ValueSerializer.Serialize(result ?? "", typeof(string), registry, target.Dispatcher);
            }
            catch (ProtocolException) { throw; }
            catch (Exception) { throw Unreadable("exception"); }
        }

        internal static string ControlTypeName(AutomationControlType controlType) => Enum.GetName(typeof(AutomationControlType), controlType) ?? throw new InvalidOperationException();
    }
}
