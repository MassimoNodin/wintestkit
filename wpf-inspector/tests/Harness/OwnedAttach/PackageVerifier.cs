using System.Reflection;
using System.Diagnostics;
using System.Reflection.Metadata;
using System.Reflection.PortableExecutable;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Text;
using System.Xml;
using System.Xml.Linq;
using WinTestKit.Inspector.Protocol;

internal static class PackageVerifier
{
    internal static void Verify(string root, string version, string upstream)
    {
        root = Path.GetFullPath(root);
        Require(Directory.Exists(root), "Payload directory missing");
        CheckTree(root);
        using var document = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(root, "manifest.json")));
        Unique(document.RootElement);
        var m = document.RootElement;
        Keys(m, "schemaVersion", "inspectorVersion", "protocolMajor", "protocolMinor", "sourceCommit", "upstreamCommit", "signed", "cells", "launchers", "agents", "files", "notices");
        Require(m.GetProperty("schemaVersion").GetInt32() == 1 && m.GetProperty("protocolMajor").GetInt32() == ProtocolInfo.Major && m.GetProperty("protocolMinor").GetInt32() == ProtocolInfo.Minor, "Manifest schema or protocol mismatch");
        Require(m.GetProperty("inspectorVersion").GetString() == version && m.GetProperty("upstreamCommit").GetString() == upstream, "Manifest version or upstream commit mismatch");
        Require(Regex.IsMatch(m.GetProperty("sourceCommit").GetString() ?? "", "^[0-9a-f]{40}(-dirty)?$"), "Invalid source commit");
        _ = m.GetProperty("signed").GetBoolean();
        var expected = new HashSet<string>(StringComparer.Ordinal);
        var launchers = m.GetProperty("launchers"); Keys(launchers, "x86", "x64");
        foreach (string arch in new[] { "x86", "x64" })
        {
            string dir = $"launchers/{arch}/";
            string launcher = dir + $"Snoop.InjectorLauncher.{arch}.exe";
            Require(launchers.GetProperty(arch).GetString() == launcher, "Unexpected launcher path");
            expected.Add(launcher); expected.Add(launcher + ".config");
            expected.Add(dir + $"Snoop.GenericInjector.{arch}.dll"); expected.Add(dir + "CommandLine.dll");
        }
        var agents = m.GetProperty("agents"); Keys(agents, "net48", "net8", "net10");
        foreach (string runtime in new[] { "net48", "net8", "net10" })
        {
            string dir = $"agents/{runtime}/";
            Require(agents.GetProperty(runtime).GetString() == dir + "WinTestKit.Inspector.Agent.dll", "Unexpected agent path");
            expected.Add(dir + "WinTestKit.Inspector.Agent.dll");
        }
        string[] notices = { "notices/THIRD-PARTY-NOTICES.md", "notices/Snoop-License.txt", "notices/CommandLineParser-License.md" };
        Require(m.GetProperty("notices").EnumerateArray().Select(x => x.GetString()).SequenceEqual(notices), "Notices missing or unexpected");
        expected.UnionWith(notices);
        var cells = new HashSet<string>();
        foreach (var cell in m.GetProperty("cells").EnumerateArray())
        {
            Keys(cell, "runtime", "architecture", "verified");
            string runtime = cell.GetProperty("runtime").GetString() ?? "";
            string arch = cell.GetProperty("architecture").GetString() ?? "";
            Require(new[] { "net48", "net8", "net10" }.Contains(runtime) && new[] { "x86", "x64" }.Contains(arch), "Invalid compatibility cell");
            _ = cell.GetProperty("verified").GetBoolean();
            Require(cells.Add(runtime + "/" + arch), "Duplicate compatibility cell");
        }
        Require(cells.Count == 6, "Incomplete compatibility cells");
        var listed = new HashSet<string>(StringComparer.Ordinal);
        foreach (var entry in m.GetProperty("files").EnumerateArray())
        {
            Keys(entry, "path", "sha256");
            string path = entry.GetProperty("path").GetString() ?? "";
            string hash = entry.GetProperty("sha256").GetString() ?? "";
            Require(expected.Contains(path) && listed.Add(path), "Unexpected or duplicate file in manifest");
            Require(Regex.IsMatch(hash, "^[0-9a-f]{64}$"), "Invalid file hash");
            string full = Path.Combine(root, path.Replace('/', Path.DirectorySeparatorChar));
            Require(File.Exists(full), $"Missing payload file: {path}");
            using var stream = File.OpenRead(full);
            Require(Convert.ToHexStringLower(SHA256.HashData(stream)) == hash, $"Payload hash mismatch: {path}");
        }
        Require(listed.SetEquals(expected), "Incomplete payload inventory");
        var actual = Directory.EnumerateFiles(root, "*", SearchOption.AllDirectories).Select(x => Path.GetRelativePath(root, x).Replace('\\', '/')).ToHashSet(StringComparer.Ordinal);
        expected.Add("manifest.json");
        Require(actual.SetEquals(expected), "Payload contains missing or unlisted files");
        foreach (string arch in new[] { "x86", "x64" })
        {
            Machine machine = arch == "x86" ? Machine.I386 : Machine.Amd64;
            CheckPe(Path.Combine(root, $"launchers/{arch}/Snoop.GenericInjector.{arch}.dll"), machine, false, null, null, false);
            CheckPe(Path.Combine(root, $"launchers/{arch}/Snoop.InjectorLauncher.{arch}.exe"), machine, true, ".NETFramework,Version=v4.8", null, false, arch == "x86");
            CheckPe(Path.Combine(root, $"launchers/{arch}/CommandLine.dll"), Machine.I386, true, null, null, false);
            CheckLauncherConfig(Path.Combine(root, $"launchers/{arch}/Snoop.InjectorLauncher.{arch}.exe.config"));
            ProbeLauncher(Path.Combine(root, $"launchers/{arch}/Snoop.InjectorLauncher.{arch}.exe"));
        }
        foreach (var target in new[] { ("net48", ".NETFramework,Version=v4.8"), ("net8", ".NETCoreApp,Version=v8.0"), ("net10", ".NETCoreApp,Version=v10.0") })
        {
            CheckPe(Path.Combine(root, $"agents/{target.Item1}/WinTestKit.Inspector.Agent.dll"), Machine.I386, true, target.Item2, version, true);
        }
        Console.WriteLine($"Package: {listed.Count} hashes, inventory, notices, six cells, PE architectures, TFMs, strong-name headers, dependencies, entry points and both launcher load probes verified; signed={m.GetProperty("signed").GetBoolean()}.");
    }

    private static void ProbeLauncher(string exe)
    {
        var start = new ProcessStartInfo(exe) { UseShellExecute = false, CreateNoWindow = true, WorkingDirectory = Path.GetDirectoryName(exe)!, RedirectStandardOutput = true, RedirectStandardError = true };
        using var process = Process.Start(start) ?? throw new InvalidOperationException("Launcher load probe could not start");
        var stdout = process.StandardOutput.ReadToEndAsync();
        var stderr = process.StandardError.ReadToEndAsync();
        try
        {
            if (!process.WaitForExit(5000)) throw new TimeoutException("Launcher load probe timed out");
            string output = stdout.GetAwaiter().GetResult() + stderr.GetAwaiter().GetResult();
            Require(process.ExitCode == 1 && output.Contains("targetPID", StringComparison.Ordinal) && output.Contains("settingsFile", StringComparison.Ordinal), "Launcher load/required-arguments probe failed");
        }
        finally { if (!process.HasExited) { process.Kill(); process.WaitForExit(); } }
    }

    private static void CheckPe(string file, Machine machine, bool managed, string? tfm, string? version, bool agentDependencyPolicy, bool requires32 = false)
    {
        using var stream = File.OpenRead(file);
        using var pe = new PEReader(stream);
        Require(pe.PEHeaders.CoffHeader.Machine == machine && pe.HasMetadata == managed, $"Invalid PE architecture/type: {Path.GetFileName(file)}");
        if (!managed) { CheckNativeExport(pe); return; }
        var flags = pe.PEHeaders.CorHeader!.Flags;
        Require(((flags & CorFlags.Requires32Bit) != 0) == requires32, $"Invalid CLR architecture flags: {Path.GetFileName(file)}");
        var md = pe.GetMetadataReader();
        var assembly = md.GetAssemblyDefinition();
        if (tfm != null) Require(Attribute(md, assembly, "TargetFrameworkAttribute") == tfm, $"Unexpected target framework: {file}");
        if (tfm != null && tfm.StartsWith(".NETCoreApp", StringComparison.Ordinal)) Require(Attribute(md, assembly, "TargetPlatformAttribute") == "Windows7.0", $"Unexpected target platform: {file}");
        if (version != null) Require(Attribute(md, assembly, "AssemblyInformationalVersionAttribute") == version, $"Unexpected assembly version: {file}");
        if (agentDependencyPolicy)
        {
            Require(!assembly.PublicKey.IsNil && (flags & CorFlags.StrongNameSigned) != 0, $"Assembly is not strong-named: {file}");
            var frameworkReferences = new HashSet<string>(StringComparer.Ordinal) {
                "mscorlib", "System", "System.Core", "System.Runtime", "System.Collections", "System.Text.Encoding.Extensions",
                "System.Diagnostics.Process", "System.IO.Pipes", "System.Security.Principal.Windows", "System.Threading",
                "WindowsBase", "PresentationCore", "PresentationFramework", "System.Security.Cryptography", "System.ComponentModel.TypeConverter",
                "System.Text.RegularExpressions", "System.Threading.Thread", "System.Diagnostics.TraceSource", "System.Runtime.InteropServices",
                "Microsoft.Win32.Primitives", "System.Linq"
            };
            if (tfm != ".NETFramework,Version=v4.8") frameworkReferences.Add("System.Memory");
            foreach (var handle in md.AssemblyReferences)
            {
                string name = md.GetString(md.GetAssemblyReference(handle).Name);
                Require(frameworkReferences.Contains(name), $"Unexpected bundled Agent dependency: {name}");
            }
        }
        bool entry = false;
        foreach (var handle in md.TypeDefinitions)
        {
            var type = md.GetTypeDefinition(handle);
            string ns = md.GetString(type.Namespace), name = md.GetString(type.Name);
            Require(!ns.StartsWith("Snoop.Scripting", StringComparison.OrdinalIgnoreCase) && !ns.StartsWith("Snoop.Core", StringComparison.OrdinalIgnoreCase) && name != "SnoopUI", "Snoop UI or scripting type present");
            if (ns == "WinTestKit.Inspector.Agent" && name == "EntryPoint")
                entry = type.GetMethods().Any(h => { var method = md.GetMethodDefinition(h); return md.GetString(method.Name) == "Start" && (method.Attributes & (MethodAttributes.Public | MethodAttributes.Static)) == (MethodAttributes.Public | MethodAttributes.Static) && md.GetBlobBytes(method.Signature).SequenceEqual(new byte[] { 0, 1, 8, 14 }); });
        }
        if (Path.GetFileName(file) == "WinTestKit.Inspector.Agent.dll") Require(entry, "Agent entry point missing");
    }

    private static void CheckNativeExport(PEReader pe)
    {
        int rva = pe.PEHeaders.PEHeader!.ExportTableDirectory.RelativeVirtualAddress;
        Require(rva != 0, "Native injector export missing");
        var directory = pe.GetSectionData(rva).GetReader();
        directory.Offset = 20;
        uint functions = directory.ReadUInt32(), names = directory.ReadUInt32();
        _ = directory.ReadUInt32();
        int namesRva = directory.ReadInt32();
        Require(functions == 1 && names == 1, "Unexpected native injector exports");
        var pointers = pe.GetSectionData(namesRva).GetReader();
        var name = pe.GetSectionData(pointers.ReadInt32()).GetReader();
        var value = new StringBuilder();
        while (name.RemainingBytes > 0 && value.Length < 128)
        {
            byte next = name.ReadByte();
            if (next == 0) break;
            value.Append((char)next);
        }
        Require(value.ToString() == "ExecuteInDefaultAppDomain", "Native injector export missing");
    }

    private static void CheckLauncherConfig(string path)
    {
        using var reader = XmlReader.Create(path, new XmlReaderSettings { DtdProcessing = DtdProcessing.Prohibit, XmlResolver = null });
        var root = XDocument.Load(reader).Root;
        Require(root != null && root.Name == "configuration" && !root.HasAttributes && root.Elements().Count() == 1, "Unexpected launcher configuration");
        var startup = root!.Elements().Single();
        Require(startup.Name == "startup" && !startup.HasAttributes && startup.Elements().Count() == 1, "Unexpected launcher configuration");
        var supported = startup.Elements().Single();
        Require(supported.Name == "supportedRuntime" && !supported.HasElements && supported.Attributes().Count() == 2 && (string?)supported.Attribute("version") == "v4.0" && (string?)supported.Attribute("sku") == ".NETFramework,Version=v4.8", "Unexpected launcher configuration");
    }

    private static string? Attribute(MetadataReader md, AssemblyDefinition assembly, string name)
    {
        foreach (var handle in assembly.GetCustomAttributes())
        {
            var attr = md.GetCustomAttribute(handle);
            if (attr.Constructor.Kind != HandleKind.MemberReference) continue;
            var member = md.GetMemberReference((MemberReferenceHandle)attr.Constructor);
            if (member.Parent.Kind != HandleKind.TypeReference) continue;
            var type = md.GetTypeReference((TypeReferenceHandle)member.Parent);
            if (md.GetString(type.Name) != name) continue;
            var blob = md.GetBlobReader(attr.Value);
            if (blob.ReadUInt16() != 1) throw new InvalidDataException("Invalid attribute blob");
            return blob.ReadSerializedString();
        }
        return null;
    }

    private static void CheckTree(string directory)
    {
        Require((File.GetAttributes(directory) & FileAttributes.ReparsePoint) == 0, "Payload contains a reparse point");
        foreach (string item in Directory.EnumerateFileSystemEntries(directory))
        {
            var attributes = File.GetAttributes(item);
            Require((attributes & FileAttributes.ReparsePoint) == 0, "Payload contains a reparse point");
            if ((attributes & FileAttributes.Directory) != 0) CheckTree(item);
        }
    }
    private static void Unique(JsonElement node)
    {
        if (node.ValueKind == JsonValueKind.Object)
        {
            var keys = new HashSet<string>(StringComparer.Ordinal);
            foreach (var property in node.EnumerateObject()) { Require(keys.Add(property.Name), "Duplicate JSON key"); Unique(property.Value); }
        }
        else if (node.ValueKind == JsonValueKind.Array) foreach (var item in node.EnumerateArray()) Unique(item);
    }
    private static void Keys(JsonElement node, params string[] keys) => Require(node.ValueKind == JsonValueKind.Object && node.EnumerateObject().Select(x => x.Name).ToHashSet(StringComparer.Ordinal).SetEquals(keys), "Unexpected manifest fields");
    internal static void Require(bool condition, string message) { if (!condition) throw new InvalidDataException(message); }
}
