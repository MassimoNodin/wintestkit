using System.Collections.Generic;
using WinTestKit.Inspector.Agent.Contracts;

namespace WinTestKit.Inspector.Agent.Inspection
{
    public sealed class WpfInspectionServiceFactory : IInspectionServiceFactory
    {
        public WpfInspectionServiceFactory() { }
        public IInspectionService Create(string sessionId, IReadOnlyList<string> redactNames) =>
            new WpfInspectionService(sessionId, new Members.ObjectInspector(redactNames));
    }
}
