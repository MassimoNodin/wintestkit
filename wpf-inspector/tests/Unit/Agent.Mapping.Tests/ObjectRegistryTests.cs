using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Inspection;
using WinTestKit.Inspector.Protocol;
using Xunit;

namespace WinTestKit.Inspector.Agent.Mapping.Tests
{
    [Trait("Category", "Unit")]
    [Collection("WPF dispatchers")]
    public sealed class ObjectRegistryTests
    {
        private sealed class HostileIdentity
        {
            public override bool Equals(object? other) => throw new InvalidOperationException("Target Equals called.");
            public override int GetHashCode() => throw new InvalidOperationException("Target GetHashCode called.");
            public override string ToString() => throw new InvalidOperationException("Target ToString called.");
        }

        [Fact]
        public void UsesOnlyReferenceIdentityAndSessionCounterGeneration()
        {
            using (var ui = new DispatcherThread())
            using (var registry = Registry())
            {
                var target = new HostileIdentity();
                ObjectRef first = registry.Register(target, ui.Dispatcher, new TypeInfoDto());
                Assert.Same(first, registry.Register(target, ui.Dispatcher, new TypeInfoDto()));
                ObjectRef second = registry.Register(new HostileIdentity(), ui.Dispatcher, new TypeInfoDto());
                Assert.NotEqual(first.ObjectId, second.ObjectId);
                Assert.True(second.Generation > first.Generation);
                Assert.StartsWith(first.SessionId + ":", first.ObjectId);
                Assert.EndsWith(":" + first.Generation, first.ObjectId);
                Assert.True(registry.TryGet(first.ObjectId, first.Generation, out object found, out Dispatcher dispatcher));
                Assert.Same(target, found);
                Assert.Same(ui.Dispatcher, dispatcher);
            }
        }

        [Fact]
        public async Task DispatcherObjectsUseTheirOwnerAndPlainObjectsUseTraversalDispatcher()
        {
            using (var ui = new DispatcherThread())
            using (var other = new DispatcherThread())
            {
                var executor = new DispatcherExecutor();
                using (var registry = new ObjectRegistry(Guid.NewGuid().ToString(), executor))
                {
                    object dependency = await ui.Dispatcher.InvokeAsync(() => new DependencyObject()).Task;
                    ObjectRef owned = registry.Register(dependency, other.Dispatcher, new TypeInfoDto());
                    ObjectRef plain = registry.Register(new object(), other.Dispatcher, new TypeInfoDto());
                    Assert.Equal(executor.GetDispatcherId(ui.Dispatcher), owned.DispatcherId);
                    Assert.Equal(executor.GetDispatcherId(other.Dispatcher), plain.DispatcherId);
                }
            }
        }

        [Fact]
        public void UnleasedObjectsAreWeakAndCollectedHandlesAreStale()
        {
            using (var ui = new DispatcherThread())
            using (var registry = Registry())
            {
                ObjectRef reference = RegisterEphemeral(registry, ui.Dispatcher, false, out WeakReference weak);
                Collect();
                Assert.False(weak.IsAlive);
                Assert.False(registry.TryGet(reference.ObjectId, reference.Generation, out _, out _));
            }
        }

        [Fact]
        public void ActiveLeaseKeepsTargetAliveUntilInactivityExpiry()
        {
            DateTime now = DateTime.UtcNow;
            using (var ui = new DispatcherThread())
            using (var registry = Registry(() => now))
            {
                ObjectRef reference = RegisterEphemeral(registry, ui.Dispatcher, true, out WeakReference weak);
                Collect();
                Assert.True(weak.IsAlive);
                now = now.AddMilliseconds(ProtocolLimits.LeaseInactivityMs);
                registry.Register(new object(), ui.Dispatcher, new TypeInfoDto());
                Collect();
                Assert.False(weak.IsAlive);
                Assert.False(registry.TryGet(reference.ObjectId, reference.Generation, out _, out _));
            }
        }

        [Fact]
        public void StrongLeaseLimitAndRefreshUseInjectedClock()
        {
            DateTime now = DateTime.UtcNow;
            using (var ui = new DispatcherThread())
            using (var registry = Registry(() => now))
            {
                object[] targets = Enumerable.Range(0, ProtocolLimits.MaxStrongHandles + 1).Select(_ => new object()).ToArray();
                ObjectRef[] handles = targets.Select(target => registry.Register(target, ui.Dispatcher, new TypeInfoDto())).ToArray();
                for (int index = 0; index < ProtocolLimits.MaxStrongHandles; index++)
                    Assert.True(registry.TryGet(handles[index].ObjectId, handles[index].Generation, out _, out _));
                ObjectRef overflow = handles[handles.Length - 1];
                Assert.Equal(ErrorCodes.LimitExceeded, Assert.Throws<ProtocolException>(() => registry.TryGet(overflow.ObjectId, overflow.Generation, out _, out _)).Code);
                now = now.AddMilliseconds(ProtocolLimits.LeaseInactivityMs - 1);
                Assert.True(registry.TryGet(handles[0].ObjectId, handles[0].Generation, out _, out _));
                now = now.AddMilliseconds(1);
                Assert.True(registry.TryGet(overflow.ObjectId, overflow.Generation, out _, out _));
                GC.KeepAlive(targets);
            }
        }

