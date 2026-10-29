using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.InteropServices;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Automation.Peers;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Documents;
using System.Windows.Interop;
using WinTestKit.Inspector.Agent.Contracts;
using WinTestKit.Inspector.Protocol;
using Xunit;
using Xunit.Abstractions;

namespace WinTestKit.Inspector.Agent.Mapping.Tests
{
    [Trait("Category", "Unit")]
    [Collection("WPF dispatchers")]
    public sealed class ElementMapperTests
    {
        private readonly ITestOutputHelper output;
        public ElementMapperTests(ITestOutputHelper output) { this.output = output; }

        [Fact]
        public async Task TwentyFourRealUiaSelectionsRoundTripToExactObjects()
        {
            using (var fixture = new MappingWindow(24))
            {
                Dictionary<string, int[]> ids = await MappingWindow.ReadUia(fixture.Handle);
                Assert.Equal(24, ids.Keys.Count(key => key.StartsWith("selection-", StringComparison.Ordinal)));
                for (int index = 0; index < 24; index++)
                {
                    int[] id = ids["selection-" + index];
                    Assert.Same(fixture.Buttons[index], fixture.Target(await fixture.Mapper.Resolve(id, null)));
                }
                int[] peerId = await fixture.PeerId(fixture.Buttons[0]);
                output.WriteLine("TFM runtime: " + typeof(object).Assembly.ImageRuntimeVersion);
                output.WriteLine("WPF UIA element runtime ID: [" + string.Join(",", ids["selection-0"]) + "]");
                output.WriteLine("WPF peer runtime ID: [" + string.Join(",", peerId) + "]");
                output.WriteLine("Top-level HWND UIA runtime ID: [" + string.Join(",", ids["window"]) + "]");
                Assert.Equal(peerId, ids["selection-0"]);
                Assert.False(peerId.SequenceEqual(ids["window"]));
                Assert.Same(fixture.Window, fixture.Target(await fixture.Mapper.Resolve(ids["window"], fixture.Handle.ToInt64())));
            }
        }

        [Fact]
        public async Task IdenticalNameAndSizeSiblingsRemainDistinct()
        {
            using (var fixture = new MappingWindow())
            {
                var ids = await MappingWindow.ReadUia(fixture.Handle);
                Assert.False(ids["selection-0"].SequenceEqual(ids["selection-1"]));
                MappingDto first = await fixture.Mapper.Resolve(ids["selection-0"], null);
                MappingDto second = await fixture.Mapper.Resolve(ids["selection-1"], null);
                Assert.Same(fixture.Buttons[0], fixture.Target(first));
                Assert.Same(fixture.Buttons[1], fixture.Target(second));
                Assert.NotEqual(first.Object!.ObjectId, second.Object!.ObjectId);
            }
        }

        [Fact]
        public async Task CompleteSignedArrayIsIdentityNotJustSuffix()
        {
            using (var fixture = new MappingWindow())
            {
                int[] id = await fixture.PeerId(fixture.Buttons[0]);
                int[] different = (int[])id.Clone();
                different[0] = int.MinValue;
                Assert.Equal(MappingStatus.NotFound, (await fixture.Mapper.Resolve(different, null)).Status);
                Assert.Equal(MappingStatus.NotFound, (await fixture.Mapper.Resolve(id.Skip(1).ToArray(), null)).Status);
            }
        }

        [Fact]
        public async Task NestedHwndRootAndPeerMapExactly()
        {
            using (var fixture = new MappingWindow())
            {
                NestedHwndHost host = await fixture.Thread.Dispatcher.InvokeAsync(() =>
                {
                    var result = new NestedHwndHost { Width = 150, Height = 50 };
                    fixture.Panel.Children.Add(result);
                    return result;
                }).Task;
                await fixture.Thread.Dispatcher.InvokeAsync(() => { }, System.Windows.Threading.DispatcherPriority.ApplicationIdle).Task;
                IntPtr hwnd = await fixture.Thread.Dispatcher.InvokeAsync(() => host.Source!.Handle).Task;
                var ids = await MappingWindow.ReadUia(hwnd);
                Assert.Same(host.Child, fixture.Target(await fixture.Mapper.Resolve(ids["window"], hwnd.ToInt64())));
                int[] peerId = await fixture.PeerId(host.Child);
                Assert.Same(host.Child, fixture.Target(await fixture.Mapper.Resolve(peerId, null)));
            }
        }

