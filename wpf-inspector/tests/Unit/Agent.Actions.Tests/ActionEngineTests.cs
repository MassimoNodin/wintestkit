using System;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Actions;
using WinTestKit.Inspector.Agent.Inspection;
using WinTestKit.Inspector.Protocol;
using Xunit;

namespace WinTestKit.Inspector.Agent.Actions.Tests
{
    [Trait("Category", "Unit")]
    public sealed class ActionEngineTests
    {
        private sealed class Scrollable : FrameworkElement
        {
            internal int Calls;
            protected override System.Windows.Automation.Peers.AutomationPeer OnCreateAutomationPeer() => new ScrollablePeer(this);
        }
        private sealed class ScrollablePeer : System.Windows.Automation.Peers.FrameworkElementAutomationPeer, System.Windows.Automation.Provider.IScrollProvider
        {
            internal ScrollablePeer(Scrollable owner) : base(owner) { }
            public override object GetPattern(System.Windows.Automation.Peers.PatternInterface pattern) => pattern == System.Windows.Automation.Peers.PatternInterface.Scroll ? this : base.GetPattern(pattern);
            public bool HorizontallyScrollable => false;
            public bool VerticallyScrollable => true;
            public double HorizontalScrollPercent => -1;
            public double VerticalScrollPercent => 0;
            public double HorizontalViewSize => 100;
            public double VerticalViewSize => 50;
            public void Scroll(System.Windows.Automation.ScrollAmount horizontal, System.Windows.Automation.ScrollAmount vertical) => ((Scrollable)Owner).Calls++;
            public void SetScrollPercent(double horizontal, double vertical) { }
        }
        private sealed class Selectable : FrameworkElement
        {
            internal bool Selected;
            protected override System.Windows.Automation.Peers.AutomationPeer OnCreateAutomationPeer() => new SelectablePeer(this);
        }
        private sealed class SelectablePeer : System.Windows.Automation.Peers.FrameworkElementAutomationPeer, System.Windows.Automation.Provider.ISelectionItemProvider
        {
            internal SelectablePeer(Selectable owner) : base(owner) { }
            public override object GetPattern(System.Windows.Automation.Peers.PatternInterface pattern) => pattern == System.Windows.Automation.Peers.PatternInterface.SelectionItem ? this : base.GetPattern(pattern);
            public bool IsSelected => ((Selectable)Owner).Selected;
            public System.Windows.Automation.Provider.IRawElementProviderSimple SelectionContainer => null!;
            public void Select() { ((Selectable)Owner).Selected = true; }
            public void AddToSelection() => Select();
            public void RemoveFromSelection() { ((Selectable)Owner).Selected = false; }
        }
        private sealed class BlockingToggle : FrameworkElement
        {
            internal readonly ManualResetEventSlim Entered = new ManualResetEventSlim();
            internal readonly ManualResetEventSlim Release = new ManualResetEventSlim();
            protected override System.Windows.Automation.Peers.AutomationPeer OnCreateAutomationPeer() => new BlockingTogglePeer(this);
        }
        private sealed class BlockingTogglePeer : System.Windows.Automation.Peers.FrameworkElementAutomationPeer, System.Windows.Automation.Provider.IToggleProvider
        {
            internal BlockingTogglePeer(BlockingToggle owner) : base(owner) { }
            public override object GetPattern(System.Windows.Automation.Peers.PatternInterface pattern) => pattern == System.Windows.Automation.Peers.PatternInterface.Toggle ? this : base.GetPattern(pattern);
            public System.Windows.Automation.ToggleState ToggleState => System.Windows.Automation.ToggleState.Off;
            public void Toggle() { var owner = (BlockingToggle)Owner; owner.Entered.Set(); owner.Release.Wait(); }
        }
        private sealed class ThrowingInvoke : FrameworkElement
        {
            internal readonly TaskCompletionSource<bool> Invoked = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            protected override System.Windows.Automation.Peers.AutomationPeer OnCreateAutomationPeer() => new ThrowingInvokePeer(this);
        }
        private sealed class ThrowingInvokePeer : System.Windows.Automation.Peers.FrameworkElementAutomationPeer, System.Windows.Automation.Provider.IInvokeProvider
        {
            internal ThrowingInvokePeer(ThrowingInvoke owner) : base(owner) { }
            public override object GetPattern(System.Windows.Automation.Peers.PatternInterface pattern) => pattern == System.Windows.Automation.Peers.PatternInterface.Invoke ? this : base.GetPattern(pattern);
            public void Invoke() { ((ThrowingInvoke)Owner).Invoked.TrySetResult(true); throw new System.Windows.Automation.ElementNotEnabledException(); }
        }
        private sealed class Ui : IDisposable
        {
            private readonly Thread thread;
            internal Dispatcher Dispatcher { get; }
            internal Ui()
            {
                var ready = new TaskCompletionSource<Dispatcher>();
                thread = new Thread(() => { ready.SetResult(Dispatcher.CurrentDispatcher); Dispatcher.Run(); }) { IsBackground = true };
                thread.SetApartmentState(ApartmentState.STA);
                thread.Start();
                Dispatcher = ready.Task.GetAwaiter().GetResult();
            }
            public void Dispose() { Dispatcher.BeginInvokeShutdown(DispatcherPriority.Send); thread.Join(); }
        }

