using System;
using System.Collections.Generic;
using System.Text;
using WinTestKit.Inspector.Protocol;
using Xunit;

namespace Protocol.Tests;

[Trait("Category", "Unit")]
public class MethodDtoTests
{
    private static JsonNode Parse(string text) { var bytes = Encoding.UTF8.GetBytes(text); return StrictJson.Parse(bytes, 0, bytes.Length); }
    public static IEnumerable<object[]> Cases()
    {
        yield return new object[] { "{\"runtimeId\":[1],\"nativeWindowHandle\":-1}", (Func<JsonNode, JsonObjectNode>)(n => ResolveParams.FromJson(n).ToJson()) };
        yield return new object[] { "{\"runtimeId\":[1]}", (Func<JsonNode, JsonObjectNode>)(n => CandidateRequestDto.FromJson(n).ToJson()) };
        yield return new object[] { "{\"candidates\":[{\"runtimeId\":[1]}],\"paths\":[[{\"kind\":\"property\",\"name\":\"X\"}]]}", (Func<JsonNode, JsonObjectNode>)(n => ReadBatchParams.FromJson(n).ToJson()) };
        yield return new object[] { "{\"sessionId\":\"s\",\"pageSize\":200}", (Func<JsonNode, JsonObjectNode>)(n => RootsParams.FromJson(n).ToJson()) };
        yield return new object[] { "{\"sessionId\":\"s\",\"objectId\":\"o\",\"generation\":1,\"tree\":\"visual\"}", (Func<JsonNode, JsonObjectNode>)(n => ChildrenParams.FromJson(n).ToJson()) };
        yield return new object[] { "{\"sessionId\":\"s\",\"objectId\":\"o\",\"generation\":1}", (Func<JsonNode, JsonObjectNode>)(n => MembersParams.FromJson(n).ToJson()) };
        yield return new object[] { "{\"sessionId\":\"s\",\"objectId\":\"o\",\"generation\":1,\"paths\":[[{\"kind\":\"property\",\"name\":\"X\"}]]}", (Func<JsonNode, JsonObjectNode>)(n => ReadParams.FromJson(n).ToJson()) };
        yield return new object[] { "{\"sessionId\":\"s\",\"objectId\":\"o\",\"generation\":1,\"memberKeys\":[]}", (Func<JsonNode, JsonObjectNode>)(n => BindingsParams.FromJson(n).ToJson()) };
        yield return new object[] { "{\"bindings\":[]}", (Func<JsonNode, JsonObjectNode>)(n => BindingsResult.FromJson(n).ToJson()) };
        yield return new object[] { "{\"sessionId\":\"s\",\"objectIds\":[]}", (Func<JsonNode, JsonObjectNode>)(n => ReleaseParams.FromJson(n).ToJson()) };
        yield return new object[] { "{\"releasedCount\":256}", (Func<JsonNode, JsonObjectNode>)(n => ReleaseResult.FromJson(n).ToJson()) };
        yield return new object[] { "{\"requestId\":1}", (Func<JsonNode, JsonObjectNode>)(n => CancelParams.FromJson(n).ToJson()) };
        yield return new object[] { "{\"accepted\":false}", (Func<JsonNode, JsonObjectNode>)(n => CancelResult.FromJson(n).ToJson()) };
        yield return new object[] { "{}", (Func<JsonNode, JsonObjectNode>)(n => CloseParams.FromJson(n).ToJson()) };
        yield return new object[] { "{\"closed\":true}", (Func<JsonNode, JsonObjectNode>)(n => CloseResult.FromJson(n).ToJson()) };
    }
    [Theory, MemberData(nameof(Cases))]
    public void RoundTripAndRejectUnknown(string json, Func<JsonNode, JsonObjectNode> read)
    {
        var node = read(Parse(json));
        read(node);
        node.Add("unknown", JsonNullNode.Instance);
        Assert.Throws<ProtocolException>(() => read(node));
    }
    [Fact] public void EnforcesBoundsAndEnums()
    {
        Assert.Throws<ProtocolException>(() => RootsParams.FromJson(Parse("{\"sessionId\":\"s\",\"pageSize\":201}")));
        Assert.Throws<ProtocolException>(() => ReadBatchParams.FromJson(Parse("{\"candidates\":[],\"paths\":[]}")));
        Assert.Throws<ProtocolException>(() => CloseResult.FromJson(Parse("{\"closed\":false}")));
        Assert.Throws<ProtocolException>(() => ReleaseResult.FromJson(Parse("{\"releasedCount\":257}")));
        Assert.Equal(ErrorCodes.InvalidParams, Assert.Throws<ProtocolException>(() => RequestEnvelope.FromJson(Parse("{\"id\":1,\"method\":\"unknown\",\"params\":{}}"))).Code);
    }
    [Fact] public void RejectsUnknownFeatures()
    {
        var process = new ProcessIdentity { Pid = 12, CreationTimeUtc = "2026-10-27T00:00:00Z" };
        Assert.Throws<ProtocolException>(() => new HelloResult { AgentVersion = "1", Tfm = "net48", Architecture = "x86", RuntimeVersion = "4", Process = process, Features = new[] { "future" } }.ToJson());
        Assert.Throws<ProtocolException>(() => new SessionInfo { SessionId = "s", Process = process, State = SessionState.Ready, Features = new[] { "future" } }.ToJson());
    }
}