        [Fact]
        public async Task PopupPresentationRootIsIncluded()
        {
            using (var fixture = new MappingWindow())
            {
                Popup popup = await fixture.Thread.Dispatcher.InvokeAsync(() =>
                {
                    var child = new Button { Content = "Popup" };
                    AutomationProperties.SetAutomationId(child, "popup-child");
                    var result = new Popup { Child = child, PlacementTarget = fixture.Buttons[0], StaysOpen = true, IsOpen = true };
                    return result;
                }).Task;
                try
                {
                    Button child = await fixture.Thread.Dispatcher.InvokeAsync(() => (Button)popup.Child).Task;
                    IntPtr handle = await fixture.Thread.Dispatcher.InvokeAsync(() => ((HwndSource)PresentationSource.FromVisual(child)).Handle).Task;
                    var ids = await MappingWindow.ReadUia(handle);
                    Assert.Same(child, fixture.Target(await fixture.Mapper.Resolve(ids["popup-child"], null)));
                }
                finally { await fixture.Thread.Dispatcher.InvokeAsync(() => popup.IsOpen = false).Task; }
            }
        }

        [Fact]
        public async Task CustomControlPeerUsesDocumentedOwner()
        {
            using (var fixture = new MappingWindow())
            {
                CustomButton child = await fixture.Thread.Dispatcher.InvokeAsync(() =>
                {
                    var result = new CustomButton { Content = "Custom" };
                    AutomationProperties.SetAutomationId(result, "custom");
                    fixture.Panel.Children.Add(result);
                    return result;
                }).Task;
                var ids = await MappingWindow.ReadUia(fixture.Handle);
                Assert.Same(child, fixture.Target(await fixture.Mapper.Resolve(ids["custom"], null)));
                Assert.Equal(1, child.Creations);
            }
        }

        [Fact]
        public async Task HyperlinkContentPeerRoundTripsFromUia()
        {
            using (var fixture = new MappingWindow())
            {
                Hyperlink link = await fixture.Thread.Dispatcher.InvokeAsync(() =>
                {
                    var result = new Hyperlink(new Run("A hyperlink"));
                    AutomationProperties.SetAutomationId(result, "hyperlink");
                    var text = new TextBlock();
                    text.Inlines.Add(result);
                    fixture.Panel.Children.Add(text);
                    return result;
                }).Task;
                var ids = await MappingWindow.ReadUia(fixture.Handle);
                Assert.Same(link, fixture.Target(await fixture.Mapper.Resolve(ids["hyperlink"], null)));
            }
        }

        [Fact]
        public async Task TwoDispatchersBatchBuildsExactlyOneIndexEach()
        {
            using (var first = new MappingWindow(16))
            using (var second = new MappingWindow(16))
            {
                var firstIds = await MappingWindow.ReadUia(first.Handle);
                var secondIds = await MappingWindow.ReadUia(second.Handle);
                var candidates = Enumerable.Range(0, 16).Select(index => new CandidateRequest(firstIds["selection-" + index], null))
                    .Concat(Enumerable.Range(0, 16).Select(index => new CandidateRequest(secondIds["selection-" + index], null))).ToArray();
                int before = first.Mapper.IndexBuildCount;
                var results = await first.Mapper.ResolveBatch(candidates);
                Assert.Equal(2, first.Mapper.IndexBuildCount - before);
                for (int index = 0; index < 32; index++)
                    Assert.Same(index < 16 ? first.Buttons[index] : second.Buttons[index - 16], first.Target(results[index]));
                Assert.NotEqual(results[0].Object!.DispatcherId, results[16].Object!.DispatcherId);
            }
        }

        [Fact]
        public async Task BatchOfThirtyTwoUsesOneIndexAndRejectsOversize()
        {
            using (var fixture = new MappingWindow(32))
            {
                var ids = await MappingWindow.ReadUia(fixture.Handle);
                var candidates = Enumerable.Range(0, 32).Select(index => new CandidateRequest(ids["selection-" + index], null)).ToArray();
                var results = await fixture.Mapper.ResolveBatch(candidates);
                Assert.Equal(1, fixture.Mapper.IndexBuildCount);
                Assert.Equal(32, results.Count);
                for (int index = 0; index < 32; index++) Assert.Same(fixture.Buttons[index], fixture.Target(results[index]));
                await Assert.ThrowsAsync<ProtocolException>(() => fixture.Mapper.ResolveBatch(candidates.Concat(new[] { candidates[0] }).ToArray()));
                await Assert.ThrowsAsync<ProtocolException>(() => fixture.Mapper.ResolveBatch(Array.Empty<CandidateRequest>()));
            }
        }

