using System;
using System.Threading;
using System.Windows;
using WinTestKit.Inspector.Agent.Inspection.Members;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Query
{
    /// <summary>Per-request evaluation state shared by the predicates of one query pass.</summary>
    internal sealed class QueryPredicateContext : IDisposable
    {
        private CancellationTokenSource? cancellation;
        private object? lastTarget;
        private bool lastProtected;
        internal QueryPredicateContext(DateTime deadline) { Deadline = deadline; }
        internal DateTime Deadline { get; }
        internal TimeSpan Remaining => Deadline - DateTime.UtcNow;

        /// <summary>A token that cancels when the request budget elapses; created once per request instead of once per element.</summary>
        internal CancellationToken Token
        {
            get
            {
                if (cancellation == null)
                {
                    cancellation = new CancellationTokenSource();
                    cancellation.CancelAfter(Remaining > TimeSpan.Zero ? Remaining : TimeSpan.Zero);
                }
                return cancellation.Token;
            }
        }

        /// <summary>Protection of the element being evaluated, computed once however many predicates inspect it.</summary>
        internal bool IsProtected(object target)
        {
            if (!ReferenceEquals(target, lastTarget))
            {
                lastProtected = RedactionPolicy.IsProtectedIdentity(target);
                lastTarget = target;
            }
            return lastProtected;
        }

        public void Dispose() { cancellation?.Dispose(); cancellation = null; lastTarget = null; }
    }

    internal interface IQueryPredicate
    {
        bool Matches(DependencyObject target, QueryPredicateContext context);
        /// <summary>Relative evaluation cost; cheaper predicates run first so expensive reads see fewer elements.</summary>
        int Cost { get; }
    }

    internal static class PredicateFactory
    {
        internal static IQueryPredicate Create(Predicate predicate, Inspection.Members.ObjectInspector inspector, Inspection.ObjectRegistry registry)
        {
            if (predicate.Kind == "assignableTo") return new AssignablePredicate(predicate.FullName!);
            if (predicate.Kind == "equals" || predicate.Kind == "equalsText" || predicate.Kind == "regex")
                return new ValuePredicate(predicate, inspector, registry);
            throw new ProtocolException(ErrorCodes.InvalidParams, "Unknown predicate kind.");
        }

        private sealed class AssignablePredicate : IQueryPredicate
        {
            private readonly string fullName;
            internal AssignablePredicate(string fullName) { this.fullName = fullName; }
            public int Cost => 0;
            public bool Matches(DependencyObject target, QueryPredicateContext context)
            {
                Type type = target.GetType();
                for (Type? current = type; current != null; current = current.BaseType)
                    if (current.FullName == fullName) return true;
                foreach (Type implemented in type.GetInterfaces())
                    if (implemented.FullName == fullName) return true;
                return false;
            }
        }
    }
}
