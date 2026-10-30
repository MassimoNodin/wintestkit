using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Interop;
using System.Windows.Media;
using WinTestKit.Inspector.Agent.Mapping;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.State
{
    internal static class StateReader
    {
        // Limit both traversal and output to bound work on the dispatcher.
        private const int MaxParts = 64;
        private const int MaxVisited = 4096;

        internal static ElementState Read(object target, ObjectRef handle, IPeerRuntimeIdAdapter adapter)
        {
            var dependency = target as DependencyObject;
            UIElement? element = target as UIElement;
            ContentElement? content = target as ContentElement;
            Visual? visual = element as Visual;
            if (visual == null && content != null)
            {
                DependencyObject? parent = ContentOperations.GetParent(content);
                while (parent != null && !(parent is Visual)) parent = LogicalTreeHelper.GetParent(parent);
                visual = parent as Visual;
            }
            var source = visual == null ? null : PresentationSource.FromVisual(visual) as HwndSource;
            Matrix scale = source?.CompositionTarget?.TransformToDevice ?? Matrix.Identity;
            Rect? bounds = visual == null ? null : Bounds(visual);
            bool isVisible = element?.IsVisible ?? (visual as UIElement)?.IsVisible ?? false;
            bool enabled = element?.IsEnabled ?? content?.IsEnabled ?? false;
            bool focused = element?.IsKeyboardFocused ?? content?.IsKeyboardFocused ?? false;
            bool focusable = element?.Focusable ?? content?.Focusable ?? false;
            Rect intersection = bounds ?? Rect.Empty;
            bool transparent = false;
            for (DependencyObject? node = visual; node != null; node = VisualTreeHelper.GetParent(node))
            {
                if (node is UIElement ui)
                {
                    if (ui.Opacity <= 0) transparent = true;
                    if (ui.Clip != null) Intersect(ref intersection, ScreenRect((Visual)ui, ui.Clip.Bounds));
                    if (ui.ClipToBounds || ui is ScrollContentPresenter)
                        Intersect(ref intersection, ScreenRect((Visual)ui, new Rect(new Point(), ui.RenderSize)));
                }
            }
            bool clipped = bounds.HasValue && !intersection.IsEmpty && intersection != bounds.Value;
            bool visible = isVisible && !transparent && bounds.HasValue && !intersection.IsEmpty;
            var peer = dependency == null ? null : PeerRuntimeIdAdapter.ResolveSingleElement(dependency);
            int[]? id = peer == null || !adapter.IsAvailable ? null : adapter.GetRuntimeId(peer);
            return new ElementState
            {
                Handle = handle,
                WindowHandle = source == null || source.Handle == IntPtr.Zero ? (long?)null : source.Handle.ToInt64(),
                Bounds = bounds.HasValue ? Dto(bounds.Value) : null,
                Dpi = new PointDto { X = 96 * scale.M11, Y = 96 * scale.M22 },
                Visible = visible,
                Clipped = clipped,
                Offscreen = !visible || !OnMonitor(intersection),
                Enabled = enabled,
                Focused = focused,
                IsKeyboardFocusable = focusable && enabled && isVisible,
                Parts = Parts(element as Control),
                UiaRuntimeId = id != null && id.Length > 0 ? id : null
            };
        }

        private static Rect? Bounds(Visual visual)
        {
            if (!(visual is UIElement ui) || !ui.IsVisible || ui.RenderSize.Width <= 0 || ui.RenderSize.Height <= 0 || PresentationSource.FromVisual(visual) == null) return null;
            Rect result = ScreenRect(visual, new Rect(new Point(), ui.RenderSize));
            return result.IsEmpty || result.Width <= 0 || result.Height <= 0 ? (Rect?)null : result;
        }
        private static Rect ScreenRect(Visual visual, Rect rect)
        {
            if (rect.IsEmpty) return Rect.Empty;
            try
            {
                Point a = visual.PointToScreen(rect.TopLeft), b = visual.PointToScreen(rect.TopRight);
                Point c = visual.PointToScreen(rect.BottomLeft), d = visual.PointToScreen(rect.BottomRight);
                double left = Math.Min(Math.Min(a.X, b.X), Math.Min(c.X, d.X));
                double top = Math.Min(Math.Min(a.Y, b.Y), Math.Min(c.Y, d.Y));
                double right = Math.Max(Math.Max(a.X, b.X), Math.Max(c.X, d.X));
                double bottom = Math.Max(Math.Max(a.Y, b.Y), Math.Max(c.Y, d.Y));
                return new Rect(left, top, right - left, bottom - top);
            }
            catch (InvalidOperationException) { return Rect.Empty; }
        }
        private static void Intersect(ref Rect current, Rect clip) { current.Intersect(clip); }
        private static RectDto Dto(Rect r) => new RectDto { X = r.X, Y = r.Y, Width = r.Width, Height = r.Height };

        private static IReadOnlyList<PartGeometry> Parts(Control? control)
        {
            var parts = new List<PartGeometry>();
            if (control == null) return parts;
            var stack = new Stack<DependencyObject>(); stack.Push(control);
            int visited = 0;
            while (stack.Count > 0 && parts.Count < MaxParts && visited++ < MaxVisited)
            {
                DependencyObject node = stack.Pop();
                if (node is FrameworkElement fe && fe.TemplatedParent == control && !string.IsNullOrEmpty(fe.Name))
                {
                    Rect? bounds = Bounds(fe);
                    parts.Add(new PartGeometry { Name = fe.Name, Role = Role(control, fe), Bounds = bounds.HasValue ? Dto(bounds.Value) : null });
                }
                if (control is DataGrid && node is DataGridColumnHeader header && parts.Count < MaxParts &&
                    !(header.TemplatedParent == control && !string.IsNullOrEmpty(header.Name)))
                {
                    Rect? headerBounds = Bounds(header);
                    parts.Add(new PartGeometry { Name = string.IsNullOrEmpty(header.Name) ? "ColumnHeader" : header.Name, Role = "gridColumnHeader", Bounds = headerBounds.HasValue ? Dto(headerBounds.Value) : null });
                }
                // WPF's default Track.Thumb is an unnamed template object.
                if (control is ScrollBar && node is Track track && track.TemplatedParent == control && track.Thumb != null && (track.Thumb.TemplatedParent != control || string.IsNullOrEmpty(track.Thumb.Name)) && parts.Count < MaxParts)
                {
                    Rect? thumbBounds = Bounds(track.Thumb);
                    parts.Add(new PartGeometry { Name = string.IsNullOrEmpty(track.Thumb.Name) ? "Thumb" : track.Thumb.Name, Role = "scrollThumb", Bounds = thumbBounds.HasValue ? Dto(thumbBounds.Value) : null });
                }
                int count = VisualTreeHelper.GetChildrenCount(node);
                for (int i = count - 1; i >= 0; i--) stack.Push(VisualTreeHelper.GetChild(node, i));
            }
            return parts;
        }
        private static string Role(Control control, FrameworkElement part)
        {
            string name = part.Name;
            if (control is ComboBox && (name == "PART_DropDown" || part is ToggleButton)) return "comboDropDown";
            if (control is TreeViewItem && name.IndexOf("Expander", StringComparison.OrdinalIgnoreCase) >= 0) return "treeItemExpander";
            if (control is Expander && part is ToggleButton) return "expanderToggle";
            if (part is DataGridColumnHeader) return "gridColumnHeader";
            if (control is ScrollBar)
            {
                if (part is Thumb) return "scrollThumb";
                if (part is Track) return "scrollTrack";
                if (name.IndexOf("LineUp", StringComparison.OrdinalIgnoreCase) >= 0 || name.IndexOf("LineLeft", StringComparison.OrdinalIgnoreCase) >= 0) return "scrollDecrement";
                if (name.IndexOf("LineDown", StringComparison.OrdinalIgnoreCase) >= 0 || name.IndexOf("LineRight", StringComparison.OrdinalIgnoreCase) >= 0) return "scrollIncrement";
            }
            return "templatePart";
        }
        [StructLayout(LayoutKind.Sequential)] private struct NativeRect { public int Left, Top, Right, Bottom; }
        [StructLayout(LayoutKind.Sequential)] private struct MonitorInfo { public int Size; public NativeRect Monitor, Work; public int Flags; }
        private delegate bool MonitorCallback(IntPtr monitor, IntPtr dc, ref NativeRect bounds, IntPtr data);
        [DllImport("user32.dll")] private static extern bool EnumDisplayMonitors(IntPtr dc, IntPtr clip, MonitorCallback callback, IntPtr data);
        [DllImport("user32.dll", CharSet = CharSet.Auto)] private static extern bool GetMonitorInfo(IntPtr monitor, ref MonitorInfo info);
        private static bool OnMonitor(Rect rect)
        {
            if (rect.IsEmpty) return false;
            bool found = false;
            EnumDisplayMonitors(IntPtr.Zero, IntPtr.Zero, (IntPtr monitor, IntPtr dc, ref NativeRect bounds, IntPtr data) =>
            {
                var info = new MonitorInfo { Size = Marshal.SizeOf(typeof(MonitorInfo)) };
                if (GetMonitorInfo(monitor, ref info) && rect.Right > info.Work.Left && rect.Left < info.Work.Right && rect.Bottom > info.Work.Top && rect.Top < info.Work.Bottom)
                { found = true; return false; }
                return true;
            }, IntPtr.Zero);
            return found;
        }
    }
}

