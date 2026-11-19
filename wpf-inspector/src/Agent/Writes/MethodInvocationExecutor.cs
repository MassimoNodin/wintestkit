using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Contracts;
using WinTestKit.Inspector.Agent.Inspection;
using WinTestKit.Inspector.Agent.Inspection.Members;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Writes
{
    internal sealed class MethodInvocationExecutor
    {
        private readonly DispatcherExecutor executor;
        private readonly RedactionPolicy redaction;

        internal MethodInvocationExecutor(DispatcherExecutor executor, IEnumerable<string> rules)
        { this.executor = executor; redaction = new RedactionPolicy(rules); }

        internal async Task<WriteCallResult> ExecuteAsync(object target, Dispatcher dispatcher, string key, IReadOnlyList<JsonNode> values, DateTime deadline, CancellationToken cancellation, IObjectRegistry registry)
        {
            string auditKey = "identity";
            WriteAudit Audit(string outcome, string? reason = null) => new WriteAudit { Operation = "call", TypeFullName = target.GetType().FullName ?? target.GetType().Name, MemberKey = auditKey, Outcome = outcome, TimestampUtc = DateTime.UtcNow.ToString("O", CultureInfo.InvariantCulture), Reason = reason };
            ProtocolException Error(string code, string outcome, string reason) { var details = new JsonObjectNode(); details.Add("audit", Audit(outcome, reason).ToJson()); return new ProtocolException(code, "Invocation failed.", details); }
            DateTime end = DateTime.UtcNow.AddMilliseconds(ProtocolLimits.RequestTimeoutMs);
            if (deadline < end) end = deadline;
            int remaining = (int)Math.Max(0, (end - DateTime.UtcNow).TotalMilliseconds);
            if (remaining == 0) throw Error(ErrorCodes.Timeout, "failed", "timeout");
            using (var timed = CancellationTokenSource.CreateLinkedTokenSource(cancellation))
            {
                timed.CancelAfter(remaining);
                try
                {
                    return await executor.ExecuteAsync(dispatcher, token =>
                    {
                        token.ThrowIfCancellationRequested();
                        if (RedactionPolicy.IsProtectedIdentity(target)) throw Error(ErrorCodes.WriteDenied, "denied", "protectedIdentity");
                        if (key == null || key.Length > 8192 || values == null || values.Count > 16) throw Error(ErrorCodes.InvalidParams, "failed", "invalidParams");
                        var matches = MethodCatalog.Get(target.GetType()).Where(item => item.Key == key).ToArray();
                        if (matches.Length != 1) throw Error(ErrorCodes.WriteDenied, "denied", matches.Length == 0 ? "notFound" : "ambiguous");
                        var method = matches[0];
                        string? rule = redaction.Match(method.Name);
                        if (rule == null) foreach (var parameter in method.Parameters) { rule = redaction.Match(parameter.Name); if (rule != null) break; }
                        if (rule != null) { auditKey = rule; throw Error(ErrorCodes.WriteDenied, "denied", "redacted"); }
                        using (var hash = System.Security.Cryptography.SHA256.Create())
                            auditKey = "sha256:" + BitConverter.ToString(hash.ComputeHash(System.Text.Encoding.UTF8.GetBytes(key))).Replace("-", "").ToLowerInvariant();
                        if (method.UnsupportedReason != null) throw Error(ErrorCodes.WriteDenied, "denied", "unsupported");
                        if (values.Count != method.Parameters.Count) throw Error(ErrorCodes.InvalidParams, "failed", "invalidParams");
                        var arguments = new object?[values.Count];
                        for (int index = 0; index < arguments.Length; index++)
                        {
                            if (!(values[index] is JsonObjectNode argument) || argument.Members.Count != 2 || argument.Members.Any(member => member.Key.Length > 16 || member.Value is JsonStringNode text && text.Value.Length > ProtocolLimits.MaxScalarChars || member.Value is JsonNumberNode number && number.RawText.Length > ProtocolLimits.MaxScalarChars))
                                throw Error(ErrorCodes.InvalidParams, "failed", "invalidParams");
                            try { arguments[index] = WriteEngine.CallScalar(argument, method.Parameters[index].ParameterType); }
                            catch (ProtocolException) { throw Error(ErrorCodes.InvalidParams, "failed", "invalidParams"); }
                        }
                        token.ThrowIfCancellationRequested();
                        object? returned;
                        try { returned = method.Method.Invoke(method.IsStatic ? null : target, arguments); }
                        catch (Exception) { throw Error(ErrorCodes.InternalError, "failed", "invocationFailed"); }
                        ValueDto result;
                        try
                        {
                            result = returned != null && RedactionPolicy.IsProtectedIdentity(returned)
                                ? new ValueDto { Status = "redacted", Kind = "unavailable", RedactionRule = "identity" }
                                : ValueSerializer.Serialize(returned, method.ReturnType, registry, dispatcher);
                        }
                        catch (Exception) { throw Error(ErrorCodes.InternalError, "failed", "serializationFailed"); }
                        return new WriteCallResult { Audit = Audit("performed"), Result = result };
                    }, timed.Token).ConfigureAwait(false);
                }
                catch (OperationCanceledException) when (!cancellation.IsCancellationRequested) { throw Error(ErrorCodes.Timeout, "failed", "timeout"); }
                catch (ProtocolException error) when (error.Details == null || !error.Details.TryGet("audit", out _))
                { throw Error(error.Code, "failed", DateTime.UtcNow >= end ? "timeout" : error.Code); }
            }
        }
    }
}
