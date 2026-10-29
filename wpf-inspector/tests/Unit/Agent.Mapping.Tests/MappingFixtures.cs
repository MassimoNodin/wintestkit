using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Automation.Peers;
using System.Windows.Controls;
using System.Windows.Interop;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Inspection;
using WinTestKit.Inspector.Protocol;
using Xunit;

namespace WinTestKit.Inspector.Agent.Mapping.Tests
{
    [CollectionDefinition("WPF dispatchers", DisableParallelization = true)]
    public sealed class MappingCollection : ICollectionFixture<ApplicationDispatcherFixture> { }

    internal sealed class MappingWindow : IDisposable
    {
        internal readonly DispatcherThread Thread = new DispatcherThread();
        internal readonly DispatcherExecutor Executor = new DispatcherExecutor();
        internal readonly ObjectRegistry Registry;
        internal readonly Window Window;
        internal readonly StackPanel Panel;
        internal readonly List<Button> Buttons = new List<Button>();
        internal readonly IntPtr Handle;
        internal ElementMapper Mapper;

        internal MappingWindow(int count = 2, IPeerRuntimeIdAdapter? adapter = null, int maxObjects = ProtocolLimits.ScanMaxObjects)
        {
            Registry = new ObjectRegistry(Guid.NewGuid().ToString(), Executor);
            Window = Thread.Dispatcher.InvokeAsync(() =>
            {
                PanelPlaceholder = new StackPanel();
                for (int index = 0; index < count; index++)
                {
                    var button = new Button { Content = "Identical", Width = 100, Height = 22 };
                    AutomationProperties.SetAutomationId(button, "selection-" + index);
                    PanelPlaceholder.Children.Add(button);
                    Buttons.Add(button);
                }
                var window = new Window { Content = PanelPlaceholder, ShowActivated = false, Width = 250, Height = 800, Left = 20, Top = 20 };
                window.Show();
                return window;
            }).Task.GetAwaiter().GetResult();
            Panel = PanelPlaceholder!;
            Handle = Thread.Dispatcher.InvokeAsync(() => new WindowInteropHelper(Window).Handle).Task.GetAwaiter().GetResult();
            Mapper = new ElementMapper(Executor, adapter ?? new PeerRuntimeIdAdapter(), Registry, maxObjects);
        }

        private StackPanel? PanelPlaceholder;

        internal Task<int[]> PeerId(DependencyObject target) => Thread.Dispatcher.InvokeAsync(() =>
        {
            AutomationPeer? peer = PeerRuntimeIdAdapter.ResolveSingleElement(target);
            Assert.NotNull(peer);
            return new PeerRuntimeIdAdapter().GetRuntimeId(peer!)!;
        }).Task;

        internal object Target(MappingDto mapping)
        {
            Assert.Equal(MappingStatus.Exact, mapping.Status);
            Assert.NotNull(mapping.Object);
            Assert.True(Registry.TryGet(mapping.Object!.ObjectId, mapping.Object.Generation, out object target, out Dispatcher dispatcher));
            Assert.Same(((DispatcherObject)target).Dispatcher, dispatcher);
            MappingDto.FromJson(mapping.ToJson());
            return target;
        }

        internal static Task<Dictionary<string, int[]>> ReadUia(IntPtr hwnd) => Task.Run(() =>
        {
            Assert.Equal(ApartmentState.MTA, System.Threading.Thread.CurrentThread.GetApartmentState());
            AutomationElement root = AutomationElement.FromHandle(hwnd);
            var found = new Dictionary<string, int[]> { ["window"] = root.GetRuntimeId() };
            var pending = new Queue<AutomationElement>();
            pending.Enqueue(root);
            int visited = 0;
            while (pending.Count != 0 && visited++ < 2000)
            {
                AutomationElement current = pending.Dequeue();
                string id = current.Current.AutomationId;
                if (id.Length != 0) found[id] = current.GetRuntimeId();
                for (AutomationElement? child = System.Windows.Automation.TreeWalker.RawViewWalker.GetFirstChild(current);
                    child != null; child = System.Windows.Automation.TreeWalker.RawViewWalker.GetNextSibling(child)) pending.Enqueue(child);
            }
            return found;
        });

