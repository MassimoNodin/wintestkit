using System;
using System.Windows;
using WinTestKit.Inspector.Agent.State;
using Xunit;

namespace WinTestKit.Inspector.Agent.Mapping.Tests
{
    [Collection("WPF dispatchers")]
    public class ScreenCoordinatesTests
    {
        private sealed class FakeApi : IScreenCoordinateApi
        {
            internal int Mode;
            internal bool Missing;
            public int Awareness(IntPtr hwnd) { if (Missing) throw new EntryPointNotFoundException(); return Mode; }
            public bool Convert(IntPtr hwnd, ref NativePoint point, bool physical)
            { point.X = physical ? point.X * 2 : point.X / 2; point.Y = physical ? point.Y * 2 : point.Y / 2; return true; }
        }
        [Fact]
        public void ConvertsOnlyWhenNeededAndToleratesMissingApis()
        {
            var original = ScreenCoordinates.Api;
            try
            {
                var api = new FakeApi { Mode = 2 }; ScreenCoordinates.Api = api;
                var point = new Point(10, 20); var hwnd = new IntPtr(1);
                Assert.Equal(point, ScreenCoordinates.Convert(hwnd, point, true));
                api.Mode = 0;
                Assert.Equal(new Point(20, 40), ScreenCoordinates.Convert(hwnd, point, true));
                Assert.Equal(point, ScreenCoordinates.Convert(hwnd, new Point(20, 40), false));
                api.Missing = true;
                Assert.Equal(point, ScreenCoordinates.Convert(hwnd, point, true));
            }
            finally { ScreenCoordinates.Api = original; }
        }
    }
}