        private static Task<ActResult> Act(Ui ui, DispatcherExecutor executor, object target, string method, int timeout = 1000) =>
            ActionEngine.ExecuteAsync(executor, ui.Dispatcher, target, new ObjectRef(), method, DateTime.UtcNow.AddSeconds(2), timeout, CancellationToken.None);

        [Theory]
        [InlineData(PipeMethods.ActSetValue)]
        [InlineData(PipeMethods.ActSetRange)]
        [InlineData(PipeMethods.ActScroll)]
        public async Task NewActionsRejectExpiredDeadlines(string method)
        {
            using (var ui = new Ui())
            {
                var element = await ui.Dispatcher.InvokeAsync(() => new Button()).Task;
                var error = await Assert.ThrowsAsync<ProtocolException>(() => ActionEngine.ExecuteAsync(new DispatcherExecutor(), ui.Dispatcher, element, new ObjectRef(), method, DateTime.UtcNow.AddSeconds(-1), 1000, CancellationToken.None));
                Assert.Equal(ErrorCodes.LimitExceeded, error.Code);
            }
        }

        [Fact]
        public async Task ValueAndRangeActionsValidateAndRespectProtection()
        {
            using (var ui = new Ui())
            {
                var controls = await ui.Dispatcher.InvokeAsync(() => (text: new TextBox(), password: new PasswordBox(), slider: new Slider { Minimum = 0, Maximum = 10 })).Task;
                var executor = new DispatcherExecutor();
                Task<ActResult> Run(object target, string method, object args) => ActionEngine.ExecuteAsync(executor, ui.Dispatcher, target, new ObjectRef(), method, DateTime.UtcNow.AddSeconds(2), 1000, CancellationToken.None, args);
                var text = new ActSetValueParams { Value = "example" };
                Assert.Equal(ActionOutcome.Performed, (await Run(controls.text, PipeMethods.ActSetValue, text)).Outcome);
                Assert.Equal(ActionOutcome.NoChange, (await Run(controls.text, PipeMethods.ActSetValue, text)).Outcome);
                await ui.Dispatcher.InvokeAsync(() => controls.text.IsReadOnly = true).Task;
                Assert.Equal(ErrorCodes.ActionUnsupported, (await Assert.ThrowsAsync<ProtocolException>(() => Run(controls.text, PipeMethods.ActSetValue, text))).Code);
                Assert.Equal(ErrorCodes.ActionUnsupported, (await Assert.ThrowsAsync<ProtocolException>(() => Run(controls.password, PipeMethods.ActSetValue, text))).Code);
                Assert.Equal(ErrorCodes.ActionUnsupported, (await Assert.ThrowsAsync<ProtocolException>(() => Run(controls.text, PipeMethods.ActSetRange, new ActSetRangeParams()))).Code);
                Assert.Equal(ErrorCodes.ActionUnsupported, (await Assert.ThrowsAsync<ProtocolException>(() => Run(controls.text, PipeMethods.ActScroll, new ActScrollParams { Horizontal = ScrollAmount.None, Vertical = ScrollAmount.None }))).Code);
                var range = new ActSetRangeParams { Value = 5 };
                Assert.Equal(ActionOutcome.Performed, (await Run(controls.slider, PipeMethods.ActSetRange, range)).Outcome);
                Assert.Equal(ActionOutcome.NoChange, (await Run(controls.slider, PipeMethods.ActSetRange, range)).Outcome);
                range.Value = 11;
                Assert.Equal(ErrorCodes.InvalidParams, (await Assert.ThrowsAsync<ProtocolException>(() => Run(controls.slider, PipeMethods.ActSetRange, range))).Code);
                range.Value = double.NaN;
                Assert.Equal(ErrorCodes.InvalidParams, (await Assert.ThrowsAsync<ProtocolException>(() => Run(controls.slider, PipeMethods.ActSetRange, range))).Code);
            }
        }

