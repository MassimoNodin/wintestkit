using WinTestKit.Inspector.Protocol;
using Xunit;

namespace Protocol.Tests;

public class ActionDtoTests
{
    private static ObjectRef Handle() => new ObjectRef { SessionId = "s", ObjectId = "o", Generation = 1, DispatcherId = "d", Type = new TypeInfoDto() };

    [Fact]
    public void SharedActionShapesRoundTrip()
    {
        var request = StateGetParams.FromJson(new StateGetParams { Handle = Handle(), TimeoutMs = 2000 }.ToJson());
        Assert.Equal(2000, request.TimeoutMs);
        var result = ActResult.FromJson(new ActResult { Handle = Handle(), Outcome = ActionOutcome.Performed }.ToJson());
        Assert.Equal(ActionOutcome.Performed, result.Outcome);
    }

    [Fact]
    public void SharedActionShapesRejectUnknownFieldsAndInvalidValues()
    {
        var request = new StateGetParams { Handle = Handle(), TimeoutMs = 1 }.ToJson();
        request.Add("unexpected", new JsonBoolNode(true));
        Assert.Throws<ProtocolException>(() => StateGetParams.FromJson(request));
        Assert.Throws<ProtocolException>(() => new StateGetParams { Handle = Handle(), TimeoutMs = 0 }.ToJson());
        Assert.Throws<ProtocolException>(() => new StateGetParams { Handle = Handle(), TimeoutMs = 2001 }.ToJson());
        Assert.Throws<ProtocolException>(() => new ActResult { Handle = Handle(), Outcome = "other" }.ToJson());
    }
}
