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
        /// <summary>
        /// Gives back hand-outs. An object's lease (strong reference and weak entry) ends only when every hand-out of it
        /// has been released; releasing more than are outstanding is clamped and reported, never freeing a live object.
        /// </summary>
        ReleaseResult Release(IReadOnlyList<ReleaseItem> items);
    }

    /// <summary>
    /// Counts how often each object ID is handed out, so a release (which carries a count) cannot end a lease that a
    /// later response, possibly on another request, handed out again. Implemented by the object registry's owner.
    /// </summary>
    public interface IHandOutLedger
    {
        /// <summary>
        /// Marks the start of a request; call <see cref="EndRequest"/> after its response has been counted. While a request
        /// is in progress an object it registered cannot be freed by a release, because the response that hands it out
        /// has not been counted yet.
        /// </summary>
        long BeginRequest();
        void EndRequest(long token);
        /// <summary>Counts handles that are about to be sent to the client, once per occurrence. Call before sending.</summary>
        void CountHandOuts(IReadOnlyList<KeyValuePair<string, long>> handles);
    }

    /// <summary>Member discovery and value reading owned by S4b. Every call runs on the object's Dispatcher thread.</summary>
    public interface IObjectInspector
    {
        TypeInfoDto DescribeType(Type type);
        /// <summary>Complete, sorted catalog. Never evaluates getters. Adds diagnostics for partial failures.</summary>
        IReadOnlyList<MemberInfo> GetMembers(object target, List<Diagnostic> diagnostics);
        ValueDto ReadPath(object root, IReadOnlyList<PathSegment> path, IObjectRegistry registry, Dispatcher dispatcher, CancellationToken ct);
        IReadOnlyList<BindingInfoDto> GetBindings(object target, IReadOnlyList<string> memberKeys, IObjectRegistry registry, Dispatcher dispatcher);
    }
}
