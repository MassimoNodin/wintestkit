using System;
using System.Collections.Generic;
using System.Text;
using WinTestKit.Inspector.Protocol;
using Xunit;

namespace Protocol.Tests;

[Trait("Category", "Unit")]
public class DtoTests
{
    private static ProcessIdentity Process() => new() { Pid = 12, CreationTimeUtc = "2026-10-27T00:00:00Z" };
    private static TypeInfoDto Type() => new() { Name = "T", FullName = "N.T", AssemblyName = "A", AssemblyQualifiedName = "N.T, A" };
    private static ObjectRef Object() => new() { SessionId = "s", ObjectId = "o", DispatcherId = "d", Generation = 1, Type = Type() };
    private static PathSegment Path() => new() { Kind = SegmentKind.Property, Name = "Name" };
    private static ValueDto Value() => new() { Status = ValueStatus.Ok, Kind = ValueKind.String, DeclaredType = "String", RuntimeType = "String", Scalar = new JsonStringNode("value") };
    private static MappingDto Mapping() => new() { Status = MappingStatus.Exact, Process = Process(), RuntimeId = new[] { 1, 2 }, Object = Object() };
    private static PathValue PathValue() => new() { Path = new[] { Path() }, Value = Value() };
    private static void RoundTrip(JsonObjectNode node, Func<JsonNode, JsonObjectNode> read) => Assert.Equal(Encoding.UTF8.GetString(StrictJson.Serialize(node)), Encoding.UTF8.GetString(StrictJson.Serialize(read(node))));
    [Fact] public void IdentityTypesRoundTrip() { RoundTrip(Process().ToJson(), n => ProcessIdentity.FromJson(n).ToJson()); RoundTrip(Type().ToJson(), n => TypeInfoDto.FromJson(n).ToJson()); RoundTrip(Object().ToJson(), n => ObjectRef.FromJson(n).ToJson()); RoundTrip(Path().ToJson(), n => PathSegment.FromJson(n).ToJson()); }
    [Fact] public void ResultsRoundTrip() { RoundTrip(Value().ToJson(), n => ValueDto.FromJson(n).ToJson()); RoundTrip(Mapping().ToJson(), n => MappingDto.FromJson(n).ToJson()); RoundTrip(new Diagnostic { Code = "partial", Message = "partial" }.ToJson(), n => Diagnostic.FromJson(n).ToJson()); RoundTrip(new ManagedNodeDto { Object = Object(), Label = "T", RuntimeId = new[] { 1 } }.ToJson(), n => ManagedNodeDto.FromJson(n).ToJson()); RoundTrip(PathValue().ToJson(), n => WinTestKit.Inspector.Protocol.PathValue.FromJson(n).ToJson()); RoundTrip(new ReadResult { ReadId = "r", Values = new[] { PathValue() } }.ToJson(), n => ReadResult.FromJson(n).ToJson()); var candidate = new CandidateResult { RuntimeId = new[] { 1, 2 }, Mapping = Mapping(), Values = new[] { PathValue() } }; RoundTrip(candidate.ToJson(), n => CandidateResult.FromJson(n).ToJson()); RoundTrip(new ReadBatchResult { Candidates = new[] { candidate } }.ToJson(), n => ReadBatchResult.FromJson(n).ToJson()); }
    [Fact] public void MetadataRoundTrip() { var attr = new AttributeInfo { TypeName = "Attribute" }; RoundTrip(attr.ToJson(), n => AttributeInfo.FromJson(n).ToJson()); var member = new WinTestKit.Inspector.Protocol.MemberInfo { MemberKey = "key", Name = "Name", Category = MemberCategory.ClrProperty, DeclaringType = "T", DeclaredType = "String", Visibility = Visibility.Public, Readable = true, Attributes = new[] { attr }, PathSegment = Path() }; RoundTrip(member.ToJson(), n => WinTestKit.Inspector.Protocol.MemberInfo.FromJson(n).ToJson()); var page = new PageDto<WinTestKit.Inspector.Protocol.MemberInfo> { Items = new[] { member }, Complete = true, SnapshotId = "snapshot" }; RoundTrip(page.ToJson(), n => PageDto<WinTestKit.Inspector.Protocol.MemberInfo>.FromJson(n, WinTestKit.Inspector.Protocol.MemberInfo.FromJson).ToJson()); var binding = new BindingInfoDto { MemberKey = "key", Kind = BindingKind.None }; RoundTrip(binding.ToJson(), n => BindingInfoDto.FromJson(n).ToJson()); }
    [Fact] public void SessionRoundTrip() { var session = new SessionInfo { SessionId = "s", Process = Process(), State = SessionState.Ready, ProtocolMajor = 1 }; RoundTrip(session.ToJson(), n => SessionInfo.FromJson(n).ToJson()); var hello = new HelloParams { ProtocolMajor = 1, SessionId = "s", Token = "token", Process = Process() }; RoundTrip(hello.ToJson(), n => HelloParams.FromJson(n).ToJson()); var result = new HelloResult { AgentVersion = "1", Tfm = "net48", Architecture = "x86", RuntimeVersion = "4", Process = Process() }; RoundTrip(result.ToJson(), n => HelloResult.FromJson(n).ToJson()); var request = new RequestEnvelope { Id = 1, Method = "roots" }; RoundTrip(request.ToJson(), n => RequestEnvelope.FromJson(n).ToJson()); var response = new ResponseEnvelope { Id = 1, Error = new ErrorInfo { Code = ErrorCodes.Busy, Message = "busy" } }; RoundTrip(response.ToJson(), n => ResponseEnvelope.FromJson(n).ToJson()); var bootstrap = new BootstrapSettings { ProtocolMajor = 1, SessionId = "21cf791c-4f3c-4ea4-a7e2-c79a0a7fbc9c", Process = Process(), PipeName = "pipe", Token = Convert.ToBase64String(new byte[32]), ClientSid = "sid", ExpiresUtc = "2026-10-27T00:00:00Z", RequestTimeoutMs = 1000, IdleTimeoutMs = 1000, AgentVersion = "1" }; RoundTrip(bootstrap.ToJson(), n => BootstrapSettings.FromJson(n).ToJson()); }
    [Fact] public void RejectsUnknownFieldsAndInvalidVariants() { var p = Process().ToJson(); p.Add("extra", JsonNullNode.Instance); Assert.Throws<ProtocolException>(() => ProcessIdentity.FromJson(p)); var path = Path(); path.OwnerType = "invalid"; Assert.Throws<ProtocolException>(() => path.ToJson()); var value = Value(); value.Status = ValueStatus.Redacted; Assert.Throws<ProtocolException>(() => value.ToJson()); var truncated = Value(); truncated.Status = ValueStatus.Truncated; Assert.Throws<ProtocolException>(() => truncated.ToJson()); var mapping = Mapping(); mapping.Status = MappingStatus.Ambiguous; Assert.Throws<ProtocolException>(() => mapping.ToJson()); var response = new ResponseEnvelope { Id = 1, Result = JsonNullNode.Instance, Error = new ErrorInfo() }; Assert.Throws<ProtocolException>(() => response.ToJson()); }
    [Fact] public void ValueVariantsPreserveAbsentAndNull() { var nullValue = new ValueDto { Status = ValueStatus.Ok, Kind = ValueKind.Null, Scalar = JsonNullNode.Instance }; Assert.IsType<JsonNullNode>(ValueDto.FromJson(nullValue.ToJson()).Scalar); nullValue.Scalar = null; Assert.Throws<ProtocolException>(() => nullValue.ToJson()); var truncated = new ValueDto { Status = ValueStatus.Truncated, Kind = ValueKind.String, Scalar = new JsonStringNode("abc"), TruncatedAt = 4 }; Assert.Equal(4, ValueDto.FromJson(truncated.ToJson()).TruncatedAt); truncated.TruncatedAt = 3; Assert.Throws<ProtocolException>(() => truncated.ToJson()); var redacted = new ValueDto { Status = ValueStatus.Redacted, Kind = ValueKind.Unavailable, RedactionRule = "password" }; Assert.Null(ValueDto.FromJson(redacted.ToJson()).Scalar); redacted.NumericValue = "42"; Assert.Throws<ProtocolException>(() => redacted.ToJson()); }
    public static IEnumerable<object[]> Readers() => new object[][]
    {
        new object[] { "ProcessIdentity", (Func<JsonNode, object>)(n => ProcessIdentity.FromJson(n)) }, new object[] { "TypeInfo", (Func<JsonNode, object>)(n => TypeInfoDto.FromJson(n)) }, new object[] { "ObjectRef", (Func<JsonNode, object>)(n => ObjectRef.FromJson(n)) }, new object[] { "PathSegment", (Func<JsonNode, object>)(n => PathSegment.FromJson(n)) }, new object[] { "Value", (Func<JsonNode, object>)(n => ValueDto.FromJson(n)) }, new object[] { "Mapping", (Func<JsonNode, object>)(n => MappingDto.FromJson(n)) }, new object[] { "Diagnostic", (Func<JsonNode, object>)(n => Diagnostic.FromJson(n)) }, new object[] { "ManagedNode", (Func<JsonNode, object>)(n => ManagedNodeDto.FromJson(n)) }, new object[] { "PathValue", (Func<JsonNode, object>)(n => WinTestKit.Inspector.Protocol.PathValue.FromJson(n)) }, new object[] { "ReadResult", (Func<JsonNode, object>)(n => ReadResult.FromJson(n)) }, new object[] { "CandidateResult", (Func<JsonNode, object>)(n => CandidateResult.FromJson(n)) }, new object[] { "ReadBatchResult", (Func<JsonNode, object>)(n => ReadBatchResult.FromJson(n)) }, new object[] { "Attribute", (Func<JsonNode, object>)(n => AttributeInfo.FromJson(n)) }, new object[] { "Member", (Func<JsonNode, object>)(n => WinTestKit.Inspector.Protocol.MemberInfo.FromJson(n)) }, new object[] { "Page", (Func<JsonNode, object>)(n => PageDto<ManagedNodeDto>.FromJson(n, ManagedNodeDto.FromJson)) }, new object[] { "Binding", (Func<JsonNode, object>)(n => BindingInfoDto.FromJson(n)) }, new object[] { "Session", (Func<JsonNode, object>)(n => SessionInfo.FromJson(n)) }, new object[] { "HelloParams", (Func<JsonNode, object>)(n => HelloParams.FromJson(n)) }, new object[] { "HelloResult", (Func<JsonNode, object>)(n => HelloResult.FromJson(n)) }, new object[] { "Request", (Func<JsonNode, object>)(n => RequestEnvelope.FromJson(n)) }, new object[] { "Error", (Func<JsonNode, object>)(n => ErrorInfo.FromJson(n)) }, new object[] { "Response", (Func<JsonNode, object>)(n => ResponseEnvelope.FromJson(n)) }, new object[] { "Bootstrap", (Func<JsonNode, object>)(n => BootstrapSettings.FromJson(n)) }
    };
    [Theory][MemberData(nameof(Readers))] public void RejectsMissingRequiredFields(string name, Func<JsonNode, object> reader) { Assert.NotEmpty(name); Assert.Throws<ProtocolException>(() => reader(new JsonObjectNode())); }

