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
    private static readonly IReadOnlyDictionary<string, Func<JsonNode, object>> Readers = new Dictionary<string, Func<JsonNode, object>>(StringComparer.Ordinal)
    {
        ["ActRealizeItemParams"] = n => ActRealizeItemParams.FromJson(n),
        ["ActRealizeItemResult"] = n => ActRealizeItemResult.FromJson(n),
        ["ActScrollParams"] = n => ActScrollParams.FromJson(n),
        ["ActSetRangeParams"] = n => ActSetRangeParams.FromJson(n),
        ["ActSetValueParams"] = n => ActSetValueParams.FromJson(n),
        ["WaitUntilParams"] = n => WaitUntilParams.FromJson(n),
        ["WaitUntilResult"] = n => WaitUntilResult.FromJson(n),
        ["WriteAudit"] = n => WriteAudit.FromJson(n),
        ["WriteCallParams"] = n => WriteCallParams.FromJson(n),
        ["WriteCallResult"] = n => WriteCallResult.FromJson(n),
        ["WriteSetPropertyParams"] = n => WriteSetPropertyParams.FromJson(n),
        ["WriteSetPropertyResult"] = n => WriteSetPropertyResult.FromJson(n),
        ["ElementState"] = n => ElementState.FromJson(n),
        ["HitTestParams"] = n => HitTestParams.FromJson(n),
        ["HitTestResult"] = n => HitTestResult.FromJson(n),
        ["Locator"] = n => Locator.FromJson(n),
        ["Predicate"] = n => Predicate.FromJson(n),
        ["QueryFindAllParams"] = n => QueryFindAllParams.FromJson(n),
        ["QueryFindAllResult"] = n => QueryFindAllResult.FromJson(n),
        ["QueryFindParams"] = n => QueryFindParams.FromJson(n),
        ["QueryFindResult"] = n => QueryFindResult.FromJson(n),
        ["Scope"] = n => Scope.FromJson(n),
        ["StateGetResult"] = n => StateGetResult.FromJson(n),
        ["StateGetParams"] = n => StateGetParams.FromJson(n),
        ["ActFocusParams"] = n => StateGetParams.FromJson(n),
        ["ActBringIntoViewParams"] = n => StateGetParams.FromJson(n),
        ["ActInvokeParams"] = n => StateGetParams.FromJson(n),
        ["ActToggleParams"] = n => StateGetParams.FromJson(n),
        ["ActExpandParams"] = n => StateGetParams.FromJson(n),
        ["ActCollapseParams"] = n => StateGetParams.FromJson(n),
        ["ActSelectParams"] = n => StateGetParams.FromJson(n),
        ["ActScrollIntoViewParams"] = n => StateGetParams.FromJson(n),
        ["ActFocusResult"] = n => ActResult.FromJson(n),
        ["ActBringIntoViewResult"] = n => ActResult.FromJson(n),
        ["ActInvokeResult"] = n => ActResult.FromJson(n),
        ["ActToggleResult"] = n => ActResult.FromJson(n),
        ["ActExpandResult"] = n => ActResult.FromJson(n),
        ["ActCollapseResult"] = n => ActResult.FromJson(n),
        ["ActSelectResult"] = n => ActResult.FromJson(n),
        ["ActScrollIntoViewResult"] = n => ActResult.FromJson(n),
        ["ActSetValueResult"] = n => ActResult.FromJson(n),
        ["ActSetRangeResult"] = n => ActResult.FromJson(n),
        ["ActScrollResult"] = n => ActResult.FromJson(n),
        ["EventsSubscribeParams"] = n => EventsSubscribeParams.FromJson(n),
        ["EventsSubscribeResult"] = n => EventsSubscription.FromJson(n),
        ["EventsUnsubscribeParams"] = n => EventsSubscription.FromJson(n),
        ["EventsUnsubscribeResult"] = n => EventsUnsubscribeResult.FromJson(n),
        ["EventsNotification"] = n => EventsNotification.FromJson(n),
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
        foreach (string kind in new[] { "valid", "invalid" }) { string folder = Path.Combine(dir.FullName, "protocol", "fixtures", kind); if (!Directory.Exists(folder)) continue; foreach (string file in Directory.EnumerateFiles(folder, "*.json").OrderBy(x => x, StringComparer.Ordinal)) { yield return new object[] { file, kind == "valid" }; } }
    }
    [FixtureTheory]
    [MemberData(nameof(Fixtures))]
    public void GoldenFixture(string file, bool valid)
    {
        byte[] bytes = File.ReadAllBytes(file); var outer = Assert.IsType<JsonObjectNode>(StrictJson.Parse(bytes, 0, bytes.Length)); string schema = Assert.IsType<JsonStringNode>(outer.Get("schema")).Value; Assert.True(Readers.TryGetValue(schema, out var reader), "Unmapped fixture schema: " + schema); if (valid) reader!(outer.Get("instance")); else Assert.Throws<ProtocolException>(() => reader!(outer.Get("instance")));
    }
}
