using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Automation.Peers;
using System.Windows.Controls;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Contracts;
using WinTestKit.Inspector.Agent.Inspection;
using WinTestKit.Inspector.Protocol;
using Xunit;
using MemberInfo = WinTestKit.Inspector.Protocol.MemberInfo;

namespace WinTestKit.Inspector.Agent.Mapping.Tests
{
    [Collection("WPF dispatchers")]
    [Trait("Category", "Unit")]
    public sealed class WpfInspectionServiceTests
    {
        [System.Runtime.InteropServices.DllImport("user32.dll")]
        private static extern IntPtr GetDesktopWindow();

        private static readonly CancellationToken None = CancellationToken.None;

        private static IReadOnlyList<IReadOnlyList<PathSegment>> Paths(params string[] names) =>
            names.Select(name => (IReadOnlyList<PathSegment>)new[] { new PathSegment { Kind = SegmentKind.Property, Name = name } }).ToArray();

        private static async Task<ObjectRef> WindowHandle(IInspectionService service, MappingWindow window) =>
            (await service.ResolveAsync(new[] { 42 }, window.Handle.ToInt64(), None)).Object!;

        private static async Task<ObjectRef> PanelHandle(IInspectionService service, MappingWindow window)
        {
            ObjectRef root = await WindowHandle(service, window);
            return Assert.Single((await service.ChildrenAsync(root.ObjectId, root.Generation, TreeKind.Logical, null, null, None)).Items).Object;
        }

        private static async Task Error(string code, Func<Task> action) =>
            Assert.Equal(code, (await Assert.ThrowsAsync<ProtocolException>(action)).Code);

