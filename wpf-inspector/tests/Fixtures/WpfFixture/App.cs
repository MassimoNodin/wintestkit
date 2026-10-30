using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.IO.Pipes;
using System.Linq;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Automation.Peers;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Data;
using System.Windows.Documents;
using System.Windows.Interop;
using System.Windows.Media.Animation;
using System.Windows.Threading;

namespace WinTestKit.Fixture;

public static class Counts
{
    private static readonly ConcurrentDictionary<string, int> Values = new();
    public static void Hit(string name) => Values.AddOrUpdate(name, 1, (_, n) => n + 1);
    public static object Snapshot() => new SortedDictionary<string, int>(Values);
    public static void Reset() => Values.Clear();
}

[AttributeUsage(AttributeTargets.All, AllowMultiple = true)]
public sealed class CountedAttribute : Attribute
{
    public CountedAttribute(string name) { Counts.Hit("attribute." + name); }
}

public class BaseControl : Button
{
    [Counted("base")] public virtual string Overridden { get { Counts.Hit("Base.Overridden"); return "base"; } }
    public string Hidden { get { Counts.Hit("Base.Hidden"); return "base"; } }
    public string BaseOnly { get { Counts.Hit("Base.BaseOnly"); return "base"; } }
}
public class MiddleControl : BaseControl
{
    public new string Hidden { get { Counts.Hit("Middle.Hidden"); return "middle"; } }
    public override string Overridden { get { Counts.Hit("Middle.Overridden"); return "middle"; } }
}
[Counted("fixture")]
public sealed class FixtureControl : MiddleControl, ICustomTypeDescriptor
{
    public static readonly DependencyProperty DefaultValueProperty = DependencyProperty.Register("DefaultValue", typeof(string), typeof(FixtureControl), new PropertyMetadata("default"));
    public static readonly DependencyProperty LocalValueProperty = DependencyProperty.Register("LocalValue", typeof(string), typeof(FixtureControl), new PropertyMetadata("default"));
    public static readonly DependencyProperty CoercedValueProperty = DependencyProperty.Register("CoercedValue", typeof(double), typeof(FixtureControl), new FrameworkPropertyMetadata(0d, null, (_, value) => Math.Min((double)value, 10)));
    public string DefaultValue { get => (string)GetValue(DefaultValueProperty); set => SetValue(DefaultValueProperty, value); }
    public string LocalValue { get => (string)GetValue(LocalValueProperty); set => SetValue(LocalValueProperty, value); }
    public double CoercedValue { get => (double)GetValue(CoercedValueProperty); set => SetValue(CoercedValueProperty, value); }
    public string PublicField = "public field";
    private string PrivateField = "private field";
    public string WriteOnly { set { Counts.Hit("WriteOnly.set"); PrivateField = value; } }
    public string this[int index] { get { Counts.Hit("Indexer"); return index.ToString(CultureInfo.InvariantCulture); } }
    public override string Overridden { get { Counts.Hit("Fixture.Overridden"); return "fixture"; } }
    public Type TypeValue { get { Counts.Hit(nameof(TypeValue)); return typeof(Customer); } }
    public FixtureFlags Flags { get { Counts.Hit(nameof(Flags)); return FixtureFlags.One | FixtureFlags.Two; } }
    public decimal Decimal { get { Counts.Hit(nameof(Decimal)); return 123.45m; } }
    public long LargeLong { get { Counts.Hit(nameof(LargeLong)); return 9007199254740993L; } }
    public ulong LargeUlong { get { Counts.Hit(nameof(LargeUlong)); return ulong.MaxValue; } }
    public double NaN { get { Counts.Hit(nameof(NaN)); return double.NaN; } }
    public double Infinity { get { Counts.Hit(nameof(Infinity)); return double.PositiveInfinity; } }
    public DateTime Date { get { Counts.Hit(nameof(Date)); return new DateTime(2024, 1, 2, 0, 0, 0, DateTimeKind.Utc); } }
    public DateTimeOffset Offset { get { Counts.Hit(nameof(Offset)); return DateTimeOffset.Parse("2024-01-02T03:04:05+02:00", CultureInfo.InvariantCulture); } }
    public TimeSpan Duration { get { Counts.Hit(nameof(Duration)); return TimeSpan.FromSeconds(42); } }
    public Guid Identifier { get { Counts.Hit(nameof(Identifier)); return Guid.Empty; } }
    public int[] Array { get { Counts.Hit(nameof(Array)); return new[] { 1, 2 }; } }
    public int[,] Matrix { get { Counts.Hit(nameof(Matrix)); return new int[2, 3]; } }
    public List<int> List { get { Counts.Hit(nameof(List)); return new List<int> { 1, 2 }; } }
    public Dictionary<string, int> Dictionary { get { Counts.Hit(nameof(Dictionary)); return new Dictionary<string, int> { ["one"] = 1 }; } }
    public Task Task { get { Counts.Hit(nameof(Task)); return System.Threading.Tasks.Task.CompletedTask; } }
    public Lazy<int> Lazy { get { Counts.Hit(nameof(Lazy)); return new Lazy<int>(() => 42); } }
    public Action Delegate { get { Counts.Hit(nameof(Delegate)); return () => { }; } }
    public object? NullValue { get { Counts.Hit(nameof(NullValue)); return null; } }
    public string Password { get { Counts.Hit(nameof(Password)); return "fixture password"; } }
    public string AccountNumber { get { Counts.Hit(nameof(AccountNumber)); return "fixture account"; } }
    public GuardedControl? Guarded { get { Counts.Hit(nameof(Guarded)); return guarded; } set => guarded = value; }
    private GuardedControl? guarded;
    public string ApiKey { get { Counts.Hit(nameof(ApiKey)); return "fixture key"; } }
    public string ConnectionString { get { Counts.Hit(nameof(ConnectionString)); return "fixture connection"; } }
    public string CancellationToken { get { Counts.Hit(nameof(CancellationToken)); return "fixture token"; } }
    public string AuthToken { get { Counts.Hit(nameof(AuthToken)); return "fixture token"; } }
    public string Throwing { get { Counts.Hit(nameof(Throwing)); throw new InvalidOperationException("fixture exception"); } }
    public string Slow { get { Counts.Hit(nameof(Slow)); Thread.Sleep(FixtureState.Delay); return "slow"; } }
    public string Hanging { get { Counts.Hit(nameof(Hanging)); FixtureState.Hang.Wait(); return "released"; } }
    AttributeCollection ICustomTypeDescriptor.GetAttributes() => TypeDescriptor.GetAttributes(GetType());
    string? ICustomTypeDescriptor.GetClassName() => TypeDescriptor.GetClassName(GetType());
    string? ICustomTypeDescriptor.GetComponentName() => null;
    TypeConverter ICustomTypeDescriptor.GetConverter() => TypeDescriptor.GetConverter(GetType());
    EventDescriptor? ICustomTypeDescriptor.GetDefaultEvent() => null;
    PropertyDescriptor? ICustomTypeDescriptor.GetDefaultProperty() => null;
    object? ICustomTypeDescriptor.GetEditor(Type editorBaseType) => null;
    EventDescriptorCollection ICustomTypeDescriptor.GetEvents() => TypeDescriptor.GetEvents(GetType());
    EventDescriptorCollection ICustomTypeDescriptor.GetEvents(Attribute[]? attributes) => attributes == null ? TypeDescriptor.GetEvents(GetType()) : TypeDescriptor.GetEvents(GetType(), attributes);
    PropertyDescriptorCollection ICustomTypeDescriptor.GetProperties() => Descriptors();
    PropertyDescriptorCollection ICustomTypeDescriptor.GetProperties(Attribute[]? attributes) => Descriptors();
    object ICustomTypeDescriptor.GetPropertyOwner(PropertyDescriptor? pd) => this;
    private PropertyDescriptorCollection Descriptors() { var list = TypeDescriptor.GetProperties(GetType()).Cast<PropertyDescriptor>().ToList(); list.Add(new DynamicDescriptor("DynamicProperty")); list.Add(new DynamicDescriptor("Hidden")); return new PropertyDescriptorCollection(list.ToArray()); }
}
public sealed class DynamicDescriptor : PropertyDescriptor
{
    public DynamicDescriptor(string name) : base(name, null) { }
    public override Type ComponentType => typeof(FixtureControl);
    public override bool IsReadOnly => true;
    public override Type PropertyType => typeof(string);
    public override bool CanResetValue(object component) => false;
    public override object GetValue(object? component) { Counts.Hit("descriptor." + Name); return "dynamic"; }
    public override void ResetValue(object component) { }
    public override void SetValue(object? component, object? value) { }
    public override bool ShouldSerializeValue(object component) => false;
}
[Flags] public enum FixtureFlags { One = 1, Two = 2 }
public static class AttachedOwner
{
    public static readonly DependencyProperty MarkerProperty = DependencyProperty.RegisterAttached("Marker", typeof(string), typeof(AttachedOwner), new PropertyMetadata("unset"));
    public static void SetMarker(DependencyObject target, string value) => target.SetValue(MarkerProperty, value);
    public static string GetMarker(DependencyObject target) => (string)target.GetValue(MarkerProperty);
}
public static class FixtureState { public static int Delay = 1000; public static readonly ManualResetEventSlim Hang = new(false); }
public sealed class UnusedType { static UnusedType() { Counts.Hit("static.UnusedType"); } }
public sealed class Address { public string City { get { Counts.Hit("Address.City"); return "Sydney"; } } }
public sealed class Customer { public Address Address { get { Counts.Hit("Customer.Address"); return address; } } private readonly Address address = new(); }
public sealed class ViewModel
{
    private readonly Customer customer = new();
    public Customer Customer { get { Counts.Hit("ViewModel.Customer"); return customer; } }
    public object SharedA { get { Counts.Hit("ViewModel.SharedA"); return customer; } }
    public object SharedB { get { Counts.Hit("ViewModel.SharedB"); return customer; } }
    public ViewModel Cycle { get { Counts.Hit("ViewModel.Cycle"); return this; } }
    public string Label { get { Counts.Hit("ViewModel.Label"); return label; } set { label = value; } }
    private string label;
    public ViewModel(string label = "fixture") { this.label = label; }
}
public sealed class CountingConverter : IValueConverter
{
    public object Convert(object value, Type targetType, object parameter, CultureInfo culture) { Counts.Hit("converter.Convert"); return value; }
    public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture) { Counts.Hit("converter.ConvertBack"); return value; }
}
public sealed class MultiConverter : IMultiValueConverter
{
    public object Convert(object[] values, Type targetType, object parameter, CultureInfo culture) { Counts.Hit("converter.MultiConvert"); return string.Join(" ", values); }
    public object[] ConvertBack(object value, Type[] targetTypes, object parameter, CultureInfo culture) { Counts.Hit("converter.MultiConvertBack"); return targetTypes.Select(_ => Binding.DoNothing).ToArray(); }
}
public sealed class FancyButton : Button { }
public sealed class LargeButton : FrameworkElement
{
    public string Group => "shared";
    public string Key { get; set; } = "";
    protected override AutomationPeer OnCreateAutomationPeer() => new LargeButtonPeer(this);
}
public sealed class LargeButtonPeer : FrameworkElementAutomationPeer
{
    public LargeButtonPeer(LargeButton owner) : base(owner) { }
    protected override AutomationControlType GetAutomationControlTypeCore() => AutomationControlType.Button;
    protected override string GetClassNameCore() => "LargeButton";
}
public sealed class PeerlessMarker : FrameworkElement { public string Marker => "peerless"; }
public sealed class PeerControl : Button { protected override AutomationPeer OnCreateAutomationPeer() => new FixturePeer(this); }
public sealed class GuardedControl : Button
{
    public string VisibleValue { get { Counts.Hit("Guarded.VisibleValue"); return "guarded value"; } }
    protected override AutomationPeer OnCreateAutomationPeer() => new GuardedPeer(this);
}
public sealed class GuardedPeer : ButtonAutomationPeer
{
    public GuardedPeer(Button owner) : base(owner) { }
    protected override bool IsPasswordCore() => true;
}
public sealed class FixturePeer : ButtonAutomationPeer
{
    public FixturePeer(Button owner) : base(owner) { }
    protected override string GetClassNameCore() => "FixturePeer";
    protected override List<AutomationPeer> GetChildrenCore() => new() { new ButtonAutomationPeer(new Button { Content = "unowned" }) };
}
public sealed class ChildHost : HwndHost
{
    [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern IntPtr CreateWindowEx(int ex, string cls, string title, int style, int x, int y, int w, int h, IntPtr parent, IntPtr menu, IntPtr instance, IntPtr param);
    [DllImport("user32.dll")] private static extern bool DestroyWindow(IntPtr hwnd);
    protected override HandleRef BuildWindowCore(HandleRef parent) => new(this, CreateWindowEx(0, "STATIC", "Native child", 0x50000000, 0, 0, 100, 25, parent.Handle, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero));
    protected override void DestroyWindowCore(HandleRef hwnd) => DestroyWindow(hwnd.Handle);
}

public sealed class MainWindow : Window
{
    private readonly Popup popup;
    private readonly ListBox rows;
    private Window? second;
    private Window? large;
    private readonly StackPanel dynamicTree = new();
    private int generation;
    public MainWindow()
    {
        Title = "WinTestKit WPF Fixture"; Width = 700; Height = 800; FontSize = 14;
        AutomationProperties.SetAutomationId(this, "MainWindow");
        DataContext = new ViewModel();
        var panel = Id(new StackPanel(), "MainPanel"); Content = new ScrollViewer { Content = panel };
        var fixture = Id(new FixtureControl { Content = "Fixture control", LocalValue = "local", CoercedValue = 25 }, "FixtureControl");
        AttachedOwner.SetMarker(fixture, "attached");
        fixture.BeginAnimation(OpacityProperty, new DoubleAnimation(0.5, 1, new Duration(TimeSpan.FromHours(1))));
        panel.Children.Add(fixture);
        var effect = Id(new TextBlock { Text = "Ready" }, "ActionEffect");
        var fancy = Id(new FancyButton { Name = "FancyXName", Content = "Fancy action", Tag = "fancy" }, "FancyAutomationId");
        int clicks = 0; fancy.Click += (_, _) => effect.Text = "Clicked " + ++clicks;
        panel.Children.Add(fancy); panel.Children.Add(effect);
        panel.Children.Add(new PeerlessMarker());
        var group = Id(new GroupBox { Header = "Parity group" }, "ParityGroup");
        group.Content = Id(new Button { Content = "Nested", Tag = "nested" }, "NestedButton");
        panel.Children.Add(group);
        var guarded = Id(new GuardedControl(), "GuardedControl");
        guarded.SetBinding(ContentControl.ContentProperty, new Binding("VisibleValue") { Source = guarded });
        fixture.Guarded = guarded;
        panel.Children.Add(guarded);
        var account = Id(new TextBox(), "AccountBinding");
        account.SetBinding(TextBox.TextProperty, new Binding("AccountNumber") { Source = fixture, Mode = BindingMode.OneWay });
        panel.Children.Add(account);
        panel.Children.Add(Id(dynamicTree, "DynamicTree"));
        panel.Children.Add(Id(new InventoryControl(), "InventoryControl"));
        panel.Children.Add(Id(new StatusControl(), "StatusControl"));
        panel.Children.Add(Id(new PasswordBox(), "PasswordBox"));
        var bound = Id(new TextBlock(), "BoundText"); bound.SetBinding(TextBlock.TextProperty, new Binding("Label") { Converter = new CountingConverter() }); panel.Children.Add(bound);
        var multi = Id(new TextBlock(), "MultiBinding"); var mb = new MultiBinding { Converter = new MultiConverter() }; mb.Bindings.Add(new Binding("Label")); mb.Bindings.Add(new Binding("Customer.Address.City")); multi.SetBinding(TextBlock.TextProperty, mb); panel.Children.Add(multi);
        var priority = Id(new TextBlock(), "PriorityBinding"); var pb = new PriorityBinding(); pb.Bindings.Add(new Binding("Missing")); pb.Bindings.Add(new Binding("Label")); priority.SetBinding(TextBlock.TextProperty, pb); panel.Children.Add(priority);
        var source = Id(new TextBox { Name = "BindingSource", Text = "source" }, "BindingSource"); panel.Children.Add(source);
        var element = Id(new TextBlock(), "ElementNameBinding"); element.SetBinding(TextBlock.TextProperty, new Binding("Text") { Source = source }); panel.Children.Add(element);
        var relative = Id(new TextBlock(), "RelativeSourceBinding"); relative.SetBinding(TextBlock.TextProperty, new Binding("FontSize") { RelativeSource = new RelativeSource(RelativeSourceMode.Self) }); panel.Children.Add(relative);
        var invalid = Id(new TextBox(), "ValidationError"); var validation = new Binding("Label") { ValidatesOnExceptions = true, UpdateSourceTrigger = UpdateSourceTrigger.PropertyChanged }; validation.ValidationRules.Add(new AlwaysInvalid()); invalid.SetBinding(TextBox.TextProperty, validation); panel.Children.Add(invalid); invalid.Text = "invalid"; invalid.GetBindingExpression(TextBox.TextProperty)?.UpdateSource();
        popup = new Popup { Child = Id(new Button { Content = "Popup content" }, "PopupContent"), PlacementTarget = fixture, Placement = PlacementMode.Bottom }; panel.Children.Add(popup);
        var duplicates = new StackPanel { Orientation = Orientation.Horizontal }; for (int i = 0; i < 2; i++) duplicates.Children.Add(Id(new Button { Content = "Duplicate", Width = 100, Height = 25 }, "Duplicate")); panel.Children.Add(duplicates);
        rows = Id(new ListBox { Height = 100, ItemsSource = Enumerable.Range(0, 10000).Select(i => "Row " + i).ToArray() }, "VirtualRows"); VirtualizingPanel.SetIsVirtualizing(rows, true); VirtualizingPanel.SetVirtualizationMode(rows, VirtualizationMode.Recycling); panel.Children.Add(rows);
        panel.Children.Add(Id(new PeerControl { Content = "Custom peer" }, "CustomPeer"));
        var text = Id(new TextBlock(), "ContentElement"); text.Inlines.Add(new Hyperlink(new Run("Hyperlink"))); panel.Children.Add(text);
        panel.Children.Add(Id(new ChildHost { Width = 100, Height = 25 }, "NativeHost"));
        panel.Children.Add(Id(new RichTextBox { Height = 80, Document = new FlowDocument(new Paragraph(new Run("Flow document fixture"))) }, "RichText"));
    }
    private static T Id<T>(T control, string id) where T : DependencyObject { AutomationProperties.SetAutomationId(control, id); return control; }
    public void Scenario(string name, int value)
    {
        switch (name)
        {
            case "openLarge":
                if (large != null) break;
                var stack = new StackPanel();
                for (int i = 0; i < 1500; i++)
                {
                    var button = Id(new LargeButton { Key = "Large " + i, Height = 1 }, "Large" + i);
                    stack.Children.Add(button);
                }
                for (int i = 0; i < 3500; i++) stack.Children.Add(new PeerlessMarker());
                large = new Window { Title = "Large", Width = 600, Height = 700, Content = new ScrollViewer { Content = stack } };
                AutomationProperties.SetAutomationId(large, "LargeWindow");
                large.Closed += (_, _) => large = null; large.Show(); break;
            case "openPopup": popup.IsOpen = true; break;
            case "changeDataContext": DataContext = new ViewModel("fixture-" + ++generation); break;
            case "addDynamic": dynamicTree.Children.Add(Id(new Button { Content = "Dynamic " + value }, "Dynamic" + value)); break;
            case "clearDynamic": dynamicTree.Children.Clear(); break;
            case "blockDispatcher": Counts.Hit("dispatcher.blocked"); FixtureState.Hang.Wait(); Counts.Hit("dispatcher.released"); break;
            case "scrollRows": rows.ScrollIntoView(rows.Items[Math.Max(0, Math.Min(value, rows.Items.Count - 1))]); break;
            case "openSecondWindow":
                if (second != null) break;
                var thread = new Thread(() => { var window = new Window { Title = "Fixture second dispatcher", Width = 300, Height = 200, Content = new Button { Content = "Second dispatcher" } }; AutomationProperties.SetAutomationId(window, "SecondWindow"); second = window; window.Closed += (_, _) => Dispatcher.CurrentDispatcher.BeginInvokeShutdown(DispatcherPriority.Background); window.Show(); Dispatcher.Run(); });
                thread.SetApartmentState(ApartmentState.STA); thread.IsBackground = true; thread.Start(); break;
            case "closeWindow": if (second != null) { var window = second; second = null; window.Dispatcher.BeginInvoke(new Action(window.Close)); } break;
        }
    }
}
public sealed class InventoryControl : Control
{
    public int Quantity = 17;
    private readonly string warehouse = "north";
    public string Warehouse { get { Counts.Hit("Inventory.Warehouse"); return warehouse; } }
    public bool Available { get { Counts.Hit("Inventory.Available"); return true; } }
    public decimal UnitPrice { get { Counts.Hit("Inventory.UnitPrice"); return 12.5m; } }
}
public sealed class StatusControl : Control
{
    public string Code = "ready";
    public int Attempts { get { Counts.Hit("Status.Attempts"); return 3; } }
    public double Ratio { get { Counts.Hit("Status.Ratio"); return 0.75; } }
    public string Description { get { Counts.Hit("Status.Description"); return "fixture status"; } }
    public string LongUnicode { get { Counts.Hit("Status.LongUnicode"); return new string('x', 4095) + "??tail"; } }
}
public sealed class AlwaysInvalid : ValidationRule { public override ValidationResult Validate(object value, CultureInfo cultureInfo) => new(false, "fixture validation error"); }

public static class Program
{
    [STAThread] public static void Main(string[] args)
    {
        // Force the deliberately conflicting dependencies into the target before inspection.
        _ = Newtonsoft.Json.JsonConvert.SerializeObject(new { fixture = true });
        _ = JsonSerializer.Serialize(new { fixture = true });
#if NETFRAMEWORK
        _ = new System.Memory<byte>(new byte[1]).Length;
#endif
        for (int i = 0; i + 1 < args.Length; i++) if (args[i] == "--hash-report") HashReport(args[++i]);
        var app = new Application(); var window = new MainWindow();
        var server = new Thread(() => Serve(window)) { IsBackground = true }; server.Start();
        for (int i = 0; i + 1 < args.Length; i++) if (args[i] == "--scenario") { var scenario = args[++i]; window.Loaded += (_, _) => window.Scenario(scenario, 0); }
        app.Run(window);
    }
    private static void HashReport(string path)
    {
        var dir = AppDomain.CurrentDomain.BaseDirectory; var hashes = new SortedDictionary<string, string>();
        foreach (string file in Directory.GetFiles(dir).Where(f => new[] { ".exe", ".dll", ".config", ".json" }.Contains(Path.GetExtension(f), StringComparer.OrdinalIgnoreCase)))
        { using var sha = SHA256.Create(); using var stream = File.OpenRead(file); hashes[Path.GetFileName(file)] = BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "").ToLowerInvariant(); }
        File.WriteAllText(path, JsonSerializer.Serialize(hashes));
    }
    private static NamedPipeServerStream CreatePipe()
    {
#if NETFRAMEWORK
        var security = new System.IO.Pipes.PipeSecurity(); var sid = System.Security.Principal.WindowsIdentity.GetCurrent().User!;
        security.SetAccessRuleProtection(true, false); security.AddAccessRule(new System.IO.Pipes.PipeAccessRule(sid, System.IO.Pipes.PipeAccessRights.FullControl, System.Security.AccessControl.AccessControlType.Allow));
        return new NamedPipeServerStream("WinTestKit.Fixture." + Process.GetCurrentProcess().Id, PipeDirection.InOut, 1, PipeTransmissionMode.Byte, PipeOptions.None, 4096, 4096, security);
#else
        return new NamedPipeServerStream("WinTestKit.Fixture." + Process.GetCurrentProcess().Id, PipeDirection.InOut, 1, PipeTransmissionMode.Byte, PipeOptions.CurrentUserOnly);
#endif
    }
    private static void Serve(MainWindow window)
    {
        while (true)
        {
            try
            {
                using var pipe = CreatePipe(); pipe.WaitForConnection(); using var reader = new StreamReader(pipe, Encoding.UTF8, false, 1024, true); using var writer = new StreamWriter(pipe, new UTF8Encoding(false), 1024, true) { AutoFlush = true };
                string? line; while ((line = reader.ReadLine()) != null)
                {
                    try
                    {
                        using var json = JsonDocument.Parse(line); var root = json.RootElement; var cmd = root.GetProperty("cmd").GetString(); object response = new { ok = true };
                        if (cmd == "counters") response = Counts.Snapshot();
                        else if (cmd == "reset") Counts.Reset();
                        else if (cmd == "gcCollect") { GC.Collect(); GC.WaitForPendingFinalizers(); GC.Collect(); }
                        else if (cmd == "exit") window.Dispatcher.BeginInvoke(new Action(() => Application.Current.Shutdown()));
                        else if (cmd == "scenario")
                        {
                            string name = root.GetProperty("name").GetString() ?? ""; int value = root.TryGetProperty("value", out var v) ? v.GetInt32() : 0;
                            if (name == "releaseHang") FixtureState.Hang.Set(); else if (name == "resetHang") FixtureState.Hang.Reset(); else if (name == "setSlowDelay") FixtureState.Delay = Math.Max(0, Math.Min(value, 60000)); else window.Dispatcher.BeginInvoke(new Action(() => window.Scenario(name, value)));
                        }
                        else response = new { error = "unknown command" };
                        writer.WriteLine(JsonSerializer.Serialize(response));
                    }
                    catch (Exception ex) { writer.WriteLine(JsonSerializer.Serialize(new { error = ex.Message })); }
                }
            }
            catch (Exception) { Thread.Sleep(100); }
        }
    }
}

