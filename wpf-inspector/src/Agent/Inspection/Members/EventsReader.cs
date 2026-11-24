using System;
using System.Collections.Generic;

using System.Reflection;
using System.Windows;
using System.Windows.Media.Media3D;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Inspection.Members
{
    /// <summary>One handler an element's event store holds for a routed event.</summary>
    internal readonly struct RoutedHandlerEntry
    {
        internal RoutedHandlerEntry(Delegate handler, bool handledEventsToo) { Handler = handler; HandledEventsToo = handledEventsToo; }
        internal Delegate Handler { get; }
        internal bool HandledEventsToo { get; }
    }

    /// <summary>
    /// Where the reader finds out who handles an event. It is the only code that touches the framework's private state, kept behind a seam so a
    /// framework that moved its internals (or a test) can make it answer "unknown". Nothing here invokes a handler.
    /// </summary>
    internal interface IEventStores
    {
        /// <returns>The instance handlers of a routed event on the element; null when they cannot be read.</returns>
        IReadOnlyList<RoutedHandlerEntry>? RoutedHandlers(DependencyObject target, RoutedEvent routedEvent);

        /// <returns>False when the CLR event has no backing delegate the reader can find; otherwise the delegate (null when nobody subscribed).</returns>
        bool TryReadDelegate(object target, EventInfo clrEvent, out Delegate? current);
    }

    /// <summary>The default seam: the internal EventHandlersStore of UIElement, ContentElement and UIElement3D, and a CLR event's backing field.</summary>
    internal sealed class ReflectedEventStores : IEventStores
    {
        private const BindingFlags Any = BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
        private static readonly PropertyInfo? ElementStore = typeof(UIElement).GetProperty("EventHandlersStore", BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public);
        private static readonly PropertyInfo? ContentStore = typeof(ContentElement).GetProperty("EventHandlersStore", BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public);
        private static readonly PropertyInfo? Element3DStore = typeof(UIElement3D).GetProperty("EventHandlersStore", BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public);

        public IReadOnlyList<RoutedHandlerEntry>? RoutedHandlers(DependencyObject target, RoutedEvent routedEvent)
        {
            try
            {
                PropertyInfo? property = target is UIElement ? ElementStore : target is ContentElement ? ContentStore : target is UIElement3D ? Element3DStore : null;
                // Anything else has no routed handlers to read: it is not an event source.
                if (property == null) return target is UIElement || target is ContentElement || target is UIElement3D ? null : new RoutedHandlerEntry[0];
                object? store = property.GetValue(target);
                if (store == null) return new RoutedHandlerEntry[0];
                MethodInfo? method = store.GetType().GetMethod("GetRoutedEventHandlers", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, new[] { typeof(RoutedEvent) }, null);
                if (method == null) return null;
                var infos = method.Invoke(store, new object[] { routedEvent }) as RoutedEventHandlerInfo[];
                var result = new List<RoutedHandlerEntry>();
                if (infos != null) foreach (RoutedEventHandlerInfo info in infos) if (info.Handler != null) result.Add(new RoutedHandlerEntry(info.Handler, info.InvokeHandledEventsToo));
                return result;
            }
            catch (Exception) { return null; }
        }

        public bool TryReadDelegate(object target, EventInfo clrEvent, out Delegate? current)
        {
            current = null;
            try
            {
                Type? declaring = clrEvent.DeclaringType;
                Type? handlerType = clrEvent.EventHandlerType;
                if (declaring == null || handlerType == null) return false;
                bool isStatic = clrEvent.GetAddMethod(true)?.IsStatic ?? clrEvent.GetRemoveMethod(true)?.IsStatic ?? false;
                // A field-like event's backing field has the event's name (C#) or the name and "Event" (Visual Basic).
                foreach (string name in new[] { clrEvent.Name, clrEvent.Name + "Event" })
                {
                    FieldInfo? field = declaring.GetField(name, Any);
                    if (field == null || field.IsStatic != isStatic || field.FieldType != handlerType) continue;
                    current = (Delegate?)field.GetValue(isStatic ? null : target);
                    return true;
                }
                return false;
            }
            catch (Exception) { current = null; return false; }
        }
    }

    /// <summary>
    /// Lists the events of an object and who handles them, from metadata and delegate lists only: no handler runs and no getter is read.
    /// Must be called on the object's dispatcher.
    /// </summary>
    internal sealed class EventsReader
    {
        private const BindingFlags Declared = BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
        private readonly IEventStores stores;

        internal EventsReader(IEventStores? stores = null) { this.stores = stores ?? new ReflectedEventStores(); }

        internal IReadOnlyList<MemberEventDto> Read(object target)
        {
            // A password field lists its events by name and nothing about who listens.
            bool protectedTarget = RedactionPolicy.IsProtectedIdentity(target);
            var events = new List<MemberEventDto>();
            var routedNames = new HashSet<string>(StringComparer.Ordinal);
            if (target is DependencyObject dependency) AddRouted(dependency, protectedTarget, events, routedNames);
            AddClr(target, protectedTarget, events, routedNames);
            return events;
        }

        private static List<Type> Hierarchy(Type type)
        {
            var levels = new List<Type>();
            for (Type? current = type; current != null; current = current.BaseType) levels.Add(current);
            levels.Reverse();
            return levels;
        }

        private void AddRouted(DependencyObject target, bool protectedTarget, List<MemberEventDto> events, HashSet<string> routedNames)
        {
            var seen = new HashSet<RoutedEvent>();
            foreach (Type level in Hierarchy(target.GetType()))
            {
                RoutedEvent[]? owned;
                try { owned = EventManager.GetRoutedEventsForOwner(level); } catch (Exception) { continue; }
                if (owned == null) continue;
                foreach (RoutedEvent routed in owned)
                {
                    if (routed == null || !seen.Add(routed)) continue;
                    var dto = new MemberEventDto
                    {
                        Kind = MemberEventValues.Routed, Name = Clip(routed.Name), DeclaringType = Clip(Declaration.TypeName(level)),
                        HandlerType = Clip(Declaration.TypeName(routed.HandlerType)), Strategy = routed.RoutingStrategy.ToString().ToLowerInvariant(),
                    };
                    routedNames.Add(Key(routed.Name, routed.HandlerType));
                    IReadOnlyList<RoutedHandlerEntry>? handlers = protectedTarget ? null : RoutedHandlersOrNull(target, routed);
                    if (handlers != null)
                    {
                        dto.Known = true;
                        dto.Count = handlers.Count;
                        var listed = new List<MemberEventHandlerDto>();
                        foreach (RoutedHandlerEntry entry in handlers)
                        {
                            if (listed.Count >= MemberEventLimits.MaxHandlers) break;
                            listed.Add(Handler(entry.Handler, entry.HandledEventsToo));
                        }
                        dto.Handlers = listed;
                        dto.Truncated = handlers.Count > listed.Count;
                    }
                    events.Add(dto);
                }
            }
        }

        private void AddClr(object target, bool protectedTarget, List<MemberEventDto> events, HashSet<string> routedNames)
        {
            foreach (Type level in Hierarchy(target.GetType()))
            {
                EventInfo[] declared;
                try { declared = level.GetEvents(Declared); } catch (Exception) { continue; }
                foreach (EventInfo clr in declared)
                {
                    Type? handlerType = null;
                    try { handlerType = clr.EventHandlerType; } catch (Exception) { /* listed without a handler type below */ }
                    // A CLR event that wraps a routed event (Button.Click wraps ButtonBase.ClickEvent) is the routed event: it is listed once, as routed.
                    if (handlerType != null && routedNames.Contains(Key(clr.Name, handlerType))) continue;
                    bool isStatic = false;
                    try { isStatic = clr.GetAddMethod(true)?.IsStatic ?? clr.GetRemoveMethod(true)?.IsStatic ?? false; } catch (Exception) { /* instance */ }
                    var dto = new MemberEventDto { Kind = MemberEventValues.Clr, Name = Clip(clr.Name), DeclaringType = Clip(Declaration.TypeName(level)), HandlerType = Clip(handlerType == null ? "" : Declaration.TypeName(handlerType)), IsStatic = isStatic };
                    if (!protectedTarget && TryReadDelegateOrUnknown(target, clr, out Delegate? current))
                    {
                        dto.Known = true;
                        Delegate[] invocation = current == null ? new Delegate[0] : InvocationList(current);
                        dto.Count = invocation.Length;
                        var listed = new List<MemberEventHandlerDto>();
                        foreach (Delegate subscriber in invocation)
                        {
                            if (listed.Count >= MemberEventLimits.MaxHandlers) break;
                            listed.Add(Handler(subscriber, null));
                        }
                        dto.Handlers = listed;
                        dto.Truncated = invocation.Length > listed.Count;
                    }
                    events.Add(dto);
                }
            }
        }

        // Whatever the seam does, the request answers: a store that throws is a store that cannot be read.
        private IReadOnlyList<RoutedHandlerEntry>? RoutedHandlersOrNull(DependencyObject target, RoutedEvent routed)
        {
            try { return stores.RoutedHandlers(target, routed); } catch (Exception) { return null; }
        }

        private bool TryReadDelegateOrUnknown(object target, EventInfo clr, out Delegate? current)
        {
            try { return stores.TryReadDelegate(target, clr, out current); } catch (Exception) { current = null; return false; }
        }

        private static string Key(string name, Type handlerType) => name + "\n" + handlerType.FullName;

        private static Delegate[] InvocationList(Delegate current)
        {
            try { return current.GetInvocationList(); } catch (Exception) { return new[] { current }; }
        }

        /// <summary>The method a delegate points at. Reading <see cref="Delegate.Method"/> does not call it.</summary>
        private static MemberEventHandlerDto Handler(Delegate handler, bool? handledEventsToo)
        {
            string type = "", method = "";
            try
            {
                MethodInfo target = handler.Method;
                method = target.Name;
                type = target.DeclaringType == null ? "" : Declaration.TypeName(target.DeclaringType);
            }
            catch (Exception) { /* the entry says what it could */ }
            return new MemberEventHandlerDto { DeclaringType = Clip(type), Method = Clip(method), HandledEventsToo = handledEventsToo };
        }

        private static string Clip(string text)
        {
            if (text.Length <= MemberEventLimits.MaxText) return text;
            int end = MemberEventLimits.MaxText;
            if (char.IsHighSurrogate(text[end - 1])) end--;
            return text.Substring(0, end);
        }
    }
}
