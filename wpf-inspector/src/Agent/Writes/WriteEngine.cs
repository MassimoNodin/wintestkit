using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.Linq;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Inspection;
using WinTestKit.Inspector.Agent.Inspection.Members;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Writes
{
    internal sealed class WriteEngine
    {
        private readonly DispatcherExecutor executor;
        private readonly WriteAllowlist allowlist;
        private readonly RedactionPolicy redaction;
        internal WriteEngine(DispatcherExecutor executor, WriteAllowlist allowlist, IEnumerable<string> rules)
        { this.executor = executor; this.allowlist = allowlist; redaction = new RedactionPolicy(rules); }

        internal async Task<WriteAudit> ExecuteAsync(Dispatcher dispatcher, object target, string operation, string key, IReadOnlyList<JsonNode> values, DateTime deadline, int timeoutMs, CancellationToken ct)
        {
            string typeName = target.GetType().FullName ?? target.GetType().Name;
            string name = MemberName(key, operation);
            string? rule = redaction.Match(name);
            // Until the owning Dispatcher has checked an object's identity, do not expose
            // a member key for a dependency object in timeout or admission errors.
            string auditKey = rule ?? (target is DependencyObject ? "identity" : key);
            WriteAudit Audit(string outcome, string? reason = null) => new WriteAudit { Operation = operation, TypeFullName = typeName, MemberKey = auditKey, Outcome = outcome, TimestampUtc = DateTime.UtcNow.ToString("O", CultureInfo.InvariantCulture), Reason = reason };
            DateTime end = DateTime.UtcNow.AddMilliseconds(timeoutMs);
            if (deadline < end) end = deadline;
            int remaining = (int)Math.Max(0, (end - DateTime.UtcNow).TotalMilliseconds);
            if (remaining == 0) throw Error(ErrorCodes.Timeout, Audit("failed", "timeout"));
            using (var timed = CancellationTokenSource.CreateLinkedTokenSource(ct))
            {
                timed.CancelAfter(remaining);
                try
                {
                    return await executor.ExecuteAsync(dispatcher, token =>
                    {
                        token.ThrowIfCancellationRequested();
                        if (rule != null) throw Error(ErrorCodes.WriteDenied, Audit("denied", "redacted"));
                        if (RedactionPolicy.IsProtectedIdentity(target)) { auditKey = "identity"; throw Error(ErrorCodes.WriteDenied, Audit("denied", "protectedIdentity")); }
                        auditKey = key;
                        if (!(operation == "call" ? allowlist.Methods : allowlist.Properties).Any(e => e.TypeFullName == typeName && e.MemberKey == key))
                            throw Error(ErrorCodes.WriteDenied, Audit("denied", "notAllowlisted"));
                        try { Perform(target, operation, key, values); }
                        catch (ProtocolException e) { throw Error(e.Code, Audit(e.Code == ErrorCodes.WriteDenied ? "denied" : "failed", e.Code)); }
                        catch (Exception e)
                        {
                            var actual = e is TargetInvocationException invocation && invocation.InnerException != null ? invocation.InnerException : e;
                            throw Error(ErrorCodes.InternalError, Audit("failed", actual.GetType().Name));
                        }
                        return Audit("performed");
                    }, timed.Token).ConfigureAwait(false);
                }
                catch (OperationCanceledException) when (!ct.IsCancellationRequested) { throw Error(ErrorCodes.Timeout, Audit("failed", "timeout")); }
                catch (ProtocolException e) when (e.Details == null || !e.Details.TryGet("audit", out _))
                { throw Error(e.Code, Audit("failed", DateTime.UtcNow >= end ? "timeout" : e.Code)); }
            }
        }

        private static string MemberName(string key, string operation)
        {
            if (operation == "call") { int index = key.IndexOf('('); return index < 0 ? key : key.Substring(0, index); }
            var parts = key.Split('|'); return parts.Length > 3 ? parts[3] : key;
        }

        // Method keys are metadata names plus exact CLR parameter names, e.g. Refresh(System.Boolean,System.Int64).
        private static string MethodKey(MethodInfo method) => method.Name + "(" + string.Join(",", method.GetParameters().Select(p => p.ParameterType.FullName ?? "")) + ")";
        private static void Perform(object target, string operation, string key, IReadOnlyList<JsonNode> values)
        {
            if (operation == "setProperty")
            {
                if (target is DependencyObject dependency)
                {
                    var dp = DependencyCatalog.Discover(dependency, _ => { }).FirstOrDefault(e => e.Key == key);
                    if (dp != null)
                    {
                        if (dp.Property.ReadOnly) throw Denied();
                        dependency.SetCurrentValue(dp.Property, Scalar(values[0], dp.Property.PropertyType)); return;
                    }
                }
                var declaration = ReflectionCatalog.Get(target.GetType()).FirstOrDefault(d => d.Key == key && d.Property != null);
                var property = declaration?.Property;
                var setter = property?.GetSetMethod(true);
                if (property == null || setter == null || !setter.IsPublic || setter.IsStatic || property.GetIndexParameters().Length != 0) throw Denied();
                if (RedactionPolicy.IsPasswordIdentity(declaration!.DeclaringType, declaration.Name)) throw Denied();
                property.SetValue(target, Scalar(values[0], property.PropertyType), null); return;
            }
            var matches = target.GetType().GetMethods(BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic).Where(m => MethodKey(m) == key).ToArray();
            if (matches.Length != 1) throw Denied();
            var method = matches[0]; var parameters = method.GetParameters();
            if (!method.IsPublic || method.IsStatic || method.IsGenericMethod || parameters.Any(p => p.ParameterType.IsByRef || p.IsOut || p.IsDefined(typeof(ParamArrayAttribute), false))) throw Denied();
            if (parameters.Length != values.Count || values.Count > 16) throw Invalid();
            var args = new object[values.Count];
            for (int i = 0; i < args.Length; i++) args[i] = Scalar(values[i], parameters[i].ParameterType);
            method.Invoke(target, args);
        }
        private static object Scalar(JsonNode node, Type expected)
        {
            object value;
            if (node is JsonStringNode s) value = s.Value;
            else if (node is JsonBoolNode b) value = b.Value;
            else if (node is JsonNumberNode n && n.RawText.IndexOfAny(new[] { '.', 'e', 'E' }) < 0 && n.TryGetInt64(out long integer)) value = integer;
            else if (node is JsonNumberNode d && d.RawText.IndexOfAny(new[] { '.', 'e', 'E' }) >= 0 && double.TryParse(d.RawText, NumberStyles.Float, CultureInfo.InvariantCulture, out double number) && !double.IsNaN(number) && !double.IsInfinity(number)) value = number;
            else throw Invalid();
            if (value.GetType() != expected) throw Invalid();
            return value;
        }
        private static ProtocolException Denied() => new ProtocolException(ErrorCodes.WriteDenied, "Write denied.");
        private static ProtocolException Invalid() => new ProtocolException(ErrorCodes.InvalidParams, "Invalid scalar.");
        private static ProtocolException Error(string code, WriteAudit audit) { var details = new JsonObjectNode(); details.Add("audit", audit.ToJson()); return new ProtocolException(code, "Write failed.", details); }
    }
}
