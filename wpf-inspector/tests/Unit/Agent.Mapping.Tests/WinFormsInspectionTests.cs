using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using WinTestKit.Inspector.Agent.Contracts;
using WinTestKit.Inspector.Agent.Inspection;
using WinTestKit.Inspector.Agent.Inspection.Members;
using WinTestKit.Inspector.Protocol;
using Xunit;
using WinForms = System.Windows.Forms;

namespace WinTestKit.Inspector.Agent.Mapping.Tests
{
    /// <summary>A WinForms UI thread with a real message loop and no visible window: handles are created, nothing is shown.</summary>
    internal sealed class WinFormsThread : IDisposable
    {
        private readonly Thread thread;
        internal WinForms.Form Form { get; private set; } = null!;
        internal WinForms.Button Button { get; private set; } = null!;
        internal WinForms.TextBox Password { get; private set; } = null!;
        internal WinForms.GroupBox Group { get; private set; } = null!;
        internal WinForms.MenuStrip Menu { get; private set; } = null!;
        internal FixtureLikeControl Custom { get; private set; } = null!;

        internal WinFormsThread()
        {
            var ready = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            thread = new Thread(() =>
            {
                try
                {
                    Form = new WinForms.Form { Name = "mainForm", Text = "WinForms Fixture" };
                    Button = new WinForms.Button { Name = "button1", Text = "OK" };
                    Password = new WinForms.TextBox { Name = "passwordBox", Text = "hunter2", UseSystemPasswordChar = true };
                    Group = new WinForms.GroupBox { Name = "group1", Text = "Group" };
                    Group.Controls.Add(new WinForms.Button { Name = "nested1", Text = "Nested" });
                    Menu = new WinForms.MenuStrip { Name = "menuStrip1" };
                    var file = new WinForms.ToolStripMenuItem("&File") { Name = "fileToolStripMenuItem" };
                    file.DropDownItems.Add(new WinForms.ToolStripMenuItem("Open") { Name = "openToolStripMenuItem" });
                    Menu.Items.Add(file);
                    Custom = new FixtureLikeControl { Name = "custom1" };
                    Form.Controls.AddRange(new WinForms.Control[] { Button, Password, Group, Custom, Menu });
                    _ = Form.Handle;
                    foreach (WinForms.Control control in Form.Controls) _ = control.Handle;
                    ready.SetResult(true);
                    WinForms.Application.Run(new WinForms.ApplicationContext());
                }
                catch (Exception error) { ready.TrySetException(error); }
            }) { IsBackground = true };
            thread.SetApartmentState(ApartmentState.STA);
            thread.Start();
            ready.Task.GetAwaiter().GetResult();
        }

        internal long Handle => Form.Handle.ToInt64();

        public void Dispose()
        {
            try { Form.BeginInvoke(new Action(() => { Form.Dispose(); WinForms.Application.ExitThread(); })); }
            catch (Exception) { /* The thread already ended. */ }
            thread.Join(TimeSpan.FromSeconds(10));
        }
    }

    public sealed class FixtureLikeControl : WinForms.UserControl
    {
        [System.ComponentModel.DesignerSerializationVisibility(System.ComponentModel.DesignerSerializationVisibility.Hidden)] public string Label { get; set; } = "label";
        public int Calls;
        public string Recorded = "";
        [System.ComponentModel.DesignerSerializationVisibility(System.ComponentModel.DesignerSerializationVisibility.Hidden)] public string Throws => throw new InvalidOperationException("getter failure");
        public string RecordWrite(string value, int number) { Recorded = value + ":" + number; Calls++; return Recorded; }
    }

    [Collection("WPF dispatchers")]
    [Trait("Category", "Unit")]
    public sealed class WinFormsInspectionTests
    {
        private static readonly CancellationToken None = CancellationToken.None;

        private static WpfInspectionService NewService() => new WpfInspectionService("winforms", new ObjectInspector());

        private static Task<MappingDto> Resolve(WpfInspectionService service, WinForms.Control control) =>
            service.ResolveAsync(new[] { 42, (int)control.Handle }, control.Handle.ToInt64(), None);