        [Fact]
        public async Task ScrollActionsRespectAxesAndDeadline()
        {
            using (var ui = new Ui())
            {
                var control = await ui.Dispatcher.InvokeAsync(() => new Scrollable()).Task;
                var executor = new DispatcherExecutor();
                var args = new ActScrollParams { Horizontal = ScrollAmount.None, Vertical = ScrollAmount.None };
                Task<ActResult> Run(DateTime deadline) => ActionEngine.ExecuteAsync(executor, ui.Dispatcher, control, new ObjectRef(), PipeMethods.ActScroll, deadline, 1000, CancellationToken.None, args);
                Assert.Equal(ActionOutcome.NoChange, (await Run(DateTime.UtcNow.AddSeconds(2))).Outcome);
                args.Vertical = ScrollAmount.SmallIncrement;
                Assert.Equal(ActionOutcome.Performed, (await Run(DateTime.UtcNow.AddSeconds(2))).Outcome);
                args.Horizontal = ScrollAmount.SmallIncrement;
                Assert.Equal(ErrorCodes.ActionUnsupported, (await Assert.ThrowsAsync<ProtocolException>(() => Run(DateTime.UtcNow.AddSeconds(2)))).Code);
                args.Horizontal = "invalid";
                Assert.Equal(ErrorCodes.InvalidParams, (await Assert.ThrowsAsync<ProtocolException>(() => Run(DateTime.UtcNow.AddSeconds(2)))).Code);
                Assert.Equal(ErrorCodes.LimitExceeded, (await Assert.ThrowsAsync<ProtocolException>(() => Run(DateTime.UtcNow.AddSeconds(-1)))).Code);
            }
        }

        [Theory]
        [InlineData(PipeMethods.ActBringIntoView)]
        [InlineData(PipeMethods.ActScrollIntoView)]
        public async Task BringsElementIntoView(string method)
        {
            using (var ui = new Ui())
            {
                var button = await ui.Dispatcher.InvokeAsync(() => new Button()).Task;
                Assert.Equal(ActionOutcome.Performed, (await Act(ui, new DispatcherExecutor(), button, method)).Outcome);
            }
        }

        [Theory]
        [InlineData(PipeMethods.ActInvoke)]
        [InlineData(PipeMethods.ActToggle)]
        [InlineData(PipeMethods.ActExpand)]
        [InlineData(PipeMethods.ActCollapse)]
        [InlineData(PipeMethods.ActSelect)]
        [InlineData(PipeMethods.ActFocus)]
        [InlineData(PipeMethods.ActBringIntoView)]
        [InlineData(PipeMethods.ActScrollIntoView)]
        public async Task MissingPatternsAreUnsupported(string method)
        {
            using (var ui = new Ui())
            {
                var element = await ui.Dispatcher.InvokeAsync(() => new Border()).Task;
                Assert.Equal(ErrorCodes.ActionUnsupported, (await Assert.ThrowsAsync<ProtocolException>(() => Act(ui, new DispatcherExecutor(), element, method))).Code);
            }
        }