        [Fact]
        public async Task BatchNeverExplicitlyCreatesMissingPeersButSingleResolveMay()
        {
            var adapter = new TestAdapter { Read = peer => peer is CustomButtonPeer ? new[] { 7, -123, 456 } : new PeerRuntimeIdAdapter().GetRuntimeId(peer) };
            using (var fixture = new MappingWindow(0, adapter))
            {
                CustomButton child = await fixture.Thread.Dispatcher.InvokeAsync(() =>
                {
                    var result = new CustomButton();
                    fixture.Panel.Children.Add(new LogicalHost(result));
                    return result;
                }).Task;
                int[] id = { 7, -123, 456 };
                var results = await fixture.Mapper.ResolveBatch(new[] { new CandidateRequest(id, null) });
                Assert.Equal(MappingStatus.NotFound, results[0].Status);
                Assert.Equal(0, child.Creations);
                Assert.Same(child, fixture.Target(await fixture.Mapper.Resolve(id, null)));
                Assert.Equal(1, child.Creations);
            }
        }

        [Fact]
        public async Task HwndRootRuleDoesNotDependOnPeerAdapter()
        {
            using (var fixture = new MappingWindow(adapter: new TestAdapter { IsAvailable = false }))
            {
                var ids = await MappingWindow.ReadUia(fixture.Handle);
                Assert.Same(fixture.Window, fixture.Target(await fixture.Mapper.Resolve(ids["window"], fixture.Handle.ToInt64())));
                Assert.Equal(MappingStatus.UnsupportedPeer, (await fixture.Mapper.Resolve(ids["selection-0"], null)).Status);
            }
        }

        [Fact]
        public async Task InvalidAndForeignHwndAreNotFoundEvenWithMatchingPeerId()
        {
            using (var fixture = new MappingWindow())
            {
                int[] id = await fixture.PeerId(fixture.Buttons[0]);
                Assert.Equal(MappingStatus.NotFound, (await fixture.Mapper.Resolve(id, -1)).Status);
                IntPtr foreign = GetDesktopWindow();
                GetWindowThreadProcessId(foreign, out uint pid);
                Assert.NotEqual((uint)System.Diagnostics.Process.GetCurrentProcess().Id, pid);
                Assert.Equal(MappingStatus.NotFound, (await fixture.Mapper.Resolve(id, foreign.ToInt64())).Status);
            }
        }

        [Fact]
        public async Task ClosedWindowCannotReturnCachedExactAndChangesGeneration()
        {
            using (var fixture = new MappingWindow())
            {
                int[] id = await fixture.PeerId(fixture.Buttons[0]);
                Assert.Same(fixture.Buttons[0], fixture.Target(await fixture.Mapper.Resolve(id, null)));
                long generation = fixture.Mapper.TreeGeneration;
                await fixture.Thread.Dispatcher.InvokeAsync(fixture.Window.Close).Task;
                Assert.Equal(MappingStatus.NotFound, (await fixture.Mapper.Resolve(id, null)).Status);
                Assert.True(fixture.Mapper.TreeGeneration > generation);
                Assert.Equal(0, fixture.Mapper.CacheCount);
                Assert.Equal(MappingStatus.NotFound, (await fixture.Mapper.Resolve(id, fixture.Handle.ToInt64())).Status);
            }
        }

        [Fact]
        public async Task SourceAdditionAndExplicitInvalidateClearCache()
        {
            using (var fixture = new MappingWindow())
            {
                int[] id = await fixture.PeerId(fixture.Buttons[0]);
                fixture.Target(await fixture.Mapper.Resolve(id, null));
                Assert.Equal(1, fixture.Mapper.CacheCount);
                long generation = fixture.Mapper.TreeGeneration;
                using (var other = new MappingWindow())
                {
                    await fixture.Mapper.Resolve(new[] { int.MinValue }, null);
                    Assert.True(fixture.Mapper.TreeGeneration > generation);
                    Assert.Equal(0, fixture.Mapper.CacheCount);
                }
                fixture.Target(await fixture.Mapper.Resolve(id, null));
                generation = fixture.Mapper.TreeGeneration;
                fixture.Mapper.Invalidate();
                Assert.Equal(generation + 1, fixture.Mapper.TreeGeneration);
                Assert.Equal(0, fixture.Mapper.CacheCount);
            }
        }

