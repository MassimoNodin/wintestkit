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
                var path = new[] { new PathSegment { Kind = "uia", Name = "name" } };
                var value = ValueTestSupport.RoundTrip(inspector.ReadPath(button, path, registry, dispatcher, CancellationToken.None));
                Assert.Equal("Caption", ((JsonStringNode)value.Scalar!).Value);
                value = ValueTestSupport.RoundTrip(inspector.ReadPath(new System.Windows.Controls.Border(), path, registry, dispatcher, CancellationToken.None));
                Assert.Equal("unavailable", value.Status);
                Assert.Equal("unavailable", value.Kind);
                Assert.Throws<ProtocolException>(() => inspector.ReadPath(button, new[] { path[0], Property("X") }, registry, dispatcher, CancellationToken.None));
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
