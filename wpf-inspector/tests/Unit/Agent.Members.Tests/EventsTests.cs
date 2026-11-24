using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Windows;
using System.Windows.Controls;
using WinTestKit.Inspector.Agent.Inspection.Members;
using WinTestKit.Inspector.Protocol;
using Xunit;

namespace WinTestKit.Inspector.Agent.Members.Tests
{
    public class Publisher
    {
        public event EventHandler? Changed;
        public static event EventHandler? Idle;
        public event EventHandler? Quiet;
        public event EventHandler<EventArgs> Explicit { add { } remove { } }
        public void RaiseNothing() { Changed?.Invoke(this, EventArgs.Empty); Idle?.Invoke(null, EventArgs.Empty); Quiet?.Invoke(this, EventArgs.Empty); }
        public static void ClearIdle() { Idle = null; }
    }

    [Trait("Category", "Unit")]
    public sealed class EventsTests
    {
        private static int calls;
        private static void Count(object? sender, EventArgs e) { calls++; throw new InvalidOperationException("handler invoked"); }
        private static void CountRouted(object sender, RoutedEventArgs e) { calls++; throw new InvalidOperationException("handler invoked"); }
        private void Instance(object? sender, EventArgs e) { calls++; }

        private static IReadOnlyList<MemberEventDto> Read(object target, IEventStores? stores = null)
        {
            var events = new EventsReader(stores).Read(target);
            // Every event survives the wire: the reader never produces something the protocol rejects.
            foreach (var item in events) { byte[] json = StrictJson.Serialize(item.ToJson()); Assert.Equal(json, StrictJson.Serialize(MemberEventDto.FromJson(StrictJson.Parse(json, 0, json.Length)).ToJson())); }
            return events;
        }

        private static MemberEventDto Find(IReadOnlyList<MemberEventDto> events, string name, string kind) => events.Single(item => item.Name == name && item.Kind == kind);

        private sealed class UnknownStores : IEventStores
        {
            public IReadOnlyList<RoutedHandlerEntry>? RoutedHandlers(DependencyObject target, RoutedEvent routedEvent) => null;
            public bool TryReadDelegate(object target, EventInfo clrEvent, out Delegate? current) { current = null; return false; }
        }

        private sealed class ThrowingStores : IEventStores
        {
            public IReadOnlyList<RoutedHandlerEntry>? RoutedHandlers(DependencyObject target, RoutedEvent routedEvent) => throw new InvalidOperationException("private state moved");
            public bool TryReadDelegate(object target, EventInfo clrEvent, out Delegate? current) => throw new InvalidOperationException("private state moved");
        }

        [Fact]
        public void RoutedEventsListTheirTypeStrategyAndEveryOwnerLevel()
        {
            ValueTestSupport.Sta(() =>
            {
                var events = Read(new Button());
                var click = Find(events, "Click", "routed");
                Assert.Equal("bubble", click.Strategy);
                Assert.Equal("System.Windows.RoutedEventHandler", click.HandlerType);
                Assert.Equal("System.Windows.Controls.Primitives.ButtonBase", click.DeclaringType);
                Assert.Equal("tunnel", Find(events, "PreviewMouseDown", "routed").Strategy);
                Assert.Equal("System.Windows.UIElement", Find(events, "PreviewMouseDown", "routed").DeclaringType);
                Assert.Equal("System.Windows.FrameworkElement", Find(events, "Loaded", "routed").DeclaringType);
                Assert.Equal("direct", Find(events, "MouseEnter", "routed").Strategy);
                Assert.NotNull(Find(events, "MouseDoubleClick", "routed"));
                Assert.True(events.Where(item => item.Kind == "routed").All(item => item.Known));
                Assert.Equal(events.Count(item => item.Kind == "routed"), events.Where(item => item.Kind == "routed").Select(item => item.Name + "|" + item.HandlerType).Distinct().Count());
            });
        }

        [Fact]
        public void ClrEventsThatWrapRoutedEventsAreListedOnlyAsRouted()
        {
            ValueTestSupport.Sta(() =>
            {
                var events = Read(new Button());
                Assert.Single(events, item => item.Name == "Click");
                Assert.Single(events, item => item.Name == "MouseDown");
                Assert.DoesNotContain(events, item => item.Kind == "clr" && item.Name == "Click");
                // A CLR event that no routed event stands for stays.
                Assert.NotNull(Find(events, "Initialized", "clr"));
                Assert.Equal("System.EventHandler", Find(events, "Initialized", "clr").HandlerType);
                Assert.Equal("System.Windows.FrameworkElement", Find(events, "Initialized", "clr").DeclaringType);
            });
        }

