using System;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using WinTestKit.Inspector.Agent.Mapping;
using WinTestKit.Inspector.Agent.State;
using WinTestKit.Inspector.Protocol;
using Xunit;

namespace WinTestKit.Inspector.Agent.Mapping.Tests
{
    [Trait("Category", "Unit")]
    [Collection("WPF dispatchers")]
    public sealed class StateReaderTests
    {
        [Fact]
        public async Task ShownButtonGeometryAndRuntimeIdFollowWpf()
        {
            using (var ui = new DispatcherThread())
            {
                await ui.Dispatcher.InvokeAsync(() =>
                {
                    var button = new Button { Content = "button", Width = 120, Height = 40 };
                    var window = new Window { Left = -300, Top = 20, Width = 300, Height = 200, Content = button, ShowInTaskbar = false };
                    try
                    {
                        window.Show(); window.UpdateLayout();
                        var adapter = new PeerRuntimeIdAdapter();
                        var state = StateReader.Read(button, new ObjectRef(), adapter);
                        Point point = button.PointToScreen(new Point());
                        Point end = button.PointToScreen(new Point(button.ActualWidth, button.ActualHeight));
                        Assert.NotNull(state.Bounds);
                        Assert.Equal(point.X, state.Bounds!.X, 4);
                        Assert.Equal(point.Y, state.Bounds.Y, 4);
                        Assert.Equal(end.X - point.X, state.Bounds.Width, 4);
                        Assert.Equal(end.Y - point.Y, state.Bounds.Height, 4);
                        Assert.True(state.Visible);
                        Assert.True(state.IsKeyboardFocusable);
                        button.Focus();
                        Assert.Equal(button.IsKeyboardFocused, StateReader.Read(button, new ObjectRef(), adapter).Focused);
                        Assert.NotNull(state.UiaRuntimeId);
                        Assert.Equal(adapter.GetRuntimeId(PeerRuntimeIdAdapter.ResolveSingleElement(button)!), state.UiaRuntimeId);
                        button.IsEnabled = false;
                        Assert.False(StateReader.Read(button, new ObjectRef(), adapter).IsKeyboardFocusable);
                        button.Visibility = System.Windows.Visibility.Hidden; window.UpdateLayout();
                        Assert.False(StateReader.Read(button, new ObjectRef(), adapter).Visible);
                        button.Visibility = System.Windows.Visibility.Collapsed; window.UpdateLayout();
                        var hidden = StateReader.Read(button, new ObjectRef(), adapter);
                        Assert.False(hidden.Visible); Assert.Null(hidden.Bounds);
                    }
                    finally { window.Close(); }
                }).Task;
            }
        }

        [Fact]
        public async Task OpacityAndTemplatePartsAreReported()
        {
            using (var ui = new DispatcherThread())
            {
                await ui.Dispatcher.InvokeAsync(() =>
                {
                    var combo = new ComboBox { Width = 120, Height = 40 };
                    var panel = new StackPanel(); panel.Children.Add(combo);
                    var window = new Window { Width = 300, Height = 200, Content = panel, ShowInTaskbar = false };
                    try
                    {
                        window.Show(); window.UpdateLayout();
                        var adapter = new PeerRuntimeIdAdapter();
                        var state = StateReader.Read(combo, new ObjectRef(), adapter);
                        Assert.Contains(state.Parts, part => part.Role == "comboDropDown" && part.Bounds != null);
                        panel.Opacity = 0;
                        Assert.False(StateReader.Read(combo, new ObjectRef(), adapter).Visible);
                        Assert.Null(StateReader.Read(new DrawingVisual(), new ObjectRef(), adapter).UiaRuntimeId);
                    }
                    finally { window.Close(); }
                }).Task;
            }
        }
        [Fact]
        public async Task ScrollBarTemplateExposesTrackAndThumb()
        {
            using (var ui = new DispatcherThread())
            {
                await ui.Dispatcher.InvokeAsync(() =>
                {
                    var bar = new System.Windows.Controls.Primitives.ScrollBar { Orientation = Orientation.Vertical, Width = 30, Height = 150, Maximum = 100, ViewportSize = 20 };
                    var window = new Window { Width = 200, Height = 200, Content = bar, ShowInTaskbar = false };
                    try
                    {
                        window.Show(); window.UpdateLayout();
                        var state = StateReader.Read(bar, new ObjectRef(), new PeerRuntimeIdAdapter());
                        Assert.Contains(state.Parts, part => part.Role == "scrollTrack");
                        Assert.Contains(state.Parts, part => part.Role == "scrollThumb");
                    }
                    finally { window.Close(); }
                }).Task;
            }
        }

        [Fact]
        public async Task ScrollViewportClipsAndHidesScrolledOutElements()
        {
            using (var ui = new DispatcherThread())
            {
                await ui.Dispatcher.InvokeAsync(() =>
                {
                    var button = new Button { Height = 80, Width = 100, Content = "item" };
                    var panel = new StackPanel(); panel.Children.Add(button); panel.Children.Add(new Border { Height = 500 });
                    var scroll = new ScrollViewer { Height = 50, Width = 150, Content = panel, VerticalScrollBarVisibility = ScrollBarVisibility.Visible };
                    var window = new Window { Width = 300, Height = 200, Content = scroll, ShowInTaskbar = false };
                    try
                    {
                        window.Show(); window.UpdateLayout();
                        var adapter = new PeerRuntimeIdAdapter();
                        var partial = StateReader.Read(button, new ObjectRef(), adapter);
                        Assert.True(partial.Visible); Assert.True(partial.Clipped);
                        scroll.ScrollToVerticalOffset(200); window.UpdateLayout();
                        var outOfView = StateReader.Read(button, new ObjectRef(), adapter);
                        Assert.False(outOfView.Visible); Assert.True(outOfView.Offscreen);
                    }
                    finally { window.Close(); }
                }).Task;
            }
        }

    }
}