        private static IReadOnlyList<IReadOnlyList<PathSegment>> Path(string kind, string name, string? declaring = null) =>
            new[] { (IReadOnlyList<PathSegment>)new[] { new PathSegment { Kind = kind, Name = name, DeclaringType = declaring } } };

        [Fact]
        public async Task ResolvesAControlFromItsWindowHandleAndReportsItsType()
        {
            using (var ui = new WinFormsThread())
            using (var service = NewService())
            {
                MappingDto mapping = await Resolve(service, ui.Button);
                Assert.Equal(MappingStatus.Exact, mapping.Status);
                Assert.Equal("System.Windows.Forms.Button", mapping.Object!.Type.FullName);
                Assert.Contains("System.Windows.Forms.Control", mapping.Object.Type.BaseTypes);
                MappingDto again = await Resolve(service, ui.Button);
                Assert.Equal(mapping.Object.ObjectId, again.Object!.ObjectId);
                Assert.Equal(mapping.Object.DispatcherId, (await Resolve(service, ui.Form)).Object!.DispatcherId);
            }
        }

        [Fact]
        public async Task AWindowThatIsNotAControlIsLeftToTheWpfMapper()
        {
            using (var service = NewService())
            {
                MappingDto mapping = await service.ResolveAsync(new[] { 42, 1 }, null, None);
                Assert.NotEqual(MappingStatus.Exact, mapping.Status);
            }
        }

        [Fact]
        public async Task ChildrenFollowControlsInNaturalOrderWithNamesAsIdentity()
        {
            using (var ui = new WinFormsThread())
            using (var service = NewService())
            {
                ObjectRef form = (await Resolve(service, ui.Form)).Object!;
                PageDto<ManagedNodeDto> page = await service.ChildrenAsync(form.ObjectId, form.Generation, TreeKind.Visual, null, null, None);
                string[] expected = await OnUi(ui, () => ui.Form.Controls.Cast<WinForms.Control>().Select(control => control is WinForms.TextBox ? "" : control.Name).ToArray());
                Assert.Equal(expected, page.Items.Select(node => node.Identity?.XName ?? "").ToArray());
                Assert.All(page.Items.Where(node => node.Identity != null), node => Assert.Equal(node.Identity!.XName, node.Identity.AutomationId));
                Assert.Equal(new[] { "Button", "TextBox", "GroupBox", "FixtureLikeControl", "MenuStrip" }.OrderBy(name => name), page.Items.Select(node => node.Label).OrderBy(name => name));
                ManagedNodeDto group = page.Items.Single(node => node.Label == "GroupBox");
                Assert.True(group.HasVisualChildren);
                Assert.False(page.Items.Single(node => node.Label == "Button").HasVisualChildren);
                PageDto<ManagedNodeDto> nested = await service.ChildrenAsync(group.Object.ObjectId, group.Object.Generation, TreeKind.Logical, null, null, None);
                Assert.Equal("nested1", Assert.Single(nested.Items).Identity!.XName);
            }
        }

        [Fact]
        public async Task ToolStripItemsAreChildrenOfTheirStripAndMenuItems()
        {
            using (var ui = new WinFormsThread())
            using (var service = NewService())
            {
                ObjectRef strip = (await Resolve(service, ui.Menu)).Object!;
                ManagedNodeDto file = Assert.Single((await service.ChildrenAsync(strip.ObjectId, strip.Generation, TreeKind.Visual, null, null, None)).Items);
                Assert.Equal("fileToolStripMenuItem", file.Identity!.XName);
                Assert.True(file.HasVisualChildren);
                ManagedNodeDto open = Assert.Single((await service.ChildrenAsync(file.Object.ObjectId, file.Object.Generation, TreeKind.Visual, null, null, None)).Items);
                Assert.Equal("openToolStripMenuItem", open.Identity!.XName);
                Assert.False(open.HasVisualChildren);
            }
        }

        [Fact]
        public async Task RootsSkipFormsThatWereNeverShown()
        {
            // WinForms lists a form in Application.OpenForms only once it has been shown; this test never shows one.
            using (var ui = new WinFormsThread())
            using (var service = NewService())
            {
                PageDto<ManagedNodeDto> roots = await service.RootsAsync(null, null, None);
                Assert.DoesNotContain(roots.Items, node => node.Object.Type.FullName == "System.Windows.Forms.Form");
            }
        }

