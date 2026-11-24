using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Inspection;
using WinTestKit.Inspector.Agent.Inspection.Members;
using WinTestKit.Inspector.Protocol;
using Xunit;

namespace WinTestKit.Inspector.Agent.Mapping.Tests
{
    [Collection("WPF dispatchers")]
    [Trait("Category", "Unit")]
    public sealed class EventsServiceTests
    {
        private static int calls;
        private static void Throwing(object sender, RoutedEventArgs e) { calls++; throw new InvalidOperationException("handler invoked"); }

        private sealed class UnreadableStores : IEventStores
        {
            public IReadOnlyList<RoutedHandlerEntry>? RoutedHandlers(DependencyObject target, RoutedEvent routedEvent) => null;
            public bool TryReadDelegate(object target, EventInfo clrEvent, out Delegate? current) { current = null; return false; }
        }

        private static async Task Run(Func<WpfInspectionService, Dispatcher, Func<object, ObjectRef>, Task> test)
        {
            var ready = new TaskCompletionSource<Dispatcher>();
            var thread = new Thread(() => { var dispatcher = Dispatcher.CurrentDispatcher; ready.SetResult(dispatcher); Dispatcher.Run(); });
            thread.SetApartmentState(ApartmentState.STA); thread.Start();
            var dispatcher = await ready.Task;
            try
            {
                using (var service = new WpfInspectionService("events", new ObjectInspector()))
                {
                    var registry = (ObjectRegistry)typeof(WpfInspectionService).GetField("registry", BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(service)!;
                    await test(service, dispatcher, target => registry.Register(target, dispatcher, new ObjectInspector().DescribeType(target.GetType())));
                }
            }
            finally { dispatcher.InvokeShutdown(); thread.Join(); }
        }

        private static async Task<List<MemberEventDto>> All(WpfInspectionService service, ObjectRef handle, int pageSize)
        {
            var events = new List<MemberEventDto>();
            string? token = null;
            for (int pages = 0; pages < 100; pages++)
            {
                var page = await service.EventsAsync(handle.ObjectId, handle.Generation, pageSize, token, CancellationToken.None);
                Assert.True(page.Items.Count <= pageSize);
                events.AddRange(page.Items);
                byte[] json = StrictJson.Serialize(page.ToJson());
                Assert.Equal(json, StrictJson.Serialize(PageDto<MemberEventDto>.FromJson(StrictJson.Parse(json, 0, json.Length), MemberEventDto.FromJson).ToJson()));
                if (page.NextToken == null) { Assert.True(page.Complete); return events; }
                Assert.False(page.Complete);
                token = page.NextToken;
            }
            throw new InvalidOperationException("The pages did not end.");
        }

        [Fact]
        public async Task EventsArePagedAndEventsWithHandlersComeFirst()
        {
            await Run(async (service, dispatcher, register) =>
            {
                calls = 0;
                var button = await dispatcher.InvokeAsync(() => { var control = new Button(); control.Click += Throwing; control.AddHandler(UIElement.MouseUpEvent, new System.Windows.Input.MouseButtonEventHandler((s, e) => calls++), true); return control; });
                var handle = register(button);
                var whole = await service.EventsAsync(handle.ObjectId, handle.Generation, ProtocolLimits.MaxPageSize, null, CancellationToken.None);
                Assert.True(whole.Items.Count > 40, "A button has many events.");
                var paged = await All(service, handle, 25);
                Assert.True(paged.Count > 25);
                Assert.Equal(ProtocolLimits.MaxPageSize >= paged.Count ? whole.Items.Count : paged.Count, paged.Count);
                Assert.Equal(paged.Count, paged.Select(item => item.Kind + "|" + item.DeclaringType + "|" + item.Name).Distinct().Count());
                Assert.Equal(new[] { "Click", "MouseUp" }, paged.Take(2).Select(item => item.Name).OrderBy(name => name, StringComparer.Ordinal));
                Assert.All(paged.Take(2), item => Assert.Equal(1, item.Count));
                int firstWithout = paged.FindIndex(item => item.Count == 0);
                Assert.Equal(2, firstWithout);
                Assert.True(paged.Skip(firstWithout).All(item => item.Count == 0));
                Assert.Equal(paged.Skip(firstWithout).Select(item => item.Name).OrderBy(name => name, StringComparer.Ordinal).ToArray(), paged.Skip(firstWithout).Select(item => item.Name).ToArray());
                Assert.Equal(0, calls);
                var stale = await Assert.ThrowsAsync<ProtocolException>(() => service.EventsAsync(handle.ObjectId, handle.Generation + 1, 10, null, CancellationToken.None));
                Assert.Equal(ErrorCodes.ObjectStale, stale.Code);
                await Assert.ThrowsAsync<ProtocolException>(() => service.EventsAsync(handle.ObjectId, handle.Generation, ProtocolLimits.MaxPageSize + 1, null, CancellationToken.None));
                await Assert.ThrowsAsync<ProtocolException>(() => service.EventsAsync(handle.ObjectId, handle.Generation, 10, "nope.nope", CancellationToken.None));
            });
        }

        [Fact]
        public async Task UnreadableFrameworkStateIsReportedAsUnknownNeverAsAnError()
        {
            await Run(async (service, dispatcher, register) =>
            {
                service.EventStores = new UnreadableStores();
                var button = await dispatcher.InvokeAsync(() => { var control = new Button(); control.Click += Throwing; return control; });
                var handle = register(button);
                var events = await All(service, handle, 50);
                Assert.NotEmpty(events);
                Assert.All(events, item => { Assert.False(item.Known); Assert.Empty(item.Handlers); });
                Assert.Contains(events, item => item.Name == "Click" && item.Kind == "routed");
            });
        }

        [Fact]
        public async Task PasswordFieldsListNamesOnly()
        {
            await Run(async (service, dispatcher, register) =>
            {
                calls = 0;
                var box = await dispatcher.InvokeAsync(() => { var control = new PasswordBox(); control.PasswordChanged += Throwing; return control; });
                var events = await All(service, register(box), 100);
                Assert.Contains(events, item => item.Name == "PasswordChanged");
                Assert.All(events, item => { Assert.False(item.Known); Assert.Empty(item.Handlers); Assert.Equal(0, item.Count); });
                Assert.Equal(0, calls);
            });
        }

        [Fact]
        public async Task ResourceReadsOneValueOnTheTargetDispatcher()
        {
            await Run(async (service, dispatcher, register) =>
            {
                var panel = await dispatcher.InvokeAsync(() => { var control = new StackPanel(); control.Resources.Add("Title", "Hello"); control.Resources.Add("Brush", new System.Windows.Media.SolidColorBrush(System.Windows.Media.Colors.Red)); return control; });
                var handle = register(panel);
                var styling = await service.StylingAsync(handle.ObjectId, handle.Generation, CancellationToken.None);
                var title = styling.Resources!.Entries.Single(item => item.Key == "Title");
                var read = await service.ResourceAsync(handle.ObjectId, handle.Generation, "local", title.Key, title.KeyKind, title.Index, CancellationToken.None);
                Assert.True(read.Found);
                Assert.Equal("System.String", read.ValueType);
                Assert.Equal("Hello", Assert.IsType<JsonStringNode>(read.Value!.Scalar).Value);
                var brush = styling.Resources.Entries.Single(item => item.Key == "Brush");
                var object1 = await service.ResourceAsync(handle.ObjectId, handle.Generation, "local", brush.Key, brush.KeyKind, null, CancellationToken.None);
                Assert.NotNull(object1.Value!.Object);
                Assert.False((await service.ResourceAsync(handle.ObjectId, handle.Generation, "local", "Missing", "string", 0, CancellationToken.None)).Found);
                Assert.False((await service.ResourceAsync(handle.ObjectId, handle.Generation, "application", "Title", "string", 0, CancellationToken.None)).Found);
                var plain = register("text");
                Assert.False((await service.ResourceAsync(plain.ObjectId, plain.Generation, "local", "Title", "string", 0, CancellationToken.None)).Found);
                var stale = await Assert.ThrowsAsync<ProtocolException>(() => service.ResourceAsync(handle.ObjectId, handle.Generation + 1, "local", "Title", "string", 0, CancellationToken.None));
                Assert.Equal(ErrorCodes.ObjectStale, stale.Code);
            });
        }
    }
}