        [Fact]
        public async Task DisabledElementsAreUnsupported()
        {
            using (var ui = new Ui())
            {
                var button = await ui.Dispatcher.InvokeAsync(() => new Button { IsEnabled = false }).Task;
                Assert.Equal(ErrorCodes.ActionUnsupported, (await Assert.ThrowsAsync<ProtocolException>(() => Act(ui, new DispatcherExecutor(), button, PipeMethods.ActInvoke))).Code);
            }
        }

        [Fact]
        public async Task FocusReportsExistingKeyboardFocus()
        {
            using (var ui = new Ui())
            {
                var pair = await ui.Dispatcher.InvokeAsync(() =>
                {
                    var panel = new StackPanel();
                    var first = new Button();
                    var button = new Button();
                    panel.Children.Add(first);
                    panel.Children.Add(button);
                    var window = new Window { Content = panel, ShowInTaskbar = false };
                    window.Show();
                    window.Activate();
                    first.Focus();
                    return (window, button);
                }).Task;
                try
                {
                    var executor = new DispatcherExecutor();
                    var first = await Act(ui, executor, pair.button, PipeMethods.ActFocus);
                    Assert.Equal(ActionOutcome.Performed, first.Outcome);
                    Assert.Equal(ActionOutcome.NoChange, (await Act(ui, executor, pair.button, PipeMethods.ActFocus)).Outcome);
                }
                finally { await ui.Dispatcher.InvokeAsync(pair.window.Close).Task; }
            }
        }

        [Fact]
        public async Task ExpanderReportsStateChanges()
        {
            using (var ui = new Ui())
            {
                var expander = await ui.Dispatcher.InvokeAsync(() => new Expander()).Task;
                var executor = new DispatcherExecutor();
                Assert.Equal(ActionOutcome.Performed, (await Act(ui, executor, expander, PipeMethods.ActExpand)).Outcome);
                Assert.Equal(ActionOutcome.NoChange, (await Act(ui, executor, expander, PipeMethods.ActExpand)).Outcome);
                Assert.Equal(ActionOutcome.Performed, (await Act(ui, executor, expander, PipeMethods.ActCollapse)).Outcome);
                Assert.Equal(ActionOutcome.NoChange, (await Act(ui, executor, expander, PipeMethods.ActCollapse)).Outcome);
            }
        }

        [Fact]
        public async Task ToggleAndSelectUsePeerPatterns()
        {
            using (var ui = new Ui())
            {
                var controls = await ui.Dispatcher.InvokeAsync(() =>
                {
                    var check = new CheckBox();
                    var item = new Selectable();
                    return (check, item);
                }).Task;
                var executor = new DispatcherExecutor();
                Assert.Equal(ActionOutcome.Performed, (await Act(ui, executor, controls.check, PipeMethods.ActToggle)).Outcome);
                Assert.True(await ui.Dispatcher.InvokeAsync(() => controls.check.IsChecked == true).Task);
                Assert.Equal(ActionOutcome.Performed, (await Act(ui, executor, controls.item, PipeMethods.ActSelect)).Outcome);
                Assert.Equal(ActionOutcome.NoChange, (await Act(ui, executor, controls.item, PipeMethods.ActSelect)).Outcome);
            }
        }