        [Fact]
        public async Task MembersReadFieldsAndPublicGettersLikeAnyManagedObject()
        {
            using (var ui = new WinFormsThread())
            using (var service = NewService())
            {
                ObjectRef button = (await Resolve(service, ui.Button)).Object!;
                var members = new List<Protocol.MemberInfo>();
                PageDto<Protocol.MemberInfo> membersPage = await service.MembersAsync(button.ObjectId, button.Generation, 200, null, None);
                members.AddRange(membersPage.Items);
                while (membersPage.NextToken != null)
                {
                    membersPage = await service.MembersAsync(button.ObjectId, button.Generation, 200, membersPage.NextToken, None);
                    members.AddRange(membersPage.Items);
                }
                Assert.Contains(members, member => member.Name == "Text" && member.Category == "clrProperty" && member.Readable);
                ReadResult text = await service.ReadAsync(button.ObjectId, button.Generation, Path("property", "Text"), None);
                Assert.Equal("OK", ((JsonStringNode)text.Values.Single().Value.Scalar!).Value);
                ObjectRef custom = (await Resolve(service, ui.Custom)).Object!;
                var customMembers = new List<Protocol.MemberInfo>();
                PageDto<Protocol.MemberInfo> customPage = await service.MembersAsync(custom.ObjectId, custom.Generation, 200, null, None);
                customMembers.AddRange(customPage.Items);
                while (customPage.NextToken != null)
                {
                    customPage = await service.MembersAsync(custom.ObjectId, custom.Generation, 200, customPage.NextToken, None);
                    customMembers.AddRange(customPage.Items);
                }
                Protocol.MemberInfo recorded = Assert.Single(customMembers, member => member.Name == "Recorded" && member.Category == "clrField");
                ReadResult field = await ((ISpyFieldInspectionService)service).ReadSpyFieldAsync(custom.ObjectId, custom.Generation, new[] { (IReadOnlyList<PathSegment>)new[] { recorded.PathSegment! } }, None);
                Assert.Equal(ValueStatus.Ok, field.Values.Single().Value.Status);
                ReadResult broken = await service.ReadAsync(custom.ObjectId, custom.Generation, Path("property", "Throws", typeof(FixtureLikeControl).FullName), None);
                Assert.Equal(ValueStatus.Exception, broken.Values.Single().Value.Status);
            }
        }

        [Fact]
        public async Task PasswordTextBoxesAreRedactedButKeepTheirNameAndTree()
        {
            using (var ui = new WinFormsThread())
            using (var service = NewService())
            {
                ObjectRef password = (await Resolve(service, ui.Password)).Object!;
                ReadResult text = await service.ReadAsync(password.ObjectId, password.Generation, Path("property", "Text"), None);
                Assert.Equal(ValueStatus.Redacted, text.Values.Single().Value.Status);
                Assert.Null(text.Values.Single().Value.Scalar);
                ReadResult name = await service.ReadAsync(password.ObjectId, password.Generation, Path("property", "Name", "System.Windows.Forms.Control"), None);
                Assert.Equal("passwordBox", ((JsonStringNode)name.Values.Single().Value.Scalar!).Value);
                ReadResult uia = await service.ReadAsync(password.ObjectId, password.Generation, Path("uia", "value"), None);
                Assert.Equal(ValueStatus.Redacted, uia.Values.Single().Value.Status);
                ObjectRef form = (await Resolve(service, ui.Form)).Object!;
                ManagedNodeDto node = (await service.ChildrenAsync(form.ObjectId, form.Generation, TreeKind.Visual, null, null, None)).Items.Single(item => item.Label == "TextBox");
                Assert.Null(node.Identity);
            }
        }

        [Fact]
        public async Task UiaIdentityComesFromTheControl()
        {
            using (var ui = new WinFormsThread())
            using (var service = NewService())
            {
                ObjectRef button = (await Resolve(service, ui.Button)).Object!;
                async Task<string> Uia(string name) =>
                    ((JsonStringNode)(await service.ReadAsync(button.ObjectId, button.Generation, Path("uia", name), None)).Values.Single().Value.Scalar!).Value;
                Assert.Equal("button1", await Uia("automation_id"));
                Assert.Equal("OK", await Uia("name"));
                Assert.Equal("Button", await Uia("control_type"));
                Assert.Contains("BUTTON", (await Uia("class_name")).ToUpperInvariant());
            }
        }

