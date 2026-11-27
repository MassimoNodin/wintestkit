using System;
using System.Collections.Generic;
using System.Reflection;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Media;
using System.Windows.Media.Media3D;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Contracts;
using WinTestKit.Inspector.Agent.Mapping;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Inspection.Members
{
    /// <summary>
    /// The object tree of the migration model: the WPF visual tree without the elements a control's templates and its items panel
    /// create. An element is hidden when its TemplatedParent is a Control (ControlTemplate parts) or an ItemsPresenter (ItemsPanel
    /// instances); content created by a DataTemplate (TemplatedParent is a ContentPresenter) and elements without a TemplatedParent
    /// stay. The visible descendants of a hidden element belong to its nearest visible ancestor, in visual order.
    /// </summary>
    internal static class ObjectTree
    {
        internal static bool Hidden(DependencyObject value)
        {
            object? parent = (value as FrameworkElement)?.TemplatedParent ?? (value as FrameworkContentElement)?.TemplatedParent;
            return parent is Control || parent is ItemsPresenter;
        }

        /// <summary>The object-tree children of <paramref name="parent"/> in visual order.</summary>
        internal static IEnumerable<DependencyObject> Children(DependencyObject parent)
        {
            foreach (DependencyObject child in VisualChildren(parent))
            {
                if (!Hidden(child)) yield return child;
                else foreach (DependencyObject descendant in Children(child)) yield return descendant;
            }
        }

        /// <summary>The nearest visible visual ancestor, or null for a root.</summary>
        internal static DependencyObject? Parent(DependencyObject value)
        {
            DependencyObject? parent = VisualParent(value);
            while (parent != null && Hidden(parent)) parent = VisualParent(parent);
            return parent;
        }

        /// <summary>The 1-based position among the object-tree siblings of the same runtime type; 1 for a root.</summary>
        internal static int Ordinal(DependencyObject value) => Ordinals(value).Ordinal(value);

        internal static OrdinalMap Ordinals(DependencyObject value)
        {
            // A hidden element has no object-tree position; its own visual siblings stand in for them.
            if (Hidden(value))
            {
                DependencyObject? visualParent = VisualParent(value);
                return new OrdinalMap(visualParent, VisualChildren(visualParent));
            }
            DependencyObject? parent = Parent(value);
            return new OrdinalMap(parent, parent == null ? null : Children(parent));
        }

        private static IEnumerable<DependencyObject> VisualChildren(DependencyObject? parent)
        {
            if (parent == null || !(parent is Visual || parent is Visual3D)) yield break;
            int count = VisualTreeHelper.GetChildrenCount(parent);
            for (int index = 0; index < count; index++) yield return VisualTreeHelper.GetChild(parent, index);
        }

        private static DependencyObject? VisualParent(DependencyObject value) =>
            value is Visual || value is Visual3D ? VisualTreeHelper.GetParent(value) : null;

        /// <summary>The same-type ordinals of one parent's children, computed in one pass.</summary>
        internal sealed class OrdinalMap
        {
            private readonly Dictionary<object, int> ordinals = new Dictionary<object, int>(ReferenceComparer.Instance);
            internal OrdinalMap(DependencyObject? parent, IEnumerable<DependencyObject>? children)
            {
                Parent = parent;
                if (children == null) return;
                var counts = new Dictionary<Type, int>();
                foreach (DependencyObject child in children)
                {
                    counts.TryGetValue(child.GetType(), out int count);
                    counts[child.GetType()] = ++count;
                    ordinals[child] = count;
                }
            }
            internal DependencyObject? Parent { get; }
            internal int Ordinal(DependencyObject value) => ordinals.TryGetValue(value, out int ordinal) ? ordinal : 1;
        }
    }

    /// <summary>Ordinals of the last parent that was asked about; a traversal asks about siblings one after another. Cleared for every slice.</summary>
    internal sealed class ObjectTreeCache
    {
        private DependencyObject? parent;
        private ObjectTree.OrdinalMap? map;

        internal void Clear() { parent = null; map = null; }

        internal int Ordinal(DependencyObject value)
        {
            if (ObjectTree.Hidden(value)) return ObjectTree.Ordinal(value);
            DependencyObject? actual = ObjectTree.Parent(value);
            if (actual == null) return 1;
            if (map == null || !ReferenceEquals(parent, actual))
            {
                map = ObjectTree.Ordinals(value);
                parent = actual;
            }
            return map.Ordinal(value);
        }
    }

    /// <summary>
    /// The managed keys <c>wpf:Text</c> and <c>wpf:Ordinal</c>. Text reads execute application code (getters and ToString overrides), so
    /// they follow the rules of any managed read: protected identities and redacted member or type names give a redacted result, a
    /// throwing getter gives an unreadable result with the sanitized error, and the request token ends a read that runs too long.
    /// </summary>
    internal static class ObjectTreeValues
    {
        internal static ValueDto Read(object root, string name, RedactionPolicy redaction, IObjectRegistry registry, Dispatcher dispatcher, CancellationToken ct, ObjectTreeCache? cache)
        {
            ct.ThrowIfCancellationRequested();
            try
            {
                if (name == "Ordinal")
                {
                    if (WinFormsNative.IsWinFormsObject(root)) return ValueSerializer.Serialize(WinFormsNative.Ordinal(root), typeof(int), registry, dispatcher);
                    if (!(root is DependencyObject element)) return new ValueDto { Status = "unavailable", Kind = "unavailable" };
                    int ordinal = cache != null ? cache.Ordinal(element) : ObjectTree.Ordinal(element);
                    return ValueSerializer.Serialize(ordinal, typeof(int), registry, dispatcher);
                }
                if (name != "Text") throw new ProtocolException(ErrorCodes.MemberNotFound, "Member was not found");
                string text = Text(root, redaction, ct, new HashSet<object>(ReferenceComparer.Instance));
                return ValueSerializer.Serialize(text, typeof(string), registry, dispatcher);
            }
            catch (Unreadable unreadable) { return unreadable.Value; }
        }

        private static string Text(object? value, RedactionPolicy redaction, CancellationToken ct, HashSet<object> seen)
        {
            ct.ThrowIfCancellationRequested();
            if (value == null) return string.Empty;
            if (value is string text) return text;
            if (WinFormsNative.IsWinFormsObject(value))
            {
                if (RedactionPolicy.IsProtectedIdentity(value)) throw new Unreadable(new ValueDto { Status = "redacted", Kind = "unavailable", RedactionRule = "identity" });
                if (!seen.Add(value)) return string.Empty;
                return Member("Text", redaction, ct, seen, () => WinFormsNative.Text(value));
            }
            if (value is UIElement || value is ContentElement)
            {
                var element = (DependencyObject)value;
                if (RedactionPolicy.IsProtectedIdentity(element)) throw new Unreadable(new ValueDto { Status = "redacted", Kind = "unavailable", RedactionRule = "identity" });
                if (!seen.Add(element)) return string.Empty;
                return ElementText(element, redaction, ct, seen);
            }
            return Rendered(value, redaction);
        }

        private static string ElementText(DependencyObject element, RedactionPolicy redaction, CancellationToken ct, HashSet<object> seen)
        {
            if (element is TextBlock block) return Member("Text", redaction, ct, seen, () => block.Text);
            if (element is TextBoxBase)
            {
                if (element is TextBox box) return Member("Text", redaction, ct, seen, () => box.Text);
                PropertyInfo? property = Guard(() => element.GetType().GetProperty("Text", BindingFlags.Public | BindingFlags.Instance, null, typeof(string), Type.EmptyTypes, null));
                return property == null ? string.Empty : Member("Text", redaction, ct, seen, () => property.GetValue(element, null));
            }
            if (element is Window window) return Member("Title", redaction, ct, seen, () => window.Title);
            if (element is HeaderedContentControl headeredContent)
            {
                string content = Member("Content", redaction, ct, seen, () => headeredContent.Content);
                return content.Length != 0 ? content : Member("Header", redaction, ct, seen, () => headeredContent.Header);
            }
            if (element is HeaderedItemsControl headeredItems) return Member("Header", redaction, ct, seen, () => headeredItems.Header);
            if (element is ContentControl control) return Member("Content", redaction, ct, seen, () => control.Content);
            if (element is ContentPresenter presenter) return Member("Content", redaction, ct, seen, () => presenter.Content);
            return string.Empty;
        }

        private static string Member(string memberName, RedactionPolicy redaction, CancellationToken ct, HashSet<object> seen, Func<object?> read)
        {
            string? rule = redaction.Match(memberName);
            if (rule != null) throw new Unreadable(new ValueDto { Status = "redacted", Kind = "unavailable", RedactionRule = rule });
            object? value = Guard(read);
            ct.ThrowIfCancellationRequested();
            return Text(value, redaction, ct, seen);
        }

        /// <summary>ToString() of a value whose runtime type overrides it (declared anywhere but System.Object); empty otherwise.</summary>
        private static string Rendered(object value, RedactionPolicy redaction)
        {
            Type type = value.GetType();
            MethodInfo? method = Guard(() => type.GetMethod(nameof(ToString), Type.EmptyTypes));
            if (method == null || method.DeclaringType == typeof(object)) return string.Empty;
            string? rule = redaction.Match(type.Name);
            if (rule != null) throw new Unreadable(new ValueDto { Status = "redacted", Kind = "unavailable", RedactionRule = rule });
            return Guard(() => value.ToString()) ?? string.Empty;
        }

        /// <summary>Runs application code; a failure becomes an unreadable result that carries the sanitized error.</summary>
        private static T Guard<T>(Func<T> action)
        {
            try { return action(); }
            catch (OperationCanceledException) { throw; }
            catch (Exception ex)
            {
                Exception actual = ex is TargetInvocationException invocation && invocation.InnerException != null ? invocation.InnerException : ex;
                throw new Unreadable(new ValueDto { Status = "exception", Kind = "unavailable", DeclaredType = "System.String", Message = actual.GetType().FullName, ErrorMessage = ValueSerializer.ErrorMessage(actual), FailedSegment = 0 });
            }
        }

        private sealed class Unreadable : Exception
        {
            internal Unreadable(ValueDto value) { Value = value; }
            internal ValueDto Value { get; }
        }
    }
}
