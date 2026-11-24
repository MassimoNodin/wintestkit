using System.Text;
using WinTestKit.Inspector.Protocol;
using Xunit;

namespace Protocol.Tests;

[Trait("Category", "Unit")]
public class BindingDetailsTests
{
    private static JsonNode Parse(string json) { var bytes = Encoding.UTF8.GetBytes(json); return StrictJson.Parse(bytes, 0, bytes.Length); }
    private static string Text(JsonNode node) => Encoding.UTF8.GetString(StrictJson.Serialize(node));
    private static ValueDto Handle(string id) => ValueDto.FromJson(Parse("{\"status\":\"ok\",\"kind\":\"object\",\"declaredType\":\"System.Object\",\"runtimeType\":\"App.Source\",\"object\":{\"sessionId\":\"s\",\"objectId\":\"" + id + "\",\"generation\":1,\"type\":{\"name\":\"Source\",\"fullName\":\"App.Source\",\"assemblyName\":\"App\",\"assemblyQualifiedName\":\"App.Source, App\",\"baseTypes\":[]},\"dispatcherId\":\"d\"}}"));
    private static ValueDto Scalar(string text) => ValueDto.FromJson(Parse("{\"status\":\"ok\",\"kind\":\"string\",\"declaredType\":\"System.Object\",\"runtimeType\":\"System.String\",\"scalar\":\"" + text + "\"}"));

    private static BindingInfoDto Full() => new()
    {
        MemberKey = "k", Kind = BindingKind.Binding, Status = "Active", Mode = "TwoWay", UpdateSourceTrigger = "PropertyChanged", Path = "Name",
        StringFormat = "{0:N2}", FallbackValue = Scalar("fb"), TargetNullValue = Scalar("none"), ConverterParameter = Handle("p"), ConverterCulture = "fr-FR", Delay = 250, BindingGroupName = "g", XPath = "item",
        IsAsync = true, NotifyOnSourceUpdated = true, NotifyOnTargetUpdated = false, NotifyOnValidationError = true, ValidatesOnDataErrors = true, ValidatesOnExceptions = false, ValidatesOnNotifyDataErrors = true,
        ValidationRules = new[] { "App.Rule" }, HasUpdateSourceExceptionFilter = true, ActiveChildIndex = 2, DataItem = Handle("d"), ResolvedSource = Handle("r"), ResolvedSourcePropertyName = "Name", HasError = false, HasValidationError = true,
    };

    [Fact] public void DetailsRoundTripThroughJson()
    {
        var info = Full();
        string json = Text(info.ToJson());
        var copy = BindingInfoDto.FromJson(Parse(json));
        Assert.Equal(json, Text(copy.ToJson()));
        Assert.Equal("{0:N2}", copy.StringFormat); Assert.Equal("d", copy.DataItem!.Object!.ObjectId); Assert.Equal("r", copy.ResolvedSource!.Object!.ObjectId); Assert.Equal("p", copy.ConverterParameter!.Object!.ObjectId);
        Assert.Equal(250, copy.Delay); Assert.Equal(2, copy.ActiveChildIndex); Assert.True(copy.HasValidationError); Assert.False(copy.HasError); Assert.False(copy.NotifyOnTargetUpdated); Assert.Equal("App.Rule", Assert.Single(copy.ValidationRules!));
    }

    [Fact] public void AbsentDetailsStayAbsent()
    {
        var copy = BindingInfoDto.FromJson(Parse("{\"memberKey\":\"k\",\"kind\":\"binding\",\"status\":\"Active\",\"mode\":\"OneWay\",\"updateSourceTrigger\":\"Default\"}"));
        Assert.Null(copy.StringFormat); Assert.Null(copy.FallbackValue); Assert.Null(copy.Delay); Assert.Null(copy.IsAsync); Assert.Null(copy.ValidationRules); Assert.Null(copy.DataItem); Assert.Null(copy.HasError);
        Assert.DoesNotContain("dataItem", Text(copy.ToJson()));
    }

    [Fact] public void NestedChildrenCarryTheirOwnDetails()
    {
        var parent = new BindingInfoDto { MemberKey = "k", Kind = BindingKind.MultiBinding, Status = "Active", Mode = "Default", UpdateSourceTrigger = "Default", ConverterParameter = Scalar("-"), Children = new[] { Full(), Full() } };
        var copy = BindingInfoDto.FromJson(Parse(Text(parent.ToJson())));
        Assert.Equal(2, copy.Children!.Count); Assert.Equal("d", copy.Children[1].DataItem!.Object!.ObjectId); Assert.Equal("-", ((JsonStringNode)copy.ConverterParameter!.Scalar!).Value);
    }

    [Theory]
    [InlineData("\"delay\":-1")]
    [InlineData("\"delay\":1.5")]
    [InlineData("\"hasError\":\"yes\"")]
    [InlineData("\"isAsync\":1")]
    [InlineData("\"activeChildIndex\":32")]
    [InlineData("\"validationRules\":[1]")]
    [InlineData("\"fallbackValue\":{\"status\":\"ok\"}")]
    [InlineData("\"dataItem\":\"object\"")]
    [InlineData("\"stringFormat\":5")]
    [InlineData("\"unknownDetail\":true")]
    public void InvalidDetailsAreRejected(string member) =>
        Assert.Throws<ProtocolException>(() => BindingInfoDto.FromJson(Parse("{\"memberKey\":\"k\",\"kind\":\"binding\",\"status\":\"Active\",\"mode\":\"OneWay\",\"updateSourceTrigger\":\"Default\"," + member + "}")));

    [Fact] public void OversizedTextAndRuleListsAreRejected()
    {
        var info = Full(); info.StringFormat = new string('x', 1025);
        Assert.Throws<ProtocolException>(() => info.ToJson());
        info = Full(); var rules = new string[33]; for (int i = 0; i < rules.Length; i++) rules[i] = "R" + i; info.ValidationRules = rules;
        Assert.Throws<ProtocolException>(() => info.ToJson());
        info = Full(); info.Delay = -5;
        Assert.Throws<ProtocolException>(() => info.ToJson());
    }
}
