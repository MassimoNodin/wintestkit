// Launcher-only replacements for the Snoop.Core helpers excluded from the vendor inventory.
// Their behavior follows Snoop at 2bf48f60c2bb1753001f6be9122395def9070fa9,
// distributed under the Microsoft Public License; see third_party/snoop/License.txt.
namespace Snoop.Infrastructure;

using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

public static class LogHelper
{
    public static void WriteLine(string message)
    {
        Trace.WriteLine(message);
        Console.WriteLine(message);
    }

    public static void WriteError(Exception exception)
    {
        Trace.TraceError(exception.ToString());
        Console.WriteLine(exception);
    }
}

public static class ConsoleHelper
{
    public static void AttachConsoleToParentProcessOrAllocateNewOne()
    {
        const uint attachParentProcess = 0xffffffff;
        const int errorAccessDenied = 5;
        if (!NativeMethods.AttachConsole(attachParentProcess) && Marshal.GetLastWin32Error() == errorAccessDenied)
        {
            if (NativeMethods.FreeConsole())
            {
                NativeMethods.AttachConsole(attachParentProcess);
            }
        }
    }
}

public static class NativeMethods
{
    [Flags]
    public enum ProcessAccessFlags : uint
    {
        All = 0x001f0fff,
        QueryLimitedInformation = 0x00001000
    }

    [Flags]
    public enum AllocationType : uint
    {
        Commit = 0x1000,
        Reserve = 0x2000,
        Release = 0x8000
    }

    public enum MemoryProtection : uint
    {
        ReadWrite = 0x04
    }

