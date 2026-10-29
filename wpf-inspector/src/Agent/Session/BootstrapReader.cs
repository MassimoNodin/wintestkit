using System;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Session
{
    /// <summary>Reads the one-use bootstrap file outside the target's dispatcher thread.</summary>
    public static class BootstrapReader
    {
        public static string BootstrapRoot => Path.GetFullPath(Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "WinTestKit", "inspector", "bootstrap"));

        public static bool IsWithinRoot(string path) => IsWithinRoot(path, BootstrapRoot);

        public static bool IsWithinRoot(string path, string bootstrapRoot)
        {
            if (string.IsNullOrWhiteSpace(path) || !Path.IsPathRooted(path)) return false;
            string root = Path.GetFullPath(bootstrapRoot).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
                + Path.DirectorySeparatorChar;
            return Path.GetFullPath(path).StartsWith(root, StringComparison.OrdinalIgnoreCase);
        }

        public static BootstrapSettings Read(string path) => Read(path, BootstrapRoot);

        public static BootstrapSettings Read(string path, string bootstrapRoot)
        {
            if (!IsWithinRoot(path, bootstrapRoot)) throw new InvalidDataException("Invalid bootstrap path.");
            string fullPath = Path.GetFullPath(path);
                byte[] bytes;
                using (var handle = CreateFile(fullPath, 0x80010000, 0, IntPtr.Zero, 3, 0x00200000, IntPtr.Zero))
                {
                    if (handle.IsInvalid) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
                    if (!GetFileInformationByHandle(handle, out var information))
                        throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
                    if ((information.Attributes & 0x400) != 0) throw new InvalidDataException("Bootstrap reparse point rejected.");
                    CheckReparsePoints(Path.GetDirectoryName(fullPath)!, bootstrapRoot);
                    var disposition = new FileDispositionInformation { DeleteFile = true };
                    if (!SetFileInformationByHandle(handle, 4, ref disposition, Marshal.SizeOf(typeof(FileDispositionInformation))))
                        throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
                    using (var stream = new FileStream(handle, FileAccess.Read))
                    {
                    if (stream.Length > ProtocolLimits.MaxBootstrapBytes) throw new InvalidDataException("Bootstrap is too large.");
                    bytes = new byte[(int)stream.Length];
                    int offset = 0;
                    while (offset < bytes.Length)
                    {
                        int read = stream.Read(bytes, offset, bytes.Length - offset);
                        if (read == 0) throw new EndOfStreamException();
                        offset += read;
                    }
                    }
                }
                var node = StrictJson.Parse(bytes, 0, bytes.Length);
                var settings = BootstrapSettings.FromJson(node);
                var obj = node as JsonObjectNode ?? throw new InvalidDataException("Invalid bootstrap.");
                if (Number(obj, "schemaVersion") != 1) throw new InvalidDataException("Invalid bootstrap schema.");
                if (!DateTimeOffset.TryParse(String(obj, "expiresUtc"), CultureInfo.InvariantCulture,
                    DateTimeStyles.RoundtripKind, out var expiry) || expiry <= DateTimeOffset.UtcNow)
                    throw new InvalidDataException("Bootstrap expired.");
                var process = obj.Get("process") as JsonObjectNode ?? throw new InvalidDataException("Invalid process identity.");
                using (var current = Process.GetCurrentProcess())
                {
                    if (Number(process, "pid") != current.Id ||
                        !DateTimeOffset.TryParse(String(process, "creationTimeUtc"), CultureInfo.InvariantCulture,
                            DateTimeStyles.RoundtripKind, out var created) ||
                        created.UtcDateTime != current.StartTime.ToUniversalTime())
                        throw new InvalidDataException("Process identity mismatch.");
                }
                string version = typeof(BootstrapReader).Assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion ?? "";
                if (!string.Equals(String(obj, "agentVersion"), version, StringComparison.Ordinal))
                    throw new ProtocolException(ErrorCodes.AgentVersionMismatch, "Agent version mismatch.");
                return settings;
        }

        private static void CheckReparsePoints(string path, string bootstrapRoot)
        {
            string root = Path.GetFullPath(bootstrapRoot).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            string? current = path;
            while (current != null)
            {
                if ((File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0)
                    throw new InvalidDataException("Bootstrap reparse point rejected.");
                if (string.Equals(current.TrimEnd(Path.DirectorySeparatorChar), root, StringComparison.OrdinalIgnoreCase)) return;
                current = Path.GetDirectoryName(current);
            }
            throw new InvalidDataException("Invalid bootstrap path.");
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct FileInformation
        {
            public uint Attributes, CreationLow, CreationHigh, AccessLow, AccessHigh, WriteLow, WriteHigh;
            public uint VolumeSerial, SizeHigh, SizeLow, Links, IndexHigh, IndexLow;
        }

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool GetFileInformationByHandle(SafeFileHandle handle, out FileInformation information);

        [StructLayout(LayoutKind.Sequential)]
        private struct FileDispositionInformation { [MarshalAs(UnmanagedType.U1)] public bool DeleteFile; }

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool SetFileInformationByHandle(SafeFileHandle handle, int informationClass, ref FileDispositionInformation information, int size);

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern SafeFileHandle CreateFile(string path, uint access, uint share, IntPtr security, uint creation, uint flags, IntPtr template);

        private static string String(JsonObjectNode obj, string key) =>
            (obj.Get(key) as JsonStringNode)?.Value ?? throw new InvalidDataException("Invalid bootstrap field.");

        private static long Number(JsonObjectNode obj, string key)
        {
            if (obj.Get(key) is JsonNumberNode number && number.TryGetInt64(out long value)) return value;
            throw new InvalidDataException("Invalid bootstrap field.");
        }
    }
}
