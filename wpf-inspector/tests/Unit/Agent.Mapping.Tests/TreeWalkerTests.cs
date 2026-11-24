using System;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using WinTestKit.Inspector.Agent.Inspection;
using WinTestKit.Inspector.Agent.Mapping;
using WinTestKit.Inspector.Protocol;
using Xunit;

namespace WinTestKit.Inspector.Agent.Mapping.Tests
{
    [Trait("Category", "Unit")]
    [Collection("WPF dispatchers")]
    public class TreeWalkerTests
    {
        [Fact]
        public async Task WalksLiveWindowAndSignalsObjectLimit()
        {
            using (var ui = new DispatcherThread())
            {
                Window window = await ui.Dispatcher.InvokeAsync(() =>
                {
                    var panel = new StackPanel();
                    panel.Children.Add(new Button());
                    panel.Children.Add(new Button());
                    var result = new Window { Content = panel, ShowActivated = false };
                    result.Show();
                    return result;
                }).Task;
                try
                {
                    var executor = new DispatcherExecutor();
                    var complete = await new TreeWalker(executor).WalkAsync(ui.Dispatcher, CancellationToken.None);
                    Assert.False(complete.LimitExceeded);
                    Assert.Contains(window, complete.Objects);
                    Assert.True(complete.Objects.OfType<Button>().Count() >= 2);
                    var limited = await new TreeWalker(executor, 1).WalkAsync(ui.Dispatcher, CancellationToken.None);
                    Assert.True(limited.LimitExceeded);
                    Assert.Single(limited.Objects);
                }
                finally { await ui.Dispatcher.InvokeAsync(window.Close).Task; }
            }
        }

        [Fact]
        public async Task ParentPrefersVisualTreeAndHandlesContent()
        {
            using (var ui = new DispatcherThread())
            {
                await ui.Dispatcher.InvokeAsync(() =>
                {
                    var panel = new StackPanel(); var button = new Button(); panel.Children.Add(button);
                    Assert.Same(panel, TreeWalker.Parent(button));
                    Assert.Null(TreeWalker.Parent(panel));
                    var span = new System.Windows.Documents.Span(); var run = new System.Windows.Documents.Run(); span.Inlines.Add(run);
                    Assert.Same(span, TreeWalker.Parent(run));
                }).Task;
            }
        }

        [Fact]
        public async Task CrossesPopupSourceBoundary()
        {
            using (var ui = new DispatcherThread())
            {
                await ui.Dispatcher.InvokeAsync(() =>
                {
                    var child = new Border { Width = 20, Height = 20 };
                    var popup = new System.Windows.Controls.Primitives.Popup { Child = child, IsOpen = true };
                    var current = (DependencyObject)child;
                    bool found = false;
                    for (int i = 0; i < 20 && current != null; i++)
                    {
                        current = TreeWalker.Parent(current);
                        if (ReferenceEquals(current, popup)) { found = true; break; }
                    }
                    popup.IsOpen = false;
                    Assert.True(found);
                }).Task;
            }
        }

        [Fact]
        public void MissingOrChangedRuntimeIdMethodIsUnavailable()
        {
            Assert.False(new PeerRuntimeIdAdapter(typeof(NoMethod)).IsAvailable);
            Assert.False(new PeerRuntimeIdAdapter(typeof(WrongReturn)).IsAvailable);
        }

        private sealed class NoMethod { }
        private sealed class WrongReturn { private string GetRuntimeId() => "wrong"; }
    }
}
