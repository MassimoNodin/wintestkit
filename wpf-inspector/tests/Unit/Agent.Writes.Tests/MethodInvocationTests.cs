using System;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Controls;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Inspection;
using WinTestKit.Inspector.Agent.Inspection.Members;
using WinTestKit.Inspector.Agent.Writes;
using WinTestKit.Inspector.Protocol;
using Xunit;

namespace WinTestKit.Inspector.Tests
{
    public class MethodInvocationTests
    {
        public class Parent
        {
            private string Hidden(int value) => "hidden:" + value;
            public virtual string Virtual() => "parent";
        }
        public sealed class Target : Parent
        {
            public string Pick(int value) => "int:" + value;
            public string Pick(string value) => "string:" + value;
            public static string Static(bool value) => value ? "yes" : "no";
            public override string Virtual() => "child";
            public void Reference(object value) { }
            public void ByReference(ref int value) { }
            public string Secret() => "not exposed";
            public object Protected() => new PasswordBox();
            public void Fail() => throw new InvalidOperationException("sensitive argument");
        }
        private sealed class Ui : IDisposable
        {
            private readonly Thread thread;
            internal Dispatcher Dispatcher { get; }
            internal Ui() { var ready = new TaskCompletionSource<Dispatcher>(); thread = new Thread(() => { ready.SetResult(Dispatcher.CurrentDispatcher); Dispatcher.Run(); }) { IsBackground = true }; thread.SetApartmentState(ApartmentState.STA); thread.Start(); Dispatcher = ready.Task.GetAwaiter().GetResult(); }
            public void Dispose() { Dispatcher.BeginInvokeShutdown(DispatcherPriority.Send); thread.Join(); }
        }
        private static string Key(string name, Type owner, params Type[] types) => MethodCatalog.Get(typeof(Target)).Single(method => method.Name == name && method.DeclaringType == owner && method.Parameters.Select(parameter => parameter.ParameterType).SequenceEqual(types)).Key;
        private static JsonObjectNode Arg(Type type, JsonNode value) { var argument = new JsonObjectNode(); argument.Add("type", new JsonStringNode(type.FullName!)); argument.Add("value", value); return argument; }

        private sealed class LongKeyTarget { public int Execute(int value0, int value1, int value2, int value3, int value4, int value5, int value6, int value7, int value8, int value9, int value10, int value11, int value12, int value13, int value14, int value15) => value0; }

        [Fact]
        public async Task LongCatalogKeyHasBoundedAudit()
        {
            var target = new LongKeyTarget();
            string key = MethodCatalog.Get(target.GetType()).Single(item => item.Name == "Execute").Key;
            Assert.InRange(key.Length, 1025, 8192);
            using (var ui = new Ui())
            using (var registry = new ObjectRegistry("test", new DispatcherExecutor()))
            {
                var executor = new MethodInvocationExecutor(new DispatcherExecutor(), Array.Empty<string>());
                var arguments = Enumerable.Range(0, 16).Select(value => (JsonNode)Arg(typeof(int), JsonNumberNode.From(value))).ToArray();
                var result = await executor.ExecuteAsync(target, ui.Dispatcher, key, arguments, DateTime.UtcNow.AddSeconds(2), CancellationToken.None, registry);
                Assert.StartsWith("sha256:", result.Audit.MemberKey);
                Assert.InRange(result.Audit.MemberKey.Length, 1, 1024);
                WriteCallResult.FromJson(result.ToJson());
            }
        }

