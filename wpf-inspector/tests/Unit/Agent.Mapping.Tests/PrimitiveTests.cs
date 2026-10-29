using System;
using System.Collections.Generic;
using WinTestKit.Inspector.Agent.Inspection;
using WinTestKit.Inspector.Protocol;
using Xunit;

namespace WinTestKit.Inspector.Agent.Mapping.Tests
{
    [Trait("Category", "Unit")]
    [Collection("WPF dispatchers")]
    public class PrimitiveTests
    {
        [Fact]
        public void SnapshotIsSortedFrozenAndUrlSafe()
        {
            using (var store = new PageSnapshotStore())
            {
                var input = new[] { 3, 1, 2 };
                string token = store.Create("object", 1, "members", "visual", input);
                Assert.Matches("^[A-Za-z0-9_-]{43}$", token);
                input[0] = 99;
                IReadOnlyList<int> snapshot = store.Get<int>(token, "object", 1, "members", "visual");
                Assert.Equal(new[] { 1, 2, 3 }, snapshot);
                Assert.Throws<NotSupportedException>(() => ((IList<int>)snapshot)[0] = 99);
                Assert.NotEqual(token, store.Create("object", 1, "members", "visual", input));
            }
        }

        [Theory]
        [InlineData("other", 1, "members", "visual")]
        [InlineData("object", 2, "members", "visual")]
        [InlineData("object", 1, "children", "visual")]
        [InlineData("object", 1, "members", "logical")]
        public void SnapshotBindsEveryDimension(string objectId, long generation, string operation, string tree)
        {
            using (var store = new PageSnapshotStore())
            {
                string token = store.Create("object", 1, "members", "visual", new[] { 1 });
                Assert.Equal(ErrorCodes.InvalidPageToken, Assert.Throws<ProtocolException>(() =>
                    store.Get<int>(token, objectId, generation, operation, tree)).Code);
            }
        }

        [Fact]
        public void InvalidTypeUnknownTokenAndDifferentStoreAreInvalid()
        {
            using (var store = new PageSnapshotStore())
            using (var other = new PageSnapshotStore())
            {
                string token = store.Create("binding", new[] { 1 });
                Assert.Equal(ErrorCodes.InvalidPageToken, Assert.Throws<ProtocolException>(() => store.Get<string>(token, "binding")).Code);
                Assert.Equal(ErrorCodes.InvalidPageToken, Assert.Throws<ProtocolException>(() => store.Get<int>("unknown", "binding")).Code);
                Assert.Equal(ErrorCodes.InvalidPageToken, Assert.Throws<ProtocolException>(() => other.Get<int>(token, "binding")).Code);
                store.Remove(token);
                Assert.Equal(ErrorCodes.InvalidPageToken, Assert.Throws<ProtocolException>(() => store.Get<int>(token, "binding")).Code);
            }
        }

        [Fact]
        public void ExpiryReclaimsCapacityAndDisposeRejectsUse()
        {
            DateTime now = DateTime.UtcNow;
            var store = new PageSnapshotStore(() => now);
            for (int index = 0; index < ProtocolLimits.MaxSnapshots; index++) store.Create("binding", new[] { index });
            now = now.AddMilliseconds(ProtocolLimits.PageTokenTtlMs);
            Assert.NotNull(store.Create("binding", new[] { 0 }));
            store.Dispose();
            store.Dispose();
            Assert.Throws<ObjectDisposedException>(() => store.Create("binding", new[] { 0 }));
            Assert.Throws<ObjectDisposedException>(() => store.Get<int>("unknown", "binding"));
        }

        [Fact]
        public void SnapshotIsBoundAndExpires()
        {
            DateTime time = DateTime.UtcNow;
            using (var store = new PageSnapshotStore(() => time))
            {
                string token = store.Create("object:1:members", new[] { 1, 2 });
                Assert.Equal(new[] { 1, 2 }, store.Get<int>(token, "object:1:members"));
                Assert.Equal(ErrorCodes.InvalidPageToken, Assert.Throws<ProtocolException>(() => store.Get<int>(token, "object:2:members")).Code);
                time = time.AddMilliseconds(ProtocolLimits.PageTokenTtlMs);
                Assert.Equal(ErrorCodes.InvalidPageToken, Assert.Throws<ProtocolException>(() => store.Get<int>(token, "object:1:members")).Code);
            }
        }

        [Fact]
        public void SnapshotLimitRejectsInsteadOfEvicting()
        {
            using (var store = new PageSnapshotStore())
            {
                string first = store.Create("roots", new[] { 42 });
                for (int i = 1; i < ProtocolLimits.MaxSnapshots; i++) store.Create("roots", new[] { i });
                Assert.Equal(ErrorCodes.LimitExceeded, Assert.Throws<ProtocolException>(() => store.Create("roots", new[] { 0 })).Code);
                Assert.Equal(new[] { 42 }, store.Get<int>(first, "roots"));
            }
        }
    }
}