    private enum ImageFileMachine : ushort
    {
        I386 = 0x014c,
        Amd64 = 0x8664,
        Arm = 0x01c0,
        Arm64 = 0xaa64
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct MODULEENTRY32
    {
        public uint dwSize;
        public uint th32ModuleID;
        public uint th32ProcessID;
        public uint GlblcntUsage;
        public uint ProccntUsage;
        public IntPtr modBaseAddr;
        public uint modBaseSize;
        public IntPtr hModule;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 256)] public string szModule;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)] public string szExePath;
    }

    public sealed class ProcessHandle : SafeHandleZeroOrMinusOneIsInvalid
    {
        private ProcessHandle() : base(true) { }
        protected override bool ReleaseHandle() => CloseHandle(handle);
    }

    private sealed class SnapshotHandle : SafeHandleZeroOrMinusOneIsInvalid
    {
        private SnapshotHandle() : base(true) { }
        protected override bool ReleaseHandle() => CloseHandle(handle);
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern ProcessHandle OpenProcess(ProcessAccessFlags access, bool inheritHandle, int processId);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern uint GetWindowThreadProcessId(IntPtr window, out int processId);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool IsWow64Process2(ProcessHandle process, out ImageFileMachine processMachine, out ImageFileMachine nativeMachine);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool IsWow64Process(ProcessHandle process, out bool wow64);

    public static string GetArchitectureWithoutException(Process process)
    {
        try
        {
            using var handle = OpenProcess(ProcessAccessFlags.QueryLimitedInformation, false, process.Id);
            if (handle.IsInvalid) throw new Win32Exception();
            try
            {
                if (!IsWow64Process2(handle, out var processMachine, out var nativeMachine)) throw new Win32Exception();
                return (processMachine == 0 ? nativeMachine : processMachine) switch
                {
                    ImageFileMachine.I386 => "x86",
                    ImageFileMachine.Amd64 => "x64",
                    ImageFileMachine.Arm => "ARM",
                    ImageFileMachine.Arm64 => "ARM64",
                    _ => "x86"
                };
            }
            catch (EntryPointNotFoundException)
            {
                if (!IsWow64Process(handle, out var wow64)) throw new Win32Exception();
                return Environment.Is64BitOperatingSystem && !wow64 ? "x64" : "x86";
            }
        }
        catch (Exception exception)
        {
            LogHelper.WriteError(exception);
            return Environment.Is64BitOperatingSystem ? "x64" : "x86";
        }
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern SnapshotHandle CreateToolhelp32Snapshot(uint flags, int processId);

    [DllImport("kernel32.dll", EntryPoint = "Module32FirstW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool Module32First(SnapshotHandle snapshot, ref MODULEENTRY32 module);

    [DllImport("kernel32.dll", EntryPoint = "Module32NextW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool Module32Next(SnapshotHandle snapshot, ref MODULEENTRY32 module);

    public static IEnumerable<MODULEENTRY32> GetModules(Process process)
    {
        // Include both native and 32-bit modules, as in the upstream helper.
        using var snapshot = CreateToolhelp32Snapshot(0x00000008 | 0x00000010, process.Id);
        if (snapshot.IsInvalid) yield break;
        var module = new MODULEENTRY32 { dwSize = (uint)Marshal.SizeOf(typeof(MODULEENTRY32)) };
        if (!Module32First(snapshot, ref module)) yield break;
        do { yield return module; } while (Module32Next(snapshot, ref module));
    }

    [DllImport("kernel32.dll", SetLastError = true, EntryPoint = "VirtualAllocEx")]
    private static extern IntPtr VirtualAllocExNative(ProcessHandle process, IntPtr address, UIntPtr size, AllocationType allocation, MemoryProtection protection);

    public static IntPtr VirtualAllocEx(ProcessHandle process, IntPtr address, uint size, AllocationType allocation, MemoryProtection protection) =>
        VirtualAllocExNative(process, address, new UIntPtr(size), allocation, protection);

    [DllImport("kernel32.dll", SetLastError = true, EntryPoint = "VirtualFreeEx")]
    private static extern bool VirtualFreeExNative(ProcessHandle process, IntPtr address, UIntPtr size, AllocationType freeType);

    public static bool VirtualFreeEx(ProcessHandle process, IntPtr address, int size, AllocationType freeType) =>
        VirtualFreeExNative(process, address, freeType == AllocationType.Release ? UIntPtr.Zero : new UIntPtr((uint)size), freeType);

    [DllImport("kernel32.dll", SetLastError = true, EntryPoint = "WriteProcessMemory")]
    private static extern bool WriteProcessMemoryNative(ProcessHandle process, IntPtr address, IntPtr buffer, UIntPtr size, out UIntPtr written);

    public static bool WriteProcessMemory(ProcessHandle process, IntPtr address, IntPtr buffer, uint size, out int written)
    {
        var result = WriteProcessMemoryNative(process, address, buffer, new UIntPtr(size), out var nativeWritten);
        written = checked((int)nativeWritten.ToUInt64());
        return result;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern IntPtr GetModuleHandle(string moduleName);

    [DllImport("kernel32.dll", CharSet = CharSet.Ansi, ExactSpelling = true, SetLastError = true)]
    public static extern IntPtr GetProcAddress(IntPtr module, string name);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern IntPtr LoadLibrary(string path);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool FreeLibrary(IntPtr module);

    [DllImport("kernel32.dll", SetLastError = true, EntryPoint = "CreateRemoteThread")]
    private static extern IntPtr CreateRemoteThreadNative(ProcessHandle process, IntPtr attributes, UIntPtr stackSize, IntPtr startAddress, IntPtr parameter, uint flags, out uint threadId);

    public static IntPtr CreateRemoteThread(ProcessHandle process, IntPtr attributes, uint stackSize, IntPtr startAddress, IntPtr parameter, uint flags, out IntPtr threadId)
    {
        var thread = CreateRemoteThreadNative(process, attributes, new UIntPtr(stackSize), startAddress, parameter, flags, out var nativeThreadId);
        threadId = new IntPtr(unchecked((long)nativeThreadId));
        return thread;
    }

    [DllImport("kernel32.dll", SetLastError = true, EntryPoint = "GetExitCodeThread")]
    private static extern bool GetExitCodeThreadNative(IntPtr thread, out uint exitCode);

    public static bool GetExitCodeThread(IntPtr thread, out IntPtr exitCode)
    {
        var result = GetExitCodeThreadNative(thread, out var nativeExitCode);
        exitCode = new IntPtr(unchecked((int)nativeExitCode));
        return result;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern uint WaitForSingleObject(IntPtr handle, uint timeoutInMilliseconds = 0xffffffff);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool CloseHandle(IntPtr handle);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool AttachConsole(uint processId);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool FreeConsole();

    public static IntPtr GetRemoteModuleHandle(Process targetProcess, string moduleName)
    {
        foreach (ProcessModule module in targetProcess.Modules)
        {
            if (string.Equals(module.ModuleName, moduleName, StringComparison.OrdinalIgnoreCase) ||
                string.Equals(module.FileName, moduleName, StringComparison.OrdinalIgnoreCase))
            {
                LogHelper.WriteLine($"Found module \"{moduleName}\" with base address \"{module.BaseAddress}\".");
                return module.BaseAddress;
            }
        }
        return IntPtr.Zero;
    }

    public static IntPtr GetRemoteProcAddress(Process targetProcess, string moduleName, string procName)
    {
        using var currentProcess = Process.GetCurrentProcess();
        var localModule = GetRemoteModuleHandle(currentProcess, moduleName);
        var localAddress = localModule == IntPtr.Zero ? IntPtr.Zero : GetProcAddress(localModule, procName);
        if (localAddress == IntPtr.Zero) throw new Exception($"Could not find local method handle for \"{procName}\" in module \"{moduleName}\".");
        var remoteModule = GetRemoteModuleHandle(targetProcess, moduleName);
        if (remoteModule == IntPtr.Zero) throw new Exception($"Could not find remote module \"{moduleName}\".");
        return new IntPtr(remoteModule.ToInt64() + localAddress.ToInt64() - localModule.ToInt64());
    }
}
