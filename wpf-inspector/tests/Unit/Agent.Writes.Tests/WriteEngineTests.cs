using System;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Inspection;
using WinTestKit.Inspector.Agent.Inspection.Members;
using WinTestKit.Inspector.Agent.Writes;
using WinTestKit.Inspector.Protocol;
using Xunit;

namespace WinTestKit.Inspector.Agent.Writes.Tests
{
    [Trait("Category", "Unit")]
    public sealed class WriteEngineTests
    {
        public sealed class Target
        {
            public string Text { get; set; } = "";
            public string ReadOnly => "";
            public int Calls;
            public void All(string s, bool b, long i, double d) { Calls++; Text = s; }
            public void Throw() { throw new InvalidOperationException("sensitive value"); }
            public string PrivateSetter { get; private set; } = "";
            public static string StaticProperty { get; set; } = "";
            public string CustomerMarker { get; set; } = "";
            public void Ref(ref long value) { }
            public void Out(out long value) { value = 0; }
            public void Params(params long[] value) { }
            public void Generic<T>() { }
            public static void Static() { }
            public string this[long index] { get => ""; set { } }
        }
        public class Base { public string Text { get; set; } = ""; }
        public interface IText { string Text { get; set; } }
        public sealed class Derived : Base, IText { }
        public sealed class Hiding : Base { public new string Text { get; set; } = ""; }
        public sealed class Blocking
        {
            public readonly ManualResetEventSlim Entered = new ManualResetEventSlim();
            public readonly ManualResetEventSlim Release = new ManualResetEventSlim();
            public void Wait() { Entered.Set(); Release.Wait(); }
        }
        private sealed class Ui : IDisposable
        {
            private readonly Thread thread;
            internal Dispatcher Dispatcher { get; }
            internal Ui() { var ready = new TaskCompletionSource<Dispatcher>(); thread = new Thread(() => { ready.SetResult(Dispatcher.CurrentDispatcher); Dispatcher.Run(); }) { IsBackground = true }; thread.SetApartmentState(ApartmentState.STA); thread.Start(); Dispatcher = ready.Task.GetAwaiter().GetResult(); }
            public void Dispose() { Dispatcher.BeginInvokeShutdown(DispatcherPriority.Send); thread.Join(); }
        }
        private static string Key(string name) => ReflectionCatalog.Get(typeof(Target)).Single(d => d.Name == name && d.Property != null).Key;
        private static WriteEngine Engine(params string[] methods) => new WriteEngine(new DispatcherExecutor(), new WriteAllowlist(new[] { new PropertyAllowEntry(typeof(Target).FullName!, "Text"), new PropertyAllowEntry(typeof(Target).FullName!, "ReadOnly") }, methods.Select(m => new AllowEntry(typeof(Target).FullName!, m))), Array.Empty<string>());
        private static async Task<WriteAudit> Run(Ui ui, WriteEngine engine, Target target, string op, string key, params JsonNode[] values)
        { await ui.Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle).Task; return await engine.ExecuteAsync(ui.Dispatcher, target, op, key, values, DateTime.UtcNow.AddSeconds(60), 2000, CancellationToken.None); }
        private static WriteAudit Audit(ProtocolException error) => WriteAudit.FromJson(error.Details!.Get("audit"));