        [Fact]
        public async Task StateReportsGeometryAndEnabledWithoutShowingAnything()
        {
            using (var ui = new WinFormsThread())
            using (var service = NewService())
            {
                ObjectRef button = (await Resolve(service, ui.Button)).Object!;
                StateGetResult state = await service.GetStateAsync(button, DateTime.UtcNow.AddSeconds(10), 5000, None);
                Assert.NotNull(state.State.Bounds);
                Assert.True(state.State.Enabled);
                Assert.False(state.State.Visible);
                Assert.Equal(ui.Button.Handle.ToInt64(), state.State.WindowHandle);
                Assert.Equal(new[] { 42, (int)ui.Button.Handle.ToInt64() }, state.State.UiaRuntimeId);
            }
        }

        [Fact]
        public async Task MethodsAreCatalogedAndInvokedOnTheUiThread()
        {
            using (var ui = new WinFormsThread())
            using (var service = NewService())
            {
                ObjectRef custom = (await Resolve(service, ui.Custom)).Object!;
                PageDto<MethodMetadataDto> methods = await ((ISpyMethodInspectionService)service).SpyMethodsAsync(custom.ObjectId, custom.Generation, 200, null, None);
                MethodMetadataDto record = Assert.Single(methods.Items, item => item.Name == "RecordWrite");
                Assert.Null(record.UnsupportedReason);
                JsonNode Argument(string type, JsonNode value) { var node = new JsonObjectNode(); node.Add("type", new JsonStringNode(type)); node.Add("value", value); return node; }
                WriteCallResult result = await ((ISpyInvokeInspectionService)service).InvokeAsync(custom, record.Key,
                    new[] { Argument("System.String", new JsonStringNode("hello")), Argument("System.Int32", JsonNumberNode.From(7)) }, DateTime.UtcNow.AddSeconds(10), None);
                Assert.Equal("performed", result.Audit.Outcome);
                Assert.Equal("hello:7", await OnUi(ui, () => ui.Custom.Recorded));
                Assert.Equal(1, await OnUi(ui, () => ui.Custom.Calls));
            }
        }

        [Fact]
        public async Task HitTestRejectsAWindowThatIsNeitherWpfNorWinForms()
        {
            using (var ui = new WinFormsThread())
            using (var service = NewService())
            {
                var error = await Assert.ThrowsAsync<ProtocolException>(() => service.HitTestAsync(1, new PointDto(), DateTime.UtcNow.AddSeconds(5), 1000, None));
                Assert.Equal(ErrorCodes.MappingFailed, error.Code);
            }
        }

        [Fact]
        public void ControlTypesFollowTheClosestKnownBaseType()
        {
            Assert.Equal("Edit", WinFormsNative.ControlType(new WinForms.TextBox()));
            Assert.Equal("Edit", WinFormsNative.ControlType(new WinForms.RichTextBox()));
            Assert.Equal("Pane", WinFormsNative.ControlType(new FixtureLikeControl()));
            Assert.Equal("Window", WinFormsNative.ControlType(new WinForms.Form()));
            Assert.Equal("MenuItem", WinFormsNative.ControlType(new WinForms.ToolStripMenuItem()));
        }

        [Fact]
        public void WinFormsObjectsAreRecognisedByTypeNameAlone()
        {
            Assert.True(WinFormsNative.IsWinFormsObject(new WinForms.Button()));
            Assert.True(WinFormsNative.IsWinFormsObject(new WinForms.ToolStripButton()));
            Assert.False(WinFormsNative.IsWinFormsObject(new object()));
            Assert.False(WinFormsNative.IsWinFormsObject(null));
        }

        private static Task<T> OnUi<T>(WinFormsThread ui, Func<T> action)
        {
            var source = new TaskCompletionSource<T>(TaskCreationOptions.RunContinuationsAsynchronously);
            ui.Form.BeginInvoke(new Action(() => { try { source.SetResult(action()); } catch (Exception error) { source.SetException(error); } }));
            return source.Task;
        }
    }
}
