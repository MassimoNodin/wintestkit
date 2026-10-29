using System.Security.Cryptography;
using System.Text.Json.Nodes;
using System.Text;

internal static class PackageNegativeTests
{
    internal static void Run(string source, string version, string upstream, string outputRoot)
    {
        source = Path.GetFullPath(source);
        outputRoot = Path.GetFullPath(outputRoot);
        Directory.CreateDirectory(outputRoot);
        string run = Path.Combine(outputRoot, "package-negative-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(run);
        PackageVerifier.Verify(source, version, upstream);
        int passed = 0;

        void Reject(string name, string expected, Action<string> mutate)
        {
            string copy = Path.Combine(run, name);
            Clone(source, copy);
            mutate(copy);
            try { PackageVerifier.Verify(copy, version, upstream); }
            catch (Exception error) when (error.Message.Contains(expected, StringComparison.Ordinal))
            {
                passed++; Console.WriteLine($"Rejected {name}: {error.Message}"); return;
            }
            throw new InvalidOperationException($"Negative case {name} did not fail as expected ({expected})");
        }

        Reject("tampered-dll", "Payload hash mismatch", root => File.AppendAllText(Path.Combine(root, "agents/net10/WinTestKit.Inspector.Agent.dll"), "tampered"));
        Reject("missing-dll", "Missing payload file", root => File.Delete(Path.Combine(root, "agents/net10/WinTestKit.Inspector.Agent.dll")));
        Reject("path-traversal", "Unexpected or duplicate file", root => Edit(root, m => m["files"]!.AsArray()[0]!["path"] = "../outside.exe"));
        Reject("version-drift", "Manifest version or upstream commit mismatch", root => Edit(root, m => m["inspectorVersion"] = "0.0.0"));
        Reject("duplicate-json", "Duplicate JSON key", root => { string path = Path.Combine(root, "manifest.json"); string text = File.ReadAllText(path); File.WriteAllText(path, text.Insert(text.IndexOf('{') + 1, "\"schemaVersion\":1,")); });
        Reject("unlisted-ui", "Payload contains missing or unlisted files", root => File.WriteAllText(Path.Combine(root, "Snoop.UI.dll"), "unexpected"));
        Reject("wrong-architecture", "Invalid PE architecture/type", root =>
        {
            string target = "launchers/x64/Snoop.GenericInjector.x64.dll";
            File.Copy(Path.Combine(root, "launchers/x86/Snoop.GenericInjector.x86.dll"), Path.Combine(root, target), true);
            Rehash(root, target);
        });
        Reject("wrong-tfm", "Unexpected target framework", root =>
        {
            string target = "agents/net10/WinTestKit.Inspector.Agent.dll";
            File.Copy(Path.Combine(root, "agents/net8/WinTestKit.Inspector.Agent.dll"), Path.Combine(root, target), true);
            Rehash(root, target);
        });
        Reject("wrong-native-export", "Native injector export missing", root =>
        {
            string target = "launchers/x64/Snoop.GenericInjector.x64.dll";
            string file = Path.Combine(root, target);
            byte[] bytes = File.ReadAllBytes(file);
            int index = bytes.AsSpan().IndexOf(Encoding.ASCII.GetBytes("ExecuteInDefaultAppDomain\0"));
            PackageVerifier.Require(index >= 0, "Test export text missing");
            bytes[index] = (byte)'X'; File.WriteAllBytes(file, bytes); Rehash(root, target);
        });
        Reject("unsafe-launcher-config", "Unexpected launcher configuration", root =>
        {
            string target = "launchers/x64/Snoop.InjectorLauncher.x64.exe.config";
            File.WriteAllText(Path.Combine(root, target), "<configuration><startup><supportedRuntime version=\"v4.0\" sku=\".NETFramework,Version=v4.8\"/></startup><runtime/></configuration>");
            Rehash(root, target);
        });
        Console.WriteLine($"Package negative tests: {passed} rejected; artifacts: {run}");
    }

    private static void Rehash(string root, string relative)
    {
        string hash = Convert.ToHexStringLower(SHA256.HashData(File.ReadAllBytes(Path.Combine(root, relative))));
        Edit(root, manifest =>
        {
            var entry = manifest["files"]!.AsArray().Single(x => x!["path"]!.GetValue<string>() == relative)!;
            entry["sha256"] = hash;
        });
    }
    private static void Edit(string root, Action<JsonNode> edit)
    {
        string path = Path.Combine(root, "manifest.json");
        var manifest = JsonNode.Parse(File.ReadAllText(path))!;
        edit(manifest);
        File.WriteAllText(path, manifest.ToJsonString());
    }
    private static void Clone(string source, string destination)
    {
        Directory.CreateDirectory(destination);
        foreach (string file in Directory.EnumerateFiles(source, "*", SearchOption.AllDirectories))
        {
            string target = Path.Combine(destination, Path.GetRelativePath(source, file));
            Directory.CreateDirectory(Path.GetDirectoryName(target)!);
            File.Copy(file, target);
        }
    }
}
