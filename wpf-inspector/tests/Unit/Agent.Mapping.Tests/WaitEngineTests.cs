using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using WinTestKit.Inspector.Agent.Inspection;
using WinTestKit.Inspector.Agent.Inspection.Members;
using WinTestKit.Inspector.Agent.Query;
using WinTestKit.Inspector.Agent.Wait;
using WinTestKit.Inspector.Protocol;
using Xunit;
using Visibility = System.Windows.Visibility;

namespace WinTestKit.Inspector.Agent.Mapping.Tests
{
    [Trait("Category", "Unit")]
    [Collection("WPF dispatchers")]
    public sealed class WaitEngineTests
    {
        [Theory]
        [InlineData("exists")]
        [InlineData("visible")]
        [InlineData("enabled")]
        [InlineData("propertyEquals")]
        public async Task RechecksChanges(string kind)
        {
            using (var ui = new DispatcherThread())
            using (var registry = new ObjectRegistry("session", new DispatcherExecutor()))
            {
                var executor = new DispatcherExecutor();
                var inspector = new ObjectInspector();
                var root = await ui.Dispatcher.InvokeAsync(() => new StackPanel()).Task;
                var handle = registry.Register(root, ui.Dispatcher, TypeInfoBuilder.Build(root.GetType()));
                var locator = new Locator { Scope = new Scope { Kind = "object", Handle = handle }, Tree = "logical", DepthMode = "tree", Depth = 10, Limit = 200,
                    Predicates = new[] { new Predicate { Kind = "equals", Path = new[] { new PathSegment { Kind = "type", Name = "FullName" } }, Value = new JsonStringNode("System.Windows.Controls.Button") } } };
                var condition = new WaitCondition { Kind = kind, Locator = locator };
                if (kind == "propertyEquals") { condition.Path = new[] { new PathSegment { Kind = "property", Name = "IsEnabled" } }; condition.Value = new JsonBoolNode(true); }
                var engine = new WaitEngine(new QueryEngine(executor, registry, inspector), executor, registry, inspector, new PeerRuntimeIdAdapter());
                Window? window = null;
                try
                {
                    await ui.Dispatcher.InvokeAsync(() => { window = new Window { Content = root, ShowInTaskbar = false }; window.Show(); if (kind != "exists") root.Children.Add(new Button { Visibility = kind == "visible" ? Visibility.Hidden : Visibility.Visible, IsEnabled = kind != "enabled" && kind != "propertyEquals" }); }).Task;
                    var task = engine.UntilAsync(condition, DateTime.UtcNow.AddSeconds(2), 1200, CancellationToken.None);
                    await Task.Delay(100);
                    await ui.Dispatcher.InvokeAsync(() => { if (kind == "exists") root.Children.Add(new Button()); else if (kind == "visible") ((Button)root.Children[0]).Visibility = Visibility.Visible; else ((Button)root.Children[0]).IsEnabled = true; }).Task;
                    Assert.True((await task).Satisfied);
                    Assert.True((await engine.UntilAsync(condition, DateTime.UtcNow.AddSeconds(2), 500, CancellationToken.None)).Satisfied);
                }
                finally { if (window != null) await ui.Dispatcher.InvokeAsync(window.Close).Task; }
            }
        }

