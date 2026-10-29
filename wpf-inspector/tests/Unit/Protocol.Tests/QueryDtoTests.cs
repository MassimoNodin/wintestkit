using System.Text;
using WinTestKit.Inspector.Protocol;
using Xunit;
namespace Protocol.Tests;
public class QueryDtoTests
{
    private static JsonNode Parse(string s) { var b = Encoding.UTF8.GetBytes(s); return StrictJson.Parse(b,0,b.Length); }
    [Fact] public void LocatorRoundTrips() { var n = Parse("{\"scope\":{\"kind\":\"allRoots\"},\"tree\":\"combined\",\"predicates\":[{\"kind\":\"equals\",\"path\":[{\"kind\":\"uia\",\"name\":\"name\"}],\"value\":false}],\"depth\":256,\"limit\":200}"); var x = Locator.FromJson(n); Assert.Equal("combined", Locator.FromJson(x.ToJson()).Tree); }
    [Theory]
    [InlineData("{\"kind\":\"allRoots\",\"handle\":null}")]
    [InlineData("{\"kind\":\"window\"}")]
    [InlineData("{\"kind\":\"allRoots\",\"extra\":1}")]
    public void RejectsInvalidScope(string s) => Assert.Throws<ProtocolException>(() => Scope.FromJson(Parse(s)));
    [Theory]
    [InlineData("{\"kind\":\"assignableTo\",\"fullName\":\"T\",\"pattern\":\"x\"}")]
    [InlineData("{\"kind\":\"equals\",\"path\":[{\"kind\":\"uia\",\"name\":\"bad\"}],\"value\":1}")]
    [InlineData("{\"kind\":\"regex\",\"path\":[{\"kind\":\"uia\",\"name\":\"name\"}],\"pattern\":\"x\",\"flags\":[\"multiline\",\"multiline\"]}")]
    public void RejectsInvalidPredicate(string s) => Assert.Throws<ProtocolException>(() => Predicate.FromJson(Parse(s)));
    [Fact] public void FindAllCountInvariant() { Assert.Throws<ProtocolException>(() => QueryFindAllResult.FromJson(Parse("{\"matches\":[],\"count\":1,\"complete\":true}"))); Assert.Equal(1, QueryFindAllResult.FromJson(Parse("{\"matches\":[],\"count\":1,\"complete\":false}")).Count); }
    [Fact] public void LocatorBounds() { var x = Locator.FromJson(Parse("{\"scope\":{\"kind\":\"allRoots\"},\"tree\":\"visual\",\"predicates\":[],\"depth\":0,\"limit\":1}")); x.Depth = 257; Assert.Throws<ProtocolException>(() => x.ToJson()); }
}