        [Fact]
        public async Task ExactCallsAndDenialsStaySeparateFromWritePolicy()
        {
            using (var ui = new Ui())
            using (var registry = new ObjectRegistry("test", new DispatcherExecutor()))
            {
                var dispatcherExecutor = new DispatcherExecutor();
                var invoker = new MethodInvocationExecutor(dispatcherExecutor, Array.Empty<string>());
                var target = new Target();
                Task<WriteCallResult> Invoke(string key, params JsonNode[] args) => invoker.ExecuteAsync(target, ui.Dispatcher, key, args, DateTime.UtcNow.AddSeconds(10), CancellationToken.None, registry);
                string numberKey = Key("Pick", typeof(Target), typeof(int));
                var number = Arg(typeof(int), JsonNumberNode.From(7));
                Assert.Equal("int:7", ((JsonStringNode)(await Invoke(numberKey, number)).Result.Scalar!).Value);
                Assert.Equal("string:x", ((JsonStringNode)(await Invoke(Key("Pick", typeof(Target), typeof(string)), Arg(typeof(string), new JsonStringNode("x")))).Result.Scalar!).Value);
                Assert.Equal("hidden:7", ((JsonStringNode)(await Invoke(Key("Hidden", typeof(Parent), typeof(int)), number)).Result.Scalar!).Value);
                Assert.Equal("yes", ((JsonStringNode)(await Invoke(Key("Static", typeof(Target), typeof(bool)), Arg(typeof(bool), new JsonBoolNode(true)))).Result.Scalar!).Value);
                Assert.Equal(ErrorCodes.WriteDenied, (await Assert.ThrowsAsync<ProtocolException>(() => Invoke("Pick(System.Int32)", number))).Code);
                Assert.Equal(ErrorCodes.InvalidParams, (await Assert.ThrowsAsync<ProtocolException>(() => Invoke(numberKey))).Code);
                Assert.Equal(ErrorCodes.InvalidParams, (await Assert.ThrowsAsync<ProtocolException>(() => Invoke(numberKey, Arg(typeof(string), new JsonStringNode("7"))))).Code);
                Assert.Equal(ErrorCodes.InvalidParams, (await Assert.ThrowsAsync<ProtocolException>(() => Invoke(Key("Pick", typeof(Target), typeof(string)), Arg(typeof(string), new JsonStringNode(new string('x', ProtocolLimits.MaxScalarChars + 1)))))).Code);
                Assert.Equal(ErrorCodes.WriteDenied, (await Assert.ThrowsAsync<ProtocolException>(() => Invoke(Key("Reference", typeof(Target), typeof(object)), number))).Code);
                Assert.Equal(ErrorCodes.WriteDenied, (await Assert.ThrowsAsync<ProtocolException>(() => Invoke(Key("ByReference", typeof(Target), typeof(int).MakeByRefType()), number))).Code);
                Assert.Equal(ErrorCodes.WriteDenied, (await Assert.ThrowsAsync<ProtocolException>(() => Invoke(Key("Virtual", typeof(Parent))))).Code);
                Assert.Equal("child", ((JsonStringNode)(await Invoke(Key("Virtual", typeof(Target)))).Result.Scalar!).Value);
                Assert.Equal(ErrorCodes.WriteDenied, (await Assert.ThrowsAsync<ProtocolException>(() => Invoke(Key("Secret", typeof(Target))))).Code);
                Assert.Equal("redacted", (await Invoke(Key("Protected", typeof(Target)))).Result.Status);
                var protectedTarget = await ui.Dispatcher.InvokeAsync(() => new PasswordBox());
                Assert.Equal(ErrorCodes.WriteDenied, (await Assert.ThrowsAsync<ProtocolException>(() => invoker.ExecuteAsync(protectedTarget, ui.Dispatcher, "unknown", Array.Empty<JsonNode>(), DateTime.UtcNow.AddSeconds(10), CancellationToken.None, registry))).Code);
                Assert.Equal(ErrorCodes.Timeout, (await Assert.ThrowsAsync<ProtocolException>(() => invoker.ExecuteAsync(target, ui.Dispatcher, numberKey, new JsonNode[] { number }, DateTime.UtcNow.AddSeconds(-1), CancellationToken.None, registry))).Code);
                var failure = await Assert.ThrowsAsync<ProtocolException>(() => Invoke(Key("Fail", typeof(Target))));
                Assert.DoesNotContain("sensitive", failure.ToString());
                var write = new WriteEngine(dispatcherExecutor, new WriteAllowlist(), Array.Empty<string>());
                Assert.Equal(ErrorCodes.WriteDenied, (await Assert.ThrowsAsync<ProtocolException>(() => write.ExecuteWithResultAsync(ui.Dispatcher, target, "call", "Pick(System.Int32)", new JsonNode[] { number }, DateTime.UtcNow.AddSeconds(10), 2000, CancellationToken.None, registry))).Code);
            }
        }
    }
}
