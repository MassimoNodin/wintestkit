using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using WinTestKit.Inspector.Protocol;
using Xunit;
using Xunit.Abstractions;
using Xunit.Sdk;

namespace Protocol.Tests;

[XunitTestCaseDiscoverer("Protocol.Tests.FixtureTheoryDiscoverer", "Protocol.Tests")]
public sealed class FixtureTheoryAttribute : TheoryAttribute { }

public sealed class FixtureTheoryDiscoverer : IXunitTestCaseDiscoverer
{
    private readonly IMessageSink sink;
    public FixtureTheoryDiscoverer(IMessageSink sink) { this.sink = sink; }
    public IEnumerable<IXunitTestCase> Discover(ITestFrameworkDiscoveryOptions options, ITestMethod method, IAttributeInfo attribute) => FixtureTests.Fixtures().Any() ? new TheoryDiscoverer(sink).Discover(options, method, attribute) : Enumerable.Empty<IXunitTestCase>();
}

[Trait("Category", "Unit")]
public class FixtureTests
{
    // Slice P0c-2 removes this list when the protocol 2 readers are implemented.
    private static readonly HashSet<string> PendingProtocol2Readers = new HashSet<string>(StringComparer.Ordinal)
    {
        "ActBringIntoViewParams",
        "ActBringIntoViewResult",
        "ActCollapseParams",
        "ActCollapseResult",
        "ActExpandParams",
        "ActExpandResult",
        "ActFocusParams",
        "ActFocusResult",
        "ActInvokeParams",
        "ActInvokeResult",
        "ActRealizeItemParams",
        "ActRealizeItemResult",
        "ActScrollIntoViewParams",
        "ActScrollIntoViewResult",
        "ActScrollParams",
        "ActScrollResult",
        "ActSelectParams",
        "ActSelectResult",
        "ActSetRangeParams",
        "ActSetRangeResult",
        "ActSetValueParams",
        "ActSetValueResult",
        "ActToggleParams",
        "ActToggleResult",
        "ElementState",
        "EventsNotification",
        "EventsSubscribeParams",
        "EventsSubscribeResult",
        "EventsUnsubscribeParams",
        "EventsUnsubscribeResult",
        "HitTestParams",
        "HitTestResult",
        "Locator",
        "Predicate",
        "QueryFindAllParams",
        "QueryFindAllResult",
        "QueryFindParams",
        "QueryFindResult",
        "Scope",
        "StateGetParams",
        "StateGetResult",
        "WaitUntilParams",
        "WaitUntilResult",
        "WriteAudit",
        "WriteCallParams",
        "WriteCallResult",
        "WriteSetPropertyParams",
        "WriteSetPropertyResult",
    };
    private static readonly IReadOnlyDictionary<string, Func<JsonNode, object>> Readers = new Dictionary<string, Func<JsonNode, object>>(StringComparer.Ordinal)
    {
        ["AllowEntry"] = n => AllowEntry.FromJson(n),
        ["ResolveParams"] = n => ResolveParams.FromJson(n),
        ["CandidateRequest"] = n => CandidateRequestDto.FromJson(n),
        ["ReadBatchParams"] = n => ReadBatchParams.FromJson(n),
        ["RootsParams"] = n => RootsParams.FromJson(n),
        ["ChildrenParams"] = n => ChildrenParams.FromJson(n),
        ["MembersParams"] = n => MembersParams.FromJson(n),
        ["ReadParams"] = n => ReadParams.FromJson(n),
        ["BindingsParams"] = n => BindingsParams.FromJson(n),
        ["BindingsResult"] = n => BindingsResult.FromJson(n),
        ["ReleaseParams"] = n => ReleaseParams.FromJson(n),
        ["ReleaseResult"] = n => ReleaseResult.FromJson(n),
        ["CancelParams"] = n => CancelParams.FromJson(n),
        ["CancelResult"] = n => CancelResult.FromJson(n),
        ["CloseParams"] = n => CloseParams.FromJson(n),
        ["CloseResult"] = n => CloseResult.FromJson(n),
        ["DependencyMetadata"] = n => { NestedMetadata.Dependency(n); return n; },
        ["AttributeLiteral"] = n => { NestedMetadata.Literal(n); return n; },
        ["DependencySource"] = n => DependencySourceDto.FromJson(n),
        ["RelativeSource"] = n => { NestedMetadata.RelativeSource(n); return n; },
        ["ProcessIdentity"] = n => ProcessIdentity.FromJson(n), ["Session"] = n => SessionInfo.FromJson(n), ["SessionInfo"] = n => SessionInfo.FromJson(n), ["TypeInfo"] = n => TypeInfoDto.FromJson(n), ["ObjectRef"] = n => ObjectRef.FromJson(n), ["Member"] = n => WinTestKit.Inspector.Protocol.MemberInfo.FromJson(n), ["AttributeInfo"] = n => AttributeInfo.FromJson(n), ["Value"] = n => ValueDto.FromJson(n), ["Diagnostic"] = n => Diagnostic.FromJson(n), ["Mapping"] = n => MappingDto.FromJson(n), ["ManagedNode"] = n => ManagedNodeDto.FromJson(n), ["BindingInfo"] = n => BindingInfoDto.FromJson(n), ["PathSegment"] = n => PathSegment.FromJson(n), ["Path"] = ReadPath, ["PathValue"] = n => PathValue.FromJson(n), ["ReadResult"] = n => ReadResult.FromJson(n), ["CandidateResult"] = n => CandidateResult.FromJson(n), ["ReadBatchResult"] = n => ReadBatchResult.FromJson(n), ["HelloParams"] = n => HelloParams.FromJson(n), ["HelloResult"] = n => HelloResult.FromJson(n), ["RequestEnvelope"] = n => RequestEnvelope.FromJson(n), ["ResponseEnvelope"] = n => ResponseEnvelope.FromJson(n), ["ErrorInfo"] = n => ErrorInfo.FromJson(n), ["BootstrapSettings"] = n => BootstrapSettings.FromJson(n), ["MemberPage"] = n => PageDto<WinTestKit.Inspector.Protocol.MemberInfo>.FromJson(n, WinTestKit.Inspector.Protocol.MemberInfo.FromJson), ["ManagedNodePage"] = n => PageDto<ManagedNodeDto>.FromJson(n, ManagedNodeDto.FromJson)
    };
    private static object ReadPath(JsonNode node)
    {
        var wrapper = new JsonObjectNode(); wrapper.Add("path", node); var value = new JsonObjectNode(); value.Add("status", new JsonStringNode("ok")); value.Add("kind", new JsonStringNode("null")); value.Add("declaredType", new JsonStringNode("")); value.Add("runtimeType", new JsonStringNode("")); value.Add("scalar", JsonNullNode.Instance); wrapper.Add("value", value); return PathValue.FromJson(wrapper).Path;
    }
    public static IEnumerable<object[]> Fixtures()
    {
        DirectoryInfo? dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir != null && !File.Exists(Path.Combine(dir.FullName, "WinTestKit.Inspector.sln"))) dir = dir.Parent;
        if (dir == null) yield break;
        foreach (string kind in new[] { "valid", "invalid" }) { string folder = Path.Combine(dir.FullName, "protocol", "fixtures", kind); if (!Directory.Exists(folder)) continue; foreach (string file in Directory.EnumerateFiles(folder, "*.json").OrderBy(x => x, StringComparer.Ordinal)) { if (Path.GetFileName(file).StartsWith("p2-", StringComparison.Ordinal)) { byte[] bytes = File.ReadAllBytes(file); var outer = (JsonObjectNode)StrictJson.Parse(bytes, 0, bytes.Length); string schema = ((JsonStringNode)outer.Get("schema")).Value; if (PendingProtocol2Readers.Contains(schema)) continue; } yield return new object[] { file, kind == "valid" }; } }
    }
    [FixtureTheory]
    [MemberData(nameof(Fixtures))]
    public void GoldenFixture(string file, bool valid)
    {
        byte[] bytes = File.ReadAllBytes(file); var outer = Assert.IsType<JsonObjectNode>(StrictJson.Parse(bytes, 0, bytes.Length)); string schema = Assert.IsType<JsonStringNode>(outer.Get("schema")).Value; Assert.True(Readers.TryGetValue(schema, out var reader), "Unmapped fixture schema: " + schema); if (valid) reader!(outer.Get("instance")); else Assert.Throws<ProtocolException>(() => reader!(outer.Get("instance")));
    }
}
