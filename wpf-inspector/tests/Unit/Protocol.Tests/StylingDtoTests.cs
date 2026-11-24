using System.Collections.Generic;
using System.Linq;
using WinTestKit.Inspector.Protocol;
using Xunit;

namespace Protocol.Tests;

[Trait("Category", "Unit")]
public class StylingDtoTests
{
    private static JsonNode Parse(string json) { byte[] bytes = System.Text.Encoding.UTF8.GetBytes(json); return StrictJson.Parse(bytes, 0, bytes.Length); }

    private static ValueDto Text(string value) => new ValueDto { Status = ValueStatus.Ok, Kind = ValueKind.String, DeclaredType = "System.Object", RuntimeType = "System.String", Scalar = new JsonStringNode(value) };

    private static StylingSetter Setter(int index) => new StylingSetter { Property = "P" + index, Owner = "O", Kind = "value", Value = Text("v") };

    [Fact]
    public void ParamsRoundTripAndRejectPaging()
    {
        var parameters = StylingParams.FromJson(Parse("{\"sessionId\":\"s\",\"objectId\":\"o\",\"generation\":2}"));
        Assert.Equal("o", parameters.ObjectId);
        Assert.Equal(2, parameters.Generation);
        Assert.Equal(PipeMethods.Styling, "members.styling");
        Assert.Throws<ProtocolException>(() => StylingParams.FromJson(Parse("{\"sessionId\":\"s\",\"objectId\":\"o\",\"generation\":2,\"pageSize\":5}")));
    }

    [Fact]
    public void FeatureIsAdvertised()
    {
        Assert.Equal("membersStyling", Features.MembersStyling);
        var hello = new HelloResult { AgentVersion = "1", Tfm = "net10.0-windows", Architecture = "x64", RuntimeVersion = "10.0", Process = new ProcessIdentity { Pid = 1, CreationTimeUtc = "2026-01-01T00:00:00.0000000Z" }, Features = new[] { Features.MembersItems, Features.MembersStyling } };
        Assert.Equal(new[] { "membersItems", "membersStyling" }, HelloResult.FromJson(hello.ToJson()).Features);
    }

    [Fact]
    public void ResultRoundTripsEveryPart()
    {
        var trigger = new StylingTrigger { Kind = "dataTrigger", Active = "unknown", Conditions = new[] { new StylingCondition { Binding = "Path=Ready", Value = Text("x"), Active = "unknown" } }, SetterCount = 1, Setters = new[] { Setter(0) } };
        var result = new StylingResult
        {
            Applicable = true,
            Style = new StylingStyle { Source = "local", Key = "K", TargetType = "T", SetterCount = 1, Setters = new[] { Setter(1) }, TriggerCount = 1, Triggers = new[] { trigger }, BasedOn = new[] { new StylingLevel { Key = "B" } } },
            Templates = new StylingTemplates { ControlTemplate = new StylingTemplate { Kind = "controlTemplate", TargetType = "T", Parts = new[] { new StylingPart { Name = "PART_A", Type = "B", Element = Text("e") } } }, TemplatedParent = Text("p") },
            Resources = new StylingResources { Count = 1, Entries = new[] { new StylingResourceEntry { Key = "k", KeyKind = "string", Index = 0 } }, MergedDictionaries = new[] { new StylingMergedDictionary { Source = "a.xaml", Count = 3 } } },
            Application = new StylingResources { Count = 0 },
        };
        byte[] json = StrictJson.Serialize(result.ToJson());
        var copy = StylingResult.FromJson(StrictJson.Parse(json, 0, json.Length));
        Assert.Equal(json, StrictJson.Serialize(copy.ToJson()));
        Assert.Equal("PART_A", copy.Templates!.ControlTemplate!.Parts.Single().Name);
        Assert.Equal("a.xaml", copy.Resources!.MergedDictionaries.Single().Source);
    }

