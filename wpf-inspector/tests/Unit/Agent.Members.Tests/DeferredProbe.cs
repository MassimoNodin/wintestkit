using System.Threading;

namespace WinTestKit.Inspector.Agent.Members.Tests
{
    /// <summary>A resource whose creation can be counted: a dictionary loaded from compiled XAML creates it only when it is looked up.</summary>
    public sealed class DeferredProbe
    {
        private static int created;
        public DeferredProbe() { Interlocked.Increment(ref created); }
        public static int Created => Volatile.Read(ref created);
        public string Label { get; set; } = "";
    }
}