        [Fact]
        public async Task CacheHitRevalidatesRuntimeIdAndLiveMembership()
        {
            var adapter = new TestAdapter();
            using (var fixture = new MappingWindow(adapter: adapter))
            {
                int[] id = await fixture.PeerId(fixture.Buttons[0]);
                fixture.Target(await fixture.Mapper.Resolve(id, null));
                int builds = fixture.Mapper.IndexBuildCount;
                fixture.Target(await fixture.Mapper.Resolve(id, null));
                Assert.Equal(builds, fixture.Mapper.IndexBuildCount);
                adapter.Read = peer => new[] { -222 };
                Assert.Equal(MappingStatus.Stale, (await fixture.Mapper.Resolve(id, null)).Status);
                adapter.Read = peer => new PeerRuntimeIdAdapter().GetRuntimeId(peer);
                await fixture.Thread.Dispatcher.InvokeAsync(() => fixture.Panel.Children.Remove(fixture.Buttons[0])).Task;
                Assert.Equal(MappingStatus.Stale, (await fixture.Mapper.Resolve(id, null)).Status);
            }
        }

        [Fact]
        public async Task ExistingPeerChildrenExposeUnownedPeerAsUnsupported()
        {
            var adapter = new TestAdapter { Read = peer => peer is UnownedPeer ? new[] { 7, -900 } : new PeerRuntimeIdAdapter().GetRuntimeId(peer) };
            using (var fixture = new MappingWindow(adapter: adapter))
            {
                await fixture.Thread.Dispatcher.InvokeAsync(() =>
                {
                    var container = new PeerContainer { ChildPeer = new UnownedPeer() };
                    fixture.Panel.Children.Add(container);
                    UIElementAutomationPeer.CreatePeerForElement(container);
                }).Task;
                Assert.Equal(MappingStatus.UnsupportedPeer, (await fixture.Mapper.Resolve(new[] { 7, -900 }, null)).Status);
            }
        }

        [Fact]
        public async Task DuplicateOwnerMatchesAreAmbiguous()
        {
            var adapter = new TestAdapter { Read = peer => peer is ButtonAutomationPeer ? new[] { 7, -444 } : new PeerRuntimeIdAdapter().GetRuntimeId(peer) };
            using (var fixture = new MappingWindow(adapter: adapter))
            {
                await fixture.PeerId(fixture.Buttons[0]);
                await fixture.PeerId(fixture.Buttons[1]);
                Assert.Equal(MappingStatus.Ambiguous, (await fixture.Mapper.Resolve(new[] { 7, -444 }, null)).Status);
            }
        }

        [Fact]
        public async Task BudgetExhaustionOverridesMissingAndPartialMatches()
        {
            using (var fixture = new MappingWindow(2, maxObjects: 1))
            {
                int[] id = await fixture.PeerId(fixture.Buttons[0]);
                Assert.Equal(MappingStatus.LimitExceeded, (await fixture.Mapper.Resolve(id, null)).Status);
                var batch = await fixture.Mapper.ResolveBatch(new[] { new CandidateRequest(new[] { -123 }, null) });
                Assert.Equal(MappingStatus.LimitExceeded, batch[0].Status);
            }
        }

        [Fact]
        public async Task RuntimeIdUnavailableOrAdapterFailureIsUnsupported()
        {
            var adapter = new TestAdapter { Read = peer => null };
            using (var fixture = new MappingWindow(adapter: adapter))
            {
                int[] id = await fixture.PeerId(fixture.Buttons[0]);
                Assert.Equal(MappingStatus.UnsupportedPeer, (await fixture.Mapper.Resolve(id, null)).Status);
                adapter.IsAvailable = false;
                var batch = await fixture.Mapper.ResolveBatch(new[] { new CandidateRequest(id, null) });
                Assert.Equal(MappingStatus.UnsupportedPeer, batch[0].Status);
            }
        }

        [Fact]
        public async Task CancelledAndMalformedRequestsAreRejected()
        {
            using (var fixture = new MappingWindow())
            {
                await Assert.ThrowsAsync<ProtocolException>(() => fixture.Mapper.Resolve(Array.Empty<int>(), null));
                await Assert.ThrowsAnyAsync<OperationCanceledException>(() => fixture.Mapper.ResolveAsync(new[] { 7 }, null, new CancellationToken(true)));
            }
        }

