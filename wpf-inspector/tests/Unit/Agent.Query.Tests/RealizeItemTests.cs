using System;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Actions;
using WinTestKit.Inspector.Agent.Inspection;
using WinTestKit.Inspector.Agent.Inspection.Members;
using WinTestKit.Inspector.Protocol;
using Xunit;
using Xunit.Abstractions;

namespace WinTestKit.Inspector.Agent.Query.Tests
{
    [Trait("Category", "Unit")]
    [Collection("Wpf windows")]
    public sealed class RealizeItemTests
    {
        public sealed class DataItem
        {
            public string Name { get; set; } = "";
            public string Password => "hidden";
        }
        private readonly ITestOutputHelper output;
        public RealizeItemTests(ITestOutputHelper output) { this.output = output; }

        [Fact]
        public async Task VirtualizedTreeRealizesImmediateItem()
        {
            var ready = new TaskCompletionSource<Dispatcher>();
            var thread = new Thread(() => { ready.SetResult(Dispatcher.CurrentDispatcher); Dispatcher.Run(); }) { IsBackground = true };
            thread.SetApartmentState(ApartmentState.STA); thread.Start();
            var dispatcher = await ready.Task;
            var executor = new DispatcherExecutor();
            using (var registry = new ObjectRegistry("session", executor))
            {
                var pair = await dispatcher.InvokeAsync(() =>
                {
                    var tree = new TreeView { ItemsSource = Enumerable.Range(0, 5000).ToArray() };
                    VirtualizingPanel.SetIsVirtualizing(tree, true);
                    var window = new Window { Width = 400, Height = 300, Content = tree, ShowInTaskbar = false };
                    window.Show(); window.UpdateLayout(); return Tuple.Create(window, tree);
                }).Task;
                try
                {
                    var search = new ItemSearch { Container = registry.Register(pair.Item2, dispatcher, TypeInfoBuilder.Build(pair.Item2.GetType())), Match = new ItemMatch { Kind = "index", Index = 4999 }, MaxItems = 5000 };
                    await dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle).Task;
                    var result = await RealizeItemEngine.ExecuteAsync(executor, dispatcher, pair.Item2, search, registry, new ObjectInspector(), DateTime.UtcNow.AddSeconds(60), 2000, CancellationToken.None);
                    Assert.Equal("performed", result.Outcome);
                    Assert.NotNull(await dispatcher.InvokeAsync(() => pair.Item2.ItemContainerGenerator.ContainerFromIndex(4999)).Task);
                }
                finally { await dispatcher.InvokeAsync(() => pair.Item1.Close()).Task; }
            }
            dispatcher.BeginInvokeShutdown(DispatcherPriority.Send); thread.Join();
        }

