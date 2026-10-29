using System;
using System.Collections.Generic;
using System.Windows;
using System.Windows.Data;

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
    }

    internal static class BindingMetadataReader
    {
        internal static BindingMetadata Read(DependencyObject target, DependencyProperty property, RedactionPolicy redaction)
        {
            BindingBase? binding = BindingOperations.GetBindingBase(target, property);
            if (binding == null) return new BindingMetadata();
            BindingExpressionBase? expression = BindingOperations.GetBindingExpressionBase(target, property);
            int count = 0;
            BindingMetadata result = ReadCore(binding, redaction, 0, ref count);
            result.Status = expression == null ? "" : expression.Status.ToString();
            if (expression?.ValidationError != null)
            {
                var error = expression.ValidationError;
                result.ValidationErrors.Add((error.Exception ?? error.ErrorContent)?.GetType().FullName ?? error.GetType().FullName!);
            }
            return result;
        }
        private static BindingMetadata ReadCore(BindingBase binding, RedactionPolicy redaction, int depth, ref int count)
        {
            count++;
            var result = new BindingMetadata();
            if (binding is Binding single)
            {
                result.Kind = "binding";
                result.Mode = single.Mode.ToString();
                result.Trigger = single.UpdateSourceTrigger.ToString();
                string? path = single.Path?.Path;
                if (path != null && redaction.Match(path) == null) result.Path = path;
                result.ElementName = single.ElementName;
                if (single.RelativeSource != null)
                {
                    result.RelativeMode = single.RelativeSource.Mode.ToString();
                    result.AncestorType = single.RelativeSource.AncestorType?.FullName;
                    if (single.RelativeSource.Mode == RelativeSourceMode.FindAncestor) result.AncestorLevel = single.RelativeSource.AncestorLevel;
                }
                if (path == null || redaction.Match(path) == null) result.SourceType = single.Source?.GetType().FullName;
                result.ConverterType = single.Converter?.GetType().FullName;
            }
            else if (binding is MultiBinding multi)
            {
                result.Kind = "multiBinding"; result.Mode = multi.Mode.ToString(); result.Trigger = multi.UpdateSourceTrigger.ToString();
                result.ConverterType = multi.Converter?.GetType().FullName;
                if (depth + 1 < 8) foreach (BindingBase child in multi.Bindings) { if (count >= 32) break; result.Children.Add(ReadCore(child, redaction, depth + 1, ref count)); }
            }
            else if (binding is PriorityBinding priority)
            {
                result.Kind = "priorityBinding";
                if (depth + 1 < 8) foreach (BindingBase child in priority.Bindings) { if (count >= 32) break; result.Children.Add(ReadCore(child, redaction, depth + 1, ref count)); }
            }
            return result;
        }
    }
}
