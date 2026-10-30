using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Inspection;
using WinTestKit.Inspector.Agent.Inspection.Members;
using WinTestKit.Inspector.Agent.Query;
using WinTestKit.Inspector.Protocol;
using Xunit;
using Xunit.Abstractions;

namespace WinTestKit.Inspector.Agent.Query.Tests
{
    [Trait("Category", "Unit")]
    public sealed class QueryEngineTests
    {
        private readonly ITestOutputHelper output;
        public QueryEngineTests(ITestOutputHelper output) { this.output = output; }
        private sealed class Ui : IDisposable
        {
            private readonly Thread thread;
            internal Dispatcher Dispatcher { get; }
            internal Ui()
            {
                var ready = new TaskCompletionSource<Dispatcher>();
                thread = new Thread(() => { ready.SetResult(Dispatcher.CurrentDispatcher); Dispatcher.Run(); });
                thread.IsBackground = true;
                thread.SetApartmentState(ApartmentState.STA);
                thread.Start();
                Dispatcher = ready.Task.GetAwaiter().GetResult();
            }
            public void Dispose() { Dispatcher.BeginInvokeShutdown(DispatcherPriority.Send); thread.Join(); }
        }
        private static Locator Scope(ObjectRef handle, string tree = "logical", int depth = 256) => new Locator
        {
            Scope = new Scope { Kind = "object", Handle = handle },
            Tree = tree,
            Depth = depth,
            Limit = 200,
            Predicates = new List<Predicate>()
        };
        private static ObjectRef Register(ObjectRegistry registry, DependencyObject target) =>
            registry.Register(target, target.Dispatcher, TypeInfoBuilder.Build(target.GetType()));
        private static DateTime Deadline => DateTime.UtcNow.AddSeconds(2);

        [Theory]
        [InlineData("visual")]
        [InlineData("logical")]
        [InlineData("combined")]
        public async Task OrderedTraversalDepthIndexAndLimit(string tree)
        {
            using (var ui = new Ui())
            {
                var executor = new DispatcherExecutor();
                using (var registry = new ObjectRegistry("session", executor))
                {
                    var objects = await ui.Dispatcher.InvokeAsync(() =>
                    {
                        var root = new StackPanel(); var nested = new StackPanel();
                        var first = new Button(); var second = new Button();
                        nested.Children.Add(first); root.Children.Add(nested); root.Children.Add(second);
                        return new DependencyObject[] { root, nested, first, second };
                    }).Task;
                    ObjectRef rootRef = Register(registry, objects[0]);
                    var engine = new QueryEngine(executor, registry);
                    Locator locator = Scope(rootRef, tree);
                    var all = await engine.FindAllAsync(locator, Deadline, CancellationToken.None);
                    Assert.True(all.Complete); Assert.Equal(4, all.Count);
                    Assert.Equal(objects.Select(item => Register(registry, item).ObjectId), all.Matches.Select(item => item.ObjectId));
                    locator.Depth = 0;
                    Assert.Single((await engine.FindAllAsync(locator, Deadline, CancellationToken.None)).Matches);
                    locator.Depth = 1;
                    Assert.Equal(3, (await engine.FindAllAsync(locator, Deadline, CancellationToken.None)).Count);
                    locator.Depth = 256; locator.Limit = 2;
                    all = await engine.FindAllAsync(locator, Deadline, CancellationToken.None);
                    Assert.False(all.Complete); Assert.Equal(4, all.Count); Assert.Equal(2, all.Matches.Count);
                    locator.Index = 2;
                    var found = await engine.FindAsync(locator, Deadline, CancellationToken.None);
                    Assert.Equal(Register(registry, objects[2]).ObjectId, found.Match.ObjectId);
                    Assert.Null(found.Warning);
                }
            }
        }
        [Fact]
        public async Task PredicateAndStaleHandling()
        {
            using (var ui = new Ui())
            {
                var executor = new DispatcherExecutor();
                using (var registry = new ObjectRegistry("session", executor))
                {
                    var button = await ui.Dispatcher.InvokeAsync(() => new Button()).Task;
                    ObjectRef handle = Register(registry, button);
                    var engine = new QueryEngine(executor, registry);
                    Locator locator = Scope(handle);
                    locator.Predicates = new[] { new Predicate { Kind = "assignableTo", FullName = typeof(Control).FullName } };
                    Assert.Null((await engine.FindAsync(locator, Deadline, CancellationToken.None)).Warning);
                    locator.Predicates = new[] { new Predicate { Kind = "assignableTo", FullName = typeof(IDisposable).FullName } };
                    Assert.Equal(ErrorCodes.NotFound, (await Assert.ThrowsAsync<ProtocolException>(() => engine.FindAsync(locator, Deadline, CancellationToken.None))).Code);
                    registry.Release(new[] { handle.ObjectId });
                    Assert.Equal(ErrorCodes.ObjectStale, (await Assert.ThrowsAsync<ProtocolException>(() => engine.FindAsync(locator, Deadline, CancellationToken.None))).Code);
                }
            }
        }
        [Fact]
        public async Task InterfaceShortDeadlineAndSameDispatcherRoots()
        {
            using (var ui = new Ui())
            {
                var windows = await ui.Dispatcher.InvokeAsync(() =>
                {
                    var first = new Window(); var second = new Window();
                    first.Show(); second.Show();
                    return new[] { first, second };
                }).Task;
                try
                {
                    var executor = new DispatcherExecutor();
                    using (var registry = new ObjectRegistry("same-roots", executor))
                    {
                        var engine = new QueryEngine(executor, registry);
                        var locator = new Locator
                        {
                            Scope = new Scope { Kind = "allRoots" },
                            Tree = "logical",
                            Depth = 0,
                            Limit = 200,
                            Predicates = new[] { new Predicate { Kind = "assignableTo", FullName = typeof(System.Windows.IInputElement).FullName } }
                        };
                        var all = await engine.FindAllAsync(locator, Deadline, CancellationToken.None);
                        Assert.Contains(all.Matches, item => item.ObjectId == Register(registry, windows[0]).ObjectId);
                        Assert.Contains(all.Matches, item => item.ObjectId == Register(registry, windows[1]).ObjectId);
                        var root = await ui.Dispatcher.InvokeAsync(() =>
                        {
                            var panel = new StackPanel();
                            for (int index = 0; index < 5000; index++) panel.Children.Add(new Button());
                            return panel;
                        }).Task;
                        locator = Scope(Register(registry, root));
                        try { Assert.NotNull((await engine.FindAsync(locator, Deadline, 1, CancellationToken.None)).Match); }
                        catch (ProtocolException error) { Assert.Equal(ErrorCodes.LimitExceeded, error.Code); }
                    }
                }
                finally
                {
                    foreach (var window in windows) await ui.Dispatcher.InvokeAsync(window.Close).Task;
                }
            }
        }

