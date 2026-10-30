using System;
using System.Windows;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Query
{
    internal sealed class QueryPredicateContext
    {
        internal QueryPredicateContext(DateTime deadline) { Deadline = deadline; }
        internal DateTime Deadline { get; }
        internal TimeSpan Remaining => Deadline - DateTime.UtcNow;
    }

    internal interface IQueryPredicate
    {
        bool Matches(DependencyObject target, QueryPredicateContext context);
    }

    internal static class PredicateFactory
    {
        internal static IQueryPredicate Create(Predicate predicate, Inspection.Members.ObjectInspector inspector, Inspection.ObjectRegistry registry)
        {
            if (predicate.Kind == "assignableTo") return new AssignablePredicate(predicate.FullName!);
            if (predicate.Kind == "equals" || predicate.Kind == "regex")
                return new ValuePredicate(predicate, inspector, registry);
            throw new ProtocolException(ErrorCodes.InvalidParams, "Unknown predicate kind.");
        }

        private sealed class AssignablePredicate : IQueryPredicate
        {
            private readonly string fullName;
            internal AssignablePredicate(string fullName) { this.fullName = fullName; }
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