        [Fact]
        public async Task MatchesDataAndReportsSearchErrors()
        {
            var ready = new TaskCompletionSource<Dispatcher>();
            var thread = new Thread(() => { ready.SetResult(Dispatcher.CurrentDispatcher); Dispatcher.Run(); }) { IsBackground = true };
            thread.SetApartmentState(ApartmentState.STA); thread.Start();
            var dispatcher = await ready.Task;
            var executor = new DispatcherExecutor();
            using (var registry = new ObjectRegistry("session", executor))
            {
                var pair = await dispatcher.InvokeAsync(() =>
                {
                    var list = new ListBox { ItemsSource = new[] { new DataItem { Name = "Alpha" }, new DataItem { Name = "Alpha" }, new DataItem { Name = "Beta" } } };
                    var window = new Window { Width = 300, Height = 200, Content = list, ShowInTaskbar = false };
                    window.Show(); window.UpdateLayout(); return Tuple.Create(window, list);
                }).Task;
                try
                {
                    var search = new ItemSearch { Container = registry.Register(pair.Item2, dispatcher, TypeInfoBuilder.Build(pair.Item2.GetType())), MaxItems = 3 };
                    async Task<ActRealizeItemResult> Run() { await dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle).Task; return await RealizeItemEngine.ExecuteAsync(executor, dispatcher, pair.Item2, search, registry, new ObjectInspector(), DateTime.UtcNow.AddSeconds(60), 2000, CancellationToken.None); }
                    search.Match = new ItemMatch { Kind = "equals", Path = new[] { new PathSegment { Kind = "property", Name = "Name" } }, Value = new JsonStringNode("Alpha") };
                    var duplicate = await Run(); Assert.Equal(2, duplicate.Warning!.Count); Assert.Equal("noChange", duplicate.Outcome);
                    search.Match = new ItemMatch { Kind = "regex", Path = search.Match.Path, Pattern = "^beta$", Flags = new[] { "ignoreCase" } };
                    Assert.NotNull((await Run()).Handle);
                    search.Match = new ItemMatch { Kind = "equals", Path = new[] { new PathSegment { Kind = "property", Name = "Absent" } }, Value = new JsonStringNode("x") };
                    Assert.Equal(ErrorCodes.NotFound, (await Assert.ThrowsAsync<ProtocolException>(Run)).Code);
                    search.MaxItems = 1;
                    var cap = await Assert.ThrowsAsync<ProtocolException>(Run); Assert.Equal(ErrorCodes.LimitExceeded, cap.Code); Assert.Null(cap.Details);
                    search.MaxItems = 3; search.Match.Path = new[] { new PathSegment { Kind = "property", Name = "Password" } };
                    Assert.Equal(ErrorCodes.ValueUnreadable, (await Assert.ThrowsAsync<ProtocolException>(Run)).Code);
                    var expired = await Assert.ThrowsAsync<ProtocolException>(() => RealizeItemEngine.ExecuteAsync(executor, dispatcher, pair.Item2, search, registry, new ObjectInspector(), DateTime.UtcNow.AddSeconds(-1), 2000, CancellationToken.None));
                    Assert.Equal(ErrorCodes.LimitExceeded, expired.Code); Assert.NotNull(expired.Details);
                    await dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle).Task;
                    var unsupported = await Assert.ThrowsAsync<ProtocolException>(() => RealizeItemEngine.ExecuteAsync(executor, dispatcher, pair.Item1, search, registry, new ObjectInspector(), DateTime.UtcNow.AddSeconds(60), 2000, CancellationToken.None));
                    Assert.Equal(ErrorCodes.ActionUnsupported, unsupported.Code);
                }
                finally { await dispatcher.InvokeAsync(() => pair.Item1.Close()).Task; }
            }
            dispatcher.BeginInvokeShutdown(DispatcherPriority.Send); thread.Join();
        }

        [Fact]
        public async Task VirtualizedListRealizesLastItemWithoutGeneratingAll()
        {
            var ready = new TaskCompletionSource<Dispatcher>();
            var thread = new Thread(() => { ready.SetResult(Dispatcher.CurrentDispatcher); Dispatcher.Run(); }) { IsBackground = true };
            thread.SetApartmentState(ApartmentState.STA); thread.Start();
            var dispatcher = await ready.Task;
            var executor = new DispatcherExecutor();
            using (var registry = new ObjectRegistry("session", executor))
            {
                var pair = await dispatcher.InvokeAsync(() =>
                {
                    var list = new ListBox { ItemsSource = Enumerable.Range(0, 5000).ToArray() };
                    var window = new Window { Width = 400, Height = 300, Content = list, ShowInTaskbar = false };
                    window.Show(); window.UpdateLayout();
                    return Tuple.Create(window, list);
                }).Task;
                try
                {
                    var search = new ItemSearch { Container = registry.Register(pair.Item2, dispatcher, TypeInfoBuilder.Build(pair.Item2.GetType())), Match = new ItemMatch { Kind = "index", Index = 4999 }, MaxItems = 5000 };
                    await dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle).Task;
                    var result = await RealizeItemEngine.ExecuteAsync(executor, dispatcher, pair.Item2, search, registry, new ObjectInspector(), DateTime.UtcNow.AddSeconds(60), 2000, CancellationToken.None);
                    Assert.Equal("performed", result.Outcome);
                    int count = await dispatcher.InvokeAsync(() => Enumerable.Range(0, 5000).Count(index => pair.Item2.ItemContainerGenerator.ContainerFromIndex(index) != null)).Task;
                    output.WriteLine("Generated containers: " + count);
                    Assert.InRange(count, 1, 199);
                    Assert.NotNull(await dispatcher.InvokeAsync(() => pair.Item2.ItemContainerGenerator.ContainerFromIndex(4999)).Task);
                    await dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle).Task;
                    var again = await RealizeItemEngine.ExecuteAsync(executor, dispatcher, pair.Item2, search, registry, new ObjectInspector(), DateTime.UtcNow.AddSeconds(60), 2000, CancellationToken.None);
                    Assert.Equal("noChange", again.Outcome);
                }
                finally { await dispatcher.InvokeAsync(() => pair.Item1.Close()).Task; }
            }
            dispatcher.BeginInvokeShutdown(DispatcherPriority.Send); thread.Join();
        }
    }
}
