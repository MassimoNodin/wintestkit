using System;
using System.Linq;
using WinTestKit.Inspector.Agent.Inspection.Members;
using Xunit;

namespace WinTestKit.Inspector.Agent.Members.Tests
{
    [Trait("Category", "Unit")]
    public sealed class MethodCatalogTests
    {
        private class Base
        {
            private int Hidden(string text) => throw new InvalidOperationException();
            public virtual int Overload(int number) => throw new InvalidOperationException();
        }

        private sealed class Derived : Base
        {
            public override int Overload(int number) => throw new InvalidOperationException();
            public string Overload(string text) => throw new InvalidOperationException();
            public T Generic<T>(T value) => throw new InvalidOperationException();
            public void ByReference(ref int value, out string text) => throw new InvalidOperationException();
        }

        [Fact]
        public void CatalogsExactOverloadsAndInheritedPrivateDeclarationsWithoutExecution()
        {
            var methods = MethodCatalog.Get(typeof(Derived));
            var overloads = methods.Where(method => method.Name == "Overload").ToArray();
            Assert.Equal(3, overloads.Length);
            Assert.Equal(3, overloads.Select(method => method.Key).Distinct(StringComparer.Ordinal).Count());
            var derivedInt = Assert.Single(overloads, method => method.DeclaringType == typeof(Derived) && method.Parameters[0].ParameterType == typeof(int));
            Assert.Equal("number", derivedInt.Parameters[0].Name);
            Assert.Equal(typeof(int), derivedInt.ReturnType);
            Assert.Equal("public", derivedInt.Visibility);
            Assert.Null(derivedInt.UnsupportedReason);
            var hidden = Assert.Single(methods, method => method.Name == "Hidden");
            Assert.Equal(typeof(Base), hidden.DeclaringType);
            Assert.Equal("private", hidden.Visibility);
            Assert.Equal("text", hidden.Parameters[0].Name);
            Assert.Equal(typeof(string), hidden.Parameters[0].ParameterType);
            Assert.Equal(methods.Select(method => method.Key), MethodCatalog.Get(typeof(Derived)).Select(method => method.Key));
            Assert.Equal(hidden.Key, Assert.Single(MethodCatalog.Get(typeof(Base)), method => method.Name == "Hidden").Key);
        }

        [Fact]
        public void DescribesUnsupportedGenericAndByReferenceMethods()
        {
            var methods = MethodCatalog.Get(typeof(Derived));
            var generic = Assert.Single(methods, method => method.Name == "Generic");
            Assert.Contains("generic", generic.UnsupportedReason!);
            Assert.True(generic.Parameters[0].ParameterType.IsGenericParameter);
            var byReference = Assert.Single(methods, method => method.Name == "ByReference");
            Assert.NotNull(byReference.UnsupportedReason);
            Assert.Equal(typeof(int).MakeByRefType(), byReference.Parameters[0].ParameterType);
            Assert.Equal(typeof(string).MakeByRefType(), byReference.Parameters[1].ParameterType);
            Assert.False(byReference.Parameters[0].IsOut);
            Assert.True(byReference.Parameters[1].IsOut);
        }
    }
}
