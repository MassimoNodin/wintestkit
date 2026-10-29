using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Threading;
using System.Threading.Tasks;

namespace WinTestKit.Inspector.Protocol
{
    public static class ProtocolInfo { public const int Major = 1, Minor = 0; }
    public static class ProtocolLimits
    {
        public const int MaxFrameBytes = 1048576, MaxJsonDepth = 32, AttachReadinessMs = 10000, RequestTimeoutMs = 2000, DispatcherQueueWaitMs = 500, TraversalSliceObjects = 200, TraversalSliceMs = 10, ScanMaxObjects = 10000, ScanMaxMs = 2000, DefaultPageSize = 100, MaxPageSize = 200, MaxBatchPaths = 32, MaxBatchCandidates = 32, MaxScalarChars = 4096, LeaseInactivityMs = 30000, MaxStrongHandles = 256, MaxWeakEntries = 10000, MaxPathSegments = 8, MaxPathBytes = 1024, MaxQueuedOps = 16, MaxActivePerSession = 4, MaxActivePerDispatcher = 1, MaxResponseBytes = 1048576, IdleSessionMs = 300000, PageTokenTtlMs = 30000, MaxSnapshots = 16, MaxBindingDepth = 8, MaxBindingEntries = 32, MaxBindingKeys = 32, MaxReleaseIds = 256, MaxIdentifierLength = 128, MaxKeyLength = 1024, BootstrapExpirySeconds = 30, MaxBootstrapBytes = 16384;
    }
    public static class ErrorCodes
    {
        public const string InvalidParams = "invalidParams", UnsupportedProtocol = "unsupportedProtocol", UnsupportedTarget = "unsupportedTarget", AccessDenied = "accessDenied", AuthenticationFailed = "authenticationFailed", PayloadMissing = "payloadMissing", PayloadMismatch = "payloadMismatch", AlreadyAttached = "alreadyAttached", NotAttached = "notAttached", AttachFailed = "attachFailed", BlockedByPolicy = "blockedByPolicy", AgentVersionMismatch = "agentVersionMismatch", ProcessExited = "processExited", ProcessReused = "processReused", SessionStale = "sessionStale", ObjectStale = "objectStale", MappingFailed = "mappingFailed", MemberAmbiguous = "memberAmbiguous", MemberNotFound = "memberNotFound", DispatcherUnavailable = "dispatcherUnavailable", Timeout = "timeout", Busy = "busy", LimitExceeded = "limitExceeded", InvalidPageToken = "invalidPageToken", Cancelled = "cancelled", InternalError = "internalError";
    }
    public static class Features { public const string TypeMetadata = "typeMetadata", ClrMembers = "clrMembers", DependencyProperties = "dependencyProperties", Bindings = "bindings", ExactUiaMapping = "exactUiaMapping", BatchReads = "batchReads"; }
    public static class PipeMethods { public const string Hello = "session.hello", Close = "session.close", Cancel = "request.cancel", Resolve = "element.resolve", ReadBatch = "element.readBatch", Roots = "roots", Children = "children", Members = "members", Read = "read", Bindings = "bindings", Release = "release"; }
    public sealed class ProtocolException : Exception
    {
        public ProtocolException(string code, string message, JsonObjectNode? details = null) : base(message) { Code = code; Details = details; }
        public string Code { get; }
        public JsonObjectNode? Details { get; }
    }
    public abstract class JsonNode { }
    public sealed class JsonObjectNode : JsonNode
    {
        private readonly List<KeyValuePair<string, JsonNode>> members = new List<KeyValuePair<string, JsonNode>>();
        public IReadOnlyList<KeyValuePair<string, JsonNode>> Members => members;
        public bool TryGet(string key, out JsonNode value) { foreach (var item in members) if (item.Key == key) { value = item.Value; return true; } value = null!; return false; }
        public JsonNode Get(string key) => TryGet(key, out var value) ? value : throw new ProtocolException(ErrorCodes.InvalidParams, "Missing field: " + key);
        public void Add(string key, JsonNode value) { if (TryGet(key, out _)) throw new ProtocolException(ErrorCodes.InvalidParams, "Duplicate field: " + key); members.Add(new KeyValuePair<string, JsonNode>(key, value)); }
    }
    public sealed class JsonArrayNode : JsonNode { private readonly List<JsonNode> items = new List<JsonNode>(); public IReadOnlyList<JsonNode> Items => items; public void Add(JsonNode node) => items.Add(node); }
    public sealed class JsonStringNode : JsonNode { public JsonStringNode(string value) { Value = value; } public string Value { get; } }
    public sealed class JsonNumberNode : JsonNode { public JsonNumberNode(string rawText) { RawText = rawText; } public string RawText { get; } public static JsonNumberNode From(long value) => new JsonNumberNode(value.ToString(CultureInfo.InvariantCulture)); public static JsonNumberNode From(double value) => new JsonNumberNode(value.ToString("R", CultureInfo.InvariantCulture)); public bool TryGetInt64(out long value) => long.TryParse(RawText, NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out value); }
    public sealed class JsonBoolNode : JsonNode { public JsonBoolNode(bool value) { Value = value; } public bool Value { get; } }
    public sealed class JsonNullNode : JsonNode { private JsonNullNode() { } public static JsonNullNode Instance { get; } = new JsonNullNode(); }
    public static class FrameCodec
    {
        public static async Task<byte[]?> ReadFrameAsync(Stream s, CancellationToken ct)
        {
            var header = new byte[4]; int n = await s.ReadAsync(header, 0, 4, ct).ConfigureAwait(false); if (n == 0) return null;
            await ReadRest(s, header, n, ct).ConfigureAwait(false);
            uint length = (uint)(header[0] | header[1] << 8 | header[2] << 16 | header[3] << 24);
            if (length == 0 || length > ProtocolLimits.MaxFrameBytes) throw new ProtocolException(ErrorCodes.InvalidParams, "Invalid frame length");
            var body = new byte[(int)length]; await ReadRest(s, body, 0, ct).ConfigureAwait(false); return body;
        }
        private static async Task ReadRest(Stream s, byte[] bytes, int offset, CancellationToken ct) { while (offset < bytes.Length) { int n = await s.ReadAsync(bytes, offset, bytes.Length - offset, ct).ConfigureAwait(false); if (n == 0) throw new ProtocolException(ErrorCodes.InvalidParams, "Unexpected EOF in frame"); offset += n; } }
        public static async Task WriteFrameAsync(Stream s, byte[] payload, CancellationToken ct) { if (payload.Length == 0 || payload.Length > ProtocolLimits.MaxFrameBytes) throw new ProtocolException(ErrorCodes.InvalidParams, "Invalid frame length"); int n = payload.Length; var header = new[] { (byte)n, (byte)(n >> 8), (byte)(n >> 16), (byte)(n >> 24) }; await s.WriteAsync(header, 0, 4, ct).ConfigureAwait(false); await s.WriteAsync(payload, 0, n, ct).ConfigureAwait(false); }
    }
}