        [Fact]
        public async Task InvokeReturnsWhileModalDialogIsOpen()
        {
            using (var ui = new Ui())
            {
                var shown = new TaskCompletionSource<Button>(TaskCreationOptions.RunContinuationsAsynchronously);
                var closed = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
                var button = await ui.Dispatcher.InvokeAsync(() =>
                {
                    var control = new Button();
                    control.Click += (_, __) =>
                    {
                        var close = new Button();
                        var dialog = new Window { Content = close, ShowInTaskbar = false };
                        close.Click += (_, __) => dialog.Close();
                        dialog.Dispatcher.BeginInvoke(new Action(() => shown.TrySetResult(close)), DispatcherPriority.ApplicationIdle);
                        dialog.ShowDialog();
                        closed.TrySetResult(true);
                    };
                    return control;
                }).Task;
                var executor = new DispatcherExecutor();
                var result = await Act(ui, executor, button, PipeMethods.ActInvoke);
                Assert.Equal(ActionOutcome.Performed, result.Outcome);
                var completed = await Task.WhenAny(shown.Task, Task.Delay(5000));
                Assert.Same(shown.Task, completed);
                var closeButton = await shown.Task;
                try
                {
                    Assert.Equal(ActionOutcome.Performed, (await Act(ui, executor, closeButton, PipeMethods.ActInvoke)).Outcome);
                    Assert.Same(closed.Task, await Task.WhenAny(closed.Task, Task.Delay(5000)));
                    Assert.Equal(ActionOutcome.Performed, (await Act(ui, executor, button, PipeMethods.ActBringIntoView)).Outcome);
                }
                finally { await ui.Dispatcher.InvokeAsync(() => Window.GetWindow(closeButton)?.Close()).Task; }
            }
        }

        [Fact]
        public async Task DeferredInvokeExceptionDoesNotFaultExecutor()
        {
            using (var ui = new Ui())
            {
                var button = await ui.Dispatcher.InvokeAsync(() => new ThrowingInvoke()).Task;
                var executor = new DispatcherExecutor();
                Assert.Equal(ActionOutcome.Performed, (await Act(ui, executor, button, PipeMethods.ActInvoke)).Outcome);
                Assert.Same(button.Invoked.Task, await Task.WhenAny(button.Invoked.Task, Task.Delay(5000)));
                Assert.Equal(ActionOutcome.Performed, (await Act(ui, executor, button, PipeMethods.ActBringIntoView)).Outcome);
            }
        }

        [Fact]
        public async Task QueuedActionTimesOutBeforeStarting()
        {
            using (var ui = new Ui())
            using (var entered = new ManualResetEventSlim())
            using (var release = new ManualResetEventSlim())
            {
                var button = await ui.Dispatcher.InvokeAsync(() =>
                {
                    var control = new Button();
                    control.Click += (_, __) => { entered.Set(); release.Wait(); };
                    return control;
                }).Task;
                var executor = new DispatcherExecutor();
                try
                {
                    Assert.Equal(ActionOutcome.Performed, (await Act(ui, executor, button, PipeMethods.ActInvoke)).Outcome);
                    Assert.True(entered.Wait(1000));
                    var error = await Assert.ThrowsAsync<ProtocolException>(() => Act(ui, executor, button, PipeMethods.ActBringIntoView, 50));
                    Assert.Equal(ErrorCodes.LimitExceeded, error.Code);
                }
                finally { release.Set(); }
            }
        }

        [Fact]
        public async Task HungActionMarksDispatcherUnavailable()
        {
            using (var ui = new Ui())
            {
                var control = await ui.Dispatcher.InvokeAsync(() => new BlockingToggle()).Task;
                var executor = new DispatcherExecutor();
                try
                {
                    var action = Act(ui, executor, control, PipeMethods.ActToggle, 150);
                    Assert.True(control.Entered.Wait(1000));
                    Assert.Equal(ErrorCodes.LimitExceeded, (await Assert.ThrowsAsync<ProtocolException>(() => action)).Code);
                    Assert.Equal(ErrorCodes.DispatcherUnavailable, (await Assert.ThrowsAsync<ProtocolException>(() => Act(ui, executor, control, PipeMethods.ActToggle))).Code);
                }
                finally { control.Release.Set(); }
            }
        }
    }
}
