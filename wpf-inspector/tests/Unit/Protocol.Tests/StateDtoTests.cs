using System.Text;
using WinTestKit.Inspector.Protocol;
using Xunit;
namespace Protocol.Tests;
public class StateDtoTests
{
    private static JsonNode Parse(string s) { var b = Encoding.UTF8.GetBytes(s); return StrictJson.Parse(b,0,b.Length); }
    [Fact] public void HitTestRoundTrips() { var x = HitTestParams.FromJson(Parse("{\"nativeWindowHandle\":-1,\"point\":{\"x\":-2.5,\"y\":3},\"timeoutMs\":2000}")); Assert.Equal(-2.5, HitTestParams.FromJson(x.ToJson()).Point.X); }
    [Theory]
    [InlineData("{\"x\":0,\"y\":0,\"width\":-1,\"height\":0}")]
    [InlineData("{\"x\":0,\"y\":0,\"width\":1,\"height\":0,\"extra\":1}")]
    public void RejectsInvalidBounds(string s) => Assert.Throws<ProtocolException>(() => RectDto.FromJson(Parse(s)));
    [Fact] public void PartRequiresNullableBounds() { Assert.Throws<ProtocolException>(() => PartGeometry.FromJson(Parse("{\"name\":\"PART\",\"role\":\"templatePart\"}"))); var p = PartGeometry.FromJson(Parse("{\"name\":\"PART\",\"role\":\"templatePart\",\"bounds\":null}")); Assert.Null(PartGeometry.FromJson(p.ToJson()).Bounds); }
    [Fact] public void RejectsUnknownRole() => Assert.Throws<ProtocolException>(() => PartGeometry.FromJson(Parse("{\"name\":\"PART\",\"role\":\"other\",\"bounds\":null}")));
}
