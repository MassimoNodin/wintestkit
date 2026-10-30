using System;
using WinTestKit.Inspector.Agent.Query;
using WinTestKit.Inspector.Protocol;
using Xunit;

namespace WinTestKit.Inspector.Agent.Query.Tests
{
    [Trait("Category", "Unit")]
    public class QueryRegexTests
    {
        [Theory]
        [InlineData("")]
        [InlineData("abc")]
        [InlineData("a|b")]
        [InlineData("(abc)")]
        [InlineData("(?:abc)")]
        [InlineData("[a-z]")]
        [InlineData("[^A-Z0-9]")]
        [InlineData(@"\.")]
        [InlineData("a*")]
        [InlineData("a+?")]
        [InlineData("a??")]
        [InlineData("a{1}")]
        [InlineData("a{1,}")]
        [InlineData("a{1,10000}?")]
        [InlineData("^a.$")]
        public void AcceptsSharedGrammar(string pattern) => _ = new QueryRegex(pattern, Array.Empty<string>());

        [Theory]
        [InlineData("(?i)a")]
        [InlineData("(?=a)")]
        [InlineData("(?!a)")]
        [InlineData("(?<=a)")]
        [InlineData("(?<name>a)")]
        [InlineData(@"\d")]
        [InlineData(@"\w")]
        [InlineData(@"\s")]
        [InlineData(@"\p{L}")]
        [InlineData(@"(a)\1")]
        [InlineData("[")]
        [InlineData("(")]
        [InlineData("a{2,1}")]
        [InlineData("a{10001}")]
        [InlineData("a**")]
        [InlineData("é")]
        [InlineData("[z-a]")]
        public void RejectsUnsupportedGrammar(string pattern)
        {
            var error = Assert.Throws<ProtocolException>(() => new QueryRegex(pattern, Array.Empty<string>()));
            Assert.Equal(ErrorCodes.InvalidParams, error.Code);
        }

        [Fact]
        public void IgnoreCaseFoldsAsciiOnly()
        {
            var regex = new QueryRegex("^[a-z]+$", new[] { "ignoreCase" });
            Assert.True(regex.IsMatch("Hello", 50));
            Assert.False(regex.IsMatch("\u212A", 50));
            Assert.False(regex.IsMatch("\u0130", 50));
        }

        [Fact]
        public void SearchAndFlagsFollowPythonAnchors()
        {
            Assert.True(new QueryRegex("b$", Array.Empty<string>()).IsMatch("ab\n", 50));
            Assert.True(new QueryRegex("^b$", new[] { "multiline" }).IsMatch("a\nb\nc", 50));
            Assert.False(new QueryRegex("a.b", Array.Empty<string>()).IsMatch("a\nb", 50));
            Assert.True(new QueryRegex("a.b", new[] { "singleline" }).IsMatch("a\nb", 50));
        }

        [Fact]
        public void DuplicateFlagsAreInvalid()
        {
            Assert.Equal(ErrorCodes.InvalidParams, Assert.Throws<ProtocolException>(() => new QueryRegex("x", new[] { "ignoreCase", "ignoreCase" })).Code);
        }

        [Fact]
        public void CatastrophicBacktrackingReportsRegexTimeout()
        {
            var regex = new QueryRegex("(a+)+$", Array.Empty<string>());
            Assert.Equal(ErrorCodes.RegexTimeout, Assert.Throws<ProtocolException>(() => regex.IsMatch(new string('a', 20000) + "!", 1)).Code);
        }
    }
}
