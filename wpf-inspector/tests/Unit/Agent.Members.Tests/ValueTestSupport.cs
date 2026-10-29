using System;
using System.Collections.Generic;
using System.Globalization;
using System.Runtime.CompilerServices;
using System.Runtime.ExceptionServices;
using System.Threading;
using System.Windows;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Contracts;
using WinTestKit.Inspector.Agent.Inspection.Members;
using WinTestKit.Inspector.Protocol;
using Xunit;

namespace WinTestKit.Inspector.Agent.Members.Tests
{
    internal static class ValueTestSupport
    {
        internal static PathSegment Property(string name) => new PathSegment { Kind = SegmentKind.Property, Name = name };
        internal static PathSegment Field(string name) => new PathSegment { Kind = SegmentKind.Field, Name = name };
        internal static PathSegment Dependency(DependencyProperty property) => new PathSegment
        {
            Kind = SegmentKind.Dependency, Name = property.Name,
            OwnerType = property.OwnerType.FullName, OwnerAssembly = property.OwnerType.Assembly.GetName().Name
        };

        internal static ValueDto RoundTrip(ValueDto value)
        {
            byte[] json = StrictJson.Serialize(value.ToJson());
            ValueDto copy = ValueDto.FromJson(StrictJson.Parse(json, 0, json.Length));
            Assert.Equal(json, StrictJson.Serialize(copy.ToJson()));
            return copy;
        }

        internal static void Sta(Action action)
        {
            Exception? error = null;
            var thread = new Thread(() =>
            {
                Dispatcher dispatcher = Dispatcher.CurrentDispatcher;
                try { action(); }
                catch (Exception exception) { error = exception; }
                finally { dispatcher.InvokeShutdown(); }
            });
            thread.SetApartmentState(ApartmentState.STA);
            thread.Start();
            thread.Join();
            if (error != null) ExceptionDispatchInfo.Capture(error).Throw();
        }

        internal sealed class Reader
        {
            private readonly object root;
            internal Reader(object root, params string[] extraNames)
            { this.root = root; Inspector = new ObjectInspector(extraNames); }
            internal ObjectInspector Inspector { get; }
            internal Registry Registry { get; } = new Registry();
            internal ValueDto Read(params PathSegment[] path) => RoundTrip(Inspector.ReadPath(root, path, Registry, Dispatcher.CurrentDispatcher, CancellationToken.None));
        }

        internal sealed class Registry : IObjectRegistry
        {
            private readonly Dictionary<object, ObjectRef> references = new Dictionary<object, ObjectRef>(IdentityComparer.Instance);
            internal int Count => references.Count;
            public ObjectRef Register(object target, Dispatcher traversalDispatcher, TypeInfoDto type)
            {
                if (!references.TryGetValue(target, out ObjectRef? reference))
                {
                    reference = new ObjectRef { SessionId = "values", ObjectId = (references.Count + 1).ToString(CultureInfo.InvariantCulture), Generation = 1, Type = type, DispatcherId = "sta" };
                    references.Add(target, reference);
                }
                return reference;
            }
            public bool TryGet(string objectId, long generation, out object target, out Dispatcher dispatcher)
            { target = null!; dispatcher = null!; return false; }
            public int Release(IEnumerable<string> objectIds) => 0;
        }

        private sealed class IdentityComparer : IEqualityComparer<object>
        {
            internal static readonly IdentityComparer Instance = new IdentityComparer();
            public new bool Equals(object? left, object? right) => ReferenceEquals(left, right);
            public int GetHashCode(object target) => RuntimeHelpers.GetHashCode(target);
        }
    }
}
