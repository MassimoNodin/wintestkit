using System;
using System.Collections.Generic;

namespace WinTestKit.Inspector.Protocol
{
    /// <summary>Limits of the <c>members.styling</c> answer.</summary>
    public static class StylingLimits
    {
        /// <summary>Levels of a BasedOn chain after the style itself.</summary>
        public const int MaxBasedOn = ProtocolLimits.MaxBindingDepth;
        /// <summary>Setters, triggers, conditions, template parts and merged dictionaries listed per owner.</summary>
        public const int MaxEntries = ProtocolLimits.MaxBindingEntries;
        /// <summary>Entries listed from the element's own ResourceDictionary.</summary>
        public const int MaxResources = ProtocolLimits.MaxPageSize;
        /// <summary>Entries listed from Application.Current.Resources.</summary>
        public const int MaxApplicationResources = ProtocolLimits.DefaultPageSize;
        public const int MaxText = 1024;
    }

    public static class StylingValues
    {
        public static readonly string[] StyleSources = { "local", "implicit", "typeLookup", "none" };
        public static readonly string[] TriggerKinds = { "trigger", "dataTrigger", "multiTrigger", "multiDataTrigger", "eventTrigger", "other" };
        public static readonly string[] Activity = { "active", "inactive", "unknown" };
        public static readonly string[] SetterKinds = { "value", "dynamicResource", "binding", "multiBinding", "priorityBinding", "templateBinding", "other" };
        public static readonly string[] TemplateKinds = { "controlTemplate", "dataTemplate", "hierarchicalDataTemplate", "itemsPanelTemplate", "other" };
        public static readonly string[] KeyKinds = { "string", "type", "componentResourceKey", "other" };
    }