        public void Dispose()
        {
            try { Thread.Dispatcher.InvokeAsync(Window.Close).Task.GetAwaiter().GetResult(); }
            finally { Registry.Dispose(); Thread.Dispose(); }
        }
    }

    internal sealed class TestAdapter : IPeerRuntimeIdAdapter
    {
        internal Func<AutomationPeer, int[]?> Read = peer => new PeerRuntimeIdAdapter().GetRuntimeId(peer);
        public bool IsAvailable { get; set; } = true;
        public int[]? GetRuntimeId(AutomationPeer peer) { peer.Dispatcher.VerifyAccess(); return Read(peer); }
    }

    internal sealed class CustomButton : Button
    {
        internal int Creations;
        protected override AutomationPeer OnCreateAutomationPeer() { Creations++; return new CustomButtonPeer(this); }
    }

    internal sealed class LogicalHost : FrameworkElement
    {
        private readonly DependencyObject child;
        internal LogicalHost(DependencyObject child) { this.child = child; AddLogicalChild(child); }
        protected override System.Collections.IEnumerator LogicalChildren => new[] { child }.GetEnumerator();
    }

    internal sealed class CustomButtonPeer : ButtonAutomationPeer
    {
        internal CustomButtonPeer(CustomButton owner) : base(owner) { }
        protected override string GetClassNameCore() => "MappingCustomButton";
    }

    internal sealed class PeerContainer : FrameworkElement
    {
        internal AutomationPeer? ChildPeer;
        protected override AutomationPeer OnCreateAutomationPeer() => new ContainerPeer(this);
        private sealed class ContainerPeer : FrameworkElementAutomationPeer
        {
            private readonly PeerContainer owner;
            internal ContainerPeer(PeerContainer owner) : base(owner) { this.owner = owner; }
            protected override List<AutomationPeer> GetChildrenCore() => owner.ChildPeer == null ? new List<AutomationPeer>() : new List<AutomationPeer> { owner.ChildPeer };
        }
    }

    internal sealed class UnownedPeer : AutomationPeer
    {
        public override object? GetPattern(PatternInterface patternInterface) => null;
        protected override string GetAcceleratorKeyCore() => "";
        protected override string GetAccessKeyCore() => "";
        protected override AutomationControlType GetAutomationControlTypeCore() => AutomationControlType.Custom;
        protected override string GetAutomationIdCore() => "";
        protected override Rect GetBoundingRectangleCore() => Rect.Empty;
        protected override List<AutomationPeer>? GetChildrenCore() => null;
        protected override string GetClassNameCore() => "Unowned";
        protected override Point GetClickablePointCore() => new Point(double.NaN, double.NaN);
        protected override string GetHelpTextCore() => "";
        protected override string GetItemStatusCore() => "";
        protected override string GetItemTypeCore() => "";
        protected override AutomationPeer? GetLabeledByCore() => null;
        protected override string GetLocalizedControlTypeCore() => "custom";
        protected override string GetNameCore() => "unowned";
        protected override AutomationOrientation GetOrientationCore() => AutomationOrientation.None;
        protected override bool HasKeyboardFocusCore() => false;
        protected override bool IsContentElementCore() => true;
        protected override bool IsControlElementCore() => true;
        protected override bool IsEnabledCore() => true;
        protected override bool IsKeyboardFocusableCore() => false;
        protected override bool IsOffscreenCore() => false;
        protected override bool IsPasswordCore() => false;
        protected override bool IsRequiredForFormCore() => false;
        protected override void SetFocusCore() { }
    }

    internal sealed class NestedHwndHost : HwndHost
    {
        internal HwndSource? Source;
        internal readonly Button Child = new Button { Content = "Nested WPF" };
        protected override HandleRef BuildWindowCore(HandleRef hwndParent)
        {
            Source = new HwndSource(new HwndSourceParameters("Mapping nested source")
            {
                ParentWindow = hwndParent.Handle, WindowStyle = unchecked((int)0x50000000), Width = 150, Height = 50
            });
            Source.RootVisual = Child;
            return new HandleRef(this, Source.Handle);
        }
        protected override void DestroyWindowCore(HandleRef hwnd) { Source?.Dispose(); }
    }
}
