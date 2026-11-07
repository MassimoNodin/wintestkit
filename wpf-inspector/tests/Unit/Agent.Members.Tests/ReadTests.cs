using System;
using System.Collections.Generic;
using System.Threading;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Contracts;
using WinTestKit.Inspector.Agent.Inspection.Members;
using WinTestKit.Inspector.Protocol;
using Xunit;

namespace WinTestKit.Inspector.Agent.Members.Tests
{
    [Trait("Category", "Unit")]
    public sealed class ReadTests
    {
        private sealed class Model
        {
            public int Calls;
            public int SecretCalls;
            public int Number { get { Calls++; return 42; } }
            public string Password { get { SecretCalls++; return "sensitive"; } }
            public Model Self => this;
            public Model? Missing => null;
            public decimal Amount => 123.45m;
            public long Large => 9007199254740992L;
            public string Text => "a\U0001F600b";
            public int[] Array => new[] { 1, 2 };
            public bool Flag => true;
            public DateTime Date => new DateTime(2020, 1, 2, 0, 0, 0, DateTimeKind.Utc);
            public Guid Id => Guid.Empty;
            public DayOfWeek Day => DayOfWeek.Monday;
            public int Fail => throw new InvalidOperationException("private content");
        }
        private sealed class Registry : IObjectRegistry
        {
            private readonly Dictionary<object, ObjectRef> refs = new Dictionary<object, ObjectRef>(ReferenceComparer.Instance);
            public ObjectRef Register(object target, Dispatcher dispatcher, TypeInfoDto type)
            {
                if (!refs.TryGetValue(target, out ObjectRef? value)) { value = new ObjectRef { ObjectId = (refs.Count + 1).ToString(), SessionId = "session", DispatcherId = "dispatcher", Generation = 1, Type = type }; refs.Add(target, value); }
                return value;
            }
            public bool TryGet(string objectId, long generation, out object target, out Dispatcher dispatcher) { target = null!; dispatcher = null!; return false; }
            public int Release(IEnumerable<string> objectIds) => 0;
        }
        private sealed class ReferenceComparer : IEqualityComparer<object>
        {
            internal static readonly ReferenceComparer Instance = new ReferenceComparer();
            public new bool Equals(object? a, object? b) => ReferenceEquals(a, b);
            public int GetHashCode(object value) => System.Runtime.CompilerServices.RuntimeHelpers.GetHashCode(value);
        }
        private static PathSegment Property(string name) => new PathSegment { Kind = "property", Name = name };
        private static void Sta(Action action)
        {
            Exception? error = null;
            var thread = new Thread(() => { try { action(); } catch (Exception ex) { error = ex; } });
            thread.SetApartmentState(ApartmentState.STA); thread.Start(); thread.Join();
            if (error != null) throw new Exception("STA test failed", error);
        }
        [Fact]
        public void ReadsUiaIdentityAndPeerlessValues()
        {
            Sta(() =>
            {
                var inspector = new ObjectInspector(); var registry = new Registry(); var dispatcher = Dispatcher.CurrentDispatcher;
                var button = new System.Windows.Controls.Button { Name = "MyButton", Content = "Caption" };
                Assert.Null(System.Windows.Automation.Peers.UIElementAutomationPeer.FromElement(button));
                var path = new[] { new PathSegment { Kind = "uia", Name = "name" } };
                var value = ValueTestSupport.RoundTrip(inspector.ReadPath(button, path, registry, dispatcher, CancellationToken.None));
                Assert.Equal("ok", value.Status);
                Assert.Equal("Caption", ((JsonStringNode)value.Scalar!).Value);
                value = ValueTestSupport.RoundTrip(inspector.ReadPath(new System.Windows.Controls.Border(), path, registry, dispatcher, CancellationToken.None));
                Assert.Equal("unavailable", value.Status);
                Assert.Equal("unavailable", value.Kind);
                Assert.Throws<ProtocolException>(() => inspector.ReadPath(button, new[] { path[0], Property("X") }, registry, dispatcher, CancellationToken.None));
            });
        }
        [Fact]
        public void ReadsPeerPatternsAndRedactsPasswords()
        {
            Sta(() =>
            {
                var inspector = new ObjectInspector(); var registry = new Registry(); var dispatcher = Dispatcher.CurrentDispatcher;
                ValueDto Read(object target, string name) => inspector.ReadPath(target, new[] { new PathSegment { Kind = "uia", Name = name } }, registry, dispatcher, CancellationToken.None);
                var check = new System.Windows.Controls.CheckBox { IsChecked = true };
                Assert.Contains("Toggle", ((JsonStringNode)Read(check, "supported_patterns").Scalar!).Value);
                Assert.Equal("On", ((JsonStringNode)Read(check, "toggle_state").Scalar!).Value);
                Assert.Equal("unavailable", Read(check, "range_value").Status);
                var button = new System.Windows.Controls.Button();
                foreach (string name in new[] { "value", "is_read_only", "toggle_state", "is_selected", "expand_state", "range_value", "document_text", "selection_count" })
                    Assert.Equal("unavailable", Read(button, name).Status);
                Assert.Equal("ok", Read(button, "supported_patterns").Status);
                Assert.False(((JsonBoolNode)Read(button, "is_password").Scalar!).Value);
                var text = new System.Windows.Controls.TextBox { Text = "hello" };
                Assert.Equal("hello", ((JsonStringNode)Read(text, "value").Scalar!).Value);
                Assert.False(((JsonBoolNode)Read(text, "is_read_only").Scalar!).Value);
                var expander = new System.Windows.Controls.Expander { IsExpanded = false };
                Assert.Equal("Collapsed", ((JsonStringNode)Read(expander, "expand_state").Scalar!).Value);
                var slider = new System.Windows.Controls.Slider { Value = 5 };
                Assert.Equal("ok", Read(slider, "range_value").Status);
                Assert.Equal("ok", Read(text, "document_text").Status);
                var password = new System.Windows.Controls.PasswordBox { Password = "secret" };
                Assert.Equal("redacted", Read(password, "value").Status);
                Assert.Equal("redacted", Read(password, "document_text").Status);
                Assert.True(((JsonBoolNode)Read(password, "is_password").Scalar!).Value);
                Assert.Equal("ok", Read(password, "supported_patterns").Status);
                foreach (string name in new[] { "supported_patterns", "value", "is_read_only", "toggle_state", "is_selected", "expand_state", "range_value", "document_text", "is_password" })
                    Assert.Equal("unavailable", Read(new System.Windows.Controls.Border(), name).Status);
            });
        }
        private static string SelectionDiagnostic(System.Windows.DependencyObject target, int index = 0)
        {
            var peer = PeerIdentity.GetPeer(target);
            var selection = peer?.GetPattern(System.Windows.Automation.Peers.PatternInterface.Selection) as System.Windows.Automation.Provider.ISelectionProvider;
            var selected = selection?.GetSelection();
            return $"peer={peer?.GetType().FullName ?? "null"}; selectionLength={selected?.Length.ToString() ?? "null"}; route={PeerIdentity.SelectionNameRoute ?? "none"}; provider type = {(selected != null && index < selected.Length ? selected[index]?.GetType().FullName : "null")}";
        }
        private static void AssertSelectionName(ValueDto value, string expected, System.Windows.DependencyObject target)
        {
            Assert.True(value.Status == "ok" && value.Scalar is JsonStringNode text && text.Value == expected,
                $"status={value.Status}; {SelectionDiagnostic(target)}");
        }
        [Fact]
        public void ReadsSelectionProviderNamesWithoutJoining()
        {
            Sta(() =>
            {
                var inspector = new ObjectInspector(); var registry = new Registry(); var dispatcher = Dispatcher.CurrentDispatcher;
                ValueDto Read(object target, string name) => inspector.ReadPath(target, new[] { new PathSegment { Kind = "uia", Name = name } }, registry, dispatcher, CancellationToken.None);
                var combo = new System.Windows.Controls.ComboBox();
                combo.Items.Add(new System.Windows.Controls.ComboBoxItem { Content = "first,\nsecond" });
                var window = new System.Windows.Window { Content = combo }; window.Show(); window.UpdateLayout();
                combo.SelectedIndex = 0; window.UpdateLayout();
                var count = Read(combo, "selection_count"); Assert.Equal("ok", count.Status);
                Assert.Equal("1", ((JsonNumberNode)count.Scalar!).RawText);
                var name = Read(combo, "selection_name_0"); AssertSelectionName(name, "first,\nsecond", combo);
                Assert.StartsWith("ItemsControl.", PeerIdentity.SelectionNameRoute);
                Assert.Equal("unavailable", Read(combo, "selection_name_1").Status);
                Assert.Equal("1", ((JsonNumberNode)Read(combo, "item_count").Scalar!).RawText);
                AssertSelectionName(Read(combo, "item_name_0"), "first,\nsecond", combo);
                Assert.Equal("unavailable", Read(combo, "item_name_1").Status);
                Assert.Equal("unavailable", Read(new System.Windows.Controls.Button(), "item_count").Status);
                Assert.Equal("unavailable", Read(new System.Windows.Controls.Button(), "selection_count").Status); window.Close();
            });
        }
        [Fact]
        public void ReadsVirtualizedItemNamesWithoutRealizingContainers()
        {
            Sta(() =>
            {
                var inspector = new ObjectInspector(); var registry = new Registry(); var dispatcher = Dispatcher.CurrentDispatcher;
                ValueDto Read(object target, string name) => inspector.ReadPath(target, new[] { new PathSegment { Kind = "uia", Name = name } }, registry, dispatcher, CancellationToken.None);
                var list = new System.Windows.Controls.ListBox();
                for (int index = 0; index < 5000; index++) list.Items.Add(index == 4999 ? "last,\nitem" : "item " + index);
                var window = new System.Windows.Window { Width = 300, Height = 200, Content = list }; window.Show(); window.UpdateLayout();
                Assert.Null(list.ItemContainerGenerator.ContainerFromIndex(4999));
                Assert.Equal("5000", ((JsonNumberNode)Read(list, "item_count").Scalar!).RawText);
                AssertSelectionName(Read(list, "item_name_4999"), "last,\nitem", list);
                Assert.Null(list.ItemContainerGenerator.ContainerFromIndex(4999));
                Assert.Equal("unavailable", Read(new System.Windows.Controls.Button(), "item_name_0").Status);
                window.Close();
            });
        }
        [Fact]
        public void ReadsMultipleSelectionNamesWithoutPeerFromProvider()
        {
            Sta(() =>
            {
                var inspector = new ObjectInspector(); var registry = new Registry(); var dispatcher = Dispatcher.CurrentDispatcher;
                var list = new System.Windows.Controls.ListBox { SelectionMode = System.Windows.Controls.SelectionMode.Extended };
                list.Items.Add("first,\nline"); list.Items.Add("second"); list.Items.Add("third");
                var window = new System.Windows.Window { Content = list }; window.Show(); window.UpdateLayout();
                try
                {
                    list.SelectedItems.Add(list.Items[2]); list.SelectedItems.Add(list.Items[0]);
                    var count = inspector.ReadPath(list, new[] { new PathSegment { Kind = "uia", Name = "selection_count" } }, registry, dispatcher, CancellationToken.None);
                    Assert.Equal("ok", count.Status);
                    Assert.Equal("2", ((JsonNumberNode)count.Scalar!).RawText);
                    var expected = new[] { "third", "first,\nline" };
                    for (int index = 0; index < expected.Length; index++)
                    {
                        var value = inspector.ReadPath(list, new[] { new PathSegment { Kind = "uia", Name = "selection_name_" + index } }, registry, dispatcher, CancellationToken.None);
                        Assert.True(value.Status == "ok", $"status={value.Status}; {SelectionDiagnostic(list, index)}");
                        AssertSelectionName(value, expected[index], list);
                        Assert.StartsWith("ItemsControl.", PeerIdentity.SelectionNameRoute);
                    }
                }
                finally { window.Close(); }
            });
        }
        [Fact]
        public void ReadsSelectionAfterContainerVirtualization()
        {
            Sta(() =>
            {
                var inspector = new ObjectInspector(); var registry = new Registry(); var dispatcher = Dispatcher.CurrentDispatcher;
                ValueDto Read(object target, string name) => inspector.ReadPath(target, new[] { new PathSegment { Kind = "uia", Name = name } }, registry, dispatcher, CancellationToken.None);
                var list = new System.Windows.Controls.ListBox();
                for (int index = 0; index < 200; index++) list.Items.Add("Item " + index);
                var window = new System.Windows.Window { Content = list, Width = 200, Height = 150 };
                window.Show(); window.UpdateLayout();
                list.SelectedIndex = 199;
                Assert.Null(list.ItemContainerGenerator.ContainerFromIndex(199));
                var count = Read(list, "selection_count"); Assert.Equal("ok", count.Status);
                Assert.Equal("1", ((JsonNumberNode)count.Scalar!).RawText);
                var name = Read(list, "selection_name_0"); AssertSelectionName(name, "Item 199", list);
                Assert.StartsWith("ItemsControl.", PeerIdentity.SelectionNameRoute);
                Assert.Null(list.ItemContainerGenerator.ContainerFromIndex(199));
                window.Close();
            });
        }
        [Fact]
        public void WpfItemPeerFactoryIsAvailable()
        {
            var method = typeof(System.Windows.Automation.Peers.ItemsControlAutomationPeer).GetMethod(
                "FindOrCreateItemAutomationPeer", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic,
                null, new[] { typeof(object) }, null);
            Assert.NotNull(method);
            Assert.True(typeof(System.Windows.Automation.Peers.ItemAutomationPeer).IsAssignableFrom(method!.ReturnType));
        }
        [Fact]
        public void ReadsTreeViewSelectionName()
        {
            Sta(() =>
            {
                var child = new System.Windows.Controls.TreeViewItem { Header = "nested" };
                var parent = new System.Windows.Controls.TreeViewItem { Header = "parent", IsExpanded = true };
                parent.Items.Add(child);
                var tree = new System.Windows.Controls.TreeView(); tree.Items.Add(parent);
                var window = new System.Windows.Window { Content = tree }; window.Show(); window.UpdateLayout();
                try
                {
                    child.IsSelected = true;
                    var inspector = new ObjectInspector(); var registry = new Registry(); var dispatcher = Dispatcher.CurrentDispatcher;
                    var count = inspector.ReadPath(tree, new[] { new PathSegment { Kind = "uia", Name = "selection_count" } }, registry, dispatcher, CancellationToken.None);
                    Assert.Equal("ok", count.Status); Assert.Equal("1", ((JsonNumberNode)count.Scalar!).RawText);
                    var value = inspector.ReadPath(tree, new[] { new PathSegment { Kind = "uia", Name = "selection_name_0" } }, registry, dispatcher, CancellationToken.None);
                    AssertSelectionName(value, "nested", tree);
                    Assert.StartsWith("ItemsControl.", PeerIdentity.SelectionNameRoute);
                }
                finally { window.Close(); }
            });
        }
        [Fact]
        public void ReadsScalarsAndProtectsSensitiveGetters()
        {
            Sta(() =>
            {
                var inspector = new ObjectInspector(); var model = new Model(); var registry = new Registry(); var dispatcher = Dispatcher.CurrentDispatcher;
                ValueDto Read(params PathSegment[] path) => ValueTestSupport.RoundTrip(inspector.ReadPath(model, path, registry, dispatcher, CancellationToken.None));
                Assert.Equal("integer", Read(Property("Number")).Kind); Assert.Equal(1, model.Calls);
                Assert.Equal("redacted", Read(Property("Password")).Status); Assert.Equal(0, model.SecretCalls);
                Assert.Equal("cycle", Read(Property("Self")).Status);
                Assert.Equal("null", Read(Property("Missing")).Kind);
                Assert.Equal("nullIntermediate", Read(Property("Missing"), Property("Number")).Status);
                Assert.Equal("number", Read(Property("Amount")).Kind);
                Assert.IsType<JsonStringNode>(Read(Property("Large")).Scalar);
                Assert.Equal("string", Read(Property("Text")).Kind);
                Assert.Equal(2, Read(Property("Array")).ArrayLength);
                Assert.Equal("boolean", Read(Property("Flag")).Kind);
                Assert.Equal("string", Read(Property("Date")).Kind);
                Assert.Equal("string", Read(Property("Id")).Kind);
                Assert.Equal("enum", Read(Property("Day")).Kind);
                ValueDto fail = Read(Property("Fail")); Assert.Equal("exception", fail.Status); Assert.Equal(typeof(InvalidOperationException).FullName, fail.Message);
            });
        }
    }
}
