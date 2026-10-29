using System;
using System.Diagnostics;
using System.Threading;
using WinTestKit.Inspector.Agent.Contracts;
using WinTestKit.Inspector.Agent.Session;

namespace WinTestKit.Inspector.Agent
{
    public static class EntryPoint
    {
        /// <summary>Returns 0 for handoff, 1 for an empty path, or 2 for an invalid path.</summary>
        public static int Start(string settingsFile)
        {
            try
            {
                if (string.IsNullOrWhiteSpace(settingsFile)) return 1;
                if (!BootstrapReader.IsWithinRoot(settingsFile)) return 2;
                var thread = new Thread(() => Run(settingsFile)) { IsBackground = true, Name = "WinTestKit inspector" };
                thread.Start();
                return 0;
            }
            catch (Exception) { return 2; }
        }

        private static void Run(string path)
        {
            try
            {
                var settings = BootstrapReader.Read(path);
                var type = typeof(EntryPoint).Assembly.GetType("WinTestKit.Inspector.Agent.Inspection.WpfInspectionServiceFactory", false);
                if (type == null || !(Activator.CreateInstance(type) is IInspectionServiceFactory factory))
                {
                    Trace.TraceWarning("inspection service unavailable");
                    return;
                }
                using (var host = new SessionHost(settings, factory)) host.Run();
            }
            catch (Exception error) { Trace.TraceError("Inspector session failed: {0}", error.GetType().Name); }
        }
    }
}
