using System.Diagnostics;
using System.IO.Pipes;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using Microsoft.Win32.SafeHandles;
using WinTestKit.Inspector.Protocol;

internal static class OwnedFixture
{
    internal static async Task Run(string repo, string runtime, string arch, string[] options)
    {
        PackageVerifier.Require(new[] { "net48", "net8", "net10" }.Contains(runtime) && new[] { "x86", "x64" }.Contains(arch), "Invalid cell");
        PackageVerifier.Require(options.All(x => x is "--adverse" or "--bad-token"), "Invalid harness option");
        if (runtime == "net10" && arch == "x86")
        {
            string x86Root = @"C:\Program Files (x86)\dotnet\shared";
            foreach (string framework in new[] { "Microsoft.NETCore.App", "Microsoft.WindowsDesktop.App" })
            {
                string path = Path.Combine(x86Root, framework);
                PackageVerifier.Require(Directory.Exists(path) && Directory.EnumerateDirectories(path, "10.*").Any(), "Required x86 .NET 10 runtime is not installed; fixture was not started");
            }
        }
        repo = Path.GetFullPath(repo);
        string tfm = runtime switch { "net48" => "net48", "net8" => "net8.0-windows", _ => "net10.0-windows" };
        string fixtureDir = Path.Combine(repo, "wpf-inspector", "tests", "Fixtures", "WpfFixture", "bin", "cells", tfm + "-" + arch);
        string fixture = Path.Combine(fixtureDir, "WinTestKit.Fixture.exe");
        string payload = Path.Combine(repo, "inspector-payload", "src", "wintestkit_inspector", "payload");
        var versionMatch = Regex.Match(File.ReadAllText(Path.Combine(repo, "python", "src", "wintestkit", "__init__.py")), @"(?m)^__version__\s*=\s*['""]([^'""]+)['""]");
        PackageVerifier.Require(versionMatch.Success, "Cannot determine the expected inspector version");
        string version = versionMatch.Groups[1].Value;
        PackageVerifier.Verify(payload, version, "2bf48f60c2bb1753001f6be9122395def9070fa9");
        PackageVerifier.Require(File.Exists(fixture), "Published fixture missing");
        var before = HashFixture(fixtureDir);
        string reportDir = Path.Combine(repo, "wpf-inspector", "artifacts", "verification");
        Directory.CreateDirectory(reportDir);
        string hashReport = Path.Combine(reportDir, "fixture-" + Guid.NewGuid().ToString("N") + ".json");
        File.WriteAllText(hashReport, JsonSerializer.Serialize(before));
        var start = new ProcessStartInfo(fixture) { UseShellExecute = false, RedirectStandardOutput = true, RedirectStandardError = true, WorkingDirectory = fixtureDir };
        string? dotnetRoot = Environment.GetEnvironmentVariable("DOTNET_ROOT") ??
            Environment.GetEnvironmentVariable("PATH")?.Split(Path.PathSeparator)
                .FirstOrDefault(path => File.Exists(Path.Combine(path, "dotnet.exe")));
        if (dotnetRoot is not null) start.Environment["DOTNET_ROOT_X64"] = dotnetRoot;
        start.Environment["DOTNET_ROOT_X86"] = @"C:\Program Files (x86)\dotnet";
        using Process target = Process.Start(start) ?? throw new InvalidOperationException("Fixture did not start");
        _ = target.StandardOutput.ReadToEndAsync();
        _ = target.StandardError.ReadToEndAsync();
        Process? launcher = null;
        string? sessionDir = null, bootstrap = null;
        NamedPipeClientStream? pipe = null;
        bool hangArmed = false;
        try
        {
            await WaitForFixture(target);
            PackageVerifier.Require(before.OrderBy(x => x.Key).SequenceEqual(HashFixture(fixtureDir).OrderBy(x => x.Key)), "Fixture files changed during startup");
            DateTime created = target.StartTime.ToUniversalTime();
            string createdText = created.ToString("O");
            var identity = new { pid = target.Id, creationTimeUtc = createdText };
            var beforeModules = ConflictModules(target);
            var fixturePackages = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            foreach (string name in runtime == "net48" ? new[] { "Newtonsoft.Json.dll", "System.Text.Json.dll", "System.Memory.dll" } : new[] { "Newtonsoft.Json.dll" })
            {
                string path = Path.Combine(fixtureDir, name);
                PackageVerifier.Require(File.Exists(path), "Fixture conflict package missing: " + name);
                fixturePackages[name] = AssemblyName.GetAssemblyName(path).Version!.ToString();
            }
            // Framework can map managed assemblies without exposing them through
            // Process.Modules. Its startup serializes with Newtonsoft and STJ
            // before creating the control pipe; STJ is exercised again below.
            if (runtime != "net48") PackageVerifier.Require(beforeModules.ContainsKey("Newtonsoft.Json.dll") && beforeModules.ContainsKey("System.Text.Json.dll"), "Fixture conflict dependencies not visible as loaded modules");
            string sid = WindowsIdentity.GetCurrent().User?.Value ?? throw new InvalidOperationException("No user SID");
            string session = Guid.NewGuid().ToString();
            string pipeName = $"WinTestKit.Inspector.{target.Id}.{session}";
            string token = Convert.ToBase64String(RandomNumberGenerator.GetBytes(32));
            string bootstrapRoot = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "WinTestKit", "inspector", "bootstrap");
            Directory.CreateDirectory(bootstrapRoot);
            for (var current = new DirectoryInfo(bootstrapRoot); current != null && current.FullName.StartsWith(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), StringComparison.OrdinalIgnoreCase); current = current.Parent)
                PackageVerifier.Require((current.Attributes & FileAttributes.ReparsePoint) == 0, "Bootstrap path contains a reparse point");
            string newSessionDir = Path.Combine(bootstrapRoot, session);
            CreatePrivateDirectory(newSessionDir, sid);
            sessionDir = newSessionDir;
            VerifyPrivateAcl(new DirectoryInfo(sessionDir).GetAccessControl(), sid, true);
            string newBootstrap = Path.Combine(sessionDir, Convert.ToHexStringLower(RandomNumberGenerator.GetBytes(16)) + ".json");
            var settings = new { schemaVersion = 1, protocolMajor = ProtocolInfo.Major, protocolMinor = ProtocolInfo.Minor, sessionId = session, process = identity, pipeName, token, clientSid = sid, expiresUtc = DateTime.UtcNow.AddSeconds(30).ToString("O"), requestTimeoutMs = 2000, idleTimeoutMs = 300000, agentVersion = version, redactNames = new[] { "Title" }, writeAllowlist = new { properties = Array.Empty<string>(), methods = Array.Empty<string>() } };
            using (var file = new FileStream(newBootstrap, FileMode.CreateNew, FileAccess.Write, FileShare.None)) { bootstrap = newBootstrap; JsonSerializer.Serialize(file, settings); }
            VerifyPrivateAcl(new FileInfo(bootstrap).GetAccessControl(), sid, false);
            string exe = Path.Combine(payload, "launchers", arch, $"Snoop.InjectorLauncher.{arch}.exe");
            string agent = Path.Combine(payload, "agents", runtime, "WinTestKit.Inspector.Agent.dll");
            var launch = new ProcessStartInfo(exe) { UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true, WorkingDirectory = Path.GetDirectoryName(exe)! };
            foreach (string arg in new[] { "--targetPID", target.Id.ToString(), "--assembly", agent, "--className", "WinTestKit.Inspector.Agent.EntryPoint", "--methodName", "Start", "--settingsFile", bootstrap }) launch.ArgumentList.Add(arg);
            var readiness = Stopwatch.StartNew();
            launcher = Process.Start(launch) ?? throw new InvalidOperationException("Launcher could not start");
            _ = launcher.StandardOutput.ReadToEndAsync();
            _ = launcher.StandardError.ReadToEndAsync();
            pipe = new NamedPipeClientStream(".", pipeName, PipeDirection.InOut, PipeOptions.Asynchronous);
            using (var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10))) await pipe.ConnectAsync(deadline.Token);
            PackageVerifier.Require(GetNamedPipeServerProcessId(pipe.SafePipeHandle, out uint serverPid) && serverPid == target.Id && target.StartTime.ToUniversalTime() == created && !target.HasExited, "Pipe server identity mismatch");
            string helloToken = options.Contains("--bad-token") ? Convert.ToBase64String(RandomNumberGenerator.GetBytes(32)) : token;
            var hello = new { id = 1, method = "session.hello", @params = new { protocolMajor = ProtocolInfo.Major, protocolMinor = ProtocolInfo.Minor, sessionId = session, token = helloToken, process = identity } };
            if (options.Contains("--bad-token"))
            {
                try { _ = await Exchange(pipe, hello, 1, 4000); throw new InvalidDataException("Wrong token was accepted"); }
                catch (EndOfStreamException) { Console.WriteLine($"{runtime}/{arch}: wrong token rejected with no response."); }
                PackageVerifier.Require(!File.Exists(bootstrap), "Bootstrap file was not consumed");
                return;
            }
            using var response = await Exchange(pipe, hello, 1, 10000);
            JsonElement result = GetResult(response);
            PackageVerifier.Require(result.GetProperty("agentVersion").GetString() == version && result.GetProperty("tfm").GetString() == tfm && result.GetProperty("architecture").GetString() == arch, "Hello version, framework or architecture mismatch");
            string runtimeVersion = result.GetProperty("runtimeVersion").GetString() ?? "";
            int expectedMajor = runtime == "net48" ? 4 : runtime == "net8" ? 8 : 10;
            PackageVerifier.Require(Version.TryParse(runtimeVersion, out var actualRuntime) && actualRuntime.Major == expectedMajor, "Hello runtime version mismatch");
            JsonElement responseProcess = result.GetProperty("process");
            PackageVerifier.Require(responseProcess.GetProperty("pid").GetInt32() == target.Id && DateTimeOffset.Parse(responseProcess.GetProperty("creationTimeUtc").GetString()!).UtcDateTime == created && target.StartTime.ToUniversalTime() == created, "Hello process identity mismatch");
            PackageVerifier.Require(readiness.Elapsed < TimeSpan.FromSeconds(10) && !File.Exists(bootstrap), "Readiness deadline or bootstrap deletion failed");
            Console.WriteLine($"{runtime}/{arch}: authenticated hello pid={target.Id} creationUtc={createdText} agent={version} tfm={tfm} architecture={arch} runtime={runtimeVersion} serverPid={serverPid} readinessMs={readiness.ElapsedMilliseconds}; bootstrap deleted.");
            long id = 2;
            PackageVerifier.Require(result.GetProperty("features").EnumerateArray().Any(feature => feature.GetString() == "query"), "Query feature was not advertised");
            using var query = await Exchange(pipe, new { id, method = "query.find", @params = new { locator = new { scope = new { kind = "allRoots" }, tree = "combined", predicates = new[] { new { kind = "equals", path = new[] { new { kind = "uia", name = "automation_id" } }, value = "MainWindow" } }, depth = 256, depthMode = "tree", limit = 200 }, timeoutMs = 2000 } }, id++, 5000);
            PackageVerifier.Require(GetResult(query).GetProperty("match").GetProperty("sessionId").GetString() == session, "Query did not find the fixture main window");
            JsonElement match = GetResult(query).GetProperty("match");
            PackageVerifier.Require(result.GetProperty("features").EnumerateArray().Any(feature => feature.GetString() == "waits"), "Wait feature was not advertised");
            using var wait = await Exchange(pipe, new { id, method = "wait.until", @params = new { condition = new { kind = "exists", locator = new { scope = new { kind = "object", handle = match }, tree = "logical", predicates = Array.Empty<object>(), depth = 0, depthMode = "tree", limit = 200 } }, timeoutMs = 1000 } }, id++, 5000);
            PackageVerifier.Require(GetResult(wait).GetProperty("satisfied").GetBoolean(), "Wait did not find the fixture root");
            using var waitMissing = await Exchange(pipe, new { id, method = "wait.until", @params = new { condition = new { kind = "exists", locator = new { scope = new { kind = "object", handle = match }, tree = "logical", predicates = new[] { new { kind = "equals", path = new[] { new { kind = "uia", name = "automation_id" } }, value = "missing" } }, depth = 0, depthMode = "tree", limit = 200 } }, timeoutMs = 150 } }, id++, 5000);
            PackageVerifier.Require(!GetResult(waitMissing).GetProperty("satisfied").GetBoolean(), "Missing wait did not time out");
            PackageVerifier.Require(result.GetProperty("features").EnumerateArray().Any(feature => feature.GetString() == "geometry"), "Geometry feature was not advertised");
            using var stateResponse = await Exchange(pipe, new { id, method = "state.get", @params = new { handle = match, timeoutMs = 2000 } }, id++, 5000);
            JsonElement state = GetResult(stateResponse).GetProperty("state");
            PackageVerifier.Require(state.GetProperty("bounds").ValueKind == JsonValueKind.Object && state.GetProperty("windowHandle").GetInt64() == target.MainWindowHandle.ToInt64() && state.GetProperty("uiaRuntimeId").GetArrayLength() > 0, "State geometry or UIA runtime ID mismatch");
            using var queryAll = await Exchange(pipe, new { id, method = "query.findAll", @params = new { locator = new { scope = new { kind = "object", handle = match }, tree = "logical", predicates = Array.Empty<object>(), depth = 0, depthMode = "tree", limit = 200 }, timeoutMs = 2000 } }, id++, 5000);
            PackageVerifier.Require(GetResult(queryAll).GetProperty("complete").GetBoolean() && GetResult(queryAll).GetProperty("count").GetInt32() == 1, "Scoped query.findAll did not return its root");
            var stale = new { sessionId = session, objectId = match.GetProperty("objectId").GetString(), generation = match.GetProperty("generation").GetInt64() + 1, type = match.GetProperty("type"), dispatcherId = match.GetProperty("dispatcherId").GetString() };
            using var staleState = await Exchange(pipe, new { id, method = "state.get", @params = new { handle = stale, timeoutMs = 2000 } }, id++, 5000);
            PackageVerifier.Require(staleState.RootElement.GetProperty("error").GetProperty("code").GetString() == "objectStale", "State accepted a stale handle");
            using var staleQuery = await Exchange(pipe, new { id, method = "query.find", @params = new { locator = new { scope = new { kind = "object", handle = stale }, tree = "logical", predicates = Array.Empty<object>(), depth = 0, depthMode = "tree", limit = 200 }, timeoutMs = 2000 } }, id++, 5000);
            PackageVerifier.Require(staleQuery.RootElement.GetProperty("error").GetProperty("code").GetString() == "objectStale", "Query accepted a stale scope");
            using var missingQuery = await Exchange(pipe, new { id, method = "query.find", @params = new { locator = new { scope = new { kind = "object", handle = match }, tree = "logical", predicates = new[] { new { kind = "equals", path = new[] { new { kind = "uia", name = "automation_id" } }, value = "missing" } }, depth = 0, depthMode = "tree", limit = 200 }, timeoutMs = 2000 } }, id++, 5000);
            PackageVerifier.Require(missingQuery.RootElement.GetProperty("error").GetProperty("code").GetString() == "notFound", "Query should report a missing match");
            using var redactedQuery = await Exchange(pipe, new { id, method = "query.find", @params = new { locator = new { scope = new { kind = "object", handle = match }, tree = "logical", predicates = new[] { new { kind = "equals", path = new[] { new { kind = "property", name = "Title" } }, value = "unused" } }, depth = 0, depthMode = "tree", limit = 200 }, timeoutMs = 2000 } }, id++, 5000);
            JsonElement redactedError = redactedQuery.RootElement.GetProperty("error");
            PackageVerifier.Require(redactedError.GetProperty("code").GetString() == "valueUnreadable" && redactedError.GetProperty("details").GetProperty("status").GetString() == "redacted" && !redactedError.GetProperty("details").TryGetProperty("path", out _), "Query did not preserve bootstrap redaction details");
            using var roots = await Exchange(pipe, new { id, method = "roots", @params = new { sessionId = session } }, id++, 5000);
            JsonElement items = GetResult(roots).GetProperty("items");
            PackageVerifier.Require(items.GetArrayLength() > 0, "Agent returned no WPF roots");
            JsonElement first = items[0].GetProperty("object");
            using var read = await ReadType(pipe, session, first, id++);
            PackageVerifier.Require(GetResult(read).GetProperty("values")[0].GetProperty("value").GetProperty("status").GetString() == "ok", "Agent type read failed");
            Console.WriteLine($"{runtime}/{arch}: real WPF roots={items.GetArrayLength()}; type metadata read succeeded.");
            if (options.Contains("--adverse"))
            {
                hangArmed = true;
                id = await Adverse(pipe, target.Id, session, items, id);
                hangArmed = false;
            }
            using var close = await Exchange(pipe, new { id, method = "session.close", @params = new { } }, id, 5000);
            PackageVerifier.Require(GetResult(close).GetProperty("closed").GetBoolean(), "Detach did not acknowledge close");
            pipe.Dispose(); pipe = null;
            await Task.Delay(200);
            PackageVerifier.Require(!target.HasExited && target.StartTime.ToUniversalTime() == created, "Fixture exited after detach");
            await FixtureCommand(target.Id, new { cmd = "counters" });
            await FixtureCommand(target.Id, new { cmd = "scenario", name = "resetHang" });
            hangArmed = true;
            await FixtureCommand(target.Id, new { cmd = "scenario", name = "blockDispatcher" });
            await WaitForCounter(target.Id, "dispatcher.blocked");
            await FixtureCommand(target.Id, new { cmd = "scenario", name = "releaseHang" });
            await WaitForCounter(target.Id, "dispatcher.released");
            hangArmed = false;
            var afterModules = ConflictModules(target);
            PackageVerifier.Require(beforeModules.Count == afterModules.Count && beforeModules.All(x => afterModules.TryGetValue(x.Key, out string? value) && value == x.Value), "Fixture conflict module changed during attach");
            PackageVerifier.Require(before.OrderBy(x => x.Key).SequenceEqual(HashFixture(fixtureDir).OrderBy(x => x.Key)), "Fixture files changed during attach");
            PackageVerifier.Require(File.Exists(hashReport), "Fixture pre-start hash report missing");
            using var startupHashes = JsonDocument.Parse(File.ReadAllBytes(hashReport));
            foreach (var item in before) PackageVerifier.Require(startupHashes.RootElement.GetProperty(item.Key).GetString() == item.Value, "Fixture pre-start hash report mismatch");
            Console.WriteLine($"{runtime}/{arch}: session.close acknowledged; fixture dispatcher processed a post-detach operation; {before.Count} executable/configuration/dependency hashes unchanged; fixture package assembly versions: {string.Join(", ", fixturePackages.Select(x => x.Key + "=" + x.Value))}; visible conflict modules: {string.Join(", ", beforeModules.Select(x => x.Key + "=" + x.Value))}.");
        }
        finally
        {
            if (hangArmed) { try { await FixtureCommand(target.Id, new { cmd = "scenario", name = "releaseHang" }); } catch (Exception) { } }
            pipe?.Dispose();
            if (launcher != null) { try { if (!launcher.HasExited) { launcher.Kill(); launcher.WaitForExit(); } } finally { launcher.Dispose(); } }
            if (!target.HasExited) { target.Kill(); target.WaitForExit(); }
            if (bootstrap != null && File.Exists(bootstrap)) File.Delete(bootstrap);
            if (sessionDir != null && Directory.Exists(sessionDir)) Directory.Delete(sessionDir, false);
        }
    }

    private static async Task WaitForFixture(Process target)
    {
        var watch = Stopwatch.StartNew();
        while (watch.Elapsed < TimeSpan.FromSeconds(15))
        {
            if (target.HasExited) throw new InvalidOperationException($"Fixture exited during startup (exit code {target.ExitCode})");
            target.Refresh();
            if (target.MainWindowHandle != IntPtr.Zero)
            {
                try { await FixtureCommand(target.Id, new { cmd = "counters" }); return; } catch (IOException) { } catch (TimeoutException) { }
            }
            await Task.Delay(100);
        }
        throw new TimeoutException("Fixture window/control pipe did not become ready");
    }

    private static async Task<JsonDocument> Exchange(NamedPipeClientStream pipe, object message, long expectedId, int timeoutMs)
    {
        using var timeout = new CancellationTokenSource(timeoutMs);
        byte[] bytes = JsonSerializer.SerializeToUtf8Bytes(message);
        byte[] header = BitConverter.GetBytes(bytes.Length);
        await pipe.WriteAsync(header, timeout.Token); await pipe.WriteAsync(bytes, timeout.Token); await pipe.FlushAsync(timeout.Token);
        await pipe.ReadExactlyAsync(header, timeout.Token);
        int length = BitConverter.ToInt32(header);
        PackageVerifier.Require(length > 0 && length <= 1048576, "Invalid response frame length");
        bytes = new byte[length]; await pipe.ReadExactlyAsync(bytes, timeout.Token);
        var response = JsonDocument.Parse(bytes);
        PackageVerifier.Require(response.RootElement.GetProperty("id").GetInt64() == expectedId, "Response ID mismatch");
        return response;
    }

    private static JsonElement GetResult(JsonDocument response)
    {
        if (response.RootElement.TryGetProperty("error", out var error)) throw new InvalidDataException("Agent request failed: " + error.GetProperty("code").GetString());
        return response.RootElement.GetProperty("result");
    }
    private static Task<JsonDocument> ReadType(NamedPipeClientStream pipe, string session, JsonElement obj, long id) =>
        Exchange(pipe, new { id, method = "read", @params = new { sessionId = session, objectId = obj.GetProperty("objectId").GetString(), generation = obj.GetProperty("generation").GetInt64(), paths = new[] { new[] { new { kind = "type", name = "FullName" } } } } }, id, 5000);

    private static async Task<long> Adverse(NamedPipeClientStream pipe, int pid, string session, JsonElement initialRoots, long id)
    {
        await FixtureCommand(pid, new { cmd = "scenario", name = "openSecondWindow" });
        await Task.Delay(1000);
        using var rootsDoc = await Exchange(pipe, new { id, method = "roots", @params = new { sessionId = session } }, id++, 5000);
        JsonElement roots = GetResult(rootsDoc).GetProperty("items");
        PackageVerifier.Require(roots.GetArrayLength() >= 2, "Second dispatcher root was not discovered");
        JsonElement main = default, second = default;
        foreach (var root in roots.EnumerateArray())
        {
            string label = root.GetProperty("label").GetString() ?? "";
            if (label == "MainWindow") main = root.GetProperty("object").Clone();
            if (label == "Window") second = root.GetProperty("object").Clone();
        }
        PackageVerifier.Require(main.ValueKind == JsonValueKind.Object && second.ValueKind == JsonValueKind.Object, "Could not distinguish dispatcher roots");
        var queue = new Queue<JsonElement>(); queue.Enqueue(main);
        JsonElement control = default;
        for (int count = 0; queue.Count > 0 && count < 300 && control.ValueKind == JsonValueKind.Undefined; count++)
        {
            var obj = queue.Dequeue();
            using var children = await Exchange(pipe, new { id, method = "children", @params = new { sessionId = session, objectId = obj.GetProperty("objectId").GetString(), generation = obj.GetProperty("generation").GetInt64(), tree = "logical", pageSize = 200 } }, id++, 5000);
            foreach (var item in GetResult(children).GetProperty("items").EnumerateArray())
            {
                var child = item.GetProperty("object").Clone();
                if (item.GetProperty("label").GetString() == "FixtureControl") { control = child; break; }
                queue.Enqueue(child);
            }
        }
        PackageVerifier.Require(control.ValueKind == JsonValueKind.Object, "FixtureControl not found in managed logical tree");
        await FixtureCommand(pid, new { cmd = "scenario", name = "resetHang" });
        var watch = Stopwatch.StartNew();
        using var hanging = await Exchange(pipe, new { id, method = "read", @params = new { sessionId = session, objectId = control.GetProperty("objectId").GetString(), generation = control.GetProperty("generation").GetInt64(), paths = new[] { new[] { new { kind = "property", name = "Hanging" } } } } }, id++, 5000);
        long failureMs = watch.ElapsedMilliseconds;
        PackageVerifier.Require(hanging.RootElement.TryGetProperty("error", out var error) && new[] { "timeout", "dispatcherUnavailable" }.Contains(error.GetProperty("code").GetString()) && failureMs < 3500, "Hanging getter did not return a bounded failure");
        await Task.Delay(200);
        using var blocked = await ReadType(pipe, session, control, id++);
        PackageVerifier.Require(blocked.RootElement.TryGetProperty("error", out var blockedError) && blockedError.GetProperty("code").GetString() == "dispatcherUnavailable", "Blocked dispatcher admitted a later read");
        using var independent = await ReadType(pipe, session, second, id++);
        PackageVerifier.Require(GetResult(independent).GetProperty("values")[0].GetProperty("value").GetProperty("status").GetString() == "ok", "Second dispatcher read failed");
        var counters = await FixtureCommand(pid, new { cmd = "counters" });
        PackageVerifier.Require(counters.TryGetProperty("Hanging", out var calls) && calls.GetInt32() == 1, "Hanging getter was invoked more than once");
        await FixtureCommand(pid, new { cmd = "scenario", name = "releaseHang" });
        Console.WriteLine($"Adverse: hanging getter failed in {failureMs} ms, same dispatcher rejected a later read, second dispatcher remained readable, getter count=1; fixture released.");
        return id;
    }

    private static async Task WaitForCounter(int pid, string name)
    {
        var watch = Stopwatch.StartNew();
        while (watch.Elapsed < TimeSpan.FromSeconds(4))
        {
            var counters = await FixtureCommand(pid, new { cmd = "counters" });
            if (counters.TryGetProperty(name, out var value) && value.GetInt32() > 0) return;
            await Task.Delay(50);
        }
        throw new TimeoutException("Fixture dispatcher did not complete " + name);
    }

    private static async Task<JsonElement> FixtureCommand(int pid, object message)
    {
        using var pipe = new NamedPipeClientStream(".", "WinTestKit.Fixture." + pid, PipeDirection.InOut, PipeOptions.Asynchronous);
        using var timeout = new CancellationTokenSource(2000);
        try { await pipe.ConnectAsync(timeout.Token); } catch (OperationCanceledException) { throw new TimeoutException("Fixture control pipe timeout"); }
        using var writer = new StreamWriter(pipe, new UTF8Encoding(false), leaveOpen: true) { AutoFlush = true };
        using var reader = new StreamReader(pipe, Encoding.UTF8, false, leaveOpen: true);
        await writer.WriteLineAsync(JsonSerializer.Serialize(message));
        string line = await reader.ReadLineAsync(timeout.Token) ?? throw new EndOfStreamException();
        using var doc = JsonDocument.Parse(line);
        if (doc.RootElement.TryGetProperty("error", out _)) throw new InvalidDataException("Fixture control command failed");
        return doc.RootElement.Clone();
    }
    private static Dictionary<string, string> HashFixture(string directory) => Directory.EnumerateFiles(directory).Where(f => new[] { ".exe", ".dll", ".config", ".json" }.Contains(Path.GetExtension(f), StringComparer.OrdinalIgnoreCase)).ToDictionary(f => Path.GetFileName(f)!, f => Convert.ToHexStringLower(SHA256.HashData(File.ReadAllBytes(f))), StringComparer.OrdinalIgnoreCase);
    private static Dictionary<string, string> ConflictModules(Process process)
    {
        process.Refresh();
        var wanted = new[] { "Newtonsoft.Json.dll", "System.Text.Json.dll", "System.Memory.dll" };
        return process.Modules.Cast<ProcessModule>().Where(m => wanted.Contains(m.ModuleName, StringComparer.OrdinalIgnoreCase)).ToDictionary(m => m.ModuleName, m => FileVersionInfo.GetVersionInfo(m.FileName).FileVersion ?? "unknown", StringComparer.OrdinalIgnoreCase);
    }
    private static void CreatePrivateDirectory(string path, string sid)
    {
        if (!ConvertStringSecurityDescriptorToSecurityDescriptor($"D:P(A;OICI;FA;;;{sid})", 1, out var descriptor, out _)) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        try
        {
            var attributes = new SecurityAttributes { Length = Marshal.SizeOf<SecurityAttributes>(), SecurityDescriptor = descriptor };
            if (!CreateDirectory(path, ref attributes)) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        }
        finally { LocalFree(descriptor); }
    }
    private static void VerifyPrivateAcl(FileSystemSecurity security, string sid, bool requireProtected)
    {
        var rules = security.GetAccessRules(true, true, typeof(SecurityIdentifier)).Cast<FileSystemAccessRule>().ToArray();
        PackageVerifier.Require((!requireProtected || security.AreAccessRulesProtected) && rules.Length == 1 && rules[0].IdentityReference.Value == sid && rules[0].AccessControlType == AccessControlType.Allow && (rules[0].FileSystemRights & FileSystemRights.FullControl) == FileSystemRights.FullControl, "Bootstrap ACL is not user-only");
    }
    [StructLayout(LayoutKind.Sequential)] private struct SecurityAttributes { public int Length; public IntPtr SecurityDescriptor; public int InheritHandle; }
    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern bool ConvertStringSecurityDescriptorToSecurityDescriptor(string sddl, int revision, out IntPtr descriptor, out int size);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true, EntryPoint = "CreateDirectoryW")] private static extern bool CreateDirectory(string path, ref SecurityAttributes security);
    [DllImport("kernel32.dll")] private static extern IntPtr LocalFree(IntPtr memory);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool GetNamedPipeServerProcessId(SafePipeHandle pipe, out uint serverPid);
}
