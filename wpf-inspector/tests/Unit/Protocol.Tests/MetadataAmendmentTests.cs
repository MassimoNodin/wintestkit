using System;
using System.Text;
using WinTestKit.Inspector.Protocol;
using Xunit;
using Member = WinTestKit.Inspector.Protocol.MemberInfo;

namespace Protocol.Tests;

[Trait("Category", "Unit")]
public class MetadataAmendmentTests
{
    private static JsonNode Parse(string json) { var bytes = Encoding.UTF8.GetBytes(json); return StrictJson.Parse(bytes, 0, bytes.Length); }
    private static string Text(JsonNode node) => Encoding.UTF8.GetString(StrictJson.Serialize(node));
    private const string Dependency = "{\"ownerType\":\"T\",\"ownerAssembly\":\"A\",\"propertyType\":\"P\",\"readOnly\":false,\"isAttached\":\"unknown\",\"hasLocalValue\":true,\"metadataFlags\":[\"AffectsRender\"]}";
    private static Member MemberWithDependency(string json) => new() { MemberKey = "type:FullName", Name = "FullName", Category = MemberCategory.TypeMetadata, DeclaringType = "T", DeclaredType = "String", Visibility = Visibility.Public, Readable = true, CompatibilityAlias = "ClrFullClassName", Dependency = (JsonObjectNode)Parse(json) };
    [Fact] public void MemberAmendmentsRoundTrip() { var m = MemberWithDependency(Dependency); var copy = Member.FromJson(m.ToJson()); Assert.Equal(m.CompatibilityAlias, copy.CompatibilityAlias); Assert.Equal(MemberCategory.TypeMetadata, copy.Category); Assert.Equal(Text(m.ToJson()), Text(copy.ToJson())); m.CompatibilityAlias = new string('x', 129); Assert.Throws<ProtocolException>(() => m.ToJson()); }
    [Theory]
    [InlineData("\"isAttached\":\"unknown\"", "\"isAttached\":\"maybe\"")]
    [InlineData("\"metadataFlags\":[\"AffectsRender\"]", "\"metadataFlags\":[\"Bogus\"]")]
    [InlineData("\"readOnly\":false", "\"readOnly\":false,\"extra\":1")]
    public void DependencyRejectsInvalidMetadata(string from, string to) => Assert.Throws<ProtocolException>(() => MemberWithDependency(Dependency.Replace(from, to)).ToJson());
    [Fact] public void SourceRoundTripsAndRejectsUnavailable() { var source = new DependencySourceDto { BaseValueSource = "Local", IsExpression = true }; var v = new ValueDto { Status = ValueStatus.Ok, Kind = ValueKind.Null, Scalar = JsonNullNode.Instance, DependencySource = source }; Assert.True(ValueDto.FromJson(v.ToJson()).DependencySource!.IsExpression); v.Status = ValueStatus.Redacted; v.Kind = ValueKind.Unavailable; v.Scalar = null; Assert.Throws<ProtocolException>(() => v.ToJson()); source.BaseValueSource = "Other"; Assert.Throws<ProtocolException>(() => source.ToJson()); var o = new DependencySourceDto { BaseValueSource = "Default" }.ToJson(); o.Add("extra", JsonNullNode.Instance); Assert.Throws<ProtocolException>(() => DependencySourceDto.FromJson(o)); }
    [Fact] public void SourceAcceptedOnTruncatedAndCycle() { var source = new DependencySourceDto { BaseValueSource = "Inherited" }; var truncated = new ValueDto { Status = ValueStatus.Truncated, Kind = ValueKind.String, Scalar = new JsonStringNode("a"), TruncatedAt = 2, DependencySource = source }; Assert.Equal("Inherited", ValueDto.FromJson(truncated.ToJson()).DependencySource!.BaseValueSource); var target = new ObjectRef { SessionId = "s", ObjectId = "o", DispatcherId = "d", Generation = 1, Type = new TypeInfoDto { Name = "T", FullName = "T", AssemblyName = "A", AssemblyQualifiedName = "T, A" } }; var cycle = new ValueDto { Status = ValueStatus.Cycle, Kind = ValueKind.Object, CycleTo = target, DependencySource = source }; Assert.Equal("Inherited", ValueDto.FromJson(cycle.ToJson()).DependencySource!.BaseValueSource); }
    [Fact] public void LiteralArgumentsRoundTripAndRejectInvalid() { var attr = new AttributeInfo { TypeName = "A", ConstructorArguments = new[] { Parse("{\"kind\":\"array\",\"value\":[{\"kind\":\"integer\",\"value\":1}]}") }, NamedArguments = (JsonObjectNode)Parse("{\"Name\":{\"kind\":\"string\",\"value\":\"x\"}}") }; Assert.Equal(Text(attr.ToJson()), Text(AttributeInfo.FromJson(attr.ToJson()).ToJson())); foreach (var bad in new[] { "{\"kind\":\"wat\",\"value\":1}", "{\"kind\":\"integer\",\"value\":1,\"extra\":true}", "{\"kind\":\"array\",\"value\":[{\"kind\":\"array\",\"value\":[]}]}", "{\"kind\":\"boolean\",\"value\":1}" }) { attr.ConstructorArguments = new[] { Parse(bad) }; Assert.Throws<ProtocolException>(() => attr.ToJson()); } }
    [Fact] public void RelativeSourceRoundTripsAndRejectsInvalid() { var b = new BindingInfoDto { MemberKey = "k", Kind = BindingKind.Binding, RelativeSource = Parse("{\"mode\":\"FindAncestor\",\"ancestorType\":\"T\",\"ancestorLevel\":1}") }; Assert.Equal(Text(b.ToJson()), Text(BindingInfoDto.FromJson(b.ToJson()).ToJson())); foreach (var bad in new[] { "{\"mode\":\"Other\"}", "{\"mode\":\"Self\",\"extra\":true}", "{\"mode\":\"FindAncestor\",\"ancestorLevel\":0}" }) { b.RelativeSource = Parse(bad); Assert.Throws<ProtocolException>(() => b.ToJson()); } }
}