        [Fact]
        public void CodeHandlersAreListedWithTheirMethodAndWhetherTheyTakeHandledEvents()
        {
            ValueTestSupport.Sta(() =>
            {
                calls = 0;
                var button = new Button();
                button.Click += CountRouted;
                button.AddHandler(Button.ClickEvent, new RoutedEventHandler(CountRouted), true);
                button.Click += (sender, args) => calls++;
                var click = Find(Read(button), "Click", "routed");
                Assert.True(click.Known);
                Assert.Equal(3, click.Count);
                Assert.False(click.Truncated);
                Assert.Equal(1, click.Handlers.Count(item => item.HandledEventsToo == true));
                Assert.Equal(2, click.Handlers.Count(item => item.HandledEventsToo == false));
                Assert.Equal(2, click.Handlers.Count(item => item.DeclaringType == typeof(EventsTests).FullName && item.Method == nameof(CountRouted)));
                Assert.Equal(nameof(CountRouted), click.Handlers.Single(item => item.HandledEventsToo == true).Method);
                // A lambda is a method of the compiler's closure class: still a type and a method name.
                var lambda = click.Handlers.Single(item => item.Method != nameof(CountRouted));
                Assert.Contains("EventsTests", lambda.DeclaringType);
                Assert.NotEqual("", lambda.Method);
                Assert.Equal(0, Find(Read(button), "MouseDown", "routed").Count);
                Assert.Equal(0, calls);
            });
        }

        [Fact]
        public void HandlersWiredInCompiledXamlAreListed()
        {
            ValueTestSupport.Sta(() =>
            {
                HandlerHost.Invocations = 0;
                var host = new HandlerHost();
                var events = Read(host.Target);
                var click = Find(events, "Click", "routed");
                Assert.Equal(1, click.Count);
                Assert.Equal(typeof(HandlerHost).FullName, click.Handlers[0].DeclaringType);
                Assert.Equal("OnClick", click.Handlers[0].Method);
                Assert.False(click.Handlers[0].HandledEventsToo);
                var preview = Find(events, "PreviewMouseDown", "routed");
                Assert.Equal("OnPreview", Assert.Single(preview.Handlers).Method);
                Assert.Equal(0, HandlerHost.Invocations);
                Assert.Equal(0, Find(Read(host), "PreviewMouseDown", "routed").Count);
            });
        }

        [Fact]
        public void HandlerListsAreCappedAtThirtyTwo()
        {
            ValueTestSupport.Sta(() =>
            {
                var button = new Button();
                for (int index = 0; index < 40; index++) button.Click += CountRouted;
                var click = Find(Read(button), "Click", "routed");
                Assert.Equal(40, click.Count);
                Assert.Equal(MemberEventLimits.MaxHandlers, click.Handlers.Count);
                Assert.True(click.Truncated);
                var publisher = new Publisher();
                for (int index = 0; index < 33; index++) publisher.Changed += Count;
                var changed = Find(Read(publisher), "Changed", "clr");
                Assert.Equal(33, changed.Count);
                Assert.Equal(MemberEventLimits.MaxHandlers, changed.Handlers.Count);
                Assert.True(changed.Truncated);
            });
        }

        [Fact]
        public void ClrEventsListTheirSubscribersFromTheBackingField()
        {
            ValueTestSupport.Sta(() =>
            {
                calls = 0;
                var publisher = new Publisher();
                publisher.Changed += Count;
                publisher.Changed += new EventsTests().Instance;
                var events = Read(publisher);
                var changed = Find(events, "Changed", "clr");
                Assert.True(changed.Known);
                Assert.False(changed.IsStatic);
                Assert.Equal(typeof(Publisher).FullName, changed.DeclaringType);
                Assert.Equal("System.EventHandler", changed.HandlerType);
                Assert.Equal(new[] { nameof(Count), nameof(Instance) }, changed.Handlers.Select(item => item.Method));
                Assert.All(changed.Handlers, item => { Assert.Equal(typeof(EventsTests).FullName, item.DeclaringType); Assert.Null(item.HandledEventsToo); });
                var quiet = Find(events, "Quiet", "clr");
                Assert.True(quiet.Known);
                Assert.Equal(0, quiet.Count);
                // An event written with add and remove accessors has no field to read.
                Assert.False(Find(events, "Explicit", "clr").Known);
                Assert.Equal(0, calls);
            });
        }