        [Theory]
        [InlineData(false)]
        [InlineData(true)]
        public async Task MatchIsRevalidatedAfterIndexBeforeRegistration(bool detach)
        {
            var adapter = new TestAdapter();
            using (var fixture = new MappingWindow(adapter: adapter))
            {
                int[] id = await fixture.PeerId(fixture.Buttons[0]);
                int reads = 0;
                adapter.Read = peer =>
                {
                    int[]? current = new PeerRuntimeIdAdapter().GetRuntimeId(peer);
                    if (current != null && id.SequenceEqual(current) && ++reads == 2)
                    {
                        if (detach) fixture.Panel.Children.Remove(fixture.Buttons[0]);
                        else return new[] { -789 };
                    }
                    return current;
                };
                MappingDto result = await fixture.Mapper.Resolve(id, null);
                Assert.Equal(MappingStatus.Stale, result.Status);
                Assert.Null(result.Object);
            }
        }

        [Fact]
        public async Task ElapsedBudgetIsSharedByTreeAndPeerTraversal()
        {
            var adapter = new TestAdapter();
            using (var fixture = new MappingWindow(adapter: adapter))
            {
                int[] id = await fixture.PeerId(fixture.Buttons[0]);
                adapter.Read = peer => { Thread.Sleep(30); return new PeerRuntimeIdAdapter().GetRuntimeId(peer); };
                var mapper = new ElementMapper(fixture.Executor, adapter, fixture.Registry, maxMilliseconds: 10);
                Assert.Equal(MappingStatus.LimitExceeded, (await mapper.Resolve(id, null)).Status);
            }
        }

        [Fact]
        public async Task ReplacingRootOnSamePresentationSourceChangesGeneration()
        {
            using (var fixture = new MappingWindow())
            {
                int[] id = await fixture.PeerId(fixture.Buttons[0]);
                fixture.Target(await fixture.Mapper.Resolve(id, null));
                long generation = fixture.Mapper.TreeGeneration;
                var replacement = await fixture.Thread.Dispatcher.InvokeAsync(() =>
                {
                    var root = new Button { Content = "Replacement" };
                    ((HwndSource)PresentationSource.FromVisual(fixture.Window)).RootVisual = root;
                    return root;
                }).Task;
                try
                {
                    Assert.Equal(MappingStatus.NotFound, (await fixture.Mapper.Resolve(id, null)).Status);
                    Assert.True(fixture.Mapper.TreeGeneration > generation);
                    Assert.Equal(0, fixture.Mapper.CacheCount);
                    Assert.Same(replacement, fixture.Target(await fixture.Mapper.Resolve(new[] { 42 }, fixture.Handle.ToInt64())));
                }
                finally
                {
                    await fixture.Thread.Dispatcher.InvokeAsync(() => HwndSource.FromHwnd(fixture.Handle).RootVisual = fixture.Window).Task;
                }
            }
        }

        [Fact]
        public async Task BatchDoesNotReuseCacheAndHwndCandidatesObeySameRules()
        {
            using (var fixture = new MappingWindow())
            {
                var ids = await MappingWindow.ReadUia(fixture.Handle);
                fixture.Target(await fixture.Mapper.Resolve(ids["selection-0"], null));
                int builds = fixture.Mapper.IndexBuildCount;
                var results = await fixture.Mapper.ResolveBatch(new[]
                {
                    new CandidateRequest(ids["selection-0"], null),
                    new CandidateRequest(ids["window"], fixture.Handle.ToInt64()),
                    new CandidateRequest(ids["selection-0"], -1)
                });
                Assert.Equal(builds + 1, fixture.Mapper.IndexBuildCount);
                Assert.Same(fixture.Buttons[0], fixture.Target(results[0]));
                Assert.Same(fixture.Window, fixture.Target(results[1]));
                Assert.Equal(MappingStatus.NotFound, results[2].Status);
            }
        }

        [Fact]
        public async Task PeerCreationFailureIsExplicitlyUnsupported()
        {
            using (var fixture = new MappingWindow(0))
            {
                await fixture.Thread.Dispatcher.InvokeAsync(() => fixture.Panel.Children.Add(new LogicalHost(new ThrowingPeerElement()))).Task;
                Assert.Equal(MappingStatus.UnsupportedPeer, (await fixture.Mapper.Resolve(new[] { -999 }, null)).Status);
            }
        }

        private sealed class ThrowingPeerElement : FrameworkElement
        {
            protected override AutomationPeer OnCreateAutomationPeer() => throw new InvalidOperationException("Fixture peer creation failure");
        }

        [DllImport("user32.dll")] private static extern IntPtr GetDesktopWindow();
        [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint processId);
    }
}
