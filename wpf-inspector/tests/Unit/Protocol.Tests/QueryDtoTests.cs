using System.Text;
using WinTestKit.Inspector.Protocol;
using Xunit;
namespace Protocol.Tests;
public class QueryDtoTests
{
    private static JsonNode Parse(string s) { var b = Encoding.UTF8.GetBytes(s); return StrictJson.Parse(b,0,b.Length); }
    [Fact] public void LocatorRoundTrips() { var n = Parse("{\"scope\":{\"kind\":\"allRoots\"},\"tree\":\"combined\",\"predicates\":[{\"kind\":\"equals\",\"path\":[{\"kind\":\"uia\",\"name\":\"name\"}],\"value\":false}],\"depth\":256,\"depthMode\":\"tree\",\"limit\":200}"); var x = Locator.FromJson(n); Assert.Equal("combined", Locator.FromJson(x.ToJson()).Tree); }
    [Fact] public void LocatorRequiresDepthMode() { Assert.Throws<ProtocolException>(() => Locator.FromJson(Parse("{\"scope\":{\"kind\":\"allRoots\"},\"tree\":\"visual\",\"predicates\":[],\"depth\":0,\"limit\":1}"))); }
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
    [Fact] public void UnreadableErrorRoundTrips() { const string json = "{\"code\":\"valueUnreadable\",\"message\":\"unreadable\",\"details\":{\"status\":\"redacted\",\"path\":[{\"kind\":\"property\",\"name\":\"Text\"}]}}"; var error = ErrorInfo.FromJson(Parse(json)); Assert.Equal(ErrorCodes.ValueUnreadable, error.Code); Assert.Equal(json, Encoding.UTF8.GetString(StrictJson.Serialize(ErrorInfo.FromJson(error.ToJson()).ToJson()))); }
    [Fact] public void PredicatePathLimitCountsUtf8Bytes() { string prefix = "[{\"kind\":\"property\",\"name\":\""; string suffix = "\"}]"; int count = (ProtocolLimits.MaxPathBytes - Encoding.UTF8.GetByteCount(prefix + suffix)) / 2; string path = prefix + new string('\u00e9', count) + suffix; Assert.True(Encoding.UTF8.GetByteCount(path) > path.Length); Assert.True(Encoding.UTF8.GetByteCount(path) <= ProtocolLimits.MaxPathBytes); Predicate.FromJson(Parse("{\"kind\":\"equals\",\"path\":" + path + ",\"value\":1}")); string oversized = prefix + new string('\u00e9', count + 1) + suffix; Assert.True(Encoding.UTF8.GetByteCount(oversized) > ProtocolLimits.MaxPathBytes); Assert.Throws<ProtocolException>(() => Predicate.FromJson(Parse("{\"kind\":\"equals\",\"path\":" + oversized + ",\"value\":1}"))); }
    [Fact] public void LocatorBounds() { var x = Locator.FromJson(Parse("{\"scope\":{\"kind\":\"allRoots\"},\"tree\":\"visual\",\"predicates\":[],\"depth\":0,\"depthMode\":\"tree\",\"limit\":1}")); x.Depth = 257; Assert.Throws<ProtocolException>(() => x.ToJson()); }
}
