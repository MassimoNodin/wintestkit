using WinTestKit.Inspector.Protocol;
using Xunit;

namespace Protocol.Tests;

public class EventDtoTests
{
    [Fact]
    public void NotificationRoundTripsAndRejectsOverflowHandle()
    {
        var notification = new EventsNotification { Params = new EventsEventParams { SubscriptionId = "s", Sequence = 1, Kind = EventKind.Overflow } };
        Assert.Equal(1, EventsNotification.FromJson(notification.ToJson()).Params.Sequence);
        notification.Params.Handle = new ObjectRef { SessionId = "s", ObjectId = "o", Generation = 1, DispatcherId = "d" };
        Assert.Throws<ProtocolException>(() => notification.ToJson());
    }
    [Fact]
    public void SubscriptionRejectsDuplicatesBoundsAndUnknownFields()
    {
        Assert.Throws<ProtocolException>(() => new EventsSubscribeParams().ToJson());
        Assert.Throws<ProtocolException>(() => new EventsSubscribeParams { Kinds = new[] { EventKind.TreeChanged, EventKind.TreeChanged } }.ToJson());
        var obj = new EventsSubscription { SubscriptionId = "s" }.ToJson(); obj.Add("extra", new JsonBoolNode(true));
        Assert.Throws<ProtocolException>(() => EventsSubscription.FromJson(obj));
        Assert.Throws<ProtocolException>(() => new EventsEventParams { SubscriptionId = "s", Sequence = 0, Kind = EventKind.TreeChanged }.ToJson());
    }
}