        [Fact]
        public async Task WritesAndCallsUseExactScalarsAndNeverAuditValues()
        {
            using (var ui = new Ui())
            {
                var target = new Target(); var engine = Engine("All(System.String,System.Boolean,System.Int64,System.Double)");
                var audit = await Run(ui, engine, target, "setProperty", Key("Text"), new JsonStringNode("sensitive value"));
                Assert.Equal("performed", audit.Outcome);
                Assert.Equal("performed", (await Run(ui, engine, target, "call", "All(System.String,System.Boolean,System.Int64,System.Double)", new JsonStringNode("sensitive value"), new JsonBoolNode(true), new JsonNumberNode("3"), new JsonNumberNode("1.5"))).Outcome);
                Assert.Equal(1, target.Calls);
                Assert.DoesNotContain("sensitive value", System.Text.Encoding.UTF8.GetString(StrictJson.Serialize(audit.ToJson())));
                var invalid = await Assert.ThrowsAsync<ProtocolException>(() => Run(ui, engine, target, "setProperty", Key("Text"), JsonNullNode.Instance));
                Assert.Equal(ErrorCodes.InvalidParams, invalid.Code); Assert.Equal("failed", Audit(invalid).Outcome);
                var denied = await Assert.ThrowsAsync<ProtocolException>(() => Run(ui, engine, target, "setProperty", Key("ReadOnly"), new JsonStringNode("x")));
                Assert.Equal(ErrorCodes.WriteDenied, denied.Code); Assert.Equal("denied", Audit(denied).Outcome);
            }
        }
        [Fact]
        public async Task TargetExceptionIsAuditedWithoutItsMessage()
        {
            using (var ui = new Ui())
            {
                var target = new Target(); var engine = Engine("Throw()");
                var error = await Assert.ThrowsAsync<ProtocolException>(() => Run(ui, engine, target, "call", "Throw()"));
                Assert.Equal("InvalidOperationException", Audit(error).Reason);
                Assert.DoesNotContain("sensitive value", System.Text.Encoding.UTF8.GetString(StrictJson.Serialize(error.Details!)));
            }
        }
        [Fact]
        public async Task DependencyPropertyWriteUsesCatalogKey()
        {
            using (var ui = new Ui())
            {
                var box = await ui.Dispatcher.InvokeAsync(() => new TextBox()).Task;
                string key = await ui.Dispatcher.InvokeAsync(() => DependencyCatalog.Discover(box, _ => { }).Single(e => e.Property == TextBox.TextProperty).Key).Task;
                var engine = new WriteEngine(new DispatcherExecutor(), new WriteAllowlist(new[] { new PropertyAllowEntry(typeof(TextBox).FullName!, "Text") }, Array.Empty<AllowEntry>()), Array.Empty<string>());
                await ui.Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle).Task;
                var audit = await engine.ExecuteAsync(ui.Dispatcher, box, "setProperty", key, new JsonNode[] { new JsonStringNode("example") }, DateTime.UtcNow.AddSeconds(60), 2000, CancellationToken.None);
                Assert.Equal("performed", audit.Outcome);
                Assert.Equal("example", await ui.Dispatcher.InvokeAsync(() => box.Text).Task);
            }
        }
        [Fact]
        public async Task RedactionAndNonPublicSetterAreDenied()
        {
            using (var ui = new Ui())
            {
                var target = new Target();
                var allow = new WriteAllowlist(new[] { new PropertyAllowEntry(typeof(Target).FullName!, "PrivateSetter"), new PropertyAllowEntry(typeof(Target).FullName!, "CustomerMarker") }, Array.Empty<AllowEntry>());
                var engine = new WriteEngine(new DispatcherExecutor(), allow, new[] { "CustomerMarker" });
                var redacted = await Assert.ThrowsAsync<ProtocolException>(() => Run(ui, engine, target, "setProperty", Key("CustomerMarker"), new JsonStringNode("x")));
                Assert.Equal(ErrorCodes.WriteDenied, redacted.Code); Assert.Equal("CustomerMarker", Audit(redacted).MemberKey);
                var denied = await Assert.ThrowsAsync<ProtocolException>(() => Run(ui, engine, target, "setProperty", Key("PrivateSetter"), new JsonStringNode("x")));
                Assert.Equal(ErrorCodes.WriteDenied, denied.Code);
            }
        }
        [Theory]
        [InlineData("Ref(System.Int64&)")]
        [InlineData("Out(System.Int64&)")]
        [InlineData("Params(System.Int64[])")]
        [InlineData("Generic()")]
        [InlineData("Static()")]
        public async Task UnsupportedMethodsAreDenied(string key)
        {
            using (var ui = new Ui())
            {
                var error = await Assert.ThrowsAsync<ProtocolException>(() => Run(ui, Engine(key), new Target(), "call", key));
                Assert.Equal(ErrorCodes.WriteDenied, error.Code); Assert.Equal("denied", Audit(error).Outcome);
            }
        }
        [Fact]
        public async Task RuntimeTypeOverloadIndexerAndScalarTypesAreEnforced()
        {
            using (var ui = new Ui())
            {
                var inheritedKey = ReflectionCatalog.Get(typeof(Derived)).Single(d => d.Name == "Text" && d.Property != null).Key;
                var target = new Derived();
                await ui.Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle).Task;
                foreach (var type in new[] { typeof(Base), typeof(IText) })
                {
                    var engine = new WriteEngine(new DispatcherExecutor(), new WriteAllowlist(new[] { new PropertyAllowEntry(type.FullName!, "Text") }, Array.Empty<AllowEntry>()), Array.Empty<string>());
                    var e = await Assert.ThrowsAsync<ProtocolException>(() => engine.ExecuteAsync(ui.Dispatcher, target, "setProperty", inheritedKey, new JsonNode[] { new JsonStringNode("x") }, DateTime.UtcNow.AddSeconds(60), 2000, CancellationToken.None));
                    Assert.Equal(ErrorCodes.WriteDenied, e.Code);
                }
                var ordinary = new Target();
                var index = Key("Item");
                var allow = new WriteAllowlist(new[] { new PropertyAllowEntry(typeof(Target).FullName!, "Item"), new PropertyAllowEntry(typeof(Target).FullName!, "Text") }, new[] { new AllowEntry(typeof(Target).FullName!, "All(System.String)") });
                var write = new WriteEngine(new DispatcherExecutor(), allow, Array.Empty<string>());
                Assert.Equal(ErrorCodes.WriteDenied, (await Assert.ThrowsAsync<ProtocolException>(() => Run(ui, write, ordinary, "setProperty", index, new JsonStringNode("x")))).Code);
                Assert.Equal(ErrorCodes.InvalidParams, (await Assert.ThrowsAsync<ProtocolException>(() => Run(ui, write, ordinary, "setProperty", Key("Text"), new JsonNumberNode("1")))).Code);
                Assert.Equal(ErrorCodes.WriteDenied, (await Assert.ThrowsAsync<ProtocolException>(() => Run(ui, write, ordinary, "call", "All(System.String)", new JsonStringNode("x")))).Code);
                var staticKey = Key("Text").Replace("|Text|", "|StaticProperty|");
                var staticEngine = new WriteEngine(new DispatcherExecutor(), new WriteAllowlist(new[] { new PropertyAllowEntry(typeof(Target).FullName!, "StaticProperty") }, Array.Empty<AllowEntry>()), Array.Empty<string>());
                Assert.Equal(ErrorCodes.WriteDenied, (await Assert.ThrowsAsync<ProtocolException>(() => Run(ui, staticEngine, ordinary, "setProperty", staticKey, new JsonStringNode("x")))).Code);
            }
        }
        [Fact]
        public async Task InheritedNamesResolveAndHidingOrMissingNamesAreDenied()
        {
            using (var ui = new Ui())
            {
                var target = new Derived();
                var key = ReflectionCatalog.Get(typeof(Derived)).Single(d => d.Name == "Text" && d.Property != null).Key;
                var allow = new WriteAllowlist(new[] { new PropertyAllowEntry(typeof(Derived).FullName!, "Text"), new PropertyAllowEntry(typeof(Hiding).FullName!, "Text"), new PropertyAllowEntry(typeof(Derived).FullName!, "Missing") }, Array.Empty<AllowEntry>());
                var engine = new WriteEngine(new DispatcherExecutor(), allow, Array.Empty<string>());
                await ui.Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle).Task;
                Assert.Equal("performed", (await engine.ExecuteAsync(ui.Dispatcher, target, "setProperty", key, new JsonNode[] { new JsonStringNode("ok") }, DateTime.UtcNow.AddSeconds(60), 2000, CancellationToken.None)).Outcome);
                Assert.Equal("ok", target.Text);
                var hiddenKey = ReflectionCatalog.Get(typeof(Hiding)).First(d => d.Name == "Text" && d.Property != null).Key;
                var hidden = await Assert.ThrowsAsync<ProtocolException>(() => engine.ExecuteAsync(ui.Dispatcher, new Hiding(), "setProperty", hiddenKey, new JsonNode[] { new JsonStringNode("x") }, DateTime.UtcNow.AddSeconds(60), 2000, CancellationToken.None));
                Assert.Equal("ambiguous", Audit(hidden).Reason);
                var missing = await Assert.ThrowsAsync<ProtocolException>(() => engine.ExecuteAsync(ui.Dispatcher, target, "setProperty", "clrProperty|A|T|Missing|", new JsonNode[] { new JsonStringNode("x") }, DateTime.UtcNow.AddSeconds(60), 2000, CancellationToken.None));
                Assert.Equal("notFound", Audit(missing).Reason);
            }
        }
        [Fact]
        public async Task WrapperAndDependencyKeysPreserveBinding()
        {
            using (var ui = new Ui())
            {
                var box = await ui.Dispatcher.InvokeAsync(() => { var item = new TextBox(); BindingOperations.SetBinding(item, TextBox.TextProperty, new Binding("Text") { Source = new Target { Text = "initial" }, Mode = BindingMode.OneWay }); return item; }).Task;
                var dpKey = await ui.Dispatcher.InvokeAsync(() => DependencyCatalog.Discover(box, _ => { }).Single(d => d.Property == TextBox.TextProperty).Key).Task;
                var clrKey = ReflectionCatalog.Get(typeof(TextBox)).Single(d => d.Name == "Text" && d.Property != null).Key;
                var engine = new WriteEngine(new DispatcherExecutor(), new WriteAllowlist(new[] { new PropertyAllowEntry(typeof(TextBox).FullName!, "Text") }, Array.Empty<AllowEntry>()), Array.Empty<string>());
                await ui.Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle).Task;
                foreach (var key in new[] { clrKey, dpKey })
                {
                    Assert.Equal("performed", (await engine.ExecuteAsync(ui.Dispatcher, box, "setProperty", key, new JsonNode[] { new JsonStringNode("changed") }, DateTime.UtcNow.AddSeconds(60), 2000, CancellationToken.None)).Outcome);
                    Assert.True(await ui.Dispatcher.InvokeAsync(() => BindingOperations.IsDataBound(box, TextBox.TextProperty)).Task);
                }
            }
        }
        [Fact]
        public async Task ProtectedIdentityIsDeniedWithIdentityRule()
        {
            using (var ui = new Ui())
            {
                var element = await ui.Dispatcher.InvokeAsync(() => new FrameworkElement()).Task;
                var key = ReflectionCatalog.Get(typeof(FrameworkElement)).Single(d => d.Name == "Width" && d.Property != null).Key;
                var engine = new WriteEngine(new DispatcherExecutor(), new WriteAllowlist(new[] { new PropertyAllowEntry(typeof(FrameworkElement).FullName!, "Width") }, Array.Empty<AllowEntry>()), Array.Empty<string>());
                await ui.Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle).Task;
                var error = await Assert.ThrowsAsync<ProtocolException>(() => engine.ExecuteAsync(ui.Dispatcher, element, "setProperty", key, new JsonNode[] { new JsonNumberNode("12.5") }, DateTime.UtcNow.AddSeconds(60), 2000, CancellationToken.None));
                Assert.Equal(ErrorCodes.WriteDenied, error.Code);
                Assert.Equal("identity", Audit(error).MemberKey);
                Assert.Equal("protectedIdentity", Audit(error).Reason);
            }
        }
        [Fact]
        public async Task PasswordAndDeadlineDoNotExposeValues()
        {
            using (var ui = new Ui())
            {
                var box = await ui.Dispatcher.InvokeAsync(() => new PasswordBox()).Task;
                var key = ReflectionCatalog.Get(typeof(PasswordBox)).Single(d => d.Name == "Password" && d.Property != null).Key;
                var engine = new WriteEngine(new DispatcherExecutor(), new WriteAllowlist(new[] { new PropertyAllowEntry(typeof(PasswordBox).FullName!, "Password") }, Array.Empty<AllowEntry>()), Array.Empty<string>());
                await ui.Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle).Task;
                var denied = await Assert.ThrowsAsync<ProtocolException>(() => engine.ExecuteAsync(ui.Dispatcher, box, "setProperty", key, new JsonNode[] { new JsonStringNode("private") }, DateTime.UtcNow.AddSeconds(60), 2000, CancellationToken.None));
                Assert.Equal(ErrorCodes.WriteDenied, denied.Code); Assert.Equal("password", Audit(denied).MemberKey);
                var target = new Blocking(); var slow = new WriteEngine(new DispatcherExecutor(), new WriteAllowlist(Array.Empty<PropertyAllowEntry>(), new[] { new AllowEntry(typeof(Blocking).FullName!, "Wait()") }), Array.Empty<string>());
                try
                {
                    var task = slow.ExecuteAsync(ui.Dispatcher, target, "call", "Wait()", Array.Empty<JsonNode>(), DateTime.UtcNow.AddSeconds(60), 100, CancellationToken.None);
                    Assert.True(target.Entered.Wait(3000));
                    var elapsed = System.Diagnostics.Stopwatch.StartNew();
                    var error = await Assert.ThrowsAsync<ProtocolException>(() => task);
                    Assert.True(elapsed.Elapsed < TimeSpan.FromSeconds(1));
                    Assert.Equal("failed", Audit(error).Outcome); Assert.Equal("timeout", Audit(error).Reason);
                }
                finally { target.Release.Set(); }
            }
        }
    }
}