        [Fact]
        public void WeakEntryLimitRejectsButPrunesDeadEntriesFirst()
        {
            using (var ui = new DispatcherThread())
            using (var registry = Registry())
            {
                var targets = new List<object>();
                FillRegistry(registry, ui.Dispatcher, targets);
                Assert.Equal(ErrorCodes.LimitExceeded,
                    Assert.Throws<ProtocolException>(() => registry.Register(new object(), ui.Dispatcher, new TypeInfoDto())).Code);
                targets.Clear();
                Collect();
                Assert.NotNull(registry.Register(new object(), ui.Dispatcher, new TypeInfoDto()));
            }
        }

        [Fact]
        public void ReleaseCountsDistinctKnownHandlesAndNeverReusesIds()
        {
            using (var ui = new DispatcherThread())
            using (var registry = Registry())
            {
                object target = new object();
                ObjectRef first = registry.Register(target, ui.Dispatcher, new TypeInfoDto());
                Assert.True(registry.TryGet(first.ObjectId, first.Generation, out _, out _));
                Assert.Equal(1, registry.Release(new[] { first.ObjectId, first.ObjectId, "unknown" }));
                Assert.False(registry.TryGet(first.ObjectId, first.Generation, out _, out _));
                ObjectRef next = registry.Register(target, ui.Dispatcher, new TypeInfoDto());
                Assert.NotEqual(first.ObjectId, next.ObjectId);
                Assert.True(next.Generation > first.Generation);
                Assert.Equal(0, registry.Release(new[] { first.ObjectId }));
            }
        }

        [Fact]
        public void WrongGenerationUnknownAndOtherSessionAreStale()
        {
            using (var ui = new DispatcherThread())
            using (var registry = Registry())
            using (var other = Registry())
            {
                object target = new object();
                ObjectRef reference = registry.Register(target, ui.Dispatcher, new TypeInfoDto());
                Assert.False(registry.TryGet(reference.ObjectId, reference.Generation + 1, out _, out _));
                Assert.False(registry.TryGet("unknown", reference.Generation, out _, out _));
                Assert.False(other.TryGet(reference.ObjectId, reference.Generation, out _, out _));
                GC.KeepAlive(target);
            }
        }

        [Fact]
        public void ConcurrentRegistrationReturnsOneHandle()
        {
            using (var ui = new DispatcherThread())
            using (var registry = Registry())
            {
                object target = new HostileIdentity();
                var handles = new ObjectRef[100];
                Parallel.For(0, handles.Length, index => handles[index] = registry.Register(target, ui.Dispatcher, new TypeInfoDto()));
                Assert.All(handles, handle => Assert.Same(handles[0], handle));
            }
        }

        [Fact]
        public void DisposeDropsLeasesAndRejectsFurtherUse()
        {
            using (var ui = new DispatcherThread())
            {
                var registry = Registry();
                RegisterEphemeral(registry, ui.Dispatcher, true, out WeakReference weak);
                registry.Dispose();
                registry.Dispose();
                Collect();
                Assert.False(weak.IsAlive);
                Assert.Throws<ObjectDisposedException>(() => registry.Register(new object(), ui.Dispatcher, new TypeInfoDto()));
                Assert.Throws<ObjectDisposedException>(() => registry.TryGet("unknown", 1, out _, out _));
                Assert.Throws<ObjectDisposedException>(() => registry.Release(new[] { "unknown" }));
            }
        }

        private static ObjectRegistry Registry(Func<DateTime>? now = null) =>
            new ObjectRegistry(Guid.NewGuid().ToString(), new DispatcherExecutor(), now ?? (() => DateTime.UtcNow));

        [MethodImpl(MethodImplOptions.NoInlining)]
        private static ObjectRef RegisterEphemeral(ObjectRegistry registry, Dispatcher dispatcher, bool lease, out WeakReference weak)
        {
            object target = new object();
            weak = new WeakReference(target);
            ObjectRef reference = registry.Register(target, dispatcher, new TypeInfoDto());
            if (lease) Assert.True(registry.TryGet(reference.ObjectId, reference.Generation, out _, out _));
            return reference;
        }

        [MethodImpl(MethodImplOptions.NoInlining)]
        private static void FillRegistry(ObjectRegistry registry, Dispatcher dispatcher, List<object> targets)
        {
            for (int index = 0; index < ProtocolLimits.MaxWeakEntries; index++)
            {
                object target = new object();
                targets.Add(target);
                registry.Register(target, dispatcher, new TypeInfoDto());
            }
        }

        private static void Collect() { GC.Collect(); GC.WaitForPendingFinalizers(); GC.Collect(); }
    }
}