    [Fact] public void BootstrapRedactionRulesAreRequiredBoundedAndNonDisclosing()
    {
        var settings = new BootstrapSettings { ProtocolMajor = 1, SessionId = "21cf791c-4f3c-4ea4-a7e2-c79a0a7fbc9c", Process = Process(), PipeName = "pipe", Token = Convert.ToBase64String(new byte[32]), ClientSid = "sid", ExpiresUtc = "2026-10-27T00:00:00Z", RequestTimeoutMs = 1000, IdleTimeoutMs = 1000, AgentVersion = "1" };
        JsonObjectNode valid = settings.ToJson();
        JsonObjectNode Replace(JsonNode? value)
        {
            var result = new JsonObjectNode();
            foreach (var pair in valid.Members) if (pair.Key != "redactNames") result.Add(pair.Key, pair.Value);
            if (value != null) result.Add("redactNames", value);
            return result;
        }
        var oversized = new JsonArrayNode(); for (int index = 0; index < 33; index++) oversized.Add(new JsonStringNode("rule"));
        var empty = new JsonArrayNode(); empty.Add(new JsonStringNode(""));
        var longName = new JsonArrayNode(); longName.Add(new JsonStringNode(new string('x', 129)));
        var invalidUnicode = new JsonArrayNode(); invalidUnicode.Add(new JsonStringNode("\ud800"));
        foreach (JsonNode? rules in new JsonNode?[] { null, JsonNullNode.Instance, new JsonStringNode("private"), oversized, empty, longName, invalidUnicode })
        {
            var error = Assert.Throws<ProtocolException>(() => BootstrapSettings.FromJson(Replace(rules)));
            Assert.DoesNotContain("private", error.Message);
        }
        var unicode = new JsonArrayNode(); unicode.Add(new JsonStringNode(string.Concat(System.Linq.Enumerable.Repeat("😀", 128))));
        Assert.Single(BootstrapSettings.FromJson(Replace(unicode)).RedactNames);
    }
}
