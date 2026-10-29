namespace Snoop.InjectorLauncher;

using System;
using System.Diagnostics;
using Snoop.Infrastructure;

public class ProcessWrapper
{
    public ProcessWrapper(Process process, IntPtr windowHandle)
    {
        this.Process = process ?? throw new ArgumentNullException(nameof(process));
        this.Id = process.Id;
        this.Handle = NativeMethods.OpenProcess(NativeMethods.ProcessAccessFlags.All, false, process.Id);
        this.WindowHandle = windowHandle;

        this.Architecture = NativeMethods.GetArchitectureWithoutException(this.Process);

        this.SupportedFrameworkName = GetSupportedTargetFramework(process);
    }

    public Process Process { get; }

    public int Id { get; }

    public NativeMethods.ProcessHandle Handle { get; }

    public IntPtr WindowHandle { get; }

    public string Architecture { get; }

    public string SupportedFrameworkName { get; }

    public static ProcessWrapper? From(int processId, IntPtr windowHandle)
    {
        try
        {
            var processFromId = Process.GetProcessById(processId);

            return new ProcessWrapper(processFromId, windowHandle);
        }
        catch (Exception exception)
        {
            Injector.LogMessage(exception.ToString());
            return null;
        }
    }

    public static ProcessWrapper? FromWindowHandle(IntPtr handle)
    {
        var processFromWindowHandle = GetProcessFromWindowHandle(handle);

        if (processFromWindowHandle is null)
        {
            return null;
        }

        return new ProcessWrapper(processFromWindowHandle, handle);
    }

    private static Process? GetProcessFromWindowHandle(IntPtr windowHandle)
    {
        _ = NativeMethods.GetWindowThreadProcessId(windowHandle, out var processId);

        if (processId == 0)
        {
            Injector.LogMessage($"Could not get process for window handle {windowHandle}");
            return null;
        }

        try
        {
            var process = Process.GetProcessById(processId);
            return process;
        }
        catch (Exception e)
        {
            Injector.LogMessage($"Could not get process for PID = {processId}.");
            Injector.LogMessage(e.ToString());
        }

        return null;
    }

    private static string GetSupportedTargetFramework(Process process)
    {
        var modules = NativeMethods.GetModules(process);

        FileVersionInfo? coreclrVersion = null;

        foreach (var module in modules)
        {
#if DEBUG
            Injector.LogMessage(module.szExePath);
            try
            {
                var fileVersionInfo = FileVersionInfo.GetVersionInfo(module.szExePath);
                Injector.LogMessage($"File: {fileVersionInfo.FileVersion}");
                Injector.LogMessage($"Prod: {fileVersionInfo.ProductVersion}");
            }
            catch
            {
                // Some virus scanners (e.g. SentinelOne) have kernel mode drivers that
                // may load non-existent modules into the process memory (e.g. Ntd1l.dll
                // and Kern3l.dll ... notice the unconventional spelling). Those file
                // do not exist on disk and the above will fail. As we only log the version
                // info in debug builds for diagnostics, we simply ignore the errors.
            }
#endif

            if (module.szModule.Equals("coreclr.dll", StringComparison.OrdinalIgnoreCase))
            {
                coreclrVersion = FileVersionInfo.GetVersionInfo(module.szExePath);
            }
        }

        if (coreclrVersion is null)
        {
            return "net462";
        }

        var productVersion = coreclrVersion.ProductMajorPart;
        return productVersion switch
        {
            >= 6 => "net6.0-windows",
            4 => "net462",
            _ => throw new NotSupportedException($".NET version {coreclrVersion.ProductVersion} is not supported.")
        };
    }
}