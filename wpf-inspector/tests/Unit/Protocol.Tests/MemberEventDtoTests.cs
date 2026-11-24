using System.Collections.Generic;
using System.Linq;
using WinTestKit.Inspector.Protocol;
using Xunit;

namespace Protocol.Tests;

[Trait("Category", "Unit")]
public class MemberEventDtoTests
{
    private static JsonNode Parse(string json) { byte[] bytes = System.Text.Encoding.UTF8.GetBytes(json); return StrictJson.Parse(bytes, 0, bytes.Length); }

    private static MemberEventHandlerDto Handler(int index, bool? handledEventsToo) => new MemberEventHandlerDto { DeclaringType = "T" + index, Method = "M" + index, HandledEventsToo = handledEventsToo };

    private static MemberEventDto Routed(int count = 2, bool known = true) => new MemberEventDto
    {
        Kind = "routed", Name = "Click", DeclaringType = "System.Windows.Controls.Primitives.ButtonBase", HandlerType = "System.Windows.RoutedEventHandler", Strategy = "bubble",
        Known = known, Count = known ? count : 0, Handlers = known ? Enumerable.Range(0, count).Select(index => Handler(index, index % 2 == 1)).ToList() : new List<MemberEventHandlerDto>(),
    };

    private static MemberEventDto Clr(int count = 1, bool known = true, bool isStatic = false) => new MemberEventDto
    {
        Kind = "clr", Name = "Changed", DeclaringType = "Demo.Model", HandlerType = "System.EventHandler", IsStatic = isStatic,
        Known = known, Count = known ? count : 0, Handlers = known ? Enumerable.Range(0, count).Select(index => Handler(index, null)).ToList() : new List<MemberEventHandlerDto>(),
    };

    private static MemberEventDto RoundTrip(MemberEventDto value)
    {
        byte[] json = StrictJson.Serialize(value.ToJson());
        var copy = MemberEventDto.FromJson(StrictJson.Parse(json, 0, json.Length));
        Assert.Equal(json, StrictJson.Serialize(copy.ToJson()));
        return copy;
    }

    [Fact]
    public void MethodAndFeatureAreNamed()
    {
        Assert.Equal("members.events", PipeMethods.MemberEvents);
        Assert.Equal("members.resource", PipeMethods.Resource);
        Assert.Equal("membersEvents", Features.MembersEvents);
        var hello = new HelloResult { AgentVersion = "1", Tfm = "net10.0-windows", Architecture = "x64", RuntimeVersion = "10.0", Process = new ProcessIdentity { Pid = 1, CreationTimeUtc = "2026-01-01T00:00:00Z" }, Features = new[] { "membersStyling", "membersEvents" } };
        Assert.Equal(new[] { "membersStyling", "membersEvents" }, HelloResult.FromJson(hello.ToJson()).Features);
    }

    [Fact]
    public void RoutedAndClrEventsUseTheirOwnFieldNames()
    {
        string routed = System.Text.Encoding.UTF8.GetString(StrictJson.Serialize(Routed().ToJson()));
        Assert.Contains("\"handlersKnown\":true", routed);
        Assert.Contains("\"handlerCount\":2", routed);
        Assert.Contains("\"handledEventsToo\":true", routed);
        Assert.DoesNotContain("subscribers", routed);
        Assert.DoesNotContain("isStatic", routed);
        string clr = System.Text.Encoding.UTF8.GetString(StrictJson.Serialize(Clr(isStatic: true).ToJson()));
        Assert.Contains("\"subscribersKnown\":true", clr);
        Assert.Contains("\"subscriberCount\":1", clr);
        Assert.Contains("\"isStatic\":true", clr);
        Assert.DoesNotContain("handlersKnown", clr);
        Assert.DoesNotContain("handledEventsToo", clr);
        Assert.DoesNotContain("strategy", clr);
        Assert.Equal(2, RoundTrip(Routed()).Handlers.Count);
        Assert.True(RoundTrip(Clr(isStatic: true)).IsStatic);
    }

    [Fact]
    public void UnknownHandlersAreEmptyAndSayTheyAreUnknown()
    {
        var routed = RoundTrip(Routed(known: false));
        Assert.False(routed.Known);
        Assert.Empty(routed.Handlers);
        Assert.False(RoundTrip(Clr(known: false)).Known);
        var inconsistent = Routed(known: false); inconsistent.Count = 1;
        Assert.Throws<ProtocolException>(() => MemberEventDto.FromJson(inconsistent.ToJson()));
        var truncated = Clr(known: false); truncated.Truncated = true;
        Assert.Throws<ProtocolException>(() => MemberEventDto.FromJson(truncated.ToJson()));
    }

    [Fact]
    public void HandlerListsAreCappedAndTheirTruncationIsConsistent()
    {
        Assert.Equal(32, MemberEventLimits.MaxHandlers);
        var capped = Clr(40); capped.Handlers = capped.Handlers.Take(32).ToList(); capped.Truncated = true;
        var copy = RoundTrip(capped);
        Assert.Equal(40, copy.Count);
        Assert.Equal(32, copy.Handlers.Count);
        Assert.True(copy.Truncated);
        var untruncated = Clr(40); untruncated.Handlers = untruncated.Handlers.Take(32).ToList();
        Assert.Throws<ProtocolException>(() => MemberEventDto.FromJson(untruncated.ToJson()));
        var tooMany = Routed(33);
        Assert.Throws<ProtocolException>(() => MemberEventDto.FromJson(tooMany.ToJson()));
        var fewer = Routed(2); fewer.Count = 1;
        Assert.Throws<ProtocolException>(() => MemberEventDto.FromJson(fewer.ToJson()));
    }

