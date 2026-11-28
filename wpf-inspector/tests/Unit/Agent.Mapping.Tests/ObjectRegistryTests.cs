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
        public void StrongLeasesDemoteLeastRecentlyUsedAndReuseExpiredSlots()
        {
            DateTime now = DateTime.UtcNow;
            using (var ui = new DispatcherThread())
            using (var registry = Registry(() => now))
            {
                object[] targets = Enumerable.Range(0, 301).Select(_ => new object()).ToArray();
                ObjectRef[] handles = targets.Select(target => registry.Register(target, ui.Dispatcher, new TypeInfoDto())).ToArray();
                for (int index = 0; index < 300; index++)
                {
                    Assert.True(registry.TryGet(handles[index].ObjectId, handles[index].Generation, out _, out _));
                    now = now.AddMilliseconds(1);
                }
                var entries = (System.Collections.IDictionary)typeof(ObjectRegistry).GetField("entries", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!.GetValue(registry)!;
                object oldest = entries[handles[0].ObjectId]!;
                var lease = oldest.GetType().GetField("Lease", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!;
                Assert.Null(lease.GetValue(oldest));
                Assert.True(registry.TryGet(handles[0].ObjectId, handles[0].Generation, out object resolved, out _));
                Assert.Same(targets[0], resolved);
                now = now.AddMilliseconds(ProtocolLimits.LeaseInactivityMs);
                Assert.True(registry.TryGet(handles[300].ObjectId, handles[300].Generation, out _, out _));
                Assert.Null(lease.GetValue(oldest));
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
        public void ReleaseCountsFreedObjectsAndNeverReusesIds()
        {
            using (var ui = new DispatcherThread())
            using (var registry = Registry())
            {
                object target = new object();
                ObjectRef first = registry.Register(target, ui.Dispatcher, new TypeInfoDto());
                Hand(registry, first);
                Assert.True(registry.TryGet(first.ObjectId, first.Generation, out _, out _));
                ReleaseResult result = registry.Release(new[] { Item(first, 1), Item("unknown", 1) });
                Assert.Equal(1, result.ReleasedCount);
                Assert.Equal(1, result.OverReleasedCount);
                Assert.False(registry.TryGet(first.ObjectId, first.Generation, out _, out _));
                ObjectRef next = registry.Register(target, ui.Dispatcher, new TypeInfoDto());
                Assert.NotEqual(first.ObjectId, next.ObjectId);
                Assert.True(next.Generation > first.Generation);
                result = registry.Release(new[] { Item(first, 1) });
                Assert.Equal(0, result.ReleasedCount);
                Assert.Equal(1, result.OverReleasedCount);
            }
        }

        [Fact]
        public void LeaseEndsOnlyWhenEveryHandOutIsReleased()
        {
            using (var ui = new DispatcherThread())
            using (var registry = Registry())
            {
                object target = new object();
                ObjectRef reference = registry.Register(target, ui.Dispatcher, new TypeInfoDto());
                Hand(registry, reference, 3);
                Assert.True(registry.TryGet(reference.ObjectId, reference.Generation, out _, out _));
                ReleaseResult partial = registry.Release(new[] { Item(reference, 2) });
                Assert.Equal(0, partial.ReleasedCount);
                Assert.Equal(0, partial.OverReleasedCount);
                Assert.True(registry.TryGet(reference.ObjectId, reference.Generation, out _, out _));
                ReleaseResult last = registry.Release(new[] { Item(reference, 1) });
                Assert.Equal(1, last.ReleasedCount);
                Assert.Equal(0, last.OverReleasedCount);
                Assert.False(registry.TryGet(reference.ObjectId, reference.Generation, out _, out _));
                GC.KeepAlive(target);
            }
        }

        [Fact]
        public void ReleaseOfTheSameObjectInOneRequestIsSummed()
        {
            using (var ui = new DispatcherThread())
            using (var registry = Registry())
            {
                object target = new object();
                ObjectRef reference = registry.Register(target, ui.Dispatcher, new TypeInfoDto());
                Hand(registry, reference, 3);
                Assert.Equal(0, registry.Release(new[] { Item(reference, 1), Item(reference, 1) }).ReleasedCount);
                Assert.True(registry.TryGet(reference.ObjectId, reference.Generation, out _, out _));
                Assert.Equal(1, registry.Release(new[] { Item(reference, 1) }).ReleasedCount);
                GC.KeepAlive(target);
            }
        }

        [Fact]
        public void OverReleaseIsClampedAndNeverFreesOtherLiveObjects()
        {
            using (var ui = new DispatcherThread())
            using (var registry = Registry())
            {
                object first = new object(), second = new object(), unhanded = new object();
                ObjectRef a = registry.Register(first, ui.Dispatcher, new TypeInfoDto());
                ObjectRef b = registry.Register(second, ui.Dispatcher, new TypeInfoDto());
                ObjectRef c = registry.Register(unhanded, ui.Dispatcher, new TypeInfoDto());
                Hand(registry, a, 1);
                Hand(registry, b, 2);
                ReleaseResult result = registry.Release(new[] { Item(a, 500), Item(b, 1), Item(c, 4) });
                Assert.Equal(1, result.ReleasedCount);
                Assert.Equal(2, result.OverReleasedCount);
                Assert.False(registry.TryGet(a.ObjectId, a.Generation, out _, out _));
                Assert.True(registry.TryGet(b.ObjectId, b.Generation, out _, out _));
                Assert.True(registry.TryGet(c.ObjectId, c.Generation, out _, out _));
                GC.KeepAlive(first); GC.KeepAlive(second); GC.KeepAlive(unhanded);
            }
        }

        [Fact]
        public void LateReleaseDoesNotEndALeaseThatWasHandedOutAgain()
        {
            using (var ui = new DispatcherThread())
            using (var registry = Registry())
            {
                object target = new object();
                ObjectRef reference = registry.Register(target, ui.Dispatcher, new TypeInfoDto());
                Hand(registry, reference);
                Hand(registry, registry.Register(target, ui.Dispatcher, new TypeInfoDto()));
                Assert.Equal(0, registry.Release(new[] { Item(reference, 1) }).ReleasedCount);
                Assert.True(registry.TryGet(reference.ObjectId, reference.Generation, out _, out _));
                GC.KeepAlive(target);
            }
        }

        [Fact]
        public void ReleaseBetweenRegisterAndCountDoesNotFreeTheObject()
        {
            using (var ui = new DispatcherThread())
            using (var registry = Registry())
            {
                object target = new object();
                ObjectRef held = registry.Register(target, ui.Dispatcher, new TypeInfoDto());
                Hand(registry, held);
                // The worst interleaving: a request registers the object, a release for the earlier hand-out then runs,
                // and only afterwards is the request's response counted.
                long ticket = registry.BeginRequest();
                ObjectRef again = registry.Register(target, ui.Dispatcher, new TypeInfoDto());
                Assert.Equal(1, registry.Release(new[] { Item(held, 1) }).ReleasedCount);
                registry.CountHandOuts(new[] { new KeyValuePair<string, long>(again.ObjectId, again.Generation) });
                registry.EndRequest(ticket);
                Assert.True(registry.TryGet(again.ObjectId, again.Generation, out object found, out _));
                Assert.Same(target, found);
                Assert.Equal(1, registry.Release(new[] { Item(again, 1) }).ReleasedCount);
                Assert.False(registry.TryGet(again.ObjectId, again.Generation, out _, out _));
            }
        }

        [Fact]
        public void ObjectKeptByARequestIsRemovedWhenItsResponseDoesNotHandItOut()
        {
            using (var ui = new DispatcherThread())
            using (var registry = Registry())
            {
                object target = new object();
                ObjectRef held = registry.Register(target, ui.Dispatcher, new TypeInfoDto());
                Hand(registry, held);
                long ticket = registry.BeginRequest();
                registry.Register(target, ui.Dispatcher, new TypeInfoDto());
                registry.Release(new[] { Item(held, 1) });
                Assert.True(registry.TryGet(held.ObjectId, held.Generation, out _, out _));
                registry.EndRequest(ticket);
                Assert.False(registry.TryGet(held.ObjectId, held.Generation, out _, out _));
                GC.KeepAlive(target);
            }
        }

        [Fact]
        public async Task ConcurrentHandOutAndReleaseNeverLeaveAHandedOutObjectStale()
        {
            using (var ui = new DispatcherThread())
            using (var registry = Registry())
            {
                for (int round = 0; round < 500; round++)
                {
                    object target = new object();
                    ObjectRef held = registry.Register(target, ui.Dispatcher, new TypeInfoDto());
                    Hand(registry, held);
                    ObjectRef handedOut = null!;
                    using (var start = new System.Threading.ManualResetEventSlim())
                    {
                        var request = Task.Run(() =>
                        {
                            start.Wait();
                            long ticket = registry.BeginRequest();
                            handedOut = registry.Register(target, ui.Dispatcher, new TypeInfoDto());
                            registry.CountHandOuts(new[] { new KeyValuePair<string, long>(handedOut.ObjectId, handedOut.Generation) });
                            registry.EndRequest(ticket);
                        });
                        var release = Task.Run(() =>
                        {
                            start.Wait();
                            long ticket = registry.BeginRequest();
                            registry.Release(new[] { Item(held, 1) });
                            registry.EndRequest(ticket);
                        });
                        start.Set();
                        await Task.WhenAll(request, release);
                    }
                    Assert.True(registry.TryGet(handedOut.ObjectId, handedOut.Generation, out object found, out _), "round " + round);
                    Assert.Same(target, found);
                    registry.Release(new[] { Item(handedOut, 1) });
                    GC.KeepAlive(target);
                }
            }
        }

        [Fact]
        public void ZeroCountEntriesAreRemovedOnceNoRequestCouldHaveHandedThemOut()
        {
            using (var ui = new DispatcherThread())
            using (var registry = Registry())
            {
                object target = new object();
                long first = registry.BeginRequest();
                ObjectRef reference = registry.Register(target, ui.Dispatcher, new TypeInfoDto());
                registry.CountHandOuts(new[] { new KeyValuePair<string, long>(reference.ObjectId, reference.Generation) });
                long second = registry.BeginRequest();
                registry.Release(new[] { Item(reference, 1) });
                Assert.True(registry.TryGet(reference.ObjectId, reference.Generation, out _, out _));
                registry.EndRequest(second);
                Assert.True(registry.TryGet(reference.ObjectId, reference.Generation, out _, out _));
                registry.EndRequest(first);
                Assert.False(registry.TryGet(reference.ObjectId, reference.Generation, out _, out _));
                GC.KeepAlive(target);
            }
        }

        [Fact]
        public void CountingIgnoresUnknownIdsAndWrongGenerations()
        {
            using (var ui = new DispatcherThread())
            using (var registry = Registry())
            {
                object target = new object();
                ObjectRef reference = registry.Register(target, ui.Dispatcher, new TypeInfoDto());
                registry.CountHandOuts(new[] { new KeyValuePair<string, long>("unknown", 1), new KeyValuePair<string, long>(reference.ObjectId, reference.Generation + 1) });
                Assert.Equal(1, registry.Release(new[] { Item(reference, 1) }).OverReleasedCount);
                Assert.True(registry.TryGet(reference.ObjectId, reference.Generation, out _, out _));
                GC.KeepAlive(target);
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
                Assert.Throws<ObjectDisposedException>(() => registry.Release(new[] { Item("unknown", 1) }));
            }
        }

        private static ObjectRegistry Registry(Func<DateTime>? now = null) =>
            new ObjectRegistry(Guid.NewGuid().ToString(), new DispatcherExecutor(), now ?? (() => DateTime.UtcNow));

        [MethodImpl(MethodImplOptions.NoInlining)]
        private static ReleaseItem Item(ObjectRef reference, int count) => Item(reference.ObjectId, count);
        private static ReleaseItem Item(string objectId, int count) => new ReleaseItem { ObjectId = objectId, Count = count };
        private static void Hand(ObjectRegistry registry, ObjectRef reference, int times = 1) =>
            registry.CountHandOuts(Enumerable.Repeat(new KeyValuePair<string, long>(reference.ObjectId, reference.Generation), times).ToArray());

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
