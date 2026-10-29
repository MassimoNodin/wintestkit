using System;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using WinTestKit.Inspector.Agent.Contracts;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Session
{
    public interface IRequestScheduler
    {
        Task<JsonNode> ExecuteAsync(RequestEnvelope request, Func<CancellationToken, Task<JsonNode>> operation, CancellationToken ct);
    }

    public sealed class PassThroughRequestScheduler : IRequestScheduler
    {
        public Task<JsonNode> ExecuteAsync(RequestEnvelope request, Func<CancellationToken, Task<JsonNode>> operation, CancellationToken ct) => operation(ct);
    }

    public sealed class RequestDispatcher : ISessionRequestHandler
    {
        private readonly string sessionId;
        private readonly IInspectionService service;
        private readonly IRequestScheduler scheduler;

        public RequestDispatcher(string sessionId, IInspectionService service, IRequestScheduler? scheduler = null)
        {
            this.sessionId = sessionId;
            this.service = service;
            this.scheduler = scheduler ?? new RequestScheduler(ProtocolLimits.RequestTimeoutMs);
        }

        public async Task<ResponseEnvelope> HandleAsync(RequestEnvelope request, CancellationToken ct)
        {
            try
            {
                JsonNode result;
                if (request.Method == PipeMethods.Cancel && scheduler is RequestScheduler concrete)
                    result = new CancelResult { Accepted = concrete.Cancel(CancelParams.FromJson(request.Params).RequestId) }.ToJson();
                else if (request.Method == PipeMethods.Close)
                    result = await RouteAsync(request, ct).ConfigureAwait(false);
                else
                    result = await scheduler.ExecuteAsync(request, token => RouteAsync(request, token), ct).ConfigureAwait(false);
                return new ResponseEnvelope { Id = request.Id, Result = result };
            }
            catch (ProtocolException error)
            {
                return new ResponseEnvelope { Id = request.Id, Error = new ErrorInfo { Code = error.Code, Message = "Request failed." } };
            }
            catch (Exception)
            {
                return new ResponseEnvelope { Id = request.Id, Error = new ErrorInfo { Code = ErrorCodes.InternalError, Message = "Request failed." } };
            }
        }

        private void CheckSession(string value)
        {
            if (!string.Equals(value, sessionId, StringComparison.Ordinal)) throw new ProtocolException(ErrorCodes.SessionStale, "Invalid session.");
        }

        private async Task<JsonNode> RouteAsync(RequestEnvelope request, CancellationToken ct)
        {
            switch (request.Method)
            {
                case PipeMethods.Resolve:
                    var resolve = ResolveParams.FromJson(request.Params);
                    return (await service.ResolveAsync(resolve.RuntimeId.ToArray(), resolve.NativeWindowHandle, ct).ConfigureAwait(false)).ToJson();
                case PipeMethods.ReadBatch:
                    var batch = ReadBatchParams.FromJson(request.Params);
                    return (await service.ReadBatchAsync(batch.Candidates.Select(candidate => new CandidateRequest(candidate.RuntimeId.ToArray(), candidate.NativeWindowHandle)).ToArray(), batch.Paths, ct).ConfigureAwait(false)).ToJson();
                case PipeMethods.Roots:
                    var roots = RootsParams.FromJson(request.Params); CheckSession(roots.SessionId);
                    return (await service.RootsAsync(roots.PageSize, roots.PageToken, ct).ConfigureAwait(false)).ToJson();
                case PipeMethods.Children:
                    var children = ChildrenParams.FromJson(request.Params); CheckSession(children.SessionId);
                    return (await service.ChildrenAsync(children.ObjectId, children.Generation, children.Tree, children.PageSize, children.PageToken, ct).ConfigureAwait(false)).ToJson();
                case PipeMethods.Members:
                    var members = MembersParams.FromJson(request.Params); CheckSession(members.SessionId);
                    return (await service.MembersAsync(members.ObjectId, members.Generation, members.PageSize, members.PageToken, ct).ConfigureAwait(false)).ToJson();
                case PipeMethods.Read:
                    var read = ReadParams.FromJson(request.Params); CheckSession(read.SessionId);
                    return (await service.ReadAsync(read.ObjectId, read.Generation, read.Paths, ct).ConfigureAwait(false)).ToJson();
                case PipeMethods.Bindings:
                    var bindings = BindingsParams.FromJson(request.Params); CheckSession(bindings.SessionId);
                    return new BindingsResult { Bindings = await service.BindingsAsync(bindings.ObjectId, bindings.Generation, bindings.MemberKeys, ct).ConfigureAwait(false) }.ToJson();
                case PipeMethods.Release:
                    var release = ReleaseParams.FromJson(request.Params); CheckSession(release.SessionId);
                    return new ReleaseResult { ReleasedCount = await service.ReleaseAsync(release.ObjectIds, ct).ConfigureAwait(false) }.ToJson();
                case PipeMethods.Close:
                    CloseParams.FromJson(request.Params);
                    return new CloseResult { Closed = true }.ToJson();
                case PipeMethods.QueryFind:
                case PipeMethods.QueryFindAll:
                case PipeMethods.StateGet:
                case PipeMethods.ActFocus:
                case PipeMethods.ActBringIntoView:
                case PipeMethods.ActInvoke:
                case PipeMethods.ActToggle:
                case PipeMethods.ActExpand:
                case PipeMethods.ActCollapse:
                case PipeMethods.ActSelect:
                case PipeMethods.ActScrollIntoView:
                case PipeMethods.ActSetValue:
                case PipeMethods.ActSetRange:
                case PipeMethods.ActScroll:
                case PipeMethods.ActRealizeItem:
                case PipeMethods.WaitUntil:
                case PipeMethods.HitTest:
                case PipeMethods.WriteSetProperty:
                case PipeMethods.WriteCall:
                case PipeMethods.EventsSubscribe:
                case PipeMethods.EventsUnsubscribe:
                    throw new ProtocolException(ErrorCodes.UnsupportedTarget, "Feature not available.");
                default:
                    throw new ProtocolException(ErrorCodes.InvalidParams, "Unknown method.");
            }
        }
    }
}
