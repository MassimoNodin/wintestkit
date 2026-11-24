using System;
using System.Runtime.InteropServices;
using System.Windows;

namespace WinTestKit.Inspector.Agent.State
{
    internal interface IScreenCoordinateApi
    {
        int Awareness(IntPtr hwnd);
        bool Convert(IntPtr hwnd, ref NativePoint point, bool physical);
    }
    [StructLayout(LayoutKind.Sequential)]
    internal struct NativePoint { public int X, Y; }
    internal sealed class ScreenCoordinateApi : IScreenCoordinateApi
    {
        [DllImport("user32.dll")] private static extern IntPtr GetWindowDpiAwarenessContext(IntPtr hwnd);
        [DllImport("user32.dll")] private static extern int GetAwarenessFromDpiAwarenessContext(IntPtr context);
        [DllImport("user32.dll")] private static extern bool LogicalToPhysicalPointForPerMonitorDPI(IntPtr hwnd, ref NativePoint point);
        [DllImport("user32.dll")] private static extern bool PhysicalToLogicalPointForPerMonitorDPI(IntPtr hwnd, ref NativePoint point);
        public int Awareness(IntPtr hwnd) => GetAwarenessFromDpiAwarenessContext(GetWindowDpiAwarenessContext(hwnd));
        public bool Convert(IntPtr hwnd, ref NativePoint point, bool physical) => physical ? LogicalToPhysicalPointForPerMonitorDPI(hwnd, ref point) : PhysicalToLogicalPointForPerMonitorDPI(hwnd, ref point);
    }
    internal static class ScreenCoordinates
    {
        internal static IScreenCoordinateApi Api = new ScreenCoordinateApi();
        internal static Point Convert(IntPtr hwnd, Point point, bool physical)
        {
            if (hwnd == IntPtr.Zero) return point;
            try
            {
                if (Api.Awareness(hwnd) == 2) return point;
                var native = new NativePoint { X = (int)Math.Round(point.X), Y = (int)Math.Round(point.Y) };
                return Api.Convert(hwnd, ref native, physical) ? new Point(native.X, native.Y) : point;
            }
            catch (EntryPointNotFoundException) { return point; }
            catch (DllNotFoundException) { return point; }
        }
        internal static Rect Physical(IntPtr hwnd, Rect rect)
        {
            var a = Convert(hwnd, rect.TopLeft, true); var b = Convert(hwnd, rect.BottomRight, true);
            return new Rect(a, b);
        }
    }
}