        [Fact]
        public async Task AllRootsAcrossDispatchers()
        {
            using (var first = new Ui())
            using (var second = new Ui())
            {
                Window firstWindow = await first.Dispatcher.InvokeAsync(() => { var window = new Window(); window.Show(); return window; }).Task;
                Window secondWindow = await second.Dispatcher.InvokeAsync(() => { var window = new Window(); window.Show(); return window; }).Task;
                try
                {
                    var executor = new DispatcherExecutor();
                    using (var registry = new ObjectRegistry("roots", executor))
                    {
                        var engine = new QueryEngine(executor, registry);
                        var locator = new Locator { Scope = new Scope { Kind = "allRoots" }, Tree = "logical", Depth = 0, Limit = 200 };
                        var result = await engine.FindAllAsync(locator, Deadline, CancellationToken.None);
                        Assert.Contains(result.Matches, item => item.ObjectId == Register(registry, firstWindow).ObjectId);
                        Assert.Contains(result.Matches, item => item.ObjectId == Register(registry, secondWindow).ObjectId);
                    }
                }
                finally
                {
                    await first.Dispatcher.InvokeAsync(firstWindow.Close).Task;
                    await second.Dispatcher.InvokeAsync(secondWindow.Close).Task;
                }
            }
        }

        [Fact]
        public async Task BudgetReturnsExistingMatchOrLimitExceeded()
        {
            using (var ui = new Ui())
            {
                var executor = new DispatcherExecutor();
                using (var registry = new ObjectRegistry("budget", executor))
                {
                    var root = await ui.Dispatcher.InvokeAsync(() =>
                    {
                        var panel = new StackPanel();
                        for (int index = 0; index < 10001; index++) panel.Children.Add(new Button());
                        return panel;
                    }).Task;
                    var engine = new QueryEngine(executor, registry);
                    Locator locator = Scope(Register(registry, root));
                    var found = await engine.FindAsync(locator, Deadline, CancellationToken.None);
                    Assert.NotNull(found.Match);
                    var all = await engine.FindAllAsync(locator, Deadline, CancellationToken.None);
                    Assert.False(all.Complete); Assert.Null(all.Count);
                    locator.Predicates = new[] { new Predicate { Kind = "assignableTo", FullName = "No.Such.Type" } };
                    Assert.Equal(ErrorCodes.LimitExceeded, (await Assert.ThrowsAsync<ProtocolException>(() => engine.FindAsync(locator, Deadline, CancellationToken.None))).Code);
                }
            }
        }

