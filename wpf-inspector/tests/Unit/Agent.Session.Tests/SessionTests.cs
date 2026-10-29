using System;
using System.Linq;
using System.Diagnostics;
using System.IO;
using System.IO.Pipes;
using System.Reflection;
using System.Security.Principal;
using System.Threading;
using System.Threading.Tasks;
using System.Collections.Generic;
using Microsoft.Win32.SafeHandles;
using WinTestKit.Inspector.Agent;
using WinTestKit.Inspector.Agent.Contracts;
using WinTestKit.Inspector.Agent.Session;
using WinTestKit.Inspector.Protocol;
using Xunit;

namespace WinTestKit.Inspector.Agent.Session.Tests;

[Trait("Category", "Unit")]
public class SessionTests
{
    private static BootstrapSettings Settings()
    {
        using var process = Process.GetCurrentProcess();
        var session = Guid.NewGuid().ToString();
        return new BootstrapSettings { ProtocolMajor = 1, ProtocolMinor = 0, SessionId = session,
            Process = new ProcessIdentity { Pid = process.Id, CreationTimeUtc = process.StartTime.ToUniversalTime().ToString("O") },
            PipeName = "WinTestKit.Inspector." + process.Id + "." + session, Token = Convert.ToBase64String(new byte[32]),
            ClientSid = WindowsIdentity.GetCurrent().User!.Value, ExpiresUtc = DateTime.UtcNow.AddMinutes(1).ToString("O"),
            RequestTimeoutMs = 1000, IdleTimeoutMs = 2000,
            AgentVersion = typeof(EntryPoint).Assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()!.InformationalVersion };
    }

