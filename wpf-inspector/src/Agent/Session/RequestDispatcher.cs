using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using WinTestKit.Inspector.Agent.Contracts;
using WinTestKit.Inspector.Agent.Inspection.Members;
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
        private readonly Queue<long> writeAttempts = new Queue<long>();
        private readonly RedactionPolicy redaction;

        public RequestDispatcher(string sessionId, IInspectionService service, IRequestScheduler? scheduler = null, IEnumerable<string>? redactNames = null)
        {
            this.sessionId = sessionId;
            this.service = service;
            this.scheduler = scheduler ?? new RequestScheduler(ProtocolLimits.RequestTimeoutMs);
            redaction = new RedactionPolicy(redactNames ?? Array.Empty<string>());
        }

        public async Task<ResponseEnvelope> HandleAsync(RequestEnvelope request, CancellationToken ct)
        {
            var deadline = DateTime.UtcNow.AddMilliseconds((scheduler as RequestScheduler)?.TimeoutMs ?? ProtocolLimits.RequestTimeoutMs);
            try
            {
                if (IsWrite(request.Method) && !AdmitWriteAttempt())
                    throw new ProtocolException(ErrorCodes.WriteRateExceeded, "Write rate exceeded.");
                JsonNode result;
                if (request.Method == PipeMethods.Cancel && scheduler is RequestScheduler concrete)
                    result = new CancelResult { Accepted = concrete.Cancel(CancelParams.FromJson(request.Params).RequestId) }.ToJson();
                else if (request.Method == PipeMethods.Close)
                    result = await RouteAsync(request, deadline, ct).ConfigureAwait(false);
                else
                    result = await scheduler.ExecuteAsync(request, token => RouteAsync(request, deadline, token), ct).ConfigureAwait(false);
                return new ResponseEnvelope { Id = request.Id, Result = result };
            }
            catch (ProtocolException error)
            {
                return new ResponseEnvelope { Id = request.Id, Error = new ErrorInfo { Code = error.Code, Message = "Request failed.", Details = IsWrite(request.Method) ? WriteErrorDetails(request, error) : SafeErrorDetails(error, request.Method) } };
            }
            catch (OperationCanceledException)
            {
                var error = new ProtocolException(ErrorCodes.Cancelled, "Request cancelled.");
                return new ResponseEnvelope { Id = request.Id, Error = new ErrorInfo { Code = error.Code, Message = "Request failed.", Details = IsWrite(request.Method) ? WriteErrorDetails(request, error) : null } };
            }
            catch (Exception)
            {
                return new ResponseEnvelope { Id = request.Id, Error = new ErrorInfo { Code = ErrorCodes.InternalError, Message = "Request failed.", Details = IsWrite(request.Method) ? WriteErrorDetails(request, new ProtocolException(ErrorCodes.InternalError, "Request failed.")) : null } };
            }
        }

        private static bool IsWrite(string method) => method == PipeMethods.WriteCall || method == PipeMethods.WriteSetProperty;

        private bool AdmitWriteAttempt()
        {
            lock (writeAttempts)
            {
                long now = Stopwatch.GetTimestamp();
                while (writeAttempts.Count > 0 && now - writeAttempts.Peek() >= Stopwatch.Frequency) writeAttempts.Dequeue();
                bool admitted = writeAttempts.Count < 10;
                writeAttempts.Enqueue(now);
                if (writeAttempts.Count > 10) writeAttempts.Dequeue();
                return admitted;
            }
        }

        private JsonObjectNode WriteErrorDetails(RequestEnvelope request, ProtocolException error)
        {
            var existing = SafeErrorDetails(error, request.Method);
            if (existing != null && existing.TryGet("audit", out _)) return existing;
            string typeName = "<unknown>";
            string memberKey = "<unknown>";
            if (request.Params is JsonObjectNode parameters && parameters.TryGet("handle", out var handle))
            {
                try { var name = ObjectRef.FromJson(handle).Type.FullName; if (!string.IsNullOrEmpty(name)) typeName = name; }
                catch (ProtocolException) { }
            }
            if (request.Params is JsonObjectNode input && input.TryGet("memberKey", out var member) && member is JsonStringNode key && key.Value.Length > 0 && key.Value.Length <= ProtocolLimits.MaxKeyLength)
            {
                string name = key.Value;
                if (request.Method == PipeMethods.WriteCall) { int index = name.IndexOf('('); if (index >= 0) name = name.Substring(0, index); }
                else { var parts = name.Split('|'); if (parts.Length > 3) name = parts[3]; }
                memberKey = redaction.Match(name) ?? key.Value;
            }
            string reason = error.Code == ErrorCodes.WriteRateExceeded ? "rateLimited" : error.Code == ErrorCodes.Busy ? "admission" : error.Code;
            var audit = new WriteAudit { Operation = request.Method == PipeMethods.WriteCall ? "call" : "setProperty", TypeFullName = typeName, MemberKey = memberKey, Outcome = error.Code == ErrorCodes.WriteRateExceeded || error.Code == ErrorCodes.WriteDenied || error.Code == ErrorCodes.Busy ? "denied" : "failed", TimestampUtc = DateTime.UtcNow.ToString("O"), Reason = reason };
            var details = new JsonObjectNode(); details.Add("audit", audit.ToJson()); return details;
        }

        private static JsonObjectNode? SafeErrorDetails(ProtocolException error, string method)
        {
            if ((method == PipeMethods.WriteCall || method == PipeMethods.WriteSetProperty) && error.Details != null && error.Details.TryGet("audit", out var audit))
            {
                try { var safe = new JsonObjectNode(); safe.Add("audit", WriteAudit.FromJson(audit).ToJson()); return safe; }
                catch (ProtocolException) { return null; }
            }
            if (error.Code == ErrorCodes.ValueUnreadable) return error.Details;
            if (error.Code == ErrorCodes.Timeout && error.Details != null &&
                error.Details.TryGet("dispatcherBusy", out var busy) && busy is JsonBoolNode busyBoolean && busyBoolean.Value)
            {
                var details = new JsonObjectNode();
                details.Add("dispatcherBusy", new JsonBoolNode(true));
                return details;
            }
            if (error.Code == ErrorCodes.LimitExceeded && error.Details != null &&
                error.Details.TryGet("deadline", out var marker) && marker is JsonBoolNode boolean && boolean.Value)
            {
                var details = new JsonObjectNode();
                details.Add("deadline", new JsonBoolNode(true));
                return details;
            }
            return null;
        }

        private void CheckSession(string value)
        {
            if (!string.Equals(value, sessionId, StringComparison.Ordinal)) throw new ProtocolException(ErrorCodes.SessionStale, "Invalid session.");
        }

        private async Task<JsonNode> RouteAsync(RequestEnvelope request, DateTime deadline, CancellationToken ct)
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
                    if (!(service is IQueryInspectionService queryService)) throw new ProtocolException(ErrorCodes.UnsupportedTarget, "Feature not available.");
                    var find = QueryFindParams.FromJson(request.Params);
                    return (await queryService.FindAsync(find.Locator, deadline, find.TimeoutMs, ct).ConfigureAwait(false)).ToJson();
                case PipeMethods.QueryFindAll:
                    if (!(service is IQueryInspectionService queryAllService)) throw new ProtocolException(ErrorCodes.UnsupportedTarget, "Feature not available.");
                    var findAll = QueryFindAllParams.FromJson(request.Params);
                    return (await queryAllService.FindAllAsync(findAll.Locator, deadline, findAll.TimeoutMs, ct).ConfigureAwait(false)).ToJson();
                case PipeMethods.StateGet:
                    if (!(service is IStateInspectionService stateService)) throw new ProtocolException(ErrorCodes.UnsupportedTarget, "Feature not available.");
                    var state = StateGetParams.FromJson(request.Params);
                    return (await stateService.GetStateAsync(state.Handle, deadline, state.TimeoutMs, ct).ConfigureAwait(false)).ToJson();
                case PipeMethods.WaitUntil:
                    if (!(service is IWaitInspectionService waitService)) throw new ProtocolException(ErrorCodes.UnsupportedTarget, "Feature not available.");
                    var wait = WaitUntilParams.FromJson(request.Params);
                    return (await waitService.WaitUntilAsync(wait.Condition, deadline, wait.TimeoutMs, ct).ConfigureAwait(false)).ToJson();
                case PipeMethods.ActFocus:
                case PipeMethods.ActBringIntoView:
                case PipeMethods.ActInvoke:
                case PipeMethods.ActToggle:
                case PipeMethods.ActExpand:
                case PipeMethods.ActCollapse:
                case PipeMethods.ActSelect:
                case PipeMethods.ActScrollIntoView:
                    if (!(service is IActionInspectionService actionService)) throw new ProtocolException(ErrorCodes.UnsupportedTarget, "Feature not available.");
                    var action = StateGetParams.FromJson(request.Params);
                    return (await actionService.ActAsync(request.Method, action.Handle, deadline, action.TimeoutMs, ct).ConfigureAwait(false)).ToJson();
                case PipeMethods.ActSetValue:
                    if (!(service is IActionInspectionService valueService)) throw new ProtocolException(ErrorCodes.UnsupportedTarget, "Feature not available.");
                    var setValue = ActSetValueParams.FromJson(request.Params);
                    return (await valueService.ActAsync(request.Method, setValue.Handle, deadline, setValue.TimeoutMs, ct, setValue).ConfigureAwait(false)).ToJson();
                case PipeMethods.ActSetRange:
                    if (!(service is IActionInspectionService rangeService)) throw new ProtocolException(ErrorCodes.UnsupportedTarget, "Feature not available.");
                    var setRange = ActSetRangeParams.FromJson(request.Params);
                    return (await rangeService.ActAsync(request.Method, setRange.Handle, deadline, setRange.TimeoutMs, ct, setRange).ConfigureAwait(false)).ToJson();
                case PipeMethods.ActScroll:
                    if (!(service is IActionInspectionService scrollService)) throw new ProtocolException(ErrorCodes.UnsupportedTarget, "Feature not available.");
                    var scroll = ActScrollParams.FromJson(request.Params);
                    return (await scrollService.ActAsync(request.Method, scroll.Handle, deadline, scroll.TimeoutMs, ct, scroll).ConfigureAwait(false)).ToJson();
                case PipeMethods.ActRealizeItem:
                    if (!(service is IRealizeInspectionService realizeService)) throw new ProtocolException(ErrorCodes.UnsupportedTarget, "Feature not available.");
                    var realize = ActRealizeItemParams.FromJson(request.Params);
                    return (await realizeService.RealizeItemAsync(realize.Search, deadline, realize.TimeoutMs, ct).ConfigureAwait(false)).ToJson();
                case PipeMethods.HitTest:
                    if (!(service is IHitTestInspectionService hitTestService)) throw new ProtocolException(ErrorCodes.UnsupportedTarget, "Feature not available.");
                    var hitTest = HitTestParams.FromJson(request.Params);
                    return (await hitTestService.HitTestAsync(hitTest.NativeWindowHandle, hitTest.Point, deadline, hitTest.TimeoutMs, ct, hitTest.IncludePath).ConfigureAwait(false)).ToJson();
                case PipeMethods.WriteSetProperty:
                    var set = WriteSetPropertyParams.FromJson(request.Params, false);
                    if (!(service is IWriteInspectionService setService)) throw new ProtocolException(ErrorCodes.UnsupportedTarget, "Feature not available.");
                    return new WriteSetPropertyResult { Audit = await setService.WriteAsync("setProperty", set.Handle, set.MemberKey, new[] { set.Value }, deadline, set.TimeoutMs, ct).ConfigureAwait(false) }.ToJson();
                case PipeMethods.WriteCall:
                    var call = WriteCallParams.FromJson(request.Params, false);
                    if (!(service is IWriteInspectionService callService)) throw new ProtocolException(ErrorCodes.UnsupportedTarget, "Feature not available.");
                    return new WriteCallResult { Audit = await callService.WriteAsync("call", call.Handle, call.MemberKey, call.Arguments, deadline, call.TimeoutMs, ct).ConfigureAwait(false) }.ToJson();
                case PipeMethods.EventsSubscribe:
                case PipeMethods.EventsUnsubscribe:
                    throw new ProtocolException(ErrorCodes.UnsupportedTarget, "Feature not available.");
                default:
                    throw new ProtocolException(ErrorCodes.InvalidParams, "Unknown method.");
            }
        }
    }
}