        [Fact]
        public async Task LogicalOnlyChildAndWindowScope()
        {
            using (var ui = new Ui())
            {
                var executor = new DispatcherExecutor();
                using (var registry = new ObjectRegistry("logical", executor))
                {
                    var window = await ui.Dispatcher.InvokeAsync(() =>
                    {
                        var text = new System.Windows.Documents.Run("text");
                        return new Window { Content = new TextBlock(text) };
                    }).Task;
                    ObjectRef handle = Register(registry, window);
                    Locator locator = Scope(handle, "combined");
                    locator.Scope.Kind = "window";
                    locator.Predicates = new[] { new Predicate { Kind = "assignableTo", FullName = typeof(System.Windows.Documents.Run).FullName } };
                    var result = await new QueryEngine(executor, registry).FindAllAsync(locator, Deadline, CancellationToken.None);
                    Assert.Single(result.Matches);
                    locator.Tree = "visual";
                    Assert.Empty((await new QueryEngine(executor, registry).FindAllAsync(locator, Deadline, CancellationToken.None)).Matches);
                    locator.Predicates = new Predicate[0]; locator.Depth = 0;
                    Assert.Equal(handle.ObjectId, (await new QueryEngine(executor, registry).FindAsync(locator, Deadline, CancellationToken.None)).Match.ObjectId);
                }
            }
        }

        [Fact]
        public async Task DispatcherRunsOtherWorkBetweenSlices()
        {
            using (var ui = new Ui())
            {
                var executor = new DispatcherExecutor();
                using (var registry = new ObjectRegistry("yield", executor))
                {
                    var root = await ui.Dispatcher.InvokeAsync(() =>
                    {
                        var panel = new StackPanel();
                        for (int index = 0; index < 9000; index++) panel.Children.Add(new Button());
                        return panel;
                    }).Task;
                    var engine = new QueryEngine(executor, registry);
                    Locator locator = Scope(Register(registry, root));
                    var started = new TaskCompletionSource<bool>();
                    DispatcherHookEventHandler hook = (_, args) =>
                    {
                        if (args.Operation.Priority == DispatcherPriority.Background) started.TrySetResult(true);
                    };
                    ui.Dispatcher.Hooks.OperationStarted += hook;
                    try
                    {
                        Task<QueryFindResult> search = engine.FindAsync(locator, Deadline, CancellationToken.None);
                        await started.Task;
                        await ui.Dispatcher.InvokeAsync(() => { }, DispatcherPriority.Normal).Task;
                        Assert.False(search.IsCompleted);
                        await search;
                    }
                    finally { ui.Dispatcher.Hooks.OperationStarted -= hook; }
                }
            }
        }

        [Fact]
        public async Task LargeTreeMedian()
        {
            using (var ui = new Ui())
            {
                var executor = new DispatcherExecutor();
                using (var registry = new ObjectRegistry("session", executor))
                {
                    var root = await ui.Dispatcher.InvokeAsync(() =>
                    {
                        var panel = new StackPanel();
                        for (int index = 0; index < 5000; index++) panel.Children.Add(new Button());
                        return panel;
                    }).Task;
                    var engine = new QueryEngine(executor, registry);
                    Locator locator = Scope(Register(registry, root));
                    var times = new List<long>();
                    for (int iteration = 0; iteration < 20; iteration++)
                    {
                        var timer = Stopwatch.StartNew();
                        await engine.FindAsync(locator, Deadline, CancellationToken.None);
                        times.Add(timer.ElapsedMilliseconds);
                    }
                    times.Sort(); long median = (times[9] + times[10]) / 2;
                    output.WriteLine("5000 element median: {0} ms", median);
                    Assert.True(median < 1000);
                }
            }
        }
    }
}
