using System.Collections.Generic;
using WinTestKit.Inspector.Agent.Contracts;

namespace WinTestKit.Inspector.Agent.Inspection
{
    public sealed class WpfInspectionServiceFactory : IInspectionServiceFactory, IWriteInspectionServiceFactory
    {
        public WpfInspectionServiceFactory() { }
        public IInspectionService Create(string sessionId, IReadOnlyList<string> redactNames) =>
            new WpfInspectionService(sessionId, new Members.ObjectInspector(redactNames));
        public IInspectionService Create(string sessionId, IReadOnlyList<string> redactNames, WinTestKit.Inspector.Protocol.WriteAllowlist allowlist) =>
            new WpfInspectionService(sessionId, new Members.ObjectInspector(redactNames), allowlist: allowlist, redactNames: redactNames);
    }
}