    [Fact]
    public void KindsRejectEachOthersFieldsAndValues()
    {
        Assert.Throws<ProtocolException>(() => MemberEventDto.FromJson(Parse("{\"kind\":\"delegate\",\"name\":\"n\",\"declaringType\":\"t\",\"handlerType\":\"h\"}")));
        var withSubscribers = (JsonObjectNode)Parse(System.Text.Encoding.UTF8.GetString(StrictJson.Serialize(Routed().ToJson())));
        withSubscribers.Add("subscribers", new JsonArrayNode());
        Assert.Throws<ProtocolException>(() => MemberEventDto.FromJson(withSubscribers));
        var noStrategy = Routed(); noStrategy.Strategy = null;
        Assert.Throws<ProtocolException>(() => noStrategy.ToJson());
        var badStrategy = Routed(); badStrategy.Strategy = "sideways";
        Assert.Throws<ProtocolException>(() => MemberEventDto.FromJson(badStrategy.ToJson()));
        var clrWithFlag = Clr(); clrWithFlag.Handlers = new[] { Handler(0, true) };
        Assert.Throws<ProtocolException>(() => MemberEventDto.FromJson(clrWithFlag.ToJson()));
        var routedWithoutFlag = Routed(); routedWithoutFlag.Handlers = new[] { Handler(0, null), Handler(1, null) };
        Assert.Throws<ProtocolException>(() => MemberEventDto.FromJson(routedWithoutFlag.ToJson()));
    }

    [Fact]
    public void PageCarriesEventsLikeAnyOtherPage()
    {
        var page = new PageDto<MemberEventDto> { Items = new[] { Routed(), Clr() }, Complete = true, SnapshotId = "snap" };
        byte[] json = StrictJson.Serialize(page.ToJson());
        var copy = PageDto<MemberEventDto>.FromJson(StrictJson.Parse(json, 0, json.Length), MemberEventDto.FromJson);
        Assert.Equal(new[] { "routed", "clr" }, copy.Items.Select(item => item.Kind));
        Assert.Equal(json, StrictJson.Serialize(copy.ToJson()));
    }

    [Fact]
    public void ResourceParamsAndResultRoundTrip()
    {
        var parameters = ResourceParams.FromJson(Parse("{\"sessionId\":\"s\",\"objectId\":\"o\",\"generation\":2,\"scope\":\"application\",\"key\":\"Accent\",\"keyKind\":\"string\",\"index\":4}"));
        Assert.Equal("application", parameters.Scope);
        Assert.Equal(4, parameters.Index);
        Assert.Equal(parameters.Key, ResourceParams.FromJson(parameters.ToJson()).Key);
        Assert.Null(ResourceParams.FromJson(Parse("{\"sessionId\":\"s\",\"objectId\":\"o\",\"generation\":2,\"scope\":\"local\",\"key\":\"k\",\"keyKind\":\"type\"}")).Index);
        Assert.Throws<ProtocolException>(() => ResourceParams.FromJson(Parse("{\"sessionId\":\"s\",\"objectId\":\"o\",\"generation\":2,\"scope\":\"merged\",\"key\":\"k\",\"keyKind\":\"type\"}")));
        Assert.Throws<ProtocolException>(() => ResourceParams.FromJson(Parse("{\"sessionId\":\"s\",\"objectId\":\"o\",\"generation\":2,\"scope\":\"local\",\"key\":\"k\",\"keyKind\":\"number\"}")));
        Assert.Throws<ProtocolException>(() => ResourceParams.FromJson(Parse("{\"sessionId\":\"s\",\"objectId\":\"o\",\"generation\":2,\"scope\":\"local\",\"key\":\"k\",\"keyKind\":\"type\",\"index\":-1}")));

        var found = new ResourceResult { Found = true, ValueType = "System.String", Value = new ValueDto { Status = ValueStatus.Ok, Kind = ValueKind.String, DeclaredType = "System.Object", RuntimeType = "System.String", Scalar = new JsonStringNode("v") } };
        byte[] json = StrictJson.Serialize(found.ToJson());
        Assert.Equal(json, StrictJson.Serialize(ResourceResult.FromJson(StrictJson.Parse(json, 0, json.Length)).ToJson()));
        Assert.False(ResourceResult.FromJson(new ResourceResult().ToJson()).Found);
        Assert.Throws<ProtocolException>(() => ResourceResult.FromJson(Parse("{\"found\":false,\"valueType\":\"x\"}")));
        Assert.Throws<ProtocolException>(() => ResourceResult.FromJson(Parse("{\"found\":true,\"valueType\":\"x\"}")));
    }

    [Fact]
    public void ResourceEntriesCarryAKeyAndAPositionNeverAValue()
    {
        var entry = new StylingResourceEntry { Key = "Accent", KeyKind = "string", Index = 7 };
        string text = System.Text.Encoding.UTF8.GetString(StrictJson.Serialize(entry.ToJson()));
        Assert.Equal("{\"key\":\"Accent\",\"keyKind\":\"string\",\"index\":7}", text);
        Assert.Equal(7, StylingResourceEntry.FromJson(entry.ToJson()).Index);
        Assert.Throws<ProtocolException>(() => StylingResourceEntry.FromJson(Parse("{\"key\":\"Accent\",\"keyKind\":\"string\",\"index\":0,\"value\":{}}")));
        Assert.Throws<ProtocolException>(() => StylingResourceEntry.FromJson(Parse("{\"key\":\"Accent\",\"keyKind\":\"string\"}")));
    }
}
