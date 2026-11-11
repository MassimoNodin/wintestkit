using WinTestKit.Inspector.Agent.Events;
using WinTestKit.Inspector.Protocol;
using Xunit;

namespace WinTestKit.Inspector.Agent.Events.Tests;

[Trait("Category", "Unit")]
public class SubscriptionStoreTests
{
    [Fact]
    public void SequencesAreIndependentAndUnsubscribeDiscardsPending()
    {
        var store = new SubscriptionStore();
        var first = store.Subscribe(new[] { EventKind.WindowOpened });
        var second = store.Subscribe(new[] { EventKind.WindowOpened });
        store.Publish(EventKind.WindowOpened, null);
        store.Publish(EventKind.WindowOpened, null);
        Assert.True(store.Unsubscribe(first));
        Assert.False(store.Unsubscribe(first));
        var one = store.Take()!;
        var two = store.Take()!;
        Assert.Equal(second, one.SubscriptionId);
        Assert.Equal(1, one.Sequence);
        Assert.Equal(2, two.Sequence);
        Assert.Null(store.Take());
    }

    [Fact]
    public void OverflowDropsPendingAndSuppressesUntilAcknowledged()
    {
        var store = new SubscriptionStore();
        store.Subscribe(new[] { EventKind.TreeChanged });
        for (int i = 0; i < 1025; i++) store.Publish(EventKind.TreeChanged, null);
        var overflow = store.Take()!;
        Assert.Equal(EventKind.Overflow, overflow.Kind);
        Assert.Equal(1026, overflow.Sequence);
        Assert.Null(overflow.Handle);
        store.Publish(EventKind.TreeChanged, null);
        Assert.Null(store.Take());
        store.Delivered(overflow);
        store.Publish(EventKind.TreeChanged, null);
        Assert.Equal(1027, store.Take()!.Sequence);
    }

    [Fact]
    public void RejectsInvalidKinds()
    {
        var store = new SubscriptionStore();
        Assert.Throws<ProtocolException>(() => store.Subscribe(new string[0]));
        Assert.Throws<ProtocolException>(() => store.Subscribe(new[] { EventKind.Overflow }));
        Assert.Throws<ProtocolException>(() => store.Subscribe(new[] { EventKind.WindowOpened, EventKind.WindowOpened }));
    }
}