    /// <summary>Parameters of <c>members.styling</c>.</summary>
    public sealed class StylingParams
    {
        public string SessionId { get; set; } = "";
        public string ObjectId { get; set; } = "";
        public long Generation { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); DtoHelpers.Add(o, "sessionId", SessionId); DtoHelpers.Add(o, "objectId", ObjectId); o.Add("generation", JsonNumberNode.From(Generation)); FromJson(o); return o; }
        public static StylingParams FromJson(JsonNode node) { var o = DtoHelpers.Object(node, "sessionId", "objectId", "generation"); return new StylingParams { SessionId = DtoHelpers.Required(o, "sessionId"), ObjectId = DtoHelpers.Required(o, "objectId"), Generation = DtoHelpers.Integer(o.Get("generation"), 1) }; }
    }

    /// <summary>Shared JSON helpers of the styling DTOs.</summary>
    internal static class StylingJson
    {
        internal static string Text(JsonObjectNode o, string key) => DtoHelpers.Required(o, key, StylingLimits.MaxText, true);
        internal static string? OptionalText(JsonObjectNode o, string key) => DtoHelpers.Optional(o, key, StylingLimits.MaxText, true);
        internal static string Choice(JsonObjectNode o, string key, string[] values) { string value = DtoHelpers.Required(o, key); DtoHelpers.OneOf(value, values); return value; }
        internal static int Count(JsonObjectNode o, string key) => (int)DtoHelpers.Integer(o.Get(key), 0, int.MaxValue);
        internal static List<T> List<T>(JsonObjectNode o, string key, int max, Func<JsonNode, T> read) { var result = new List<T>(); foreach (var item in DtoHelpers.Array(o.Get(key), max).Items) result.Add(read(item)); return result; }
        internal static JsonArrayNode Array<T>(IEnumerable<T> items, Func<T, JsonNode> write) { var array = new JsonArrayNode(); foreach (var item in items) array.Add(write(item)); return array; }
        internal static void Flag(JsonObjectNode o, string key, bool value) => o.Add(key, new JsonBoolNode(value));
        internal static void Number(JsonObjectNode o, string key, long value) => o.Add(key, JsonNumberNode.From(value));
        internal static void Text(JsonObjectNode o, string key, string? value) => DtoHelpers.Add(o, key, value);
        internal static void Check(bool truncated, int total, int listed, int max) { if (listed > max || listed > total || (truncated && listed >= total) || (!truncated && listed != total)) throw DtoHelpers.Invalid("Inconsistent list size"); }
    }

    /// <summary>A condition of a trigger: a dependency property or a binding path, the value it is compared with and whether it holds now.</summary>
    public sealed class StylingCondition
    {
        public string? Property { get; set; }
        public string? Binding { get; set; }
        public string? SourceName { get; set; }
        public ValueDto Value { get; set; } = new ValueDto();
        public string Active { get; set; } = "unknown";
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); StylingJson.Text(o, "property", Property); StylingJson.Text(o, "binding", Binding); StylingJson.Text(o, "sourceName", SourceName); o.Add("value", Value.ToJson()); o.Add("active", new JsonStringNode(Active)); return o; }
        public static StylingCondition FromJson(JsonNode node) { var o = DtoHelpers.Object(node, "property", "binding", "sourceName", "value", "active"); return new StylingCondition { Property = StylingJson.OptionalText(o, "property"), Binding = StylingJson.OptionalText(o, "binding"), SourceName = StylingJson.OptionalText(o, "sourceName"), Value = ValueDto.FromJson(o.Get("value")), Active = StylingJson.Choice(o, "active", StylingValues.Activity) }; }
    }

    /// <summary>A Setter of a style, template or trigger. Resource and binding markup is described, never evaluated.</summary>
    public sealed class StylingSetter
    {
        public string Property { get; set; } = "";
        public string Owner { get; set; } = "";
        public string? TargetName { get; set; }
        public string Kind { get; set; } = "value";
        public string? Expression { get; set; }
        public ValueDto? Value { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("property", new JsonStringNode(Property)); o.Add("owner", new JsonStringNode(Owner)); StylingJson.Text(o, "targetName", TargetName); o.Add("kind", new JsonStringNode(Kind)); StylingJson.Text(o, "expression", Expression); if (Value != null) o.Add("value", Value.ToJson()); return o; }
        public static StylingSetter FromJson(JsonNode node) { var o = DtoHelpers.Object(node, "property", "owner", "targetName", "kind", "expression", "value"); return new StylingSetter { Property = StylingJson.Text(o, "property"), Owner = StylingJson.Text(o, "owner"), TargetName = StylingJson.OptionalText(o, "targetName"), Kind = StylingJson.Choice(o, "kind", StylingValues.SetterKinds), Expression = StylingJson.OptionalText(o, "expression"), Value = o.TryGet("value", out var value) ? ValueDto.FromJson(value) : null }; }
    }

    public sealed class StylingTrigger
    {
        public string Kind { get; set; } = "trigger";
        public string Active { get; set; } = "unknown";
        public string? RoutedEvent { get; set; }
        public IReadOnlyList<StylingCondition> Conditions { get; set; } = new List<StylingCondition>();
        public int SetterCount { get; set; }
        public bool SettersTruncated { get; set; }
        public IReadOnlyList<StylingSetter> Setters { get; set; } = new List<StylingSetter>();
        public int EnterActions { get; set; }
        public int ExitActions { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("kind", new JsonStringNode(Kind)); o.Add("active", new JsonStringNode(Active)); StylingJson.Text(o, "routedEvent", RoutedEvent); o.Add("conditions", StylingJson.Array(Conditions, item => item.ToJson())); StylingJson.Number(o, "setterCount", SetterCount); StylingJson.Flag(o, "settersTruncated", SettersTruncated); o.Add("setters", StylingJson.Array(Setters, item => item.ToJson())); StylingJson.Number(o, "enterActions", EnterActions); StylingJson.Number(o, "exitActions", ExitActions); return o; }
        public static StylingTrigger FromJson(JsonNode node)
        {
            var o = DtoHelpers.Object(node, "kind", "active", "routedEvent", "conditions", "setterCount", "settersTruncated", "setters", "enterActions", "exitActions");
            var result = new StylingTrigger { Kind = StylingJson.Choice(o, "kind", StylingValues.TriggerKinds), Active = StylingJson.Choice(o, "active", StylingValues.Activity), RoutedEvent = StylingJson.OptionalText(o, "routedEvent"), Conditions = StylingJson.List(o, "conditions", StylingLimits.MaxEntries, StylingCondition.FromJson), SetterCount = StylingJson.Count(o, "setterCount"), SettersTruncated = DtoHelpers.Boolean(o.Get("settersTruncated")), Setters = StylingJson.List(o, "setters", StylingLimits.MaxEntries, StylingSetter.FromJson), EnterActions = StylingJson.Count(o, "enterActions"), ExitActions = StylingJson.Count(o, "exitActions") };
            StylingJson.Check(result.SettersTruncated, result.SetterCount, result.Setters.Count, StylingLimits.MaxEntries);
            return result;
        }
    }

    /// <summary>One level of a style: its own setters and triggers, without the ones it inherits.</summary>
    public class StylingLevel
    {
        public string? Key { get; set; }
        public string? TargetType { get; set; }
        public int SetterCount { get; set; }
        public bool SettersTruncated { get; set; }
        public IReadOnlyList<StylingSetter> Setters { get; set; } = new List<StylingSetter>();
        public int TriggerCount { get; set; }
        public bool TriggersTruncated { get; set; }
        public IReadOnlyList<StylingTrigger> Triggers { get; set; } = new List<StylingTrigger>();
        internal static readonly string[] Keys = { "key", "targetType", "setterCount", "settersTruncated", "setters", "triggerCount", "triggersTruncated", "triggers" };
        internal void Write(JsonObjectNode o) { StylingJson.Text(o, "key", Key); StylingJson.Text(o, "targetType", TargetType); StylingJson.Number(o, "setterCount", SetterCount); StylingJson.Flag(o, "settersTruncated", SettersTruncated); o.Add("setters", StylingJson.Array(Setters, item => item.ToJson())); StylingJson.Number(o, "triggerCount", TriggerCount); StylingJson.Flag(o, "triggersTruncated", TriggersTruncated); o.Add("triggers", StylingJson.Array(Triggers, item => item.ToJson())); }
        internal void Read(JsonObjectNode o)
        {
            Key = StylingJson.OptionalText(o, "key"); TargetType = StylingJson.OptionalText(o, "targetType");
            SetterCount = StylingJson.Count(o, "setterCount"); SettersTruncated = DtoHelpers.Boolean(o.Get("settersTruncated")); Setters = StylingJson.List(o, "setters", StylingLimits.MaxEntries, StylingSetter.FromJson);
            TriggerCount = StylingJson.Count(o, "triggerCount"); TriggersTruncated = DtoHelpers.Boolean(o.Get("triggersTruncated")); Triggers = StylingJson.List(o, "triggers", StylingLimits.MaxEntries, StylingTrigger.FromJson);
            StylingJson.Check(SettersTruncated, SetterCount, Setters.Count, StylingLimits.MaxEntries);
            StylingJson.Check(TriggersTruncated, TriggerCount, Triggers.Count, StylingLimits.MaxEntries);
        }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); Write(o); return o; }
        public static StylingLevel FromJson(JsonNode node) { var o = DtoHelpers.Object(node, Keys); var level = new StylingLevel(); level.Read(o); return level; }
    }

    /// <summary>The style an element uses, and the styles it is based on.</summary>
    public sealed class StylingStyle : StylingLevel
    {
        public string Source { get; set; } = "none";
        public IReadOnlyList<StylingLevel> BasedOn { get; set; } = new List<StylingLevel>();
        public bool BasedOnTruncated { get; set; }
        public new JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("source", new JsonStringNode(Source)); Write(o); o.Add("basedOn", StylingJson.Array(BasedOn, item => item.ToJson())); StylingJson.Flag(o, "basedOnTruncated", BasedOnTruncated); return o; }
        public static new StylingStyle FromJson(JsonNode node)
        {
            var keys = new List<string>(Keys) { "source", "basedOn", "basedOnTruncated" };
            var o = DtoHelpers.Object(node, keys.ToArray());
            var style = new StylingStyle { Source = StylingJson.Choice(o, "source", StylingValues.StyleSources), BasedOn = StylingJson.List(o, "basedOn", StylingLimits.MaxBasedOn, StylingLevel.FromJson), BasedOnTruncated = DtoHelpers.Boolean(o.Get("basedOnTruncated")) };
            style.Read(o);
            if (style.BasedOnTruncated && style.BasedOn.Count != StylingLimits.MaxBasedOn) throw DtoHelpers.Invalid("Inconsistent BasedOn chain");
            return style;
        }
    }

    /// <summary>A named element the template created on this element.</summary>
    public sealed class StylingPart
    {
        public string Name { get; set; } = "";
        public string Type { get; set; } = "";
        public ValueDto Element { get; set; } = new ValueDto();
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("name", new JsonStringNode(Name)); o.Add("type", new JsonStringNode(Type)); o.Add("element", Element.ToJson()); return o; }
        public static StylingPart FromJson(JsonNode node) { var o = DtoHelpers.Object(node, "name", "type", "element"); return new StylingPart { Name = StylingJson.Text(o, "name"), Type = StylingJson.Text(o, "type"), Element = ValueDto.FromJson(o.Get("element")) }; }
    }

    public sealed class StylingTemplate
    {
        public string Kind { get; set; } = "other";
        public string? Key { get; set; }
        public string? TargetType { get; set; }
        public string? DataType { get; set; }
        public string? RootType { get; set; }
        public int TriggerCount { get; set; }
        public bool TriggersTruncated { get; set; }
        public IReadOnlyList<StylingTrigger> Triggers { get; set; } = new List<StylingTrigger>();
        public bool PartsTruncated { get; set; }
        public IReadOnlyList<StylingPart> Parts { get; set; } = new List<StylingPart>();
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("kind", new JsonStringNode(Kind)); StylingJson.Text(o, "key", Key); StylingJson.Text(o, "targetType", TargetType); StylingJson.Text(o, "dataType", DataType); StylingJson.Text(o, "rootType", RootType); StylingJson.Number(o, "triggerCount", TriggerCount); StylingJson.Flag(o, "triggersTruncated", TriggersTruncated); o.Add("triggers", StylingJson.Array(Triggers, item => item.ToJson())); StylingJson.Flag(o, "partsTruncated", PartsTruncated); o.Add("parts", StylingJson.Array(Parts, item => item.ToJson())); return o; }
        public static StylingTemplate FromJson(JsonNode node)
        {
            var o = DtoHelpers.Object(node, "kind", "key", "targetType", "dataType", "rootType", "triggerCount", "triggersTruncated", "triggers", "partsTruncated", "parts");
            var result = new StylingTemplate { Kind = StylingJson.Choice(o, "kind", StylingValues.TemplateKinds), Key = StylingJson.OptionalText(o, "key"), TargetType = StylingJson.OptionalText(o, "targetType"), DataType = StylingJson.OptionalText(o, "dataType"), RootType = StylingJson.OptionalText(o, "rootType"), TriggerCount = StylingJson.Count(o, "triggerCount"), TriggersTruncated = DtoHelpers.Boolean(o.Get("triggersTruncated")), Triggers = StylingJson.List(o, "triggers", StylingLimits.MaxEntries, StylingTrigger.FromJson), PartsTruncated = DtoHelpers.Boolean(o.Get("partsTruncated")), Parts = StylingJson.List(o, "parts", StylingLimits.MaxEntries, StylingPart.FromJson) };
            StylingJson.Check(result.TriggersTruncated, result.TriggerCount, result.Triggers.Count, StylingLimits.MaxEntries);
            if (result.PartsTruncated && result.Parts.Count != StylingLimits.MaxEntries) throw DtoHelpers.Invalid("Inconsistent template parts");
            return result;
        }
    }

    /// <summary>The templates of an element and the element the template that built it belongs to.</summary>
    public sealed class StylingTemplates
    {
        public StylingTemplate? ControlTemplate { get; set; }
        public StylingTemplate? ContentTemplate { get; set; }
        public StylingTemplate? ItemTemplate { get; set; }
        public StylingStyle? ItemContainerStyle { get; set; }
        public StylingTemplate? ItemsPanel { get; set; }
        public ValueDto? TemplatedParent { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); if (ControlTemplate != null) o.Add("controlTemplate", ControlTemplate.ToJson()); if (ContentTemplate != null) o.Add("contentTemplate", ContentTemplate.ToJson()); if (ItemTemplate != null) o.Add("itemTemplate", ItemTemplate.ToJson()); if (ItemContainerStyle != null) o.Add("itemContainerStyle", ItemContainerStyle.ToJson()); if (ItemsPanel != null) o.Add("itemsPanel", ItemsPanel.ToJson()); if (TemplatedParent != null) o.Add("templatedParent", TemplatedParent.ToJson()); return o; }
        public static StylingTemplates FromJson(JsonNode node)
        {
            var o = DtoHelpers.Object(node, "controlTemplate", "contentTemplate", "itemTemplate", "itemContainerStyle", "itemsPanel", "templatedParent");
            return new StylingTemplates
            {
                ControlTemplate = o.TryGet("controlTemplate", out var control) ? StylingTemplate.FromJson(control) : null,
                ContentTemplate = o.TryGet("contentTemplate", out var content) ? StylingTemplate.FromJson(content) : null,
                ItemTemplate = o.TryGet("itemTemplate", out var item) ? StylingTemplate.FromJson(item) : null,
                ItemContainerStyle = o.TryGet("itemContainerStyle", out var container) ? StylingStyle.FromJson(container) : null,
                ItemsPanel = o.TryGet("itemsPanel", out var panel) ? StylingTemplate.FromJson(panel) : null,
                TemplatedParent = o.TryGet("templatedParent", out var parent) ? ValueDto.FromJson(parent) : null,
            };
        }
    }

    /// <summary>A resource's key. The listing never reads the value: <c>members.resource</c> does, on demand, from the key and its position.</summary>
    public sealed class StylingResourceEntry
    {
        public string Key { get; set; } = "";
        public string KeyKind { get; set; } = "string";
        /// <summary>The key's position in the dictionary's key order.</summary>
        public int Index { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("key", new JsonStringNode(Key)); o.Add("keyKind", new JsonStringNode(KeyKind)); StylingJson.Number(o, "index", Index); return o; }
        public static StylingResourceEntry FromJson(JsonNode node) { var o = DtoHelpers.Object(node, "key", "keyKind", "index"); return new StylingResourceEntry { Key = StylingJson.Text(o, "key"), KeyKind = StylingJson.Choice(o, "keyKind", StylingValues.KeyKinds), Index = StylingJson.Count(o, "index") }; }
    }

    public sealed class StylingMergedDictionary
    {
        public string? Source { get; set; }
        public int Count { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); StylingJson.Text(o, "source", Source); StylingJson.Number(o, "count", Count); return o; }
        public static StylingMergedDictionary FromJson(JsonNode node) { var o = DtoHelpers.Object(node, "source", "count"); return new StylingMergedDictionary { Source = StylingJson.OptionalText(o, "source"), Count = StylingJson.Count(o, "count") }; }
    }

    /// <summary>A resource dictionary: how many entries it has, the first page of them and the dictionaries merged into it.</summary>
    public sealed class StylingResources
    {
        public string? Source { get; set; }
        public int Count { get; set; }
        public bool Truncated { get; set; }
        public IReadOnlyList<StylingResourceEntry> Entries { get; set; } = new List<StylingResourceEntry>();
        public bool MergedTruncated { get; set; }
        public IReadOnlyList<StylingMergedDictionary> MergedDictionaries { get; set; } = new List<StylingMergedDictionary>();
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); StylingJson.Text(o, "source", Source); StylingJson.Number(o, "count", Count); StylingJson.Flag(o, "truncated", Truncated); o.Add("entries", StylingJson.Array(Entries, item => item.ToJson())); StylingJson.Flag(o, "mergedTruncated", MergedTruncated); o.Add("mergedDictionaries", StylingJson.Array(MergedDictionaries, item => item.ToJson())); return o; }
        public static StylingResources FromJson(JsonNode node)
        {
            var o = DtoHelpers.Object(node, "source", "count", "truncated", "entries", "mergedTruncated", "mergedDictionaries");
            var result = new StylingResources { Source = StylingJson.OptionalText(o, "source"), Count = StylingJson.Count(o, "count"), Truncated = DtoHelpers.Boolean(o.Get("truncated")), Entries = StylingJson.List(o, "entries", StylingLimits.MaxResources, StylingResourceEntry.FromJson), MergedTruncated = DtoHelpers.Boolean(o.Get("mergedTruncated")), MergedDictionaries = StylingJson.List(o, "mergedDictionaries", StylingLimits.MaxResources, StylingMergedDictionary.FromJson) };
            StylingJson.Check(result.Truncated, result.Count, result.Entries.Count, StylingLimits.MaxResources);
            if (result.MergedTruncated && result.MergedDictionaries.Count != StylingLimits.MaxResources) throw DtoHelpers.Invalid("Inconsistent merged dictionaries");
            return result;
        }
    }

    /// <summary>Result of <c>members.styling</c>. Not applicable (and empty) for an object that is not a FrameworkElement or FrameworkContentElement.</summary>
    public sealed class StylingResult
    {
        public bool Applicable { get; set; }
        public StylingStyle? Style { get; set; }
        public StylingTemplates? Templates { get; set; }
        public StylingResources? Resources { get; set; }
        public StylingResources? Application { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); StylingJson.Flag(o, "applicable", Applicable); if (Style != null) o.Add("style", Style.ToJson()); if (Templates != null) o.Add("templates", Templates.ToJson()); if (Resources != null) o.Add("resources", Resources.ToJson()); if (Application != null) o.Add("application", Application.ToJson()); return o; }
        public static StylingResult FromJson(JsonNode node)
        {
            var o = DtoHelpers.Object(node, "applicable", "style", "templates", "resources", "application");
            var result = new StylingResult { Applicable = DtoHelpers.Boolean(o.Get("applicable")), Style = o.TryGet("style", out var style) ? StylingStyle.FromJson(style) : null, Templates = o.TryGet("templates", out var templates) ? StylingTemplates.FromJson(templates) : null, Resources = o.TryGet("resources", out var resources) ? StylingResources.FromJson(resources) : null, Application = o.TryGet("application", out var application) ? StylingResources.FromJson(application) : null };
            if (!result.Applicable && (result.Style != null || result.Templates != null || result.Resources != null || result.Application != null)) throw DtoHelpers.Invalid("Not applicable result must be empty");
            return result;
        }
    }
}
