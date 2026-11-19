using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Inspection.Members;
using WinTestKit.Inspector.Protocol;
using Xunit;

namespace WinTestKit.Inspector.Agent.Members.Tests
{
    public class SpyFieldTests
    {
        private class Base { private int shared = 11; private string password = "secret"; public int Touch() => shared + password.Length; }
        private class Derived : Base { private int shared = 22; private int HiddenProperty => 42; public int TouchDerived() => shared; }

        [Fact]
        public void ExactSpyFieldsIncludePrivateBaseAndPreserveOrdinaryRedaction()
        {
            ValueTestSupport.Sta(() => {
                var target = new Derived(); var inspector = new ObjectInspector(); var registry = new ValueTestSupport.Registry();
                var members = inspector.GetMembers(target, new List<Diagnostic>());
                var fields = members.Where(m => m.Name == "shared" && m.Category == "clrField").ToArray();
                Assert.Equal(2, fields.Length);
                foreach (var field in fields) {
                    var path = new[] { field.PathSegment! };
                    Assert.Equal("notReadable", inspector.ReadPath(target, path, registry, Dispatcher.CurrentDispatcher, CancellationToken.None).Status);
                    var value = inspector.ReadSpyField(target, path, registry, Dispatcher.CurrentDispatcher, CancellationToken.None);
                    Assert.Equal(field.DeclaringType == typeof(Base).FullName ? "11" : "22", ((JsonNumberNode)value.Scalar!).RawText);
                }
                var secret = members.Single(m => m.Name == "password");
                Assert.Equal("redacted", inspector.ReadSpyField(target, new[] { secret.PathSegment! }, registry, Dispatcher.CurrentDispatcher, CancellationToken.None).Status);
                Assert.Equal("redacted", inspector.ReadPath(target, new[] { secret.PathSegment! }, registry, Dispatcher.CurrentDispatcher, CancellationToken.None).Status);
                Assert.Throws<ProtocolException>(() => inspector.ReadSpyField(target, new[] { fields[0].PathSegment!, fields[1].PathSegment! }, registry, Dispatcher.CurrentDispatcher, CancellationToken.None));
                var property = members.Single(m => m.Name == "HiddenProperty");
                Assert.Throws<ProtocolException>(() => inspector.ReadSpyField(target, new[] { property.PathSegment! }, registry, Dispatcher.CurrentDispatcher, CancellationToken.None));
                Assert.Throws<ProtocolException>(() => inspector.ReadSpyField(target, new[] { new PathSegment { Kind = "field", Name = "shared" } }, registry, Dispatcher.CurrentDispatcher, CancellationToken.None));
            });
        }
    }
}
