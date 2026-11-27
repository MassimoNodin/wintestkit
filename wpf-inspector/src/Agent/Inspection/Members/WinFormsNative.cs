using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Contracts;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Inspection.Members
{
    /// <summary>
    /// Everything the agent needs from System.Windows.Forms. Callers decide with <see cref="IsLoaded"/> and
    /// <see cref="IsWinFormsObject"/> (both free of WinForms types) before calling a method that names
    /// <c>Control</c>, so a WPF process never has to load the assembly. Every such method is NoInlining for that reason.
    /// Unless a method says otherwise it must run on the thread that owns the control.
    /// </summary>
    internal static class WinFormsNative
    {
        private const string ControlTypeName = "System.Windows.Forms.Control";
        private const string ToolStripItemTypeName = "System.Windows.Forms.ToolStripItem";
        private static bool loaded;

        /// <summary>True once the target has loaded System.Windows.Forms. Needs no WinForms type.</summary>
        internal static bool IsLoaded
        {
            get
            {
                if (loaded) return true;
                foreach (System.Reflection.Assembly assembly in AppDomain.CurrentDomain.GetAssemblies())
                    if (string.Equals(assembly.GetName().Name, "System.Windows.Forms", StringComparison.OrdinalIgnoreCase)) return loaded = true;
                return false;
            }
        }

        /// <summary>True for a WinForms Control or a ToolStripItem, decided by type name so WinForms is not loaded.</summary>
        internal static bool IsWinFormsObject(object? target)
        {
            for (Type? type = target?.GetType(); type != null; type = type.BaseType)
                if (type.FullName == ControlTypeName || type.FullName == ToolStripItemTypeName) return true;
            return false;
        }

        [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint processId);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetClassName(IntPtr hwnd, StringBuilder text, int count);

        /// <summary>Any thread. The Control that owns <paramref name="handle"/>, or null for a window that is not a Control.</summary>
        [MethodImpl(MethodImplOptions.NoInlining)]
        internal static object? FromHandle(IntPtr handle) => Control.FromHandle(handle);

        /// <summary>Any thread. The forms with a window, in the order WinForms opened them.</summary>
        [MethodImpl(MethodImplOptions.NoInlining)]
        internal static IReadOnlyList<object> OpenForms()
        {
            var forms = new List<object>();
            try
            {
                foreach (Form form in Application.OpenForms)
                    if (form.IsHandleCreated) forms.Add(form);
            }
            catch (InvalidOperationException) { /* The collection changed while it was copied: report what was copied. */ }
            return forms;
        }

        /// <summary>Any thread. The native thread that owns the control's window, or 0.</summary>
        [MethodImpl(MethodImplOptions.NoInlining)]
        internal static uint ThreadOf(object target)
        {
            IntPtr handle = HandleOf(target);
            return handle == IntPtr.Zero ? 0 : GetWindowThreadProcessId(handle, out _);
        }

        /// <summary>Any thread. The window of a control, or of the strip that owns an item.</summary>
        [MethodImpl(MethodImplOptions.NoInlining)]
        internal static IntPtr HandleOf(object target)
        {
            Control? control = target as Control ?? (target as ToolStripItem)?.Owner;
            return control != null && control.IsHandleCreated ? control.Handle : IntPtr.Zero;
        }

        /// <summary>
        /// Any thread. The WPF Dispatcher of the thread that owns the control. The WinForms message loop pumps it:
        /// that is what lets the executor keep its queue, timeout and hang rules unchanged for WinForms.
        /// </summary>
        [MethodImpl(MethodImplOptions.NoInlining)]
        internal static async Task<Dispatcher> GetDispatcherAsync(object target, int timeoutMs, CancellationToken ct)
        {
            Control? control = target as Control ?? (target as ToolStripItem)?.Owner;
            if (control == null || !control.IsHandleCreated) throw new ProtocolException(ErrorCodes.MappingFailed, "The control has no window.");
            var source = new TaskCompletionSource<Dispatcher>(TaskCreationOptions.RunContinuationsAsynchronously);
            try { control.BeginInvoke(new Action(() => source.TrySetResult(Dispatcher.CurrentDispatcher))); }
            catch (Exception error) when (error is InvalidOperationException || error is ObjectDisposedException)
            { throw new ProtocolException(ErrorCodes.MappingFailed, "The control has no window."); }
            Task completed = await Task.WhenAny(source.Task, Task.Delay(timeoutMs, ct)).ConfigureAwait(false);
            ct.ThrowIfCancellationRequested();
            if (completed != source.Task) throw new ProtocolException(ErrorCodes.DispatcherUnavailable, "The WinForms thread did not respond.");
            return await source.Task.ConfigureAwait(false);
        }

        [MethodImpl(MethodImplOptions.NoInlining)]
        internal static string Name(object target) => (target as Control)?.Name ?? (target as ToolStripItem)?.Name ?? "";

        /// <summary>The control's or item's Text: the migrated <c>wpf:Text</c> of a WinForms object. Must run on the owning thread.</summary>
        [MethodImpl(MethodImplOptions.NoInlining)]
        internal static string Text(object target) => (target as Control)?.Text ?? (target as ToolStripItem)?.Text ?? "";

        /// <summary>The 1-based position among the siblings of the same runtime type, in natural order; 1 without a parent.</summary>
        internal static int Ordinal(object target)
        {
            object? parent = ParentOf(target);
            if (parent == null) return 1;
            int count = 0;
            foreach (object sibling in Children(parent))
            {
                if (sibling.GetType() == target.GetType()) count++;
                if (ReferenceEquals(sibling, target)) return count;
            }
            return 1;
        }

        private const string HostTypeName = "System.Windows.Forms.Integration.WindowsFormsHost";
        private static readonly Dictionary<Type, System.Reflection.PropertyInfo?> HostChildren = new Dictionary<Type, System.Reflection.PropertyInfo?>();

        /// <summary>
        /// The WinForms control a WPF <c>WindowsFormsHost</c> holds, or null for any other object. The host is recognised by type
        /// name, so neither WinForms nor the integration assembly is loaded for a WPF-only process. Must run on the host's thread.
        /// </summary>
        internal static object? HostedChild(object target)
        {
            Type type = target.GetType();
            System.Reflection.PropertyInfo? property;
            bool known;
            lock (HostChildren) known = HostChildren.TryGetValue(type, out property);
            if (!known)
            {
                property = null;
                for (Type? current = type; current != null && property == null; current = current.BaseType)
                    if (current.FullName == HostTypeName) property = current.GetProperty("Child", System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Instance);
                lock (HostChildren) HostChildren[type] = property;
            }
            if (property == null) return null;
            object? child = property.GetValue(target, null);
            return IsWinFormsObject(child) ? child : null;
        }

        [MethodImpl(MethodImplOptions.NoInlining)]
        internal static bool IsTopLevel(object target) => target is Control control && control.Parent == null;

        [MethodImpl(MethodImplOptions.NoInlining)]
        internal static object? ParentOf(object target)
        {
            if (target is Control control) return control.Parent;
            return target is ToolStripItem item ? item.Owner : null;
        }

        /// <summary>The children of a node in natural order: a control's Controls, a strip's items, a menu item's drop-down items.</summary>
        [MethodImpl(MethodImplOptions.NoInlining)]
        internal static IEnumerable<object> Children(object target)
        {
            if (target is ToolStrip strip)
            {
                foreach (ToolStripItem item in strip.Items) yield return item;
            }
            else if (target is Control control)
            {
                foreach (Control child in control.Controls) yield return child;
            }
            else if (target is ToolStripDropDownItem menu && menu.HasDropDownItems)
            {
                foreach (ToolStripItem item in menu.DropDownItems) yield return item;
            }
        }

        [MethodImpl(MethodImplOptions.NoInlining)]
        internal static bool HasChildren(object target)
        {
            if (target is ToolStrip strip) return strip.Items.Count != 0;
            if (target is Control control) return control.Controls.Count != 0;
            return target is ToolStripDropDownItem menu && menu.HasDropDownItems && menu.DropDownItems.Count != 0;
        }

        /// <summary>The deepest control, or strip item, under a screen point inside the window <paramref name="root"/>.</summary>
        [MethodImpl(MethodImplOptions.NoInlining)]
        internal static object? HitTest(IntPtr root, int x, int y)
        {
            Control? current = Control.FromHandle(root);
            if (current == null) return null;
            var screen = new System.Drawing.Point(x, y);
            object? hit = current;
            for (int depth = 0; depth < 256; depth++)
            {
                if (current is ToolStrip strip)
                {
                    ToolStripItem? item = strip.GetItemAt(strip.PointToClient(screen));
                    if (item != null) hit = item;
                    break;
                }
                Control? child = current.GetChildAtPoint(current.PointToClient(screen), GetChildAtPointSkip.Invisible);
                if (child == null) break;
                current = child;
                hit = child;
            }
            return hit;
        }

        [MethodImpl(MethodImplOptions.NoInlining)]
        internal static bool IsPasswordText(object target)
        {
            if (target is TextBox text) return text.UseSystemPasswordChar || text.PasswordChar != '\0';
            return target is MaskedTextBox masked && (masked.UseSystemPasswordChar || masked.PasswordChar != '\0');
        }

        /// <summary>The members of a protected (password) control that stay readable.</summary>
        internal static bool IsAllowedOnProtected(Type declaringType, string name) =>
            declaringType.FullName == ControlTypeName && Array.IndexOf(new[] { "Name", "Visible", "Enabled", "Focused", "Width", "Height" }, name) >= 0;

        [MethodImpl(MethodImplOptions.NoInlining)]
        internal static ElementState ReadState(object target, ObjectRef handle)
        {
            var control = target as Control;
            var item = target as ToolStripItem;
            Control? owner = control ?? item?.Owner;
            System.Drawing.Rectangle bounds = System.Drawing.Rectangle.Empty;
            bool hasBounds = false;
            if (control != null)
            {
                bounds = control.Parent != null ? control.Parent.RectangleToScreen(control.Bounds) : control.Bounds;
                hasBounds = control.IsHandleCreated || control.Parent != null;
            }
            else if (item != null && item.Owner != null)
            {
                bounds = item.Owner.RectangleToScreen(item.Bounds);
                hasBounds = item.Available && item.Owner.IsHandleCreated;
            }
            var visibleBounds = bounds;
            for (Control? ancestor = control?.Parent ?? item?.Owner; ancestor != null; ancestor = ancestor.Parent)
                visibleBounds = System.Drawing.Rectangle.Intersect(visibleBounds, ancestor.RectangleToScreen(ancestor.ClientRectangle));
            bool visible = hasBounds && !visibleBounds.IsEmpty && (control?.Visible ?? item?.Visible ?? false)
                && (owner == null || owner.Visible) && bounds.IntersectsWith(SystemInformation.VirtualScreen);
            bool enabled = control != null ? control.Enabled : item?.Enabled ?? false;
            int dpi = owner != null && owner.IsHandleCreated ? owner.DeviceDpi : 96;
            IntPtr window = owner != null && owner.IsHandleCreated ? owner.Handle : IntPtr.Zero;
            var physicalBounds = State.ScreenCoordinates.Physical(window, new System.Windows.Rect(bounds.X, bounds.Y, bounds.Width, bounds.Height));
            var physicalVisible = State.ScreenCoordinates.Physical(window, new System.Windows.Rect(visibleBounds.X, visibleBounds.Y, visibleBounds.Width, visibleBounds.Height));
            return new ElementState
            {
                Handle = handle,
                WindowHandle = window == IntPtr.Zero ? (long?)null : window.ToInt64(),
                Bounds = hasBounds ? new RectDto { X = physicalBounds.X, Y = physicalBounds.Y, Width = physicalBounds.Width, Height = physicalBounds.Height } : null,
                VisibleBounds = visible ? new RectDto { X = physicalVisible.X, Y = physicalVisible.Y, Width = physicalVisible.Width, Height = physicalVisible.Height } : null,
                ClickPoint = visible ? new PointDto { X = physicalVisible.X + physicalVisible.Width / 2.0, Y = physicalVisible.Y + physicalVisible.Height / 2.0 } : null,
                Dpi = new PointDto { X = dpi, Y = dpi },
                Visible = visible,
                Clipped = hasBounds && visibleBounds != bounds,
                Offscreen = !visible,
                Enabled = enabled,
                Focused = control != null && control.Focused,
                IsKeyboardFocusable = visible && enabled && control != null && control.CanFocus,
                Parts = Array.Empty<PartGeometry>(),
                // A window of its own is the root of a UI Automation HWND provider: runtime id {42, hwnd}.
                UiaRuntimeId = control != null && control.IsHandleCreated ? new[] { 42, unchecked((int)control.Handle.ToInt64()) } : null
            };
        }

        [MethodImpl(MethodImplOptions.NoInlining)]
        internal static ValueDto ReadUia(object target, string name, IObjectRegistry registry, Dispatcher dispatcher)
        {
            try
            {
                var control = target as Control;
                bool password = IsPasswordText(target);
                object? result = null;
                switch (name)
                {
                    case "class_name":
                        if (control != null && control.IsHandleCreated)
                        {
                            var text = new StringBuilder(256);
                            if (GetClassName(control.Handle, text, text.Capacity) > 0) result = text.ToString();
                        }
                        break;
                    case "automation_id": result = Name(target); break;
                    case "name":
                        if (password) return new ValueDto { Status = "redacted", Kind = "unavailable", RedactionRule = "identity" };
                        result = AccessibleName(target);
                        break;
                    case "control_type": result = ControlType(target); break;
                    case "is_password": result = password; break;
                    case "value":
                    case "document_text":
                        if (password) return new ValueDto { Status = "redacted", Kind = "unavailable", RedactionRule = "identity" };
                        if (control is TextBoxBase) result = control.Text;
                        break;
                }
                if (result == null) return new ValueDto { Status = "unavailable", Kind = "unavailable" };
                return ValueSerializer.Serialize(result, result.GetType(), registry, dispatcher);
            }
            catch (Exception) { return new ValueDto { Status = "exception", Kind = "unavailable", FailedSegment = 0 }; }
        }

        private static string AccessibleName(object target)
        {
            if (target is Control control)
            {
                if (!string.IsNullOrEmpty(control.AccessibleName)) return control.AccessibleName;
                // Edit-like controls are named by their label, not by their contents.
                return control is TextBoxBase || control is ListControl || control is UpDownBase ? "" : (control.Text ?? "").Replace("&", "");
            }
            if (target is ToolStripItem item) return !string.IsNullOrEmpty(item.AccessibleName) ? item.AccessibleName : (item.Text ?? "").Replace("&", "");
            return "";
        }

        /// <summary>The UI Automation control type the WinForms provider reports for a control, by the closest known base type.</summary>
        internal static string ControlType(object target)
        {
            for (Type? type = target.GetType(); type != null; type = type.BaseType)
                switch (type.FullName)
                {
                    case "System.Windows.Forms.Form": return "Window";
                    case "System.Windows.Forms.Button": return "Button";
                    case "System.Windows.Forms.CheckBox": return "CheckBox";
                    case "System.Windows.Forms.RadioButton": return "RadioButton";
                    case "System.Windows.Forms.TextBoxBase": return "Edit";
                    case "System.Windows.Forms.Label": return "Text";
                    case "System.Windows.Forms.LinkLabel": return "Hyperlink";
                    case "System.Windows.Forms.ComboBox": return "ComboBox";
                    case "System.Windows.Forms.ListBox": return "List";
                    case "System.Windows.Forms.ListView": return "List";
                    case "System.Windows.Forms.TreeView": return "Tree";
                    case "System.Windows.Forms.GroupBox": return "Group";
                    case "System.Windows.Forms.TabControl": return "Tab";
                    case "System.Windows.Forms.TabPage": return "Pane";
                    case "System.Windows.Forms.DataGridView": return "Table";
                    case "System.Windows.Forms.MenuStrip": return "MenuBar";
                    case "System.Windows.Forms.StatusStrip": return "StatusBar";
                    case "System.Windows.Forms.ToolStrip": return "ToolBar";
                    case "System.Windows.Forms.ToolStripMenuItem": return "MenuItem";
                    case "System.Windows.Forms.ToolStripButton": return "Button";
                    case "System.Windows.Forms.ToolStripDropDownButton": return "Button";
                    case "System.Windows.Forms.ToolStripSplitButton": return "SplitButton";
                    case "System.Windows.Forms.ToolStripLabel": return "Text";
                    case "System.Windows.Forms.ToolStripTextBox": return "Edit";
                    case "System.Windows.Forms.ToolStripComboBox": return "ComboBox";
                    case "System.Windows.Forms.ToolStripProgressBar": return "ProgressBar";
                    case "System.Windows.Forms.ToolStripSeparator": return "Separator";
                    case "System.Windows.Forms.PictureBox": return "Image";
                    case "System.Windows.Forms.ProgressBar": return "ProgressBar";
                    case "System.Windows.Forms.TrackBar": return "Slider";
                    case "System.Windows.Forms.UpDownBase": return "Spinner";
                    case "System.Windows.Forms.MonthCalendar": return "Calendar";
                    case "System.Windows.Forms.ScrollBar": return "ScrollBar";
                }
            return "Pane";
        }
    }
}
