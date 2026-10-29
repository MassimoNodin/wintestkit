using System;
using System.Linq;
using WinTestKit.Inspector.Agent.Inspection.Members;
using Xunit;

namespace WinTestKit.Inspector.Agent.Members.Tests
{
    [Trait("Category", "Unit")]
    public sealed class ReflectionCatalogTests
    {
        private class Base
        {
            public virtual int Override => 1;
            public int Hidden => 1;
            private int PrivateField = 1; public int ReadPrivateField() => PrivateField;
        }
        private sealed class Derived : Base
        {
            public override int Override => 2;
            public new int Hidden => 2;
        }

        [Fact]
        public void KeepsHiddenDeclarationsButMergesOverrides()
        {
            var declarations = ReflectionCatalog.Get(typeof(Derived));
            Assert.Equal(2, declarations.Count(d => d.Name == "Hidden"));
            Assert.Single(declarations, d => d.Name == "Override");
            Assert.Contains(declarations, d => d.Name == "PrivateField");
        }

        [Fact]
        public void RedactionIsAdditiveAndOrdinalCaseInsensitive()
        {
            var policy = new RedactionPolicy(new[] { "customer" });
            Assert.Equal("token", policy.Match("CancellationTOKEN"));
            Assert.Equal("customer", policy.Match("CustomerName"));
            Assert.Null(policy.Match("Ordinary"));
        }
        [Fact]
        public void ScalarPrefixDoesNotSplitSurrogatePairs()
        {
            string prefix = ScalarText.Prefix("a\U0001F600b", 2, out int length);
            Assert.Equal("a\U0001F600", prefix);
            Assert.Equal(3, length);
        }
    }
}