    [Fact]
    public void ValidBootstrapIsDeleted()
    {
        var root = Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString()); Directory.CreateDirectory(root);
        try { var path = Path.Combine(root, "settings.json"); var settings = Settings(); File.WriteAllBytes(path, StrictJson.Serialize(settings.ToJson())); Assert.Equal(settings.SessionId, BootstrapReader.Read(path, root).SessionId); Assert.False(File.Exists(path)); }
        finally { Directory.Delete(root, true); }
    }

    [Theory]
    [InlineData("malformed")][InlineData("unknown")][InlineData("expired")][InlineData("pid")][InlineData("creation")][InlineData("version")][InlineData("oversized")]
    public void InvalidBootstrapIsDeleted(string kind)
    {
        var root = Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString()); Directory.CreateDirectory(root);
        try
        {
            var path = Path.Combine(root, "settings.json"); var settings = Settings();
            if (kind == "expired") settings.ExpiresUtc = DateTime.UtcNow.AddMinutes(-1).ToString("O");
            if (kind == "pid") settings.Process.Pid++;
            if (kind == "creation") settings.Process.CreationTimeUtc = DateTime.UtcNow.ToString("O");
            if (kind == "version") settings.AgentVersion = "other";
            var json = settings.ToJson(); if (kind == "unknown") json.Add("unexpected", new JsonBoolNode(true));
            File.WriteAllBytes(path, kind == "malformed" ? new byte[] { 123 } : kind == "oversized" ? new byte[ProtocolLimits.MaxBootstrapBytes + 1] : StrictJson.Serialize(json));
            var error = Record.Exception(() => BootstrapReader.Read(path, root)); Assert.NotNull(error);
            if (kind == "version") Assert.Equal(ErrorCodes.AgentVersionMismatch, Assert.IsType<ProtocolException>(error).Code);
            Assert.False(File.Exists(path));
        }
        finally { Directory.Delete(root, true); }
    }

    [Fact]
    public void OutsideRootRemainsUntouched()
    {
        var path = Path.GetTempFileName(); try { Assert.Throws<InvalidDataException>(() => BootstrapReader.Read(path, Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString()))); Assert.True(File.Exists(path)); } finally { File.Delete(path); }
    }

    [Fact]
    [Trait("Category", "Security")]
    public void BootstrapFileReparsePointIsRejected()
    {
        var root = Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString());
        Directory.CreateDirectory(root);
        try
        {
            var target = Path.Combine(root, "target.json");
            var link = Path.Combine(root, "link.json");
            File.WriteAllBytes(target, StrictJson.Serialize(Settings().ToJson()));
            try { File.CreateSymbolicLink(link, target); }
            catch (Exception error) when (error is UnauthorizedAccessException || error is IOException)
            { throw Xunit.Sdk.SkipException.ForSkip("File symbolic links are not permitted."); }
            Assert.Throws<InvalidDataException>(() => BootstrapReader.Read(link, root));
            Assert.True(File.Exists(target));
        }
        finally { Directory.Delete(root, true); }
    }

    [Fact]
    [Trait("Category", "Security")]
    public void BootstrapParentReparsePointIsRejected()
    {
        var root = Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString());
        var target = Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString());
        Directory.CreateDirectory(root);
        Directory.CreateDirectory(target);
        try
        {
            var file = Path.Combine(target, "settings.json");
            File.WriteAllBytes(file, StrictJson.Serialize(Settings().ToJson()));
            var link = Path.Combine(root, "junction");
            using var process = Process.Start(new ProcessStartInfo("cmd.exe")
            {
                UseShellExecute = false, CreateNoWindow = true,
                ArgumentList = { "/c", "mklink", "/J", link, target }
            })!;
            process.WaitForExit();
            if (process.ExitCode != 0) throw Xunit.Sdk.SkipException.ForSkip("Junction creation is not permitted.");
            Assert.Throws<InvalidDataException>(() => BootstrapReader.Read(Path.Combine(link, "settings.json"), root));
            Assert.True(File.Exists(file));
        }
        finally
        {
            var link = Path.Combine(root, "junction");
            if (Directory.Exists(link)) Directory.Delete(link);
            Directory.Delete(root, true);
            Directory.Delete(target, true);
        }
    }

    [Fact]
    public void StartNeverThrowsForInvalidPaths()
    {
        Assert.Equal(1, EntryPoint.Start(null!)); Assert.Equal(1, EntryPoint.Start("")); Assert.NotEqual(0, EntryPoint.Start("bad\0path"));
    }

    [Fact]
    public void StartWithValidPathReturnsPromptly()
    {
        var path = Path.Combine(BootstrapReader.BootstrapRoot, Guid.NewGuid() + ".json");
        var timer = Stopwatch.StartNew();
        var result = EntryPoint.Start(path);
        timer.Stop();
        Assert.Equal(0, result);
        Assert.True(timer.Elapsed < TimeSpan.FromMilliseconds(100), $"Start took {timer.Elapsed}.");
    }

    [Fact]
    public async Task IdleTimeoutDisposesServiceAndAllowsNewHost()
    {
        var settings = Settings(); settings.IdleTimeoutMs = 200;
        var factory = new FakeFactory();
        using var host = new SessionHost(settings, factory);
        await Task.Run(host.Run).WaitAsync(TimeSpan.FromSeconds(5));
        Assert.True(factory.Service.Disposed);
        Assert.Equal(SessionState.Detached, host.State);
        using var next = new SessionHost(Settings(), new FakeFactory());
        var task = Task.Run(next.Run);
        await Task.Delay(150);
        next.Dispose();
        await task.WaitAsync(TimeSpan.FromSeconds(5));
        Assert.Equal(SessionState.Detached, next.State);
    }

    [Fact]
    public async Task MutexRejectsConcurrentHost()
    {
        using var first = new SessionHost(Settings(), new FakeFactory());
        var running = Task.Run(first.Run);
        for (int attempt = 0; attempt < 100 && first.State != SessionState.Ready; attempt++) await Task.Delay(10);
        Assert.Equal(SessionState.Ready, first.State);
        using var second = new SessionHost(Settings(), new FakeFactory());
        await Task.Run(second.Run).WaitAsync(TimeSpan.FromSeconds(5));
        Assert.Equal(SessionState.Faulted, second.State);
        first.Dispose(); await running.WaitAsync(TimeSpan.FromSeconds(5));
    }

    [Theory]
    [Trait("Category", "Security")]
    [InlineData("success")][InlineData("realSid")][InlineData("token")][InlineData("session")][InlineData("major")][InlineData("sid")][InlineData("first")]
    public async Task HelloAuthentication(string mode)
    {
        var settings = Settings();
        using var server = new PipeServer(settings, new RequestDispatcher(settings.SessionId, new FakeService()), mode == "realSid" ? new ClientIdentityVerifier() : new Verifier(mode != "sid"), false, () => { });
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        var serving = server.RunAsync(timeout.Token);
        using var client = new NamedPipeClientStream(".", settings.PipeName, PipeDirection.InOut, PipeOptions.Asynchronous);
        await client.ConnectAsync(timeout.Token);
        var hello = new HelloParams { ProtocolMajor = 1, ProtocolMinor = 0, SessionId = settings.SessionId, Token = settings.Token, Process = settings.Process };
        if (mode == "token") hello.Token = Convert.ToBase64String(new byte[32] { 1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0 });
        if (mode == "session") hello.SessionId = Guid.NewGuid().ToString();
        var args = hello.ToJson();
        if (mode == "major") { args = new JsonObjectNode(); args.Add("protocolMajor", JsonNumberNode.From(2)); args.Add("protocolMinor", JsonNumberNode.From(0)); args.Add("sessionId", new JsonStringNode(hello.SessionId)); args.Add("token", new JsonStringNode(hello.Token)); args.Add("process", hello.Process.ToJson()); }
        var request = new RequestEnvelope { Id = 1, Method = mode == "first" ? PipeMethods.Close : PipeMethods.Hello, Params = args };
        try { await FrameCodec.WriteFrameAsync(client, StrictJson.Serialize(request.ToJson()), timeout.Token); } catch (IOException) when (mode == "sid") { }
        if (mode == "success" || mode == "realSid")
        {
            var bytes = await FrameCodec.ReadFrameAsync(client, timeout.Token); Assert.NotNull(bytes);
            var response = ResponseEnvelope.FromJson(StrictJson.Parse(bytes!, 0, bytes!.Length)); Assert.Empty(HelloResult.FromJson(response.Result!).Features);
            await FrameCodec.WriteFrameAsync(client, StrictJson.Serialize(new RequestEnvelope { Id = 2, Method = PipeMethods.Close }.ToJson()), timeout.Token);
            Assert.NotNull(await FrameCodec.ReadFrameAsync(client, timeout.Token));
        }
        await serving.WaitAsync(timeout.Token);
        if (mode != "success" && mode != "realSid") { server.Dispose(); Assert.Null(await FrameCodec.ReadFrameAsync(client, timeout.Token)); }
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task HelloAdvertisesExactMappingOnlyWhenAvailable(bool available)
    {
        var settings = Settings();
        using var server = new PipeServer(settings, new RequestDispatcher(settings.SessionId, new FakeService()), new Verifier(true), true, () => { }, available);
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        var serving = server.RunAsync(timeout.Token);
        using var client = new NamedPipeClientStream(".", settings.PipeName, PipeDirection.InOut, PipeOptions.Asynchronous);
        await client.ConnectAsync(timeout.Token);
        var hello = new HelloParams { ProtocolMajor = 1, ProtocolMinor = 0, SessionId = settings.SessionId, Token = settings.Token, Process = settings.Process };
        await FrameCodec.WriteFrameAsync(client, StrictJson.Serialize(new RequestEnvelope { Id = 1, Method = PipeMethods.Hello, Params = hello.ToJson() }.ToJson()), timeout.Token);
        var bytes = (await FrameCodec.ReadFrameAsync(client, timeout.Token))!;
        var response = HelloResult.FromJson(ResponseEnvelope.FromJson(StrictJson.Parse(bytes, 0, bytes.Length)).Result!);
        Assert.Equal(available, response.Features.Contains(Features.ExactUiaMapping));
        await FrameCodec.WriteFrameAsync(client, StrictJson.Serialize(new RequestEnvelope { Id = 2, Method = PipeMethods.Close }.ToJson()), timeout.Token);
        await FrameCodec.ReadFrameAsync(client, timeout.Token);
        await serving.WaitAsync(timeout.Token);
    }

    [Fact]
    [Trait("Category", "Security")]
    public async Task SecondConnectionIsRefused()
    {
        var settings = Settings();
        using var server = new PipeServer(settings, new RequestDispatcher(settings.SessionId, new FakeService()), new Verifier(true), false, () => { });
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        var serving = server.RunAsync(timeout.Token);
        using var client = new NamedPipeClientStream(".", settings.PipeName, PipeDirection.InOut, PipeOptions.Asynchronous);
        await client.ConnectAsync(timeout.Token);
        using var second = new NamedPipeClientStream(".", settings.PipeName, PipeDirection.InOut, PipeOptions.Asynchronous);
        using var shortTimeout = new CancellationTokenSource(TimeSpan.FromMilliseconds(250));
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => second.ConnectAsync(shortTimeout.Token));
        client.Dispose(); await serving.WaitAsync(timeout.Token);
    }

    [Fact(Skip = "requires dedicated test account")]
    [Trait("Category", "Security")]
    public void DifferentAccountCannotConnect() { }

    private sealed class Verifier(bool allowed) : IClientIdentityVerifier
    { public bool IsExpectedClient(SafePipeHandle pipe, string expectedSid) => allowed; }

    private sealed class FakeFactory : IInspectionServiceFactory
    {
        public FakeService Service { get; } = new();
        public IInspectionService Create(string sessionId) => Service;
    }

    private sealed class FakeService : IInspectionService
    {
        public bool Disposed { get; private set; }
        public void Dispose() => Disposed = true;
        public Task<MappingDto> ResolveAsync(int[] runtimeId, long? nativeWindowHandle, CancellationToken ct) => throw new NotSupportedException();
        public Task<ReadBatchResult> ReadBatchAsync(IReadOnlyList<CandidateRequest> candidates, IReadOnlyList<IReadOnlyList<PathSegment>> paths, CancellationToken ct) => throw new NotSupportedException();
        public Task<PageDto<ManagedNodeDto>> RootsAsync(int? pageSize, string? pageToken, CancellationToken ct) => Task.FromResult(new PageDto<ManagedNodeDto> { Complete = true, SnapshotId = "snapshot" });
        public Task<PageDto<ManagedNodeDto>> ChildrenAsync(string objectId, long generation, string tree, int? pageSize, string? pageToken, CancellationToken ct) => throw new NotSupportedException();
        public Task<PageDto<WinTestKit.Inspector.Protocol.MemberInfo>> MembersAsync(string objectId, long generation, int? pageSize, string? pageToken, CancellationToken ct) => throw new NotSupportedException();
        public Task<ReadResult> ReadAsync(string objectId, long generation, IReadOnlyList<IReadOnlyList<PathSegment>> paths, CancellationToken ct) => throw new NotSupportedException();
        public Task<IReadOnlyList<BindingInfoDto>> BindingsAsync(string objectId, long generation, IReadOnlyList<string> memberKeys, CancellationToken ct) => throw new NotSupportedException();
        public Task<int> ReleaseAsync(IReadOnlyList<string> objectIds, CancellationToken ct) => throw new NotSupportedException();
    }

    [Theory]
    [InlineData(3)]
    [InlineData(1)]
    public async Task ReusedOrDecreasingIdClosesPipe(long invalidId)
    {
        var settings = Settings();
        using var server = new PipeServer(settings, new RequestDispatcher(settings.SessionId, new FakeService()), new Verifier(true), false, () => { });
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        var serving = server.RunAsync(timeout.Token);
        using var client = new NamedPipeClientStream(".", settings.PipeName, PipeDirection.InOut, PipeOptions.Asynchronous);
        await client.ConnectAsync(timeout.Token);
        await Send(client, new RequestEnvelope { Id = 1, Method = PipeMethods.Hello, Params = new HelloParams { ProtocolMajor = 1, ProtocolMinor = 0, SessionId = settings.SessionId, Token = settings.Token, Process = settings.Process }.ToJson() }, timeout.Token);
        Assert.NotNull(await FrameCodec.ReadFrameAsync(client, timeout.Token));
        var unknown = new JsonObjectNode(); unknown.Add("id", JsonNumberNode.From(2)); unknown.Add("method", new JsonStringNode("unknown")); unknown.Add("params", new JsonObjectNode());
        await FrameCodec.WriteFrameAsync(client, StrictJson.Serialize(unknown), timeout.Token);
        var invalid = await FrameCodec.ReadFrameAsync(client, timeout.Token);
        Assert.Equal(ErrorCodes.InvalidParams, ResponseEnvelope.FromJson(StrictJson.Parse(invalid!, 0, invalid!.Length)).Error!.Code);
        await Send(client, new RequestEnvelope { Id = 3, Method = PipeMethods.Roots, Params = new RootsParams { SessionId = settings.SessionId }.ToJson() }, timeout.Token);
        Assert.NotNull(await FrameCodec.ReadFrameAsync(client, timeout.Token));
        await Send(client, new RequestEnvelope { Id = invalidId, Method = PipeMethods.Close }, timeout.Token);
        await serving.WaitAsync(timeout.Token);
        server.Dispose();
        Assert.Null(await FrameCodec.ReadFrameAsync(client, timeout.Token));
    }

    [Fact]
    public async Task RealPipeRoutesRootsAndClosesAfterResponse()
    {
        var settings = Settings();
        using var server = new PipeServer(settings, new RequestDispatcher(settings.SessionId, new FakeService()), new Verifier(true), false, () => { });
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        var serving = server.RunAsync(timeout.Token);
        using var client = new NamedPipeClientStream(".", settings.PipeName, PipeDirection.InOut, PipeOptions.Asynchronous);
        await client.ConnectAsync(timeout.Token);
        await Send(client, new RequestEnvelope { Id = 1, Method = PipeMethods.Hello, Params = new HelloParams { ProtocolMajor = 1, ProtocolMinor = 0, SessionId = settings.SessionId, Token = settings.Token, Process = settings.Process }.ToJson() }, timeout.Token);
        Assert.NotNull(await FrameCodec.ReadFrameAsync(client, timeout.Token));
        await Send(client, new RequestEnvelope { Id = 2, Method = PipeMethods.Roots, Params = new RootsParams { SessionId = settings.SessionId }.ToJson() }, timeout.Token);
        var roots = await FrameCodec.ReadFrameAsync(client, timeout.Token);
        var rootsResponse = ResponseEnvelope.FromJson(StrictJson.Parse(roots!, 0, roots!.Length));
        Assert.True(PageDto<ManagedNodeDto>.FromJson(rootsResponse.Result!, ManagedNodeDto.FromJson).Complete);
        await Send(client, new RequestEnvelope { Id = 4, Method = PipeMethods.Close }, timeout.Token);
        var close = await FrameCodec.ReadFrameAsync(client, timeout.Token);
        Assert.True(CloseResult.FromJson(ResponseEnvelope.FromJson(StrictJson.Parse(close!, 0, close!.Length)).Result!).Closed);
        await serving.WaitAsync(timeout.Token);
        server.Dispose();
        Assert.Null(await FrameCodec.ReadFrameAsync(client, timeout.Token));
    }

    private sealed class TestHandler : ISessionRequestHandler
    {
        public async Task<ResponseEnvelope> HandleAsync(RequestEnvelope request, CancellationToken ct)
        {
            if (request.Method == PipeMethods.Close) return new ResponseEnvelope { Id = request.Id, Result = new CloseResult { Closed = true }.ToJson() };
            await Task.Delay((int)(request.Id % 7), ct);
            return new ResponseEnvelope { Id = request.Id, Result = new JsonStringNode(request.Id == 2 ? new string('x', ProtocolLimits.MaxResponseBytes) : "ok") };
        }
    }

    [Fact]
    public async Task ConcurrentResponsesAreUniqueAndOversizedResponseIsLimited()
    {
        var settings = Settings();
        using var server = new PipeServer(settings, new TestHandler(), new Verifier(true), false, () => { });
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        var serving = server.RunAsync(timeout.Token);
        using var client = new NamedPipeClientStream(".", settings.PipeName, PipeDirection.InOut, PipeOptions.Asynchronous);
        await client.ConnectAsync(timeout.Token);
        await Send(client, new RequestEnvelope { Id = 1, Method = PipeMethods.Hello, Params = new HelloParams { ProtocolMajor = 1, ProtocolMinor = 0, SessionId = settings.SessionId, Token = settings.Token, Process = settings.Process }.ToJson() }, timeout.Token);
        Assert.NotNull(await FrameCodec.ReadFrameAsync(client, timeout.Token));
        for (int id = 2; id <= 201; id++) await Send(client, new RequestEnvelope { Id = id, Method = PipeMethods.Roots, Params = new RootsParams { SessionId = settings.SessionId }.ToJson() }, timeout.Token);
        var ids = new HashSet<long>();
        for (int index = 0; index < 200; index++)
        {
            var frame = await FrameCodec.ReadFrameAsync(client, timeout.Token);
            Assert.NotNull(frame);
            var response = ResponseEnvelope.FromJson(StrictJson.Parse(frame!, 0, frame!.Length));
            Assert.True(ids.Add(response.Id));
            if (response.Id == 2) Assert.Equal(ErrorCodes.LimitExceeded, response.Error!.Code);
        }
        Assert.Equal(200, ids.Count);
        await Send(client, new RequestEnvelope { Id = 202, Method = PipeMethods.Close }, timeout.Token);
        Assert.NotNull(await FrameCodec.ReadFrameAsync(client, timeout.Token));
        await serving.WaitAsync(timeout.Token);
    }

    private static Task Send(Stream stream, RequestEnvelope request, CancellationToken ct) => FrameCodec.WriteFrameAsync(stream, StrictJson.Serialize(request.ToJson()), ct);
}