    [Fact]
    public void NotApplicableResultMustBeEmpty()
    {
        Assert.False(StylingResult.FromJson(Parse("{\"applicable\":false}")).Applicable);
        var empty = new JsonObjectNode();
        empty.Add("applicable", new JsonBoolNode(false));
        empty.Add("style", new StylingStyle().ToJson());
        Assert.Throws<ProtocolException>(() => StylingResult.FromJson(empty));
    }

    [Fact]
    public void TruncationFlagsMustMatchTheListedCounts()
    {
        var setters = Enumerable.Range(0, StylingLimits.MaxEntries).Select(Setter).ToList();
        var level = new StylingLevel { SetterCount = 40, SettersTruncated = true, Setters = setters };
        var copy = StylingLevel.FromJson(level.ToJson());
        Assert.True(copy.SettersTruncated);
        Assert.Throws<ProtocolException>(() => StylingLevel.FromJson(new StylingLevel { SetterCount = 40, SettersTruncated = false, Setters = setters }.ToJson()));
        Assert.Throws<ProtocolException>(() => StylingLevel.FromJson(new StylingLevel { SetterCount = 2, SettersTruncated = true, Setters = setters.Take(2).ToList() }.ToJson()));
        Assert.Throws<ProtocolException>(() => StylingLevel.FromJson(new StylingLevel { SetterCount = 40, SettersTruncated = true, Setters = Enumerable.Range(0, 33).Select(Setter).ToList() }.ToJson()));
    }

    [Fact]
    public void BasedOnChainIsCappedAtTheBindingDepth()
    {
        var levels = Enumerable.Range(0, StylingLimits.MaxBasedOn).Select(index => new StylingLevel { Key = "L" + index }).ToList();
        Assert.Equal(ProtocolLimits.MaxBindingDepth, StylingLimits.MaxBasedOn);
        Assert.True(StylingStyle.FromJson(new StylingStyle { BasedOn = levels, BasedOnTruncated = true }.ToJson()).BasedOnTruncated);
        levels.Add(new StylingLevel());
        Assert.Throws<ProtocolException>(() => StylingStyle.FromJson(new StylingStyle { BasedOn = levels }.ToJson()));
        Assert.Throws<ProtocolException>(() => StylingStyle.FromJson(new StylingStyle { BasedOn = levels.Take(2).ToList(), BasedOnTruncated = true }.ToJson()));
    }

    [Fact]
    public void ClosedValuesAreEnforced()
    {
        Assert.Throws<ProtocolException>(() => StylingSetter.FromJson(new StylingSetter { Kind = "staticResource", Property = "p", Owner = "o" }.ToJson()));
        Assert.Throws<ProtocolException>(() => StylingTrigger.FromJson(new StylingTrigger { Active = "maybe" }.ToJson()));
        Assert.Throws<ProtocolException>(() => StylingTemplate.FromJson(new StylingTemplate { Kind = "styleTemplate" }.ToJson()));
        Assert.Throws<ProtocolException>(() => StylingResourceEntry.FromJson(new StylingResourceEntry { KeyKind = "number", Key = "k" }.ToJson()));
        Assert.Throws<ProtocolException>(() => StylingStyle.FromJson(new StylingStyle { Source = "theme" }.ToJson()));
    }

    [Fact]
    public void ResourceEntriesAreCappedAtThePageSize()
    {
        var entries = Enumerable.Range(0, StylingLimits.MaxResources).Select(index => new StylingResourceEntry { Key = "k" + index, KeyKind = "string", Index = index }).ToList();
        Assert.Equal(ProtocolLimits.MaxPageSize, StylingLimits.MaxResources);
        Assert.Equal(StylingLimits.MaxResources, StylingResources.FromJson(new StylingResources { Count = StylingLimits.MaxResources, Entries = entries }.ToJson()).Entries.Count);
        entries.Add(new StylingResourceEntry { Key = "x", KeyKind = "string", Index = entries.Count });
        Assert.Throws<ProtocolException>(() => StylingResources.FromJson(new StylingResources { Count = entries.Count, Entries = entries }.ToJson()));
    }
}
