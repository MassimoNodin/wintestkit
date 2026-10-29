using System.Threading;
using System.Threading.Tasks;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Session
{
    public interface ISessionRequestHandler
    {
        Task<ResponseEnvelope> HandleAsync(RequestEnvelope request, CancellationToken ct);
    }

}
