using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Data;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Contracts;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Inspection.Members
{
    internal sealed class BindingMetadata
    {
        internal string Kind = "none";
        internal string Status = "";
        internal string Mode = "";
        internal string Trigger = "";
        internal string? Path;
        internal string? ElementName;
        internal string? RelativeMode;
        internal string? AncestorType;
        internal int? AncestorLevel;
        internal string? SourceType;
        internal string? ConverterType;
        internal List<string> ValidationErrors = new List<string>();
        internal List<BindingMetadata> Children = new List<BindingMetadata>();

        // Binding options.
        internal string? StringFormat;
        internal ValueDto? FallbackValue;
        internal ValueDto? TargetNullValue;
        internal ValueDto? ConverterParameter;
        internal string? ConverterCulture;
        internal int? Delay;
        internal string? BindingGroupName;
        internal string? XPath;
        internal bool? IsAsync;
        internal bool? NotifyOnSourceUpdated;
        internal bool? NotifyOnTargetUpdated;
        internal bool? NotifyOnValidationError;
        internal bool? ValidatesOnDataErrors;
        internal bool? ValidatesOnExceptions;
        internal bool? ValidatesOnNotifyDataErrors;
        internal List<string>? ValidationRules;
        internal bool? HasUpdateSourceExceptionFilter;
        internal int? ActiveChildIndex;

        // Expression state.
        internal ValueDto? DataItem;
        internal ValueDto? ResolvedSource;
        internal string? ResolvedSourcePropertyName;
        internal bool? HasError;
        internal bool? HasValidationError;
    }

    internal static class BindingMetadataReader
    {
        private const int TextLimit = 1024;

        internal static BindingMetadata Read(DependencyObject target, DependencyProperty property, RedactionPolicy redaction, IObjectRegistry registry, Dispatcher dispatcher)
        {
            BindingBase? binding = BindingOperations.GetBindingBase(target, property);
            if (binding == null) return new BindingMetadata();
            BindingExpressionBase? expression = BindingOperations.GetBindingExpressionBase(target, property);
            int count = 0;
            BindingMetadata result = ReadCore(binding, expression, redaction, registry, dispatcher, 0, ref count);
            if (expression?.ValidationError != null)
            {
                var error = expression.ValidationError;
                string? errorType = (error.Exception ?? error.ErrorContent)?.GetType().FullName ?? error.GetType().FullName;
                if (errorType != null && redaction.Match(errorType) == null)
                {
                    string? message = error.Exception != null && !RedactionPolicy.IsProtectedIdentity(target) && redaction.Match(property.Name) == null && result.Path != null && redaction.Match(result.Path) == null
                        ? ValueSerializer.ErrorMessage(error.Exception) : null;
                    result.ValidationErrors.Add(message == null ? errorType : errorType + ": " + message);
                }
            }
            return result;
        }

        private static BindingMetadata ReadCore(BindingBase binding, BindingExpressionBase? expression, RedactionPolicy redaction, IObjectRegistry registry, Dispatcher dispatcher, int depth, ref int count)
        {
            count++;
            var result = new BindingMetadata { Status = expression == null ? "" : expression.Status.ToString() };
            bool sensitive = AnySensitive(binding, redaction, 0);
            ReadOptions(binding, result, redaction, registry, dispatcher, sensitive);
            if (binding is Binding single)
            {
                result.Kind = "binding";
                result.Mode = single.Mode.ToString();
                result.Trigger = single.UpdateSourceTrigger.ToString();
                string? path = single.Path?.Path;
                bool sensitivePath = path != null && redaction.Match(path) != null;
                if (!sensitivePath) result.Path = path;
                if (!sensitivePath) result.ElementName = Safe(single.ElementName, redaction);
                if (single.RelativeSource != null)
                {
                    result.RelativeMode = single.RelativeSource.Mode.ToString();
                    if (!sensitivePath) result.AncestorType = Safe(single.RelativeSource.AncestorType?.FullName, redaction);
                    if (single.RelativeSource.Mode == RelativeSourceMode.FindAncestor) result.AncestorLevel = single.RelativeSource.AncestorLevel;
                }
                if (!sensitivePath) result.SourceType = Safe(single.Source?.GetType().FullName, redaction);
                if (!sensitivePath) result.ConverterType = Safe(single.Converter?.GetType().FullName, redaction);
                if (!sensitive) result.XPath = Text(single.XPath, redaction);
                result.IsAsync = single.IsAsync;
                result.NotifyOnSourceUpdated = single.NotifyOnSourceUpdated;
                result.NotifyOnTargetUpdated = single.NotifyOnTargetUpdated;
                result.NotifyOnValidationError = single.NotifyOnValidationError;
                result.ValidatesOnDataErrors = single.ValidatesOnDataErrors;
                result.ValidatesOnExceptions = single.ValidatesOnExceptions;
                result.ValidatesOnNotifyDataErrors = single.ValidatesOnNotifyDataErrors;
                result.ValidationRules = RuleTypes(single.ValidationRules, redaction);
                result.HasUpdateSourceExceptionFilter = single.UpdateSourceExceptionFilter != null;
                result.ConverterCulture = Culture(single.ConverterCulture);
                if (!sensitive) result.ConverterParameter = Capture(single.ConverterParameter, true, redaction, registry, dispatcher);
                if (expression is BindingExpression resolved) ReadResolved(resolved, result, redaction, registry, dispatcher, sensitive);
            }
            else if (binding is MultiBinding multi)
            {
                result.Kind = "multiBinding"; result.Mode = multi.Mode.ToString(); result.Trigger = multi.UpdateSourceTrigger.ToString();
                result.ConverterType = Safe(multi.Converter?.GetType().FullName, redaction);
                result.NotifyOnSourceUpdated = multi.NotifyOnSourceUpdated;
                result.NotifyOnTargetUpdated = multi.NotifyOnTargetUpdated;
                result.NotifyOnValidationError = multi.NotifyOnValidationError;
                result.ValidatesOnDataErrors = multi.ValidatesOnDataErrors;
                result.ValidatesOnExceptions = multi.ValidatesOnExceptions;
                result.ValidatesOnNotifyDataErrors = multi.ValidatesOnNotifyDataErrors;
                result.ValidationRules = RuleTypes(multi.ValidationRules, redaction);
                result.HasUpdateSourceExceptionFilter = multi.UpdateSourceExceptionFilter != null;
                result.ConverterCulture = Culture(multi.ConverterCulture);
                if (!sensitive) result.ConverterParameter = Capture(multi.ConverterParameter, true, redaction, registry, dispatcher);
                ReadChildren(multi.Bindings, (expression as MultiBindingExpression)?.BindingExpressions, result, redaction, registry, dispatcher, depth, ref count);
            }
            else if (binding is PriorityBinding priority)
            {
                result.Kind = "priorityBinding";
                if (expression is PriorityBindingExpression priorityExpression && priorityExpression.ActiveBindingExpression != null)
                {
                    int index = priorityExpression.BindingExpressions.IndexOf(priorityExpression.ActiveBindingExpression);
                    if (index >= 0) result.ActiveChildIndex = index;
                }
                ReadChildren(priority.Bindings, (expression as PriorityBindingExpression)?.BindingExpressions, result, redaction, registry, dispatcher, depth, ref count);
            }
            if (expression != null)
            {
                result.HasError = expression.HasError;
                result.HasValidationError = expression.HasValidationError;
            }
            return result;
        }

        private static void ReadChildren(IList<BindingBase> bindings, IList<BindingExpressionBase>? expressions, BindingMetadata result, RedactionPolicy redaction, IObjectRegistry registry, Dispatcher dispatcher, int depth, ref int count)
        {
            if (depth + 1 >= 8) return;
            int index = 0;
            foreach (BindingBase child in bindings)
            {
                if (count >= 32) break;
                BindingExpressionBase? childExpression = expressions != null && index < expressions.Count ? expressions[index] : null;
                result.Children.Add(ReadCore(child, childExpression, redaction, registry, dispatcher, depth + 1, ref count));
                index++;
            }
        }

        // Options every binding kind shares (BindingBase).
        private static void ReadOptions(BindingBase binding, BindingMetadata result, RedactionPolicy redaction, IObjectRegistry registry, Dispatcher dispatcher, bool sensitive)
        {
            if (!sensitive)
            {
                result.StringFormat = Text(binding.StringFormat, redaction);
                result.FallbackValue = Capture(binding.FallbackValue, false, redaction, registry, dispatcher);
                result.TargetNullValue = Capture(binding.TargetNullValue, false, redaction, registry, dispatcher);
            }
            if (binding.Delay != 0) result.Delay = binding.Delay;
            if (!string.IsNullOrEmpty(binding.BindingGroupName)) result.BindingGroupName = Text(binding.BindingGroupName, redaction);
        }

        private static void ReadResolved(BindingExpression expression, BindingMetadata result, RedactionPolicy redaction, IObjectRegistry registry, Dispatcher dispatcher, bool sensitive)
        {
            if (sensitive) return;
            try
            {
                result.DataItem = Capture(expression.DataItem, true, redaction, registry, dispatcher);
                result.ResolvedSource = Capture(expression.ResolvedSource, true, redaction, registry, dispatcher);
                result.ResolvedSourcePropertyName = Text(expression.ResolvedSourcePropertyName, redaction);
            }
            catch (Exception) { result.DataItem = null; result.ResolvedSource = null; result.ResolvedSourcePropertyName = null; }
        }

        // True when the binding, or any nested binding, reads through a redacted path or element name.
        private static bool AnySensitive(BindingBase binding, RedactionPolicy redaction, int depth)
        {
            if (binding is Binding single)
            {
                string? path = single.Path?.Path;
                return path != null && redaction.Match(path) != null || single.ElementName != null && redaction.Match(single.ElementName) != null;
            }
            if (depth >= 8) return false;
            IEnumerable<BindingBase>? children = binding is MultiBinding multi ? multi.Bindings : binding is PriorityBinding priority ? (IEnumerable<BindingBase>)priority.Bindings : null;
            return children != null && children.Any(child => AnySensitive(child, redaction, depth + 1));
        }

        // Serializes a binding-held value like a member value. Unset sentinels, redacted types and protected objects are omitted.
        private static ValueDto? Capture(object? value, bool omitNull, RedactionPolicy redaction, IObjectRegistry registry, Dispatcher dispatcher)
        {
            if (ReferenceEquals(value, DependencyProperty.UnsetValue) || ReferenceEquals(value, BindingOperations.DisconnectedSource)) return null;
            if (value == null) return omitNull ? null : ValueSerializer.Serialize(null, typeof(object), registry, dispatcher);
            try
            {
                string? typeName = value.GetType().FullName;
                if (typeName != null && redaction.Match(typeName) != null) return null;
                if (!(value is string) && !value.GetType().IsValueType && RedactionPolicy.IsProtectedIdentity(value)) return null;
                ValueDto serialized = ValueSerializer.Serialize(value, typeof(object), registry, dispatcher);
                return serialized.Status == ValueStatus.Unsupported ? null : serialized;
            }
            catch (Exception) { return null; }
        }

        private static string? Text(string? value, RedactionPolicy redaction)
        {
            if (string.IsNullOrEmpty(value) || redaction.Match(value!) != null) return null;
            for (int i = 0; i < value!.Length; i++)
            {
                if (!char.IsSurrogate(value[i])) continue;
                if (char.IsHighSurrogate(value[i]) && i + 1 < value.Length && char.IsLowSurrogate(value[i + 1])) { i++; continue; }
                return null;
            }
            return ScalarText.Prefix(value, TextLimit, out _);
        }

        private static string? Culture(System.Globalization.CultureInfo? culture) => culture?.Name;

        private static List<string>? RuleTypes(IEnumerable<System.Windows.Controls.ValidationRule>? rules, RedactionPolicy redaction)
        {
            if (rules == null) return null;
            var names = new List<string>();
            foreach (System.Windows.Controls.ValidationRule rule in rules)
            {
                if (names.Count >= 32) break;
                string? name = Safe(rule?.GetType().FullName, redaction);
                if (name != null) names.Add(name);
            }
            return names;
        }

        private static string? Safe(string? value, RedactionPolicy redaction) =>
            value != null && redaction.Match(value) == null ? value : null;
    }
}