        [Fact]
        public void StaticClrEventsAreMarkedAndListTheirSubscribers()
        {
            ValueTestSupport.Sta(() =>
            {
                calls = 0;
                Publisher.Idle += Count;
                try
                {
                    var idle = Find(Read(new Publisher()), "Idle", "clr");
                    Assert.True(idle.IsStatic);
                    Assert.True(idle.Known);
                    Assert.Equal(nameof(Count), Assert.Single(idle.Handlers).Method);
                    Assert.Equal(0, calls);
                }
                finally { Publisher.ClearIdle(); }
            });
        }

        [Fact]
        public void HandlersAreUnknownWhenTheFrameworkStateCannotBeRead()
        {
            ValueTestSupport.Sta(() =>
            {
                var button = new Button();
                button.Click += CountRouted;
                var publisher = new Publisher();
                publisher.Changed += Count;
                foreach (IEventStores stores in new IEventStores[] { new UnknownStores(), new ThrowingStores() })
                {
                    var events = Read(button, stores);
                    var click = Find(events, "Click", "routed");
                    Assert.False(click.Known);
                    Assert.Empty(click.Handlers);
                    Assert.Equal(0, click.Count);
                    Assert.All(events, item => Assert.False(item.Known));
                    var changed = Find(Read(publisher, stores), "Changed", "clr");
                    Assert.False(changed.Known);
                    Assert.Empty(changed.Handlers);
                }
                // The names and kinds do not depend on the stores.
                Assert.Equal(Read(button).Select(item => item.Kind + ":" + item.Name), Read(button, new UnknownStores()).Select(item => item.Kind + ":" + item.Name));
            });
        }

        [Fact]
        public void ReadingNeverCallsAHandler()
        {
            ValueTestSupport.Sta(() =>
            {
                calls = 0; HandlerHost.Invocations = 0;
                var button = new Button();
                button.Click += CountRouted;
                button.Loaded += CountRouted;
                var publisher = new Publisher();
                publisher.Changed += Count;
                Read(button); Read(publisher); Read(new HandlerHost());
                Assert.Equal(0, calls);
                Assert.Equal(0, HandlerHost.Invocations);
            });
        }

        [Fact]
        public void PasswordFieldsListEventNamesAndNothingAboutWhoListens()
        {
            ValueTestSupport.Sta(() =>
            {
                calls = 0;
                var box = new PasswordBox();
                box.PasswordChanged += CountRouted;
                box.GotFocus += CountRouted;
                var events = Read(box);
                var changed = Find(events, "PasswordChanged", "routed");
                Assert.False(changed.Known);
                Assert.Empty(changed.Handlers);
                Assert.All(events, item => { Assert.False(item.Known); Assert.Empty(item.Handlers); Assert.Equal(0, item.Count); });
                Assert.Contains(events, item => item.Name == "GotFocus");
                Assert.Equal(0, calls);
            });
        }

        [Fact]
        public void ObjectsThatAreNotDependencyObjectsHaveOnlyClrEvents()
        {
            ValueTestSupport.Sta(() =>
            {
                var events = Read(new Publisher());
                Assert.All(events, item => Assert.Equal("clr", item.Kind));
                Assert.Equal(new[] { "Changed", "Explicit", "Idle", "Quiet" }, events.Select(item => item.Name).OrderBy(name => name, StringComparer.Ordinal));
                Assert.Empty(Read("text"));
            });
        }

        [Fact]
        public void TheSerializedAnswerNamesMethodsOnly()
        {
            ValueTestSupport.Sta(() =>
            {
                var button = new Button { Tag = "hunter2" };
                button.Click += CountRouted;
                string json = Encoding.UTF8.GetString(StrictJson.Serialize(new PageDto<MemberEventDto> { Items = Read(button), Complete = true, SnapshotId = "s" }.ToJson()));
                Assert.DoesNotContain("hunter2", json);
                Assert.Contains("\"method\":\"CountRouted\"", json);
            });
        }
    }
}
