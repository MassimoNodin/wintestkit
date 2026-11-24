using System.Collections.Generic;

namespace WinTestKit.Inspector.Protocol
{
    /// <summary>Optional full-detail fields of <see cref="BindingInfoDto"/>: binding options, validation flags and the resolved expression state.</summary>
    internal static class BindingDetails
    {
        internal static readonly string[] Keys =
        {
            "stringFormat", "fallbackValue", "targetNullValue", "converterParameter", "converterCulture", "delay", "bindingGroupName", "xPath", "isAsync",
            "notifyOnSourceUpdated", "notifyOnTargetUpdated", "notifyOnValidationError", "validatesOnDataErrors", "validatesOnExceptions", "validatesOnNotifyDataErrors",
            "validationRules", "hasUpdateSourceExceptionFilter", "activeChildIndex", "dataItem", "resolvedSource", "resolvedSourcePropertyName", "hasError", "hasValidationError"
        };

        internal static readonly string[] Allowed = Combine(new[] { "memberKey", "kind", "status", "mode", "updateSourceTrigger", "path", "elementName", "relativeSource", "sourceType", "converterType", "children", "validationErrors" }, Keys);

        private static string[] Combine(string[] first, string[] second)
        {
            var all = new string[first.Length + second.Length];
            first.CopyTo(all, 0); second.CopyTo(all, first.Length);
            return all;
        }

        internal static void Write(BindingInfoDto x, JsonObjectNode o)
        {
            DtoHelpers.Add(o, "stringFormat", x.StringFormat);
            if (x.FallbackValue != null) o.Add("fallbackValue", x.FallbackValue.ToJson());
            if (x.TargetNullValue != null) o.Add("targetNullValue", x.TargetNullValue.ToJson());
            if (x.ConverterParameter != null) o.Add("converterParameter", x.ConverterParameter.ToJson());
            DtoHelpers.Add(o, "converterCulture", x.ConverterCulture);
            DtoHelpers.Add(o, "delay", x.Delay);
            DtoHelpers.Add(o, "bindingGroupName", x.BindingGroupName);
            DtoHelpers.Add(o, "xPath", x.XPath);
            Flag(o, "isAsync", x.IsAsync);
            Flag(o, "notifyOnSourceUpdated", x.NotifyOnSourceUpdated);
            Flag(o, "notifyOnTargetUpdated", x.NotifyOnTargetUpdated);
            Flag(o, "notifyOnValidationError", x.NotifyOnValidationError);
            Flag(o, "validatesOnDataErrors", x.ValidatesOnDataErrors);
            Flag(o, "validatesOnExceptions", x.ValidatesOnExceptions);
            Flag(o, "validatesOnNotifyDataErrors", x.ValidatesOnNotifyDataErrors);
            if (x.ValidationRules != null) o.Add("validationRules", DtoHelpers.Strings(x.ValidationRules));
            Flag(o, "hasUpdateSourceExceptionFilter", x.HasUpdateSourceExceptionFilter);
            DtoHelpers.Add(o, "activeChildIndex", x.ActiveChildIndex);
            if (x.DataItem != null) o.Add("dataItem", x.DataItem.ToJson());
            if (x.ResolvedSource != null) o.Add("resolvedSource", x.ResolvedSource.ToJson());
            DtoHelpers.Add(o, "resolvedSourcePropertyName", x.ResolvedSourcePropertyName);
            Flag(o, "hasError", x.HasError);
            Flag(o, "hasValidationError", x.HasValidationError);
        }

        internal static void Read(BindingInfoDto x, JsonObjectNode o)
        {
            x.StringFormat = DtoHelpers.Optional(o, "stringFormat", 1024, true);
            x.FallbackValue = Value(o, "fallbackValue");
            x.TargetNullValue = Value(o, "targetNullValue");
            x.ConverterParameter = Value(o, "converterParameter");
            x.ConverterCulture = DtoHelpers.Optional(o, "converterCulture", 128, true);
            x.Delay = o.TryGet("delay", out var delay) ? (int)DtoHelpers.Integer(delay, 0, int.MaxValue) : (int?)null;
            x.BindingGroupName = DtoHelpers.Optional(o, "bindingGroupName", 1024, true);
            x.XPath = DtoHelpers.Optional(o, "xPath", 1024, true);
            x.IsAsync = Flag(o, "isAsync");
            x.NotifyOnSourceUpdated = Flag(o, "notifyOnSourceUpdated");
            x.NotifyOnTargetUpdated = Flag(o, "notifyOnTargetUpdated");
            x.NotifyOnValidationError = Flag(o, "notifyOnValidationError");
            x.ValidatesOnDataErrors = Flag(o, "validatesOnDataErrors");
            x.ValidatesOnExceptions = Flag(o, "validatesOnExceptions");
            x.ValidatesOnNotifyDataErrors = Flag(o, "validatesOnNotifyDataErrors");
            if (o.TryGet("validationRules", out var rules)) x.ValidationRules = DtoHelpers.Strings(rules, 32);
            x.HasUpdateSourceExceptionFilter = Flag(o, "hasUpdateSourceExceptionFilter");
            x.ActiveChildIndex = o.TryGet("activeChildIndex", out var active) ? (int)DtoHelpers.Integer(active, 0, ProtocolLimits.MaxBindingEntries - 1) : (int?)null;
            x.DataItem = Value(o, "dataItem");
            x.ResolvedSource = Value(o, "resolvedSource");
            x.ResolvedSourcePropertyName = DtoHelpers.Optional(o, "resolvedSourcePropertyName", 1024, true);
            x.HasError = Flag(o, "hasError");
            x.HasValidationError = Flag(o, "hasValidationError");
        }

        private static ValueDto? Value(JsonObjectNode o, string key) => o.TryGet(key, out var node) ? ValueDto.FromJson(node) : null;
        private static bool? Flag(JsonObjectNode o, string key) => o.TryGet(key, out var node) ? DtoHelpers.Boolean(node) : (bool?)null;
        private static void Flag(JsonObjectNode o, string key, bool? value) { if (value.HasValue) o.Add(key, new JsonBoolNode(value.Value)); }
    }
}
