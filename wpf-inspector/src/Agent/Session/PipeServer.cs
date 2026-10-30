using System;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.IO.Pipes;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Win32.SafeHandles;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Session
{
    public interface IClientIdentityVerifier
    {
        bool IsExpectedClient(SafePipeHandle pipe, string expectedSid);
    }

    public sealed class ClientIdentityVerifier : IClientIdentityVerifier
    {
        public bool IsExpectedClient(SafePipeHandle pipe, string expectedSid)
        {
            if (!GetNamedPipeClientProcessId(pipe, out uint pid)) return false;
            using (var process = OpenProcess(0x1000, false, pid))
            {
                if (process.IsInvalid || !OpenProcessToken(process, 0x0008, out var token)) return false;
                using (token)
                using (var identity = new WindowsIdentity(token.DangerousGetHandle()))
                    return string.Equals(identity.User?.Value, expectedSid, StringComparison.OrdinalIgnoreCase);
            }
        }

        [DllImport("kernel32.dll", SetLastError = true)] private static extern bool GetNamedPipeClientProcessId(SafePipeHandle pipe, out uint pid);
        [DllImport("kernel32.dll", SetLastError = true)] private static extern SafeFileHandle OpenProcess(uint access, bool inherit, uint pid);
        [DllImport("advapi32.dll", SetLastError = true)] private static extern bool OpenProcessToken(SafeFileHandle process, uint access, out SafeFileHandle token);
    }

    public sealed class PipeServer : IDisposable
    {
        private readonly BootstrapSettings settings;
        private readonly ISessionRequestHandler handler;
        private readonly IClientIdentityVerifier verifier;
        private readonly bool production;
        private readonly bool exactMappingAvailable;
        private readonly NamedPipeServerStream pipe;
        private readonly Action activity;
        private readonly SemaphoreSlim writer = new SemaphoreSlim(1, 1);

        public PipeServer(BootstrapSettings settings, ISessionRequestHandler handler, IClientIdentityVerifier verifier, bool production, Action activity, bool exactMappingAvailable = false)
        {
            this.settings = settings; this.handler = handler; this.verifier = verifier; this.production = production; this.activity = activity; this.exactMappingAvailable = exactMappingAvailable;
            string expectedName = "WinTestKit.Inspector." + settings.Process.Pid + "." + settings.SessionId;
            if (!string.Equals(settings.PipeName, expectedName, StringComparison.Ordinal)) throw new InvalidDataException("Invalid pipe name.");
            var sid = new SecurityIdentifier(settings.ClientSid);
            if (!ConvertStringSecurityDescriptorToSecurityDescriptor("D:P(A;;GA;;;" + sid.Value + ")", 1, out var descriptor, out _)) throw new Win32Exception(Marshal.GetLastWin32Error());
            try
            {
                var security = new SecurityAttributes { Length = Marshal.SizeOf(typeof(SecurityAttributes)), SecurityDescriptor = descriptor };
                var handle = CreateNamedPipe(@"\\.\pipe\" + expectedName, 0x40000003 | 0x00080000, 0x00000008, 1, 65536, 65536, 0, ref security);
                if (handle.IsInvalid) { int error = Marshal.GetLastWin32Error(); handle.Dispose(); throw new Win32Exception(error); }
                pipe = new NamedPipeServerStream(PipeDirection.InOut, true, false, handle);
            }
            finally { LocalFree(descriptor); }
        }

        public async Task RunAsync(CancellationToken ct)
        {
            await pipe.WaitForConnectionAsync(ct).ConfigureAwait(false);
            if (!verifier.IsExpectedClient(pipe.SafePipeHandle, settings.ClientSid)) return;
            var first = await FrameCodec.ReadFrameAsync(pipe, ct).ConfigureAwait(false);
            if (first == null) return;
            RequestEnvelope request;
            HelloParams hello;
            try
            {
                request = RequestEnvelope.FromJson(StrictJson.Parse(first, 0, first.Length));
                if (request.Method != PipeMethods.Hello) return;
                hello = HelloParams.FromJson(request.Params);
                if (hello.ProtocolMajor != ProtocolInfo.Major || hello.ProtocolMinor > ProtocolInfo.Minor ||
                    hello.SessionId != settings.SessionId || !TokenEquals(hello.Token, settings.Token) ||
                    hello.Process.Pid != settings.Process.Pid || DateTimeOffset.Parse(hello.Process.CreationTimeUtc) != DateTimeOffset.Parse(settings.Process.CreationTimeUtc)) return;
            }
            catch (Exception error) when (error is ProtocolException || error is FormatException || error is ArgumentException) { return; }
            var result = new HelloResult { AgentVersion = typeof(PipeServer).Assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion ?? "", Tfm = Tfm, Architecture = Environment.Is64BitProcess ? "x64" : "x86", RuntimeVersion = Environment.Version.ToString(), Process = settings.Process,
                Features = production ? (exactMappingAvailable ? new[] { Features.TypeMetadata, Features.ClrMembers, Features.DependencyProperties, Features.Bindings, Features.ExactUiaMapping, Features.BatchReads, Features.Query, Features.Geometry } : new[] { Features.TypeMetadata, Features.ClrMembers, Features.DependencyProperties, Features.Bindings, Features.BatchReads, Features.Query, Features.Geometry }) : Array.Empty<string>() };
            await SendAsync(new ResponseEnvelope { Id = request.Id, Result = result.ToJson() }, ct).ConfigureAwait(false);
            activity();
            long lastId = request.Id;
            using (var session = CancellationTokenSource.CreateLinkedTokenSource(ct))
            try
            {
              while (!session.IsCancellationRequested)
              {
                var bytes = await FrameCodec.ReadFrameAsync(pipe, session.Token).ConfigureAwait(false);
                if (bytes == null) return;
                try { request = ParseRequest(StrictJson.Parse(bytes, 0, bytes.Length)); }
                catch (ProtocolException) { return; }
                if (request.Id <= lastId || request.Method == PipeMethods.Hello) return;
                lastId = request.Id;
                activity();
                if (request.Method == PipeMethods.Close)
                {
                    var response = await handler.HandleAsync(request, session.Token).ConfigureAwait(false);
                    if (response.Error == null)
                    {
                        await writer.WaitAsync(ct).ConfigureAwait(false);
                        try
                        {
                            session.Cancel();
                            await FrameCodec.WriteFrameAsync(pipe, StrictJson.Serialize(response.ToJson()), ct).ConfigureAwait(false);
                        }
                        finally { writer.Release(); }
                        return;
                    }
                    await SendAsync(response, session.Token).ConfigureAwait(false);
                }
                else _ = HandleAndSendAsync(request, session.Token);
              }
            }
            finally { session.Cancel(); }
        }

        private async Task HandleAndSendAsync(RequestEnvelope request, CancellationToken ct)
        {
            try
            {
                var response = !production && (request.Method == PipeMethods.QueryFind || request.Method == PipeMethods.QueryFindAll || request.Method == PipeMethods.StateGet)
                    ? new ResponseEnvelope { Id = request.Id, Error = new ErrorInfo { Code = ErrorCodes.UnsupportedTarget, Message = "Request failed." } }
                    : await handler.HandleAsync(request, ct).ConfigureAwait(false);
                await SendAsync(response, ct).ConfigureAwait(false);
            }
            catch (Exception error) when (error is OperationCanceledException || error is ObjectDisposedException || error is IOException) { }
        }

        private async Task SendAsync(ResponseEnvelope response, CancellationToken ct)
        {
            var bytes = StrictJson.Serialize(response.ToJson());
            if (bytes.Length > ProtocolLimits.MaxResponseBytes)
                bytes = StrictJson.Serialize(new ResponseEnvelope { Id = response.Id, Error = new ErrorInfo { Code = ErrorCodes.LimitExceeded, Message = "Response too large." } }.ToJson());
            await writer.WaitAsync(ct).ConfigureAwait(false);
            try { ct.ThrowIfCancellationRequested(); await FrameCodec.WriteFrameAsync(pipe, bytes, ct).ConfigureAwait(false); }
            finally { writer.Release(); }
        }
        private static RequestEnvelope ParseRequest(JsonNode node)
        {
            if (!(node is JsonObjectNode input) || !input.TryGet("method", out var methodNode) || !(methodNode is JsonStringNode method))
                return RequestEnvelope.FromJson(node);
            var normalized = new JsonObjectNode();
            foreach (var member in input.Members)
                normalized.Add(member.Key, member.Key == "method" ? new JsonStringNode(PipeMethods.Close) : member.Value);
            var request = RequestEnvelope.FromJson(normalized);
            if (string.IsNullOrEmpty(method.Value) || method.Value.Length > ProtocolLimits.MaxIdentifierLength)
                throw new ProtocolException(ErrorCodes.InvalidParams, "Invalid method.");
            request.Method = method.Value;
            return request;
        }
        private static bool TokenEquals(string first, string second)
        {
            byte[] left = Encoding.UTF8.GetBytes(first), right = Encoding.UTF8.GetBytes(second);
            int difference = left.Length ^ right.Length;
            for (int index = 0; index < Math.Max(left.Length, right.Length); index++) difference |= (index < left.Length ? left[index] : 0) ^ (index < right.Length ? right[index] : 0);
            return difference == 0;
        }
        public void Dispose() => pipe.Dispose();
        private static string Tfm
        {
            get
            {
#if NET48
                return "net48";
#elif NET8_0
                return "net8.0-windows";
#else
                return "net10.0-windows";
#endif
            }
        }
        [StructLayout(LayoutKind.Sequential)] private struct SecurityAttributes { public int Length; public IntPtr SecurityDescriptor; public int InheritHandle; }
        [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern bool ConvertStringSecurityDescriptorToSecurityDescriptor(string sddl, uint revision, out IntPtr descriptor, out uint size);
        [DllImport("kernel32.dll")] private static extern IntPtr LocalFree(IntPtr memory);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern SafePipeHandle CreateNamedPipe(string name, uint openMode, uint pipeMode, uint maxInstances, uint outSize, uint inSize, uint timeout, ref SecurityAttributes security);
    }
}
