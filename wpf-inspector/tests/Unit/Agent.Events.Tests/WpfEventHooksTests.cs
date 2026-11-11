using System;
using System.Diagnostics;
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

namespace WinTestKit.Inspector.Agent.Events.Tests;

[Trait("Category", "Unit")]
public class WpfEventHooksTests
{
    [Fact]
    public async Task WindowsAndTreesAreObservedOnBothDispatchersAndHooksStop()
    {
        var store = new SubscriptionStore();
        var executor = new DispatcherExecutor();
        using var registry = new ObjectRegistry("test", executor);
        using var hooks = new WpfEventHooks(store, executor, registry, new ObjectInspector());
        var subscription = store.Subscribe(new[] { EventKind.WindowOpened, EventKind.WindowClosed, EventKind.TreeChanged });
        var first = StartDispatcher(); var second = StartDispatcher();
        var d1 = await first.Task; var d2 = await second.Task;
        Window? w1 = null; Window? w2 = null; StackPanel? panel = null;
        try
        {
            await d1.InvokeAsync(() => { panel = new StackPanel(); w1 = new Window { Content = panel }; w1.Show(); });
            var opened1 = await Next(store, EventKind.WindowOpened);
            await d2.InvokeAsync(() => { w2 = new Window { Content = new Button() }; w2.Show(); });
            var opened2 = await Next(store, EventKind.WindowOpened);
            Assert.NotEqual(opened1.Handle!.DispatcherId, opened2.Handle!.DispatcherId);
            Assert.True(registry.TryGet(opened1.Handle.ObjectId, opened1.Handle.Generation, out var target, out _));
            Assert.Same(w1, target);
            await d1.InvokeAsync(() => { panel!.Children.Add(new Button()); panel.Children.Add(new Button()); });
            var changed = await Next(store, EventKind.TreeChanged);
            Assert.Equal(opened1.Handle.ObjectId, changed.Handle!.ObjectId);
            await Task.Delay(300);
            Assert.Null(store.Take());
            await d2.InvokeAsync(() => w2!.Close());
            var closed2 = await Next(store, EventKind.WindowClosed);
            Assert.Equal(opened2.Handle.ObjectId, closed2.Handle!.ObjectId);
            Assert.True(store.Unsubscribe(subscription));
            await d1.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
            await d2.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
            Assert.Null(typeof(WpfEventHooks).GetField("timer", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(hooks));
            Assert.Equal(0, hooks.HandlerCount);
            await d1.InvokeAsync(() => w1!.Close());
            Assert.Null(store.Take());
        }
        finally
        {
            d1.BeginInvokeShutdown(DispatcherPriority.Send);
            d2.BeginInvokeShutdown(DispatcherPriority.Send);
        }
    }

    [Fact]
    public async Task UnwantedKindsAreNotPublished()
    {
        var store = new SubscriptionStore(); var executor = new DispatcherExecutor();
        using var registry = new ObjectRegistry("test", executor);
        using var hooks = new WpfEventHooks(store, executor, registry, new ObjectInspector());
        var subscription = store.Subscribe(new[] { EventKind.WindowClosed });
        var dispatcher = await StartDispatcher().Task;
        Window? window = null;
        try
        {
            await dispatcher.InvokeAsync(() => { window = new Window(); window.Show(); });
            await Task.Delay(500);
            Assert.Null(store.Take());
            await dispatcher.InvokeAsync(() => window!.Close());
            Assert.Equal(EventKind.WindowClosed, (await Next(store, EventKind.WindowClosed)).Kind);
            store.Unsubscribe(subscription);
        }
        finally { dispatcher.BeginInvokeShutdown(DispatcherPriority.Send); }
    }

    private static TaskCompletionSource<Dispatcher> StartDispatcher()
    {
        var ready = new TaskCompletionSource<Dispatcher>();
        var thread = new Thread(() => { ready.SetResult(Dispatcher.CurrentDispatcher); Dispatcher.Run(); });
        thread.SetApartmentState(ApartmentState.STA); thread.IsBackground = true; thread.Start();
        return ready;
    }

    private static async Task<EventsEventParams> Next(SubscriptionStore store, string kind)
    {
        var watch = Stopwatch.StartNew();
        while (watch.Elapsed < TimeSpan.FromSeconds(60))
        {
            var item = store.Take();
            if (item != null) { Assert.Equal(kind, item.Kind); return item; }
            await Task.Delay(20);
        }
        throw new TimeoutException("Expected " + kind);
    }
}
