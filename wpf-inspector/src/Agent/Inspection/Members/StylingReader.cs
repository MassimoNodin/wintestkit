using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Text;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;
using System.Windows.Media;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Contracts;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Inspection.Members
{
    /// <summary>
    /// Describes the Style, templates and resources of a FrameworkElement or FrameworkContentElement. It reads the framework's
    /// own properties only: markup (DynamicResource, Binding, TemplateBinding) is named, never evaluated, and no converter,
    /// selector or application getter runs. Resources are listed by key; their values are not read (a deferred resource would be
    /// created in the application) until <see cref="ReadResource"/> asks for one. Must be called on the object's dispatcher.
    /// </summary>
    internal sealed class StylingReader
    {
        private const int MaxVisuals = 2000;
        private const int MaxScannedResources = 1024;
        private const int MaxScannedKeys = 16384;
        private static readonly FieldInfo? BaseDictionary = typeof(ResourceDictionary).GetField("_baseDictionary", BindingFlags.Instance | BindingFlags.NonPublic);
        private const int MaxLogicalHops = 32;
        private static readonly FieldInfo? ElementDefaultStyleKey = typeof(FrameworkElement).GetField("DefaultStyleKeyProperty", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
        private static readonly FieldInfo? ContentDefaultStyleKey = typeof(FrameworkContentElement).GetField("DefaultStyleKeyProperty", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
        private static readonly PropertyInfo? ElementHasResources = typeof(FrameworkElement).GetProperty("HasResources", BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public);
        private static readonly PropertyInfo? ContentHasResources = typeof(FrameworkContentElement).GetProperty("HasResources", BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public);

        private readonly RedactionPolicy redaction;
        private readonly IObjectRegistry registry;
        private readonly Dispatcher dispatcher;
        private readonly Func<ResourceDictionary?> application;
        private Dictionary<object, string>? keys;
        private DependencyObject owner = null!;

        /// <param name="application">The application's resources, or null when the target has no application on this dispatcher.</param>
        internal StylingReader(RedactionPolicy redaction, IObjectRegistry registry, Dispatcher dispatcher, Func<ResourceDictionary?>? application = null)
        {
            this.application = application ?? CurrentApplicationResources;
            this.redaction = redaction;
            this.registry = registry;
            this.dispatcher = dispatcher;
        }

        private ResourceDictionary? CurrentApplicationResources()
        {
            Application? current = Application.Current;
            return current != null && ReferenceEquals(current.Dispatcher, dispatcher) ? current.Resources : null;
        }

        internal StylingResult Read(object target)
        {
            var result = new StylingResult();
            if (!(target is FrameworkElement) && !(target is FrameworkContentElement)) return result;
            owner = (DependencyObject)target;
            if (IsPassword(owner)) return result;
            keys = null;
            result.Applicable = true;
            result.Style = ReadStyleOf();
            result.Templates = ReadTemplates();
            result.Resources = ReadLocalResources();
            result.Application = ReadApplicationResources();
            return result;
        }

        /// <summary>A password field has nothing to describe. An element without an automation peer is not one: styling says nothing about an element's content.</summary>
        private static bool IsPassword(DependencyObject target)
        {
            if (target is PasswordBox) return true;
            try
            {
                if (!(target is UIElement element)) return false;
                var peer = System.Windows.Automation.Peers.UIElementAutomationPeer.FromElement(element) ?? System.Windows.Automation.Peers.UIElementAutomationPeer.CreatePeerForElement(element);
                return peer != null && peer.IsPassword();
            }
            catch (Exception) { return true; }
        }

        // ---- Style ----------------------------------------------------------------------------------------------

        private StylingStyle ReadStyleOf()
        {
            Style? style = (owner as FrameworkElement)?.Style ?? (owner as FrameworkContentElement)?.Style;
            if (style != null)
            {
                BaseValueSource source = BaseSource(owner is FrameworkElement ? FrameworkElement.StyleProperty : FrameworkContentElement.StyleProperty);
                var result = BuildStyle(style, source == BaseValueSource.ImplicitStyleReference ? "implicit" : "local");
                if (source == BaseValueSource.ImplicitStyleReference && result.Key == null) result.Key = StyleKeyText(style.TargetType);
                return result;
            }
            Style? found = null;
            Type key = DefaultStyleKeyType();
            try { found = (owner as FrameworkElement)?.TryFindResource(key) as Style ?? (owner as FrameworkContentElement)?.TryFindResource(key) as Style; }
            catch (Exception) { found = null; }
            if (found == null) return new StylingStyle { Source = "none" };
            var lookup = BuildStyle(found, "typeLookup");
            lookup.Key = StyleKeyText(key);
            return lookup;
        }

        private BaseValueSource BaseSource(DependencyProperty property)
        {
            try { return DependencyPropertyHelper.GetValueSource(owner, property).BaseValueSource; }
            catch (Exception) { return BaseValueSource.Unknown; }
        }

        private Type DefaultStyleKeyType()
        {
            try
            {
                FieldInfo? field = owner is FrameworkElement ? ElementDefaultStyleKey : ContentDefaultStyleKey;
                if (field?.GetValue(null) is DependencyProperty property && owner.GetValue(property) is Type type) return type;
            }
            catch (Exception) { /* fall back to the element's own type */ }
            return owner.GetType();
        }

        private static string? StyleKeyText(Type? type) => type == null ? null : Declaration.TypeName(type);

        private StylingStyle BuildStyle(Style style, string source)
        {
            var result = new StylingStyle { Source = source };
            Fill(result, style);
            var chain = new List<StylingLevel>();
            var seen = new HashSet<Style>(new IdentityComparer<Style>()) { style };
            Style? next = style.BasedOn;
            while (next != null && chain.Count < StylingLimits.MaxBasedOn && seen.Add(next))
            {
                var level = new StylingLevel();
                Fill(level, next);
                chain.Add(level);
                next = next.BasedOn;
            }
            result.BasedOn = chain;
            result.BasedOnTruncated = next != null && chain.Count >= StylingLimits.MaxBasedOn;
            return result;
        }

        private void Fill(StylingLevel level, Style style)
        {
            level.Key = KeyOf(style);
            level.TargetType = style.TargetType == null ? null : Declaration.TypeName(style.TargetType);
            var setters = new List<StylingSetter>();
            level.SetterCount = Setters(style.Setters, setters);
            level.Setters = setters;
            level.SettersTruncated = level.SetterCount > setters.Count;
            var triggers = new List<StylingTrigger>();
            level.TriggerCount = Triggers(style.Triggers, triggers, null);
            level.Triggers = triggers;
            level.TriggersTruncated = level.TriggerCount > triggers.Count;
        }

        private int Setters(SetterBaseCollection? collection, List<StylingSetter> into)
        {
            if (collection == null) return 0;
            int total = collection.Count;
            for (int index = 0; index < total && into.Count < StylingLimits.MaxEntries; index++) into.Add(Setter(collection[index]));
            return total;
        }

        private StylingSetter Setter(SetterBase setterBase)
        {
            if (setterBase is Setter setter)
            {
                string name = setter.Property?.Name ?? "";
                var result = new StylingSetter { Property = name, Owner = setter.Property == null ? "" : Declaration.TypeName(setter.Property.OwnerType), TargetName = Clip(setter.TargetName) };
                Classify(setter.Value, setter.Property?.PropertyType, out string kind, out string? expression, out bool plain);
                result.Kind = kind;
                result.Expression = expression;
                if (name.Length != 0 && redaction.Match(name) != null) { result.Expression = null; result.Value = Redacted(redaction.Match(name)!); }
                else if (plain) result.Value = Serialize(setter.Value, setter.Property?.PropertyType);
                return result;
            }
            if (setterBase is EventSetter events)
            {
                string handler = "";
                try { handler = events.Handler?.Method.Name ?? ""; } catch (Exception) { handler = ""; }
                return new StylingSetter { Property = events.Event?.Name ?? "", Owner = events.Event == null ? "" : Declaration.TypeName(events.Event.OwnerType), Kind = "other", Expression = Clip(handler.Length == 0 ? "EventSetter" : "EventSetter: " + handler) };
            }
            return new StylingSetter { Kind = "other", Property = "", Owner = "", Expression = Declaration.TypeName(setterBase.GetType()) };
        }

        /// <summary>Names the markup a Setter value is, without evaluating it.</summary>
        private void Classify(object? value, Type? propertyType, out string kind, out string? expression, out bool plain)
        {
            plain = false; expression = null;
            switch (value)
            {
                case DynamicResourceExtension dynamicResource: kind = "dynamicResource"; expression = KeyText(dynamicResource.ResourceKey, out _); return;
                case TemplateBindingExtension template: kind = "templateBinding"; expression = template.Property?.Name; return;
                case MultiBinding multi: kind = "multiBinding"; expression = Clip(Join(multi.Bindings)); return;
                case PriorityBinding priority: kind = "priorityBinding"; expression = Clip(Join(priority.Bindings)); return;
                case BindingBase binding: kind = "binding"; expression = Clip(BindingText(binding)); return;
                case BindingExpressionBase _: kind = "binding"; return;
            }
            string? typeName = value?.GetType().FullName;
            if (typeName == "System.Windows.ResourceReferenceExpression")
            {
                kind = "dynamicResource";
                try { expression = KeyText(typeof(Style).Assembly.GetType(typeName)?.GetProperty("ResourceKey", BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public)?.GetValue(value), out _); }
                catch (Exception) { expression = null; }
                return;
            }
            if (typeName == "System.Windows.DeferredReference" || value is Expression || (value != null && IsMarkupExtension(value.GetType()))) { kind = "other"; expression = typeName; return; }
            kind = "value"; plain = true;
        }

        /// <summary>Whether a type derives from MarkupExtension, found by name: the agent must not reference System.Xaml.</summary>
        private static bool IsMarkupExtension(Type type)
        {
            for (Type? current = type.BaseType; current != null; current = current.BaseType)
                if (current.FullName == "System.Windows.Markup.MarkupExtension") return true;
            return false;
        }

        private static string Join(IEnumerable bindings)
        {
            var builder = new StringBuilder();
            foreach (object item in bindings)
            {
                if (builder.Length != 0) builder.Append("; ");
                builder.Append(item is BindingBase binding ? BindingText(binding) : Declaration.TypeName(item.GetType()));
                if (builder.Length > StylingLimits.MaxText) break;
            }
            return builder.ToString();
        }

        /// <summary>The path and source of a binding, as XAML would write them.</summary>
        internal static string BindingText(BindingBase binding)
        {
            if (binding is MultiBinding multi) return "MultiBinding(" + multi.Bindings.Count + ")";
            if (binding is PriorityBinding priority) return "PriorityBinding(" + priority.Bindings.Count + ")";
            if (!(binding is Binding single)) return Declaration.TypeName(binding.GetType());
            var parts = new List<string>();
            string path = single.Path?.Path ?? "";
            if (path.Length != 0) parts.Add("Path=" + path);
            if (!string.IsNullOrEmpty(single.XPath)) parts.Add("XPath=" + single.XPath);
            if (!string.IsNullOrEmpty(single.ElementName)) parts.Add("ElementName=" + single.ElementName);
            if (single.RelativeSource != null) parts.Add("RelativeSource=" + single.RelativeSource.Mode);
            if (parts.Count == 0) parts.Add("Path=.");
            return string.Join(", ", parts.ToArray());
        }

        // ---- Triggers -------------------------------------------------------------------------------------------

        /// <summary>Lists up to the cap; <paramref name="template"/> resolves a trigger's SourceName.</summary>
        private int Triggers(TriggerCollection? collection, List<StylingTrigger> into, FrameworkTemplate? template)
        {
            if (collection == null) return 0;
            int total = collection.Count;
            for (int index = 0; index < total && into.Count < StylingLimits.MaxEntries; index++) into.Add(Trigger(collection[index], template));
            return total;
        }

        private StylingTrigger Trigger(TriggerBase trigger, FrameworkTemplate? template)
        {
            var result = new StylingTrigger();
            var setters = new List<StylingSetter>();
            try { result.EnterActions = trigger.EnterActions.Count; result.ExitActions = trigger.ExitActions.Count; } catch (Exception) { /* leave zero */ }
            var conditions = new List<StylingCondition>();
            switch (trigger)
            {
                case Trigger single:
                    result.Kind = "trigger";
                    conditions.Add(PropertyCondition(single.Property, single.Value, single.SourceName, template));
                    result.SetterCount = Setters(single.Setters, setters);
                    result.Active = conditions[0].Active;
                    break;
                case MultiTrigger multi:
                    result.Kind = "multiTrigger";
                    foreach (Condition condition in multi.Conditions) { if (conditions.Count >= StylingLimits.MaxEntries) break; conditions.Add(ConditionOf(condition, template)); }
                    result.SetterCount = Setters(multi.Setters, setters);
                    result.Active = AllOf(conditions);
                    break;
                case DataTrigger data:
                    result.Kind = "dataTrigger";
                    conditions.Add(BindingCondition(data.Binding, data.Value));
                    result.SetterCount = Setters(data.Setters, setters);
                    break;
                case MultiDataTrigger multiData:
                    result.Kind = "multiDataTrigger";
                    foreach (Condition condition in multiData.Conditions) { if (conditions.Count >= StylingLimits.MaxEntries) break; conditions.Add(ConditionOf(condition, template)); }
                    result.SetterCount = Setters(multiData.Setters, setters);
                    break;
                case EventTrigger events:
                    result.Kind = "eventTrigger";
                    result.RoutedEvent = events.RoutedEvent == null ? null : Declaration.TypeName(events.RoutedEvent.OwnerType) + "." + events.RoutedEvent.Name;
                    try { result.EnterActions = events.Actions.Count; } catch (Exception) { /* leave */ }
                    break;
                default:
                    result.Kind = "other";
                    break;
            }
            result.Conditions = conditions;
            result.Setters = setters;
            result.SettersTruncated = result.SetterCount > setters.Count;
            return result;
        }

        private static string AllOf(List<StylingCondition> conditions)
        {
            bool unknown = false;
            foreach (StylingCondition condition in conditions)
            {
                if (condition.Active == "inactive") return "inactive";
                if (condition.Active != "active") unknown = true;
            }
            return conditions.Count == 0 || unknown ? "unknown" : "active";
        }

        private StylingCondition ConditionOf(Condition condition, FrameworkTemplate? template)
        {
            if (condition.Binding != null) return BindingCondition(condition.Binding, condition.Value);
            return PropertyCondition(condition.Property, condition.Value, condition.SourceName, template);
        }

        private StylingCondition PropertyCondition(DependencyProperty? property, object? expected, string? sourceName, FrameworkTemplate? template)
        {
            string name = property?.Name ?? "";
            var result = new StylingCondition { Property = property == null ? null : Declaration.TypeName(property.OwnerType) + "." + name, SourceName = Clip(sourceName) };
            string? rule = name.Length == 0 ? null : redaction.Match(name);
            result.Value = rule != null ? Redacted(rule) : Serialize(expected, property?.PropertyType);
            result.Active = property == null ? "unknown" : Evaluate(Source(sourceName, template), property, expected);
            return result;
        }

        private StylingCondition BindingCondition(BindingBase? binding, object? expected)
        {
            string text = binding == null ? "" : BindingText(binding);
            string? rule = binding is Binding single ? redaction.Match(single.Path?.Path ?? "") : null;
            return new StylingCondition { Binding = Clip(text), Value = rule != null ? Redacted(rule) : Serialize(expected, null), Active = "unknown" };
        }

        /// <summary>The element a trigger condition reads: this element, or a named part of its template.</summary>
        private DependencyObject? Source(string? sourceName, FrameworkTemplate? template)
        {
            if (string.IsNullOrEmpty(sourceName)) return owner;
            if (template == null || !(owner is FrameworkElement element)) return null;
            try { return template.FindName(sourceName, element) as DependencyObject; }
            catch (Exception) { return null; }
        }

        private static string Evaluate(DependencyObject? element, DependencyProperty property, object? expected)
        {
            if (element == null) return "unknown";
            object? current;
            try { current = element.GetValue(property); }
            catch (Exception) { return "unknown"; }
            if (Equals(current, expected)) return "active";
            if (current == null || expected == null) return "inactive";
            if (current.GetType() == expected.GetType()) return "inactive";
            // A condition written as text compares as the property's own type once converted; only the framework's
            // primitive and enum types are converted, never an application type.
            Type type = property.PropertyType;
            try
            {
                if (expected is string text && (type.IsEnum || type.IsPrimitive) && current.GetType() == type)
                    return Equals(type.IsEnum ? Enum.Parse(type, text, true) : Convert.ChangeType(text, type, CultureInfo.InvariantCulture), current) ? "active" : "inactive";
                if (current is IConvertible && expected is IConvertible && current.GetType().IsPrimitive && expected.GetType().IsPrimitive)
                    return Equals(Convert.ChangeType(expected, current.GetType(), CultureInfo.InvariantCulture), current) ? "active" : "inactive";
            }
            catch (Exception) { return "unknown"; }
            return "unknown";
        }

        // ---- Templates ------------------------------------------------------------------------------------------

        private StylingTemplates ReadTemplates()
        {
            var result = new StylingTemplates();
            if (owner is Control control && control.Template != null) result.ControlTemplate = BuildTemplate(control.Template, true);
            if (owner is ContentControl content && content.ContentTemplate != null) result.ContentTemplate = BuildTemplate(content.ContentTemplate, false);
            else if (owner is ContentPresenter presenter && presenter.ContentTemplate != null) result.ContentTemplate = BuildTemplate(presenter.ContentTemplate, true);
            if (owner is ItemsControl items)
            {
                if (items.ItemTemplate != null) result.ItemTemplate = BuildTemplate(items.ItemTemplate, false);
                if (items.ItemContainerStyle != null) result.ItemContainerStyle = BuildStyle(items.ItemContainerStyle, "local");
                if (items.ItemsPanel != null) result.ItemsPanel = BuildTemplate(items.ItemsPanel, false);
            }
            DependencyObject? parent = (owner as FrameworkElement)?.TemplatedParent ?? (owner as FrameworkContentElement)?.TemplatedParent;
            if (parent != null) result.TemplatedParent = Serialize(parent, typeof(DependencyObject));
            return result;
        }

        /// <param name="applied">True when the template builds this element's own visuals, so the parts and the root can be read from them.</param>
        private StylingTemplate BuildTemplate(FrameworkTemplate template, bool applied)
        {
            var result = new StylingTemplate { Key = KeyOf(template) };
            var triggers = new List<StylingTrigger>();
            if (template is ControlTemplate control)
            {
                result.Kind = "controlTemplate";
                result.TargetType = control.TargetType == null ? null : Declaration.TypeName(control.TargetType);
                result.TriggerCount = Triggers(control.Triggers, triggers, template);
            }
            else if (template is DataTemplate data)
            {
                result.Kind = template is HierarchicalDataTemplate ? "hierarchicalDataTemplate" : "dataTemplate";
                result.DataType = data.DataType is Type type ? Declaration.TypeName(type) : Clip(data.DataType?.GetType().FullName);
                result.TriggerCount = Triggers(data.Triggers, triggers, template);
            }
            else result.Kind = template is ItemsPanelTemplate ? "itemsPanelTemplate" : "other";
            result.Triggers = triggers;
            result.TriggersTruncated = result.TriggerCount > triggers.Count;
            result.RootType = template.VisualTree?.Type == null ? null : Declaration.TypeName(template.VisualTree.Type);
            if (template is ItemsPanelTemplate) result.RootType ??= ItemsPanelType();
            else if (applied) result.RootType ??= AppliedRootType();
            if (applied) Parts(template, result);
            else result.Parts = new List<StylingPart>();
            return result;
        }

        private string? ItemsPanelType()
        {
            Panel? panel = null;
            Walk(owner, node => { if (panel != null) return false; if (node is Panel candidate && candidate.IsItemsHost && ReferenceEquals(ItemsControl.GetItemsOwner(candidate), owner)) { panel = candidate; return false; } return true; });
            return panel == null ? null : Declaration.TypeName(panel.GetType());
        }

        private string? AppliedRootType()
        {
            try
            {
                if (!(owner is Visual) || VisualTreeHelper.GetChildrenCount(owner) == 0) return null;
                DependencyObject root = VisualTreeHelper.GetChild(owner, 0);
                return ReferenceEquals((root as FrameworkElement)?.TemplatedParent, owner) ? Declaration.TypeName(root.GetType()) : null;
            }
            catch (Exception) { return null; }
        }

        /// <summary>The named elements the template created on this element, confirmed through Template.FindName.</summary>
        private void Parts(FrameworkTemplate template, StylingTemplate result)
        {
            var parts = new List<StylingPart>();
            result.Parts = parts;
            if (!(owner is FrameworkElement element)) return;
            var names = new List<string>();
            FactoryNames(template.VisualTree, names);
            Walk(owner, node =>
            {
                if (ReferenceEquals(node, owner)) return true;
                if (!(node is FrameworkElement child) || !ReferenceEquals(child.TemplatedParent, owner)) return false;
                if (!string.IsNullOrEmpty(child.Name) && !names.Contains(child.Name)) names.Add(child.Name);
                return true;
            });
            foreach (string name in names)
            {
                object? part;
                try { part = template.FindName(name, element); }
                catch (Exception) { return; }
                if (part == null) continue;
                if (parts.Count >= StylingLimits.MaxEntries) { result.PartsTruncated = true; return; }
                parts.Add(new StylingPart { Name = name, Type = Declaration.TypeName(part.GetType()), Element = Serialize(part, typeof(object)) });
            }
        }

        /// <summary>The names of a code-built template's factories: those elements are named in the template's namescope, not by their Name property.</summary>
        private static void FactoryNames(FrameworkElementFactory? root, List<string> names)
        {
            var pending = new Stack<FrameworkElementFactory>();
            if (root != null) pending.Push(root);
            for (int visited = 0; pending.Count != 0 && visited < MaxVisuals; visited++)
            {
                FrameworkElementFactory factory = pending.Pop();
                // The framework names an unnamed factory "~ChildID<n>"; that name is not the template author's.
                if (!string.IsNullOrEmpty(factory.Name) && !factory.Name.StartsWith("~", StringComparison.Ordinal) && !names.Contains(factory.Name)) names.Add(factory.Name);
                if (factory.NextSibling != null) pending.Push(factory.NextSibling);
                if (factory.FirstChild != null) pending.Push(factory.FirstChild);
            }
        }

        /// <summary>Visits the visual tree below <paramref name="start"/> breadth-first; the visitor returns false to not descend into a node.</summary>
        private static void Walk(DependencyObject start, Func<DependencyObject, bool> visit)
        {
            var queue = new Queue<DependencyObject>();
            queue.Enqueue(start);
            int visited = 0;
            while (queue.Count != 0 && visited++ < MaxVisuals)
            {
                DependencyObject node = queue.Dequeue();
                if (!visit(node)) continue;
                int count;
                try { count = node is Visual || node is System.Windows.Media.Media3D.Visual3D ? VisualTreeHelper.GetChildrenCount(node) : 0; } catch (Exception) { continue; }
                for (int index = 0; index < count; index++) queue.Enqueue(VisualTreeHelper.GetChild(node, index));
            }
        }

        // ---- Resources ------------------------------------------------------------------------------------------

        /// <summary>The element's own dictionary; null when it has none. Reading Resources would create an empty dictionary on an element that has none.</summary>
        private ResourceDictionary? LocalDictionary()
        {
            PropertyInfo? has = owner is FrameworkElement ? ElementHasResources : ContentHasResources;
            if (has != null && has.GetValue(owner) is bool present && !present) return null;
            return (owner as FrameworkElement)?.Resources ?? (owner as FrameworkContentElement)?.Resources;
        }

        private StylingResources? ReadLocalResources()
        {
            ResourceDictionary? local;
            try { local = LocalDictionary(); }
            catch (Exception) { return null; }
            return local == null ? new StylingResources() : Describe(local, StylingLimits.MaxResources);
        }

        private StylingResources? ReadApplicationResources()
        {
            try
            {
                ResourceDictionary? resources = application();
                return resources == null ? null : Describe(resources, StylingLimits.MaxApplicationResources);
            }
            catch (Exception) { return null; }
        }

        private StylingResources Describe(ResourceDictionary dictionary, int max)
        {
            var result = new StylingResources { Source = Clip(dictionary.Source?.OriginalString), Count = dictionary.Count };
            var entries = new List<StylingResourceEntry>();
            try
            {
                // Keys only: reading a value, or enumerating the dictionary itself, would create a deferred resource in the application.
                int position = 0;
                foreach (object key in dictionary.Keys)
                {
                    if (entries.Count >= max) break;
                    entries.Add(Entry(key, position++));
                }
            }
            catch (Exception) { /* the entries listed so far stand */ }
            result.Entries = entries;
            result.Truncated = result.Count > entries.Count;
            var merged = new List<StylingMergedDictionary>();
            int total = dictionary.MergedDictionaries.Count;
            for (int index = 0; index < total; index++)
            {
                if (merged.Count >= StylingLimits.MaxResources) { result.MergedTruncated = true; break; }
                ResourceDictionary child = dictionary.MergedDictionaries[index];
                merged.Add(new StylingMergedDictionary { Source = Clip(child.Source?.OriginalString), Count = child.Count });
            }
            result.MergedDictionaries = merged;
            return result;
        }

        private static StylingResourceEntry Entry(object key, int position) => new StylingResourceEntry { Key = KeyText(key, out string kind) ?? "", KeyKind = kind, Index = position };

        // ---- One resource's value, on demand -------------------------------------------------------------------

        /// <summary>
        /// Reads one value of the element's dictionary or the application's, found by the key the listing returned. This is the only place a
        /// resource is created: reading the value of a deferred resource instantiates it in the application, which is why it is a request of its own.
        /// </summary>
        internal ResourceResult ReadResource(object target, string scope, string key, string keyKind, int? hint)
        {
            var result = new ResourceResult();
            if (!(target is FrameworkElement) && !(target is FrameworkContentElement)) return result;
            owner = (DependencyObject)target;
            if (IsPassword(owner)) return result;
            ResourceDictionary? dictionary;
            try { dictionary = scope == MemberEventValues.ResourceScopes[1] ? application() : LocalDictionary(); }
            catch (Exception) { return result; }
            if (dictionary == null || !TryFindKey(dictionary, key, keyKind, hint, out object? found)) return result;
            result.Found = true;
            string? rule = redaction.Match(key);
            // A redacted key's value is never read, not even to name its type.
            if (rule != null) { result.Value = Redacted(rule); return result; }
            object? value;
            try { value = dictionary[found!]; }
            catch (Exception exception) { result.Value = Failure(exception, typeof(object)); return result; }
            result.ValueType = value == null ? "" : Declaration.TypeName(value.GetType());
            result.Value = Serialize(value, typeof(object));
            return result;
        }

        /// <summary>Finds the key a listing named: the one at the listed position when it still matches, otherwise the first that does.</summary>
        private static bool TryFindKey(ResourceDictionary dictionary, string text, string kind, int? hint, out object? found)
        {
            found = null;
            int position = 0;
            foreach (object candidate in dictionary.Keys)
            {
                if (position++ >= MaxScannedKeys) break;
                if (KeyText(candidate, out string candidateKind) != text || candidateKind != kind) continue;
                if (position - 1 == hint) { found = candidate; return true; }
                found ??= candidate;
            }
            return found != null;
        }

        /// <summary>Describes a resource key as text: strings as they are, types by name, component keys and template keys by what they name.</summary>
        internal static string? KeyText(object? key, out string kind)
        {
            kind = "other";
            switch (key)
            {
                case null: return null;
                case string text: kind = "string"; return Clip(text);
                case Type type: kind = "type"; return Declaration.TypeName(type);
                case ComponentResourceKey component:
                    kind = "componentResourceKey";
                    return Clip("ComponentResourceKey(" + (component.TypeInTargetAssembly == null ? "" : Declaration.TypeName(component.TypeInTargetAssembly)) + ", " + Scalar(component.ResourceId) + ")");
                case DataTemplateKey dataTemplate: return "DataTemplateKey(" + Scalar(dataTemplate.DataType) + ")";
                default:
                    return Clip(Declaration.TypeName(key.GetType()) + (key is IConvertible && !(key is string) ? ": " + Convert.ToString(key, CultureInfo.InvariantCulture) : ""));
            }
        }

        private static string Scalar(object? value)
        {
            switch (value)
            {
                case null: return "";
                case Type type: return Declaration.TypeName(type);
                case string text: return text;
                case IConvertible convertible: return convertible.ToString(CultureInfo.InvariantCulture);
                default: return Declaration.TypeName(value.GetType());
            }
        }

        // ---- Shared ---------------------------------------------------------------------------------------------

        /// <summary>The resource key of a style or template, when it lives in a dictionary on the element's path to the application.</summary>
        private string? KeyOf(object resource)
        {
            keys ??= IndexKeys();
            return keys.TryGetValue(resource, out string? key) ? key : null;
        }

        private Dictionary<object, string> IndexKeys()
        {
            var index = new Dictionary<object, string>(new IdentityComparer<object>());
            int budget = MaxScannedResources;
            var dictionaries = new List<ResourceDictionary>();
            try
            {
                DependencyObject? node = owner;
                for (int hop = 0; node != null && hop < MaxLogicalHops; hop++)
                {
                    ResourceDictionary? own = null;
                    PropertyInfo? has = node is FrameworkElement ? ElementHasResources : node is FrameworkContentElement ? ContentHasResources : null;
                    if (has == null || !(has.GetValue(node) is bool present) || present) own = (node as FrameworkElement)?.Resources ?? (node as FrameworkContentElement)?.Resources;
                    if (own != null) dictionaries.Add(own);
                    node = LogicalTreeHelper.GetParent(node);
                }
                ResourceDictionary? global = application();
                if (global != null) dictionaries.Add(global);
            }
            catch (Exception) { /* index what was reached */ }
            foreach (ResourceDictionary dictionary in dictionaries)
            {
                if (budget <= 0) break;
                Scan(dictionary, index, ref budget, 0);
            }
            return index;
        }

        private static void Scan(ResourceDictionary dictionary, Dictionary<object, string> index, ref int budget, int depth)
        {
            try
            {
                foreach (DictionaryEntry entry in Realized(dictionary))
                {
                    if (budget-- <= 0) return;
                    if ((entry.Value is Style || entry.Value is FrameworkTemplate) && !index.ContainsKey(entry.Value)) { string? text = KeyText(entry.Key, out _); if (text != null) index.Add(entry.Value, text); }
                }
                if (depth >= StylingLimits.MaxBasedOn) return;
                foreach (ResourceDictionary merged in dictionary.MergedDictionaries)
                {
                    if (budget <= 0) return;
                    Scan(merged, index, ref budget, depth + 1);
                }
            }
            catch (Exception) { /* a dictionary that cannot be listed adds no keys */ }
        }

        /// <summary>
        /// The entries a dictionary already holds as values. A deferred resource is still a reference the dictionary has not created, and
        /// looking at it would create it, so it is skipped; one the application has used is in the dictionary as the object itself. When the
        /// dictionary's storage cannot be found, nothing is listed: the key of a style or template is then left unnamed.
        /// </summary>
        private static IEnumerable<DictionaryEntry> Realized(ResourceDictionary dictionary)
        {
            IDictionary? raw;
            try { raw = BaseDictionary?.GetValue(dictionary) as IDictionary; }
            catch (Exception) { yield break; }
            if (raw == null) yield break;
            foreach (DictionaryEntry entry in raw)
            {
                string? name = entry.Value?.GetType().FullName;
                // The framework keeps a deferred resource as a KeyRecord (loaded from compiled XAML) or a DeferredResourceReference until it is first used.
                if (name != null && (name.StartsWith("System.Windows.Baml2006.", StringComparison.Ordinal) || name.StartsWith("System.Windows.Deferred", StringComparison.Ordinal))) continue;
                yield return entry;
            }
        }

        private ValueDto Serialize(object? value, Type? declared)
        {
            try { return ValueSerializer.Serialize(value, declared ?? typeof(object), registry, dispatcher); }
            catch (Exception exception) { return Failure(exception, declared ?? typeof(object)); }
        }

        private static ValueDto Failure(Exception exception, Type declared) =>
            new ValueDto { Status = ValueStatus.Exception, Kind = ValueKind.Unavailable, DeclaredType = Declaration.TypeName(declared), Message = exception.GetType().FullName, ErrorMessage = ValueSerializer.ErrorMessage(exception), FailedSegment = 0 };

        private static ValueDto Redacted(string rule) => new ValueDto { Status = ValueStatus.Redacted, Kind = ValueKind.Unavailable, RedactionRule = rule };

        private static string? Clip(string? text)
        {
            if (text == null) return null;
            if (text.Length <= StylingLimits.MaxText) return text;
            int end = StylingLimits.MaxText;
            if (char.IsHighSurrogate(text[end - 1])) end--;
            return text.Substring(0, end);
        }

        private sealed class IdentityComparer<T> : IEqualityComparer<T> where T : class
        {
            public bool Equals(T? left, T? right) => ReferenceEquals(left, right);
            public int GetHashCode(T value) => RuntimeHelpers.GetHashCode(value);
        }
    }
}
