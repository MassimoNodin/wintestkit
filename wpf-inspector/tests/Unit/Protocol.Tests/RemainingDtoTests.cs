using System;
using System.Linq;
using System.Text;
using WinTestKit.Inspector.Protocol;
using Xunit;
namespace Protocol.Tests;
public class RemainingDtoTests
{
    private static JsonNode Parse(string s) { var b = Encoding.UTF8.GetBytes(s); return StrictJson.Parse(b, 0, b.Length); }
    private const string Handle = "{\"sessionId\":\"s\",\"objectId\":\"o\",\"generation\":1,\"type\":{\"name\":\"T\",\"fullName\":\"T\",\"assemblyName\":\"A\",\"assemblyQualifiedName\":\"T, A\",\"baseTypes\":[]},\"dispatcherId\":\"d\"}";
    [Fact] public void ItemVariantsAndBounds() {
        foreach (var s in new[]{"{\"kind\":\"index\",\"index\":9999}","{\"kind\":\"equals\",\"path\":[{\"kind\":\"uia\",\"name\":\"name\"}],\"value\":true}","{\"kind\":\"regex\",\"path\":[{\"kind\":\"uia\",\"name\":\"name\"}],\"pattern\":\"x\",\"flags\":[\"ignoreCase\"]}"}) ItemMatch.FromJson(ItemMatch.FromJson(Parse(s)).ToJson());
        Assert.Throws<ProtocolException>(() => ItemMatch.FromJson(Parse("{\"kind\":\"index\",\"index\":10000}")));
        Assert.Throws<ProtocolException>(() => ItemMatch.FromJson(Parse("{\"kind\":\"index\",\"index\":0,\"value\":1}")));
    }
    [Fact] public void ActionBoundsAndUnknownFields() {
        var s = "{\"handle\":"+Handle+",\"value\":1.5,\"timeoutMs\":2000}"; ActSetRangeParams.FromJson(ActSetRangeParams.FromJson(Parse(s)).ToJson());
        Assert.Throws<ProtocolException>(() => ActSetRangeParams.FromJson(Parse(s.Replace("2000","2001"))));
        Assert.Throws<ProtocolException>(() => ActSetRangeParams.FromJson(Parse(s.Replace("1.5","1.5,\"extra\":true"))));
        Assert.Throws<ProtocolException>(() => ActScrollParams.FromJson(Parse("{\"handle\":"+Handle+",\"horizontal\":\"bad\",\"vertical\":\"none\",\"timeoutMs\":1}")));
    }
    [Fact] public void WaitResultRequiresBothOrNeither() {
        var result = WaitUntilResult.FromJson(Parse("{\"satisfied\":false}")); WaitUntilResult.FromJson(result.ToJson());
        Assert.Throws<ProtocolException>(() => WaitUntilResult.FromJson(Parse("{\"satisfied\":true}")));
        Assert.Throws<ProtocolException>(() => WaitUntilResult.FromJson(Parse("{\"satisfied\":false,\"handle\":"+Handle+"}")));
    }
    [Fact] public void WriteGrammarScalarsAndAudit() {
        string Call(string key,string arg) => "{\"handle\":"+Handle+",\"memberKey\":\""+key+"\",\"arguments\":["+arg+"],\"timeoutMs\":1}";
        var call = WriteCallParams.FromJson(Parse(Call("Refresh(System.Boolean)","true"))); WriteCallParams.FromJson(call.ToJson());
        foreach (var key in new[]{"Refresh", "Refresh( System.Boolean)", "Refresh(System.Int32[])", "Refresh(System.Int32&)", "Refresh(System.Int32?,System.Int32)"}) Assert.Throws<ProtocolException>(() => WriteCallParams.FromJson(Parse(Call(key,"true"))));
        foreach (var arg in new[]{"null", "9223372036854775808"}) Assert.Throws<ProtocolException>(() => WriteCallParams.FromJson(Parse(Call("Reset()",arg))));
        foreach (var outcome in new[]{"performed","denied","failed"}) { var audit = WriteAudit.FromJson(Parse("{\"operation\":\"call\",\"typeFullName\":\"redacted-rule\",\"memberKey\":\"redacted-rule\",\"outcome\":\""+outcome+"\",\"timestampUtc\":\"2026-01-01T00:00:00Z\"}")); WriteAudit.FromJson(audit.ToJson()); }
        Assert.Throws<ProtocolException>(() => WriteAudit.FromJson(Parse("{\"operation\":\"call\",\"typeFullName\":\"T\",\"memberKey\":\"M\",\"outcome\":\"performed\",\"timestampUtc\":\"2026-01-01T00:00:00Z\",\"reason\":\"timeout\"}")));
    }
}