        [Fact]
        public async Task HitTestUsesScreenCoordinatesAndRejectsMissingWindows()
        {
            using (var window = new MappingWindow())
            using (var service = new WpfInspectionService("hit", new FakeInspector()))
            {
                Point screen = await window.Thread.Dispatcher.InvokeAsync(() => window.Buttons[0].PointToScreen(new Point(5, 5))).Task;
                var result = await service.HitTestAsync(window.Handle.ToInt64(), new PointDto { X = screen.X, Y = screen.Y }, DateTime.UtcNow.AddSeconds(2), 1000, None);
                Assert.NotNull(result.Handle);
                var registry = (ObjectRegistry)typeof(WpfInspectionService).GetField("registry", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(service)!;
                Assert.True(registry.TryGet(result.Handle.ObjectId, result.Handle.Generation, out object target, out _));
                Assert.True(await window.Thread.Dispatcher.InvokeAsync(() => ReferenceEquals(target, window.Buttons[0]) || window.Buttons[0].IsAncestorOf((DependencyObject)target)).Task);
                await Error(ErrorCodes.NotFound, () => service.HitTestAsync(window.Handle.ToInt64(), new PointDto { X = -100000, Y = -100000 }, DateTime.UtcNow.AddSeconds(2), 1000, None));
                await Error(ErrorCodes.MappingFailed, () => service.HitTestAsync(0, new PointDto(), DateTime.UtcNow.AddSeconds(2), 1000, None));
                await Error(ErrorCodes.MappingFailed, () => service.HitTestAsync(GetDesktopWindow().ToInt64(), new PointDto(), DateTime.UtcNow.AddSeconds(2), 1000, None));
            }
        }

        [Fact]
        public async Task HitTestFindsPeerlessDeepestAndSkipsDisabledOverlay()
        {
            using (var window = new MappingWindow())
            using (var service = new WpfInspectionService("hit", new FakeInspector()))
            {
                Border? peerless = null;
                Point screen = await window.Thread.Dispatcher.InvokeAsync(() =>
                {
                    peerless = new Border { Name = "PeerlessTarget", LayoutTransform = new System.Windows.Media.ScaleTransform(1.5, 1.5) };
                    var grid = new Grid();
                    peerless.Width = 80; peerless.Height = 40; peerless.Background = System.Windows.Media.Brushes.Red;
                    grid.Children.Add(peerless);
                    grid.Children.Add(new Border { Width = 80, Height = 40, Background = System.Windows.Media.Brushes.Blue, IsHitTestVisible = false });
                    window.Window.Content = grid;
                    window.Window.UpdateLayout();
                    return peerless.PointToScreen(new Point(20, 20));
                }).Task;
                var result = await service.HitTestAsync(window.Handle.ToInt64(), new PointDto { X = screen.X, Y = screen.Y }, DateTime.UtcNow.AddSeconds(2), 1000, None, true);
                var registry = (ObjectRegistry)typeof(WpfInspectionService).GetField("registry", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(service)!;
                Assert.NotNull(result.Path);
                Assert.Equal(result.Handle.ObjectId, result.Path!.Last().Object.ObjectId);
                Assert.Equal("Name", result.Path.Last().Identity!.XName);
                var entries = (System.Collections.IDictionary)typeof(ObjectRegistry).GetField("entries", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(registry)!;
                foreach (object entry in entries.Values) Assert.Null(entry.GetType().GetField("Lease", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(entry));
                Assert.True(registry.TryGetWeak(result.Path.First().Object.ObjectId, result.Path.First().Object.Generation, out object root));
                Assert.Same(window.Window, root);
                Assert.True(registry.TryGet(result.Handle.ObjectId, result.Handle.Generation, out object target, out _));
                Assert.Same(peerless, target);
            }
        }

        [Fact]
        public async Task HitTestPathUsesPopupHwndRoot()
        {
            using (var window = new MappingWindow())
            using (var service = new WpfInspectionService("hit", new FakeInspector()))
            {
                var data = await window.Thread.Dispatcher.InvokeAsync(() =>
                {
                    var child = new Border { Width = 80, Height = 40, Background = System.Windows.Media.Brushes.Red };
                    var popup = new System.Windows.Controls.Primitives.Popup { Child = child, PlacementTarget = window.Window, IsOpen = true };
                    child.UpdateLayout();
                    var source = (System.Windows.Interop.HwndSource)PresentationSource.FromVisual(child);
                    return (popup, child, source.Handle, source.RootVisual, child.PointToScreen(new Point(10, 10)));
                }).Task;
                try
                {
                    var hit = await service.HitTestAsync(data.Handle.ToInt64(), new PointDto { X = data.Item5.X, Y = data.Item5.Y }, DateTime.UtcNow.AddSeconds(2), 1000, None, true);
                    var registry = (ObjectRegistry)typeof(WpfInspectionService).GetField("registry", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(service)!;
                    Assert.NotNull(hit.Path);
                    Assert.True(registry.TryGetWeak(hit.Path!.First().Object.ObjectId, hit.Path.First().Object.Generation, out object root));
                    Assert.Same(data.RootVisual, root);
                    Assert.Equal(hit.Handle.ObjectId, hit.Path.Last().Object.ObjectId);
                }
                finally { await window.Thread.Dispatcher.InvokeAsync(() => data.popup.IsOpen = false).Task; }
            }
        }

        [Fact]
        public async Task HitTestReturnsContentElement()
        {
            using (var window = new MappingWindow())
            using (var service = new WpfInspectionService("hit", new FakeInspector()))
            {
                Point screen = await window.Thread.Dispatcher.InvokeAsync(() =>
                {
                    var text = new TextBlock { FontSize = 30 };
                    text.Inlines.Add(new System.Windows.Documents.Hyperlink(new System.Windows.Documents.Run("Content target")));
                    window.Window.Content = text;
                    window.Window.UpdateLayout();
                    return text.PointToScreen(new Point(10, 10));
                }).Task;
                var result = await service.HitTestAsync(window.Handle.ToInt64(), new PointDto { X = screen.X, Y = screen.Y }, DateTime.UtcNow.AddSeconds(2), 1000, None, true);
                var registry = (ObjectRegistry)typeof(WpfInspectionService).GetField("registry", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(service)!;
                Assert.True(registry.TryGet(result.Handle.ObjectId, result.Handle.Generation, out object target, out _));
                Assert.IsAssignableFrom<ContentElement>(target);
                Assert.NotNull(result.Path);
                Assert.Equal(result.Handle.ObjectId, result.Path!.Last().Object.ObjectId);
            }
        }

        [Fact]
        public async Task RootsPageAcrossDispatchersAndFreezeHandles()
        {
            using (var first = new MappingWindow())
            using (var second = new MappingWindow())
            using (var service = new WpfInspectionService("roots", new FakeInspector()))
            {
                PageDto<ManagedNodeDto> page = await service.RootsAsync(1, null, None);
                Assert.Single(page.Items);
                Assert.False(page.Complete);
                Assert.NotNull(page.NextToken);
                string snapshot = page.SnapshotId;
                var nodes = new List<ManagedNodeDto>(page.Items);
                while (page.NextToken != null)
                {
                    page = await service.RootsAsync(1, page.NextToken, None);
                    Assert.Equal(snapshot, page.SnapshotId);
                    nodes.AddRange(page.Items);
                    Assert.Equal(page.NextToken == null, page.Complete);
                }
                ObjectRef firstRoot = await WindowHandle(service, first);
                Assert.Contains(nodes, node => node.Object.ObjectId == firstRoot.ObjectId);
                Assert.Equal(2, nodes.Count);
                Assert.All(nodes, node => { Assert.Equal("Window", node.Label); Assert.True(node.HasLogicalChildren); Assert.True(node.HasVisualChildren); });
                Assert.Equal(2, nodes.Select(node => node.Object.DispatcherId).Distinct().Count());
            }
        }

        [Theory]
        [InlineData("visual")]
        [InlineData("logical")]
        public async Task ChildrenPagesRemainFrozenAfterTreeChanges(string tree)
        {
            using (var window = new MappingWindow(5))
            using (var service = new WpfInspectionService("children", new FakeInspector()))
            {
                ObjectRef panel = await PanelHandle(service, window);
                PageDto<ManagedNodeDto> first = await service.ChildrenAsync(panel.ObjectId, panel.Generation, tree, 2, null, None);
                Assert.Equal(2, first.Items.Count);
                Assert.False(first.Complete);
                await window.Thread.Dispatcher.InvokeAsync(() => window.Panel.Children.Clear()).Task;
                PageDto<ManagedNodeDto> second = await service.ChildrenAsync(panel.ObjectId, panel.Generation, tree, 2, first.NextToken, None);
                Assert.Equal(2, second.Items.Count);
                Assert.False(second.Complete);
                PageDto<ManagedNodeDto> last = await service.ChildrenAsync(panel.ObjectId, panel.Generation, tree, 2, second.NextToken, None);
                Assert.Single(last.Items);
                Assert.True(last.Complete);
                Assert.Null(last.NextToken);
                Assert.Equal(first.SnapshotId, last.SnapshotId);
                Assert.Equal(5, first.Items.Concat(second.Items).Concat(last.Items).Select(node => node.Object.ObjectId).Distinct().Count());
            }
        }

        [Fact]
        public async Task ChildrenIdentityDoesNotLeasePages()
        {
            using (var window = new MappingWindow(600))
            using (var service = new WpfInspectionService("identity", new WinTestKit.Inspector.Agent.Inspection.Members.ObjectInspector()))
            {
                await window.Thread.Dispatcher.InvokeAsync(() => window.Buttons[0].Name = "NamedButton").Task;
                await window.Thread.Dispatcher.InvokeAsync(() => window.Panel.Children.Add(new Border { Name = "Peerless" })).Task;
                ObjectRef panel = await PanelHandle(service, window);
                string? token = null;
                var nodes = new List<ManagedNodeDto>();
                do
                {
                    var page = await service.ChildrenAsync(panel.ObjectId, panel.Generation, TreeKind.Logical, 200, token, None);
                    nodes.AddRange(page.Items);
                    token = page.NextToken;
                } while (token != null);
                Assert.Equal(601, nodes.Count);
                Assert.Null(Assert.Single(nodes, node => node.Label == "Border").Identity);
                Assert.Equal(600, nodes.Count(node => node.Identity?.AutomationId != null));
                Assert.Contains(nodes, node => node.Identity?.XName == "NamedButton" && node.Identity.AutomationId == "selection-0");
                var registry = (ObjectRegistry)typeof(WpfInspectionService).GetField("registry", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(service)!;
                foreach (var node in nodes) Assert.True(registry.TryGetWeak(node.Object.ObjectId, node.Object.Generation, out _));
                Assert.True(registry.TryGet(nodes[0].Object.ObjectId, nodes[0].Object.Generation, out _, out _));
            }
        }

        [Fact]
        public async Task TokensRejectExpiredForeignOperationObjectTreeAndMalformedCursors()
        {
            DateTime now = DateTime.UtcNow;
            using (var window = new MappingWindow(3))
            using (var service = new WpfInspectionService("tokens", new FakeInspector(), new PageSnapshotStore(() => now)))
            using (var foreign = new WpfInspectionService("foreign", new FakeInspector()))
            {
                ObjectRef panel = await PanelHandle(service, window);
                ObjectRef root = await WindowHandle(service, window);
                var page = await service.ChildrenAsync(panel.ObjectId, panel.Generation, TreeKind.Visual, 1, null, None);
                string token = page.NextToken!;
                await Error(ErrorCodes.InvalidPageToken, () => foreign.RootsAsync(1, token, None));
                await Error(ErrorCodes.InvalidPageToken, () => service.RootsAsync(1, token, None));
                await Error(ErrorCodes.InvalidPageToken, () => service.MembersAsync(panel.ObjectId, panel.Generation, 1, token, None));
                await Error(ErrorCodes.InvalidPageToken, () => service.ChildrenAsync(root.ObjectId, root.Generation, TreeKind.Visual, 1, token, None));
                await Error(ErrorCodes.InvalidPageToken, () => service.ChildrenAsync(panel.ObjectId, panel.Generation, TreeKind.Logical, 1, token, None));
                foreach (string invalid in new[] { "", "garbage", page.SnapshotId + ".0", page.SnapshotId + ".999999", token + ".1" })
                    await Error(ErrorCodes.InvalidPageToken, () => service.ChildrenAsync(panel.ObjectId, panel.Generation, TreeKind.Visual, 1, invalid, None));
                now = now.AddMilliseconds(ProtocolLimits.PageTokenTtlMs);
                await Error(ErrorCodes.InvalidPageToken, () => service.ChildrenAsync(panel.ObjectId, panel.Generation, TreeKind.Visual, 1, token, None));
            }
        }

        [Fact]
        public async Task LabelsFlagsAndRuntimeIdsNeverCreatePeersOrRealizeTemplates()
        {
            using (var window = new MappingWindow(0))
            using (var service = new WpfInspectionService("nodes", new FakeInspector()))
            {
                var button = await window.Thread.Dispatcher.InvokeAsync(() =>
                {
                    var child = new UnobservedButton { Content = "must not display" };
                    window.Panel.Children.Add(new LogicalHost(child));
                    return child;
                }).Task;
                ObjectRef panel = await PanelHandle(service, window);
                ManagedNodeDto host = Assert.Single((await service.ChildrenAsync(panel.ObjectId, panel.Generation, TreeKind.Logical, null, null, None)).Items);
                Assert.Equal("LogicalHost", host.Label);
                Assert.False(host.HasVisualChildren);
                Assert.True(host.HasLogicalChildren);
                ManagedNodeDto childNode = Assert.Single((await service.ChildrenAsync(host.Object.ObjectId, host.Object.Generation, TreeKind.Logical, null, null, None)).Items);
                Assert.Equal(nameof(UnobservedButton), childNode.Label);
                Assert.False(childNode.HasVisualChildren);
                Assert.False(childNode.HasLogicalChildren);
                Assert.Null(childNode.RuntimeId);
                Assert.Equal(0, button.PeerCreations);
                Assert.Equal(0, button.TemplateApplications);
                int[] expected = await window.PeerId(button);
                childNode = Assert.Single((await service.ChildrenAsync(host.Object.ObjectId, host.Object.Generation, TreeKind.Logical, null, null, None)).Items);
                Assert.Equal(expected, childNode.RuntimeId);
                Assert.Equal(1, button.PeerCreations);
            }
        }

        [Theory]
        [InlineData(false)]
        [InlineData(true)]
        public async Task MembersAreSortedFrozenAndCarryDiagnosticsOnEveryPage(bool partial)
        {
            var inspector = new FakeInspector { Partial = partial };
            using (var window = new MappingWindow())
            using (var service = new WpfInspectionService("members", inspector))
            {
                ObjectRef root = await WindowHandle(service, window);
                var first = await service.MembersAsync(root.ObjectId, root.Generation, 2, null, None);
                Assert.Equal(new[] { "A", "B" }, first.Items.Select(member => member.Name));
                inspector.Members = Array.Empty<MemberInfo>();
                var last = await service.MembersAsync(root.ObjectId, root.Generation, 2, first.NextToken, None);
                Assert.Equal("C", Assert.Single(last.Items).Name);
                Assert.Equal(!partial, last.Complete);
                Assert.Null(last.NextToken);
                Assert.Equal(first.SnapshotId, last.SnapshotId);
                Assert.Equal(1, inspector.MemberCalls);
                Assert.Equal(partial ? 1 : 0, first.Diagnostics.Count);
                Assert.Equal(first.Diagnostics, last.Diagnostics);
            }
        }

        [Fact]
        public async Task DefaultAndMaximumPageSizesAreEnforced()
        {
            var inspector = new FakeInspector
            {
                Members = Enumerable.Range(0, 205).Select(index => new MemberInfo { Name = index.ToString("D3"), Category = "clrProperty", MemberKey = index.ToString(), DeclaringType = "Test" }).ToArray()
            };
            using (var window = new MappingWindow())
            using (var service = new WpfInspectionService("sizes", inspector))
            {
                ObjectRef root = await WindowHandle(service, window);
                var first = await service.MembersAsync(root.ObjectId, root.Generation, null, null, None);
                Assert.Equal(100, first.Items.Count);
                var last = await service.MembersAsync(root.ObjectId, root.Generation, 200, first.NextToken, None);
                Assert.Equal(105, last.Items.Count);
                Assert.True(last.Complete);
                Assert.Equal(200, (await service.MembersAsync(root.ObjectId, root.Generation, 200, null, None)).Items.Count);
                await Error(ErrorCodes.LimitExceeded, () => service.RootsAsync(201, null, None));
                await Error(ErrorCodes.InvalidParams, () => service.RootsAsync(0, null, None));
            }
        }

        [Fact]
        public async Task ReadPreservesPathOrderAndReturnsFreshReadIds()
        {
            var inspector = new FakeInspector();
            using (var window = new MappingWindow())
            using (var service = new WpfInspectionService("reads", inspector))
            {
                ObjectRef root = await WindowHandle(service, window);
                var paths = Paths("Z", "A", "Z");
                ReadResult first = await service.ReadAsync(root.ObjectId, root.Generation, paths, None);
                ReadResult second = await service.ReadAsync(root.ObjectId, root.Generation, paths, None);
                Assert.Equal(new[] { "Z", "A", "Z" }, first.Values.Select(value => value.Path[0].Name));
                Assert.Equal(new[] { "Z", "A", "Z", "Z", "A", "Z" }, inspector.Reads);
                Assert.True(Guid.TryParseExact(first.ReadId, "N", out _));
                Assert.NotEqual(first.ReadId, second.ReadId);
                Assert.All(inspector.Targets, target => Assert.Same(window.Window, target));
            }
        }

        [Fact]
        public async Task BatchResolvesOnceKeepsOrderAndReadsOnlyExactCandidates()
        {
            var inspector = new FakeInspector();
            using (var window = new MappingWindow())
            using (var service = new WpfInspectionService("batch", inspector))
            {
                int[] first = await window.PeerId(window.Buttons[0]);
                int[] second = await window.PeerId(window.Buttons[1]);
                var candidates = new[] { new CandidateRequest(second, null), new CandidateRequest(new[] { int.MinValue, 999 }, null), new CandidateRequest(first, null) };
                ReadBatchResult result = await service.ReadBatchAsync(candidates, Paths("B", "A"), None);
                Assert.Equal(new[] { MappingStatus.Exact, MappingStatus.NotFound, MappingStatus.Exact }, result.Candidates.Select(candidate => candidate.Mapping.Status));
                Assert.Equal(second, result.Candidates[0].RuntimeId);
                Assert.Equal(first, result.Candidates[2].RuntimeId);
                Assert.Empty(result.Candidates[1].Values);
                Assert.Equal(new[] { "B", "A", "B", "A" }, inspector.Reads);
                Assert.Same(window.Buttons[1], inspector.Targets[0]);
                Assert.Same(window.Buttons[0], inspector.Targets[2]);
                var mapper = (ElementMapper)typeof(WpfInspectionService).GetField("mapper", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(service)!;
                Assert.Equal(1, mapper.IndexBuildCount);
                ReadBatchResult.FromJson(result.ToJson());
            }
        }

        [Fact]
        public async Task BindingsRouteToOwnerAndReleaseInvalidatesAllObjectOperations()
        {
            var inspector = new FakeInspector();
            using (var first = new MappingWindow())
            using (var second = new MappingWindow())
            using (var service = new WpfInspectionService("bindings", inspector))
            {
                ObjectRef root = await WindowHandle(service, second);
                string[] keys = { "second", "first" };
                Assert.Same(inspector.Bindings, await service.BindingsAsync(root.ObjectId, root.Generation, keys, None));
                Assert.Same(second.Window, inspector.BindingTarget);
                Assert.Equal(keys, inspector.BindingKeys);
                await Error(ErrorCodes.ObjectStale, () => service.ReadAsync(root.ObjectId, root.Generation + 1, Paths("A"), None));
                Assert.Equal(1, await service.ReleaseAsync(new[] { root.ObjectId, root.ObjectId, "unknown" }, None));
                await Error(ErrorCodes.ObjectStale, () => service.ActAsync(PipeMethods.ActFocus, root, DateTime.UtcNow.AddSeconds(60), 2000, None));
                Assert.Equal(0, await service.ReleaseAsync(new[] { root.ObjectId }, None));
                await Error(ErrorCodes.ObjectStale, () => service.ReadAsync(root.ObjectId, root.Generation, Paths("A"), None));
                await Error(ErrorCodes.ObjectStale, () => service.BindingsAsync(root.ObjectId, root.Generation, keys, None));
                await Error(ErrorCodes.ObjectStale, () => service.MembersAsync(root.ObjectId, root.Generation, null, null, None));
                await Error(ErrorCodes.ObjectStale, () => service.ChildrenAsync(root.ObjectId, root.Generation, TreeKind.Visual, null, null, None));
                await Error(ErrorCodes.ObjectStale, () => service.ReadAsync("unknown", 1, Paths("A"), None));
                Assert.NotNull((await service.ResolveAsync(new[] { 42 }, first.Handle.ToInt64(), None)).Object);
            }
        }

        [Fact]
        public async Task RequestLimitsFailBeforeInspection()
        {
            var inspector = new FakeInspector();
            using (var service = new WpfInspectionService("limits", inspector))
            {
                var candidates = Enumerable.Range(0, 33).Select(index => new CandidateRequest(new[] { index }, null)).ToArray();
                await Error(ErrorCodes.LimitExceeded, () => service.ReadBatchAsync(candidates, Paths("A"), None));
                await Error(ErrorCodes.LimitExceeded, () => service.ReadAsync("unknown", 1, Paths(Enumerable.Repeat("A", 33).ToArray()), None));
                await Error(ErrorCodes.LimitExceeded, () => service.BindingsAsync("unknown", 1, Enumerable.Repeat("A", 33).ToArray(), None));
                await Error(ErrorCodes.LimitExceeded, () => service.ReleaseAsync(Enumerable.Repeat("A", 257).ToArray(), None));
                Assert.Empty(inspector.Reads);
            }
        }

        [Fact]
        public async Task RunningUnresponsiveDispatcherIsRejectedAndOtherDispatcherStillWorks()
        {
            using (var started = new ManualResetEventSlim())
            using (var release = new ManualResetEventSlim())
            using (var first = new MappingWindow())
            using (var second = new MappingWindow())
            {
                var inspector = new FakeInspector { BeforeRead = target => { if (ReferenceEquals(target, first.Window)) { started.Set(); release.Wait(); } } };
                using (var service = new WpfInspectionService("unresponsive", inspector))
                {
                    ObjectRef blocked = await WindowHandle(service, first);
                    ObjectRef healthy = await WindowHandle(service, second);
                    try
                    {
                        Task<ReadResult> pending = service.ReadAsync(blocked.ObjectId, blocked.Generation, Paths("A"), None);
                        Assert.True(started.Wait(TimeSpan.FromSeconds(60)));
                        await Error(ErrorCodes.DispatcherUnavailable, () => pending);
                        await Error(ErrorCodes.DispatcherUnavailable, () => service.ReadAsync(blocked.ObjectId, blocked.Generation, Paths("B"), None));
                        Assert.Single((await service.ReadAsync(healthy.ObjectId, healthy.Generation, Paths("C"), None)).Values);
                    }
                    finally { release.Set(); await first.Thread.Dispatcher.InvokeAsync(() => { }).Task; }
                }
            }
        }

        [Fact]
        public async Task FactoryCreatesRealInspectorAndSupportsRootsAndButtonMembers()
        {
            using (var window = new MappingWindow())
            using (IInspectionService service = new WpfInspectionServiceFactory().Create("factory", Array.Empty<string>()))
            {
                Assert.NotEmpty((await service.RootsAsync(null, null, None)).Items);
                int[] runtimeId = await window.PeerId(window.Buttons[0]);
                ObjectRef button = (await service.ResolveAsync(runtimeId, null, None)).Object!;
                Assert.NotNull(button);
                var members = await service.MembersAsync(button.ObjectId, button.Generation, null, null, None);
                Assert.NotEmpty(members.Items);
                Assert.Equal(new PeerRuntimeIdAdapter().IsAvailable, ((WpfInspectionService)service).ExactMappingAvailable);
            }
        }

        [Fact]
        public async Task OrdinaryObjectsRetainTraversalDispatcherForReadsMembersAndBindings()
        {
            var inspector = new FakeInspector { Nested = new object() };
            using (var window = new MappingWindow())
            using (var service = new WpfInspectionService("ordinary", inspector))
            {
                inspector.ExpectedDispatcher = window.Thread.Dispatcher;
                ObjectRef root = await WindowHandle(service, window);
                ObjectRef nested = Assert.Single((await service.ReadAsync(root.ObjectId, root.Generation, Paths("Nested"), None)).Values).Value.Object!;
                Assert.Equal(root.DispatcherId, nested.DispatcherId);
                await service.ReadAsync(nested.ObjectId, nested.Generation, Paths("Value"), None);
                Assert.Same(inspector.Nested, inspector.Targets.Last());
                Assert.NotEmpty((await service.MembersAsync(nested.ObjectId, nested.Generation, null, null, None)).Items);
                await service.BindingsAsync(nested.ObjectId, nested.Generation, new[] { "Value" }, None);
                Assert.Same(inspector.Nested, inspector.BindingTarget);
                var children = await service.ChildrenAsync(nested.ObjectId, nested.Generation, TreeKind.Visual, null, null, None);
                Assert.Empty(children.Items);
                Assert.True(children.Complete);
            }
        }

        [Fact]
        public async Task SinglePagesDoNotConsumeSnapshotSlots()
        {
            using (var window = new MappingWindow(0))
            using (var service = new WpfInspectionService("bounded", new FakeInspector()))
            {
                ObjectRef panel = await PanelHandle(service, window);
                var empty = await service.ChildrenAsync(panel.ObjectId, panel.Generation, TreeKind.Logical, null, null, None);
                Assert.Empty(empty.Items);
                Assert.True(empty.Complete);
                Assert.Null(empty.NextToken);
                for (int index = 0; index < 100; index++)
                {
                    Assert.Null((await service.RootsAsync(null, null, None)).NextToken);
                    Assert.Null((await service.MembersAsync(panel.ObjectId, panel.Generation, null, null, None)).NextToken);
                    Assert.Null((await service.ChildrenAsync(panel.ObjectId, panel.Generation, TreeKind.Logical, null, null, None)).NextToken);
                }
            }
        }

        [Fact]
        public async Task FinalPageReleasesSlotAndInvalidatesTokenWhileOpenSnapshotsRemainBounded()
        {
            using (var window = new MappingWindow())
            using (var service = new WpfInspectionService("slots", new FakeInspector()))
            {
                ObjectRef root = await WindowHandle(service, window);
                var tokens = new List<string>();
                for (int index = 0; index < ProtocolLimits.MaxSnapshots; index++)
                    tokens.Add((await service.MembersAsync(root.ObjectId, root.Generation, 1, null, None)).NextToken!);
                await Error(ErrorCodes.LimitExceeded, () => service.MembersAsync(root.ObjectId, root.Generation, 1, null, None));
                var final = await service.MembersAsync(root.ObjectId, root.Generation, 2, tokens[0], None);
                Assert.Equal(2, final.Items.Count);
                Assert.Null(final.NextToken);
                await Error(ErrorCodes.InvalidPageToken, () => service.MembersAsync(root.ObjectId, root.Generation, 2, tokens[0], None));
                Assert.NotNull((await service.MembersAsync(root.ObjectId, root.Generation, 1, null, None)).NextToken);
                await Error(ErrorCodes.LimitExceeded, () => service.MembersAsync(root.ObjectId, root.Generation, 1, null, None));
            }
        }

        private sealed class ConfiguredRedactionModel
        {
            internal int GetterCalls;
            public string CustomerMarker { get { GetterCalls++; return "value"; } }
        }

        [Fact]
        public async Task FactoryPassesConfiguredRedactNamesToInspector()
        {
            var model = new ConfiguredRedactionModel();
            using (var window = new MappingWindow())
            using (IInspectionService service = new WpfInspectionServiceFactory().Create("redaction", new[] { "CustomerMarker" }))
            {
                await window.Thread.Dispatcher.InvokeAsync(() => window.Window.DataContext = model).Task;
                ObjectRef root = await WindowHandle(service, window);
                var path = new[] { (IReadOnlyList<PathSegment>)new[] {
                    new PathSegment { Kind = SegmentKind.Property, Name = "DataContext" },
                    new PathSegment { Kind = SegmentKind.Property, Name = "CustomerMarker" } } };
                Assert.Equal(ValueStatus.Redacted, Assert.Single((await service.ReadAsync(root.ObjectId, root.Generation, path, None)).Values).Value.Status);
                Assert.Equal(0, model.GetterCalls);
            }
        }

        [Fact]
        public async Task ReadAndBindingLimitsAcceptTheirExactMaximum()
        {
            var inspector = new FakeInspector();
            using (var window = new MappingWindow())
            using (var service = new WpfInspectionService("boundaries", inspector))
            {
                ObjectRef root = await WindowHandle(service, window);
                var paths = Paths(Enumerable.Repeat("A", 32).ToArray());
                Assert.Equal(32, (await service.ReadAsync(root.ObjectId, root.Generation, paths, None)).Values.Count);
                await service.BindingsAsync(root.ObjectId, root.Generation, Enumerable.Repeat("A", 32).ToArray(), None);
                Assert.Equal(32, inspector.BindingKeys!.Count);
                var candidates = Enumerable.Range(0, 32).Select(index => new CandidateRequest(new[] { index + 1 }, window.Handle.ToInt64())).ToArray();
                Assert.Equal(32, (await service.ReadBatchAsync(candidates, Paths("A"), None)).Candidates.Count);
                Assert.Equal(1, await service.ReleaseAsync(Enumerable.Repeat(root.ObjectId, 256).ToArray(), None));
                Assert.Equal(0, await service.ReleaseAsync(Array.Empty<string>(), None));
            }
        }

        [Fact]
        public async Task CancellationAndDisposalRejectWorkAndReleaseSnapshots()
        {
            var store = new PageSnapshotStore();
            var service = new WpfInspectionService("dispose", new FakeInspector(), store, new TestAdapter { IsAvailable = false });
            Assert.False(service.ExactMappingAvailable);
            using (var cancellation = new CancellationTokenSource())
            {
                cancellation.Cancel();
                await Assert.ThrowsAnyAsync<OperationCanceledException>(() => service.RootsAsync(null, null, cancellation.Token));
            }
            service.Dispose();
            service.Dispose();
            await Assert.ThrowsAsync<ObjectDisposedException>(() => service.RootsAsync(null, null, None));
            Assert.Throws<ObjectDisposedException>(() => store.Get<int>("any", "binding"));
        }

        private sealed class UnobservedButton : Button
        {
            internal int PeerCreations;
            internal int TemplateApplications;
            public override string ToString() => throw new InvalidOperationException("Inspector must not call ToString.");
            protected override AutomationPeer OnCreateAutomationPeer() { PeerCreations++; return new ButtonAutomationPeer(this); }
            public override void OnApplyTemplate() { TemplateApplications++; base.OnApplyTemplate(); }
        }

        private sealed class ThrowingModel
        {
            public int Fail => throw new InvalidOperationException();
            public int Good => 42;
        }

        [Fact]
        public async Task ThrowingGetterDoesNotStopOtherPathsInTheSameRead()
        {
            using (var window = new MappingWindow())
            using (var service = new WpfInspectionService("throwing", new Inspection.Members.ObjectInspector()))
            {
                await window.Thread.Dispatcher.InvokeAsync(() => window.Window.DataContext = new ThrowingModel()).Task;
                ObjectRef root = await WindowHandle(service, window);
                var paths = new[] { "Fail", "Good" }.Select(name => (IReadOnlyList<PathSegment>)new[] {
                    new PathSegment { Kind = SegmentKind.Property, Name = "DataContext" },
                    new PathSegment { Kind = SegmentKind.Property, Name = name } }).ToArray();
                ReadResult result = await service.ReadAsync(root.ObjectId, root.Generation, paths, None);
                Assert.Equal(ValueStatus.Exception, result.Values[0].Value.Status);
                Assert.Equal(ValueStatus.Ok, result.Values[1].Value.Status);
                var bytes = StrictJson.Serialize(result.ToJson());
                Assert.Equal(bytes, StrictJson.Serialize(ReadResult.FromJson(StrictJson.Parse(bytes, 0, bytes.Length)).ToJson()));
            }
        }

        private sealed class FakeInspector : IObjectInspector
        {
            private readonly Inspection.Members.ObjectInspector real = new Inspection.Members.ObjectInspector();
            internal IReadOnlyList<MemberInfo> Members = new[] { "C", "A", "B" }.Select(name => new MemberInfo { Name = name, Category = "clrProperty", DeclaringType = "Test", MemberKey = name }).ToArray();
            internal readonly List<string> Reads = new List<string>();
            internal readonly List<object> Targets = new List<object>();
            internal readonly IReadOnlyList<BindingInfoDto> Bindings = new[] { new BindingInfoDto() };
            internal IReadOnlyList<string>? BindingKeys;
            internal object? BindingTarget;
            internal bool Partial;
            internal int MemberCalls;
            internal Action<object>? BeforeRead;
            internal object? Nested;
            internal Dispatcher? ExpectedDispatcher;
            public TypeInfoDto DescribeType(Type type) => real.DescribeType(type);
            public IReadOnlyList<MemberInfo> GetMembers(object target, List<Diagnostic> diagnostics)
            {
                ExpectedDispatcher?.VerifyAccess();
                if (target is DispatcherObject dispatcherObject) dispatcherObject.VerifyAccess();
                MemberCalls++;
                if (Partial) diagnostics.Add(new Diagnostic { Code = "discoveryFailed", Message = "Partial discovery", Category = "descriptor" });
                return Members;
            }
            public ValueDto ReadPath(object root, IReadOnlyList<PathSegment> path, IObjectRegistry registry, Dispatcher dispatcher, CancellationToken ct)
            {
                dispatcher.VerifyAccess();
                ExpectedDispatcher?.VerifyAccess();
                if (root is DispatcherObject dispatcherObject) dispatcherObject.VerifyAccess();
                BeforeRead?.Invoke(root);
                ct.ThrowIfCancellationRequested();
                lock (Reads) { Reads.Add(path[0].Name!); Targets.Add(root); }
                if (path[0].Name == "Nested" && Nested != null)
                    return new ValueDto { Status = ValueStatus.Ok, Kind = ValueKind.Object, DeclaredType = "System.Object", RuntimeType = "System.Object", Object = registry.Register(Nested, dispatcher, DescribeType(Nested.GetType())) };
                return new ValueDto { Status = ValueStatus.Ok, Kind = ValueKind.String, DeclaredType = "System.String", RuntimeType = "System.String", Scalar = new JsonStringNode(path[0].Name!) };
            }
            public IReadOnlyList<BindingInfoDto> GetBindings(object target, IReadOnlyList<string> memberKeys)
            {
                ExpectedDispatcher?.VerifyAccess();
                if (target is DispatcherObject dispatcherObject) dispatcherObject.VerifyAccess();
                BindingTarget = target;
                BindingKeys = memberKeys;
                return Bindings;
            }
        }
    }
}