        [Fact]
        public async Task TimeoutCancellationAndStaleScope()
        {
            using (var ui = new DispatcherThread())
            {
                var executor = new DispatcherExecutor();
                using (var registry = new ObjectRegistry("session", executor))
                {
                    var root = await ui.Dispatcher.InvokeAsync(() => new StackPanel()).Task;
                    var handle = registry.Register(root, ui.Dispatcher, TypeInfoBuilder.Build(root.GetType()));
                    var locator = new Locator { Scope = new Scope { Kind = "object", Handle = handle }, Tree = "logical", DepthMode = "tree", Depth = 10, Limit = 200,
                        Predicates = new[] { new Predicate { Kind = "equals", Path = new[] { new PathSegment { Kind = "type", Name = "FullName" } }, Value = new JsonStringNode("System.Windows.Controls.Button") } } };
                    var engine = new WaitEngine(new QueryEngine(executor, registry), executor, registry, new ObjectInspector(), new PeerRuntimeIdAdapter());
                    var condition = new WaitCondition { Kind = "exists", Locator = locator };
                    Assert.False((await engine.UntilAsync(condition, DateTime.UtcNow.AddSeconds(2), 100, CancellationToken.None)).Satisfied);
                    using (var cancel = new CancellationTokenSource(50))
                        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => engine.UntilAsync(condition, DateTime.UtcNow.AddSeconds(2), 1000, cancel.Token));
                    registry.Release(new[] { handle.ObjectId });
                    Assert.Equal(ErrorCodes.ObjectStale, (await Assert.ThrowsAsync<ProtocolException>(() => engine.UntilAsync(condition, DateTime.UtcNow.AddSeconds(2), 500, CancellationToken.None))).Code);
                }
            }
        }

        [Fact]
        public async Task UnreadablePropertyIsAnError()
        {
            using (var ui = new DispatcherThread())
            {
                var executor = new DispatcherExecutor();
                using (var registry = new ObjectRegistry("session", executor))
                {
                    var root = await ui.Dispatcher.InvokeAsync(() => new StackPanel()).Task;
                    var handle = registry.Register(root, ui.Dispatcher, TypeInfoBuilder.Build(root.GetType()));
                    var locator = new Locator { Scope = new Scope { Kind = "object", Handle = handle }, Tree = "logical", DepthMode = "tree", Depth = 0, Limit = 1 };
                    var condition = new WaitCondition { Kind = "propertyEquals", Locator = locator, Path = new[] { new PathSegment { Kind = "property", Name = "Name" } }, Value = new JsonStringNode("secret") };
                    var engine = new WaitEngine(new QueryEngine(executor, registry), executor, registry, new ObjectInspector(), new PeerRuntimeIdAdapter());
                    Assert.Equal(ErrorCodes.ValueUnreadable, (await Assert.ThrowsAsync<ProtocolException>(() => engine.UntilAsync(condition, DateTime.UtcNow.AddSeconds(2), 500, CancellationToken.None))).Code);
                }
            }
        }

        [Fact]
        public async Task IncompleteSearchIsAnError()
        {
            using (var ui = new DispatcherThread())
            {
                var executor = new DispatcherExecutor();
                using (var registry = new ObjectRegistry("session", executor))
                {
                    var root = await ui.Dispatcher.InvokeAsync(() =>
                    {
                        var panel = new StackPanel();
                        for (int index = 0; index <= ProtocolLimits.ScanMaxObjects; index++) panel.Children.Add(new Border());
                        return panel;
                    }).Task;
                    var handle = registry.Register(root, ui.Dispatcher, TypeInfoBuilder.Build(root.GetType()));
                    var locator = new Locator { Scope = new Scope { Kind = "object", Handle = handle }, Tree = "logical", DepthMode = "tree", Depth = 1, Limit = 1,
                        Predicates = new[] { new Predicate { Kind = "equals", Path = new[] { new PathSegment { Kind = "type", Name = "FullName" } }, Value = new JsonStringNode("System.Windows.Controls.Button") } } };
                    var engine = new WaitEngine(new QueryEngine(executor, registry), executor, registry, new ObjectInspector(), new PeerRuntimeIdAdapter());
                    Assert.Equal(ErrorCodes.LimitExceeded, (await Assert.ThrowsAsync<ProtocolException>(() => engine.UntilAsync(new WaitCondition { Kind = "exists", Locator = locator }, DateTime.UtcNow.AddSeconds(3), 2000, CancellationToken.None))).Code);
                }
            }
        }
    }
}
