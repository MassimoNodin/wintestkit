using System;
using System.Collections.Generic;
using System.Threading;
using System.Windows.Threading;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Contracts
{
    /// <summary>Handle registry owned by S4a. Thread-safe.</summary>
    public interface IObjectRegistry
    {
        /// <summary>Returns the existing handle for the same reference, or registers a new one.</summary>
        ObjectRef Register(object target, Dispatcher traversalDispatcher, TypeInfoDto type);
        /// <summary>False means objectStale (unknown, released, collected, or wrong generation).</summary>
        bool TryGet(string objectId, long generation, out object target, out Dispatcher dispatcher);
        int Release(IEnumerable<string> objectIds);
    }

    /// <summary>Member discovery and value reading owned by S4b. Every call runs on the object's Dispatcher thread.</summary>
    public interface IObjectInspector
    {
        TypeInfoDto DescribeType(Type type);
        /// <summary>Complete, sorted catalog. Never evaluates getters. Adds diagnostics for partial failures.</summary>
        IReadOnlyList<MemberInfo> GetMembers(object target, List<Diagnostic> diagnostics);
        ValueDto ReadPath(object root, IReadOnlyList<PathSegment> path, IObjectRegistry registry, Dispatcher dispatcher, CancellationToken ct);
        IReadOnlyList<BindingInfoDto> GetBindings(object target, IReadOnlyList<string> memberKeys);
    }
}
