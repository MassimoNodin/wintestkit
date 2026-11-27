using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Controls;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Contracts;
using WinTestKit.Inspector.Agent.Inspection;
using WinTestKit.Inspector.Agent.Inspection.Members;
using WinTestKit.Inspector.Agent.Query;
using WinTestKit.Inspector.Protocol;
using Xunit;
using WinForms = System.Windows.Forms;

namespace WinTestKit.Inspector.Agent.Mapping.Tests
{
    public sealed class ChartFooter
    {
        public string Text { get; set; } = "Page 1 of 2";
        public int Pages { get; set; } = 2;
    }

    public sealed class ChartSeries
    {
        public string Title { get; set; } = "";
        public int Points;
    }

    /// <summary>A custom control that, like a third-party chart, exposes an int member and a nested object with a string member.</summary>
    public sealed class SeriesChart : WinForms.UserControl
    {
        [System.ComponentModel.DesignerSerializationVisibility(System.ComponentModel.DesignerSerializationVisibility.Hidden)] public int SeriesCount { get; set; } = 3;
        public ChartFooter Footer { get; } = new ChartFooter();
        public ChartSeries[] Series { get; } = { new ChartSeries { Title = "Alpha", Points = 4 }, new ChartSeries { Title = "Beta", Points = 9 } };
        [System.ComponentModel.DesignerSerializationVisibility(System.ComponentModel.DesignerSerializationVisibility.Hidden)] public string Caption { get; set; } = "caption";
        [System.ComponentModel.DesignerSerializationVisibility(System.ComponentModel.DesignerSerializationVisibility.Hidden)] public string ApiKey { get; set; } = "k-123";
        public string Refresh(int count) { SeriesCount = count; return "refreshed:" + count; }
    }

    /// <summary>
    /// A WinForms UI thread with a real message loop and nothing shown. The form holds chart1 (3 series), a panel with chart2 (5 series),
    /// a label, two buttons and a password box.
    /// </summary>
    internal sealed class ChartUi : IDisposable
    {
        private readonly Thread thread;
        internal WinForms.Form Form { get; private set; } = null!;
        internal SeriesChart Chart { get; private set; } = null!;
        internal SeriesChart Second { get; private set; } = null!;
        internal WinForms.TextBox Password { get; private set; } = null!;

        internal ChartUi()
        {
            var ready = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            thread = new Thread(() =>
            {
                try
                {
                    Form = new WinForms.Form { Name = "chartForm", Text = "Charts" };
                    Chart = new SeriesChart { Name = "chart1", SeriesCount = 3 };
                    Second = new SeriesChart { Name = "chart2", SeriesCount = 5 };
                    var side = new WinForms.Panel { Name = "side" };
                    side.Controls.Add(Second);
                    Password = new WinForms.TextBox { Name = "secretBox", Text = "hunter2", UseSystemPasswordChar = true };
                    Form.Controls.AddRange(new WinForms.Control[]
                    {
                        Chart, side, new WinForms.Label { Name = "title", Text = "Revenue" },
                        new WinForms.Button { Name = "ok", Text = "OK" }, new WinForms.Button { Name = "cancel", Text = "Cancel" }, Password
                    });
                    _ = Form.Handle;
                    foreach (WinForms.Control control in Form.Controls) _ = control.Handle;
                    _ = Second.Handle;
                    ready.SetResult(true);
                    WinForms.Application.Run(new WinForms.ApplicationContext());
                }
                catch (Exception error) { ready.TrySetException(error); }
            }) { IsBackground = true };
            thread.SetApartmentState(ApartmentState.STA);
            thread.Start();
            ready.Task.GetAwaiter().GetResult();
        }

        public void Dispose()
        {
            try { Form.BeginInvoke(new Action(() => { Form.Dispose(); WinForms.Application.ExitThread(); })); }
            catch (Exception) { /* The thread already ended. */ }
            thread.Join(TimeSpan.FromSeconds(10));
        }
    }

    [Collection("WPF dispatchers")]
    [Trait("Category", "Unit")]
    public sealed class WinFormsManagedTests
    {
        private static readonly CancellationToken None = CancellationToken.None;
        private static DateTime Deadline => DateTime.UtcNow.AddSeconds(60);

        private static WpfInspectionService NewService(ObjectInspector? inspector = null, WriteAllowlist? allowlist = null, params string[] redact) =>
            new WpfInspectionService("winforms-managed", inspector ?? new ObjectInspector(), null, null, allowlist, redact);

        private static async Task<ObjectRef> Resolve(WpfInspectionService service, WinForms.Control control)
        {
            MappingDto mapping = await service.ResolveAsync(new[] { 42, (int)control.Handle }, control.Handle.ToInt64(), None);
            Assert.Equal(MappingStatus.Exact, mapping.Status);
            return mapping.Object!;
        }

        private static PathSegment Property(string name) => new PathSegment { Kind = "property", Name = name };
        private static PathSegment Field(string name) => new PathSegment { Kind = "field", Name = name };

        private static async Task<ValueDto> Read(WpfInspectionService service, ObjectRef handle, params PathSegment[] path) =>
            (await service.ReadAsync(handle.ObjectId, handle.Generation, new[] { (IReadOnlyList<PathSegment>)path }, None)).Values.Single().Value;

        private static string Text(ValueDto value) => ((JsonStringNode)value.Scalar!).Value;

        private static Locator Search(ObjectRef scope, int depth, params Predicate[] predicates) => new Locator
        {
            Scope = new Scope { Kind = "object", Handle = scope },
            Tree = "combined", DepthMode = "peers", Depth = depth, Limit = 200, Predicates = predicates
        };

        private static Predicate Equal(JsonNode value, params PathSegment[] path) => new Predicate { Kind = "equals", Path = path, Value = value };
        private static PathSegment Uia(string name) => new PathSegment { Kind = "uia", Name = name };
        private static PathSegment ObjectKey(string name) => new PathSegment { Kind = "object", Name = name };
        private static PathSegment TypeFacet(string name) => new PathSegment { Kind = "type", Name = name };

        private static async Task<string[]> Names(WpfInspectionService service, QueryFindAllResult result)
        {
            var names = new List<string>();
            foreach (ObjectRef match in result.Matches) names.Add(Text(await Read(service, match, Uia("automation_id"))));
            return names.ToArray();
        }

        [Fact]
        public async Task ReadsAnIntAndANestedStringOfACustomControl()
        {
            using (var ui = new ChartUi())
            using (var service = NewService())
            {
                ObjectRef chart = await Resolve(service, ui.Chart);
                ValueDto count = await Read(service, chart, Property("SeriesCount"));
                Assert.Equal(ValueStatus.Ok, count.Status);
                Assert.Equal(ValueKind.Integer, count.Kind);
                Assert.Equal("3", ((JsonNumberNode)count.Scalar!).RawText);
                Assert.Equal("Page 1 of 2", Text(await Read(service, chart, Property("Footer"), Property("Text"))));
                Assert.Equal("Beta", Text(await Read(service, chart, Property("Series[1]"), Property("Title"))));
                Assert.Equal("9", ((JsonNumberNode)(await Read(service, chart, Property("Series[1]"), Field("Points"))).Scalar!).RawText);
                Assert.Equal("SeriesChart", Text(await Read(service, chart, TypeFacet("Name"))));
                Assert.Equal(typeof(SeriesChart).FullName, Text(await Read(service, chart, TypeFacet("FullName"))));
                ValueDto outOfRange = await Read(service, chart, Property("Series[5]"), Property("Title"));
                Assert.Equal(ValueStatus.Exception, outOfRange.Status);
                ObjectRef second = await Resolve(service, ui.Second);
                Assert.Equal("5", ((JsonNumberNode)(await Read(service, second, Property("SeriesCount"))).Scalar!).RawText);
            }
        }

        [Fact]
        public async Task RedactionNamesApplyToWinFormsMembers()
        {
            using (var ui = new ChartUi())
            using (var service = NewService(new ObjectInspector(new[] { "Footer" }), null, "Footer"))
            {
                ObjectRef chart = await Resolve(service, ui.Chart);
                ValueDto footer = await Read(service, chart, Property("Footer"), Property("Text"));
                Assert.Equal(ValueStatus.Redacted, footer.Status);
                Assert.Null(footer.Scalar);
                ValueDto apiKey = await Read(service, chart, Property("ApiKey"));
                Assert.Equal(ValueStatus.Redacted, apiKey.Status);
                Assert.Equal("3", ((JsonNumberNode)(await Read(service, chart, Property("SeriesCount"))).Scalar!).RawText);
            }
        }

        [Fact]
        public async Task QueryFindsWinFormsControlsByManagedMembersIdentityAndType()
        {
            using (var ui = new ChartUi())
            using (var service = NewService())
            {
                ObjectRef form = await Resolve(service, ui.Form);
                QueryFindAllResult five = await service.FindAllAsync(Search(form, 256, Equal(JsonNumberNode.From(5), Property("SeriesCount"))), Deadline, 2000, null, None);
                Assert.True(five.Complete);
                Assert.Equal(new[] { "chart2" }, await Names(service, five));

                QueryFindAllResult charts = await service.FindAllAsync(Search(form, 256, Equal(new JsonStringNode("SeriesChart"), TypeFacet("Name"))), Deadline, 2000, null, None);
                Assert.Equal(new[] { "chart1", "chart2" }, await Names(service, charts));

                QueryFindAllResult byName = await service.FindAllAsync(Search(form, 256, Equal(new JsonStringNode("chart2"), Uia("automation_id"))), Deadline, 2000, null, None);
                Assert.Equal(new[] { "chart2" }, await Names(service, byName));

                QueryFindAllResult nested = await service.FindAllAsync(Search(form, 256, Equal(new JsonStringNode("Page 1 of 2"), Property("Footer"), Property("Text"))), Deadline, 2000, null, None);
                Assert.Equal(new[] { "chart1", "chart2" }, await Names(service, nested));

                QueryFindAllResult label = await service.FindAllAsync(Search(form, 256, Equal(new JsonStringNode("Revenue"), ObjectKey("Text"))), Deadline, 2000, null, None);
                Assert.Equal(new[] { "title" }, await Names(service, label));

                QueryFindAllResult secondButton = await service.FindAllAsync(Search(form, 256,
                    Equal(new JsonStringNode("Button"), TypeFacet("Name")), Equal(JsonNumberNode.From(2), ObjectKey("Ordinal"))), Deadline, 2000, null, None);
                Assert.Equal(new[] { "cancel" }, await Names(service, secondButton));

                QueryFindAllResult shallow = await service.FindAllAsync(Search(form, 1, Equal(JsonNumberNode.From(5), Property("SeriesCount"))), Deadline, 2000, null, None);
                Assert.Empty(shallow.Matches);
                QueryFindAllResult second = await service.FindAllAsync(Search(form, 2, Equal(JsonNumberNode.From(5), Property("SeriesCount"))), Deadline, 2000, null, None);
                Assert.Single(second.Matches);

                QueryFindResult first = await service.FindAsync(Search(form, 256, Equal(new JsonStringNode("SeriesChart"), TypeFacet("Name"))), Deadline, 2000, None);
                Assert.Equal("chart1", Text(await Read(service, first.Match, Uia("automation_id"))));
                Assert.Equal(2, first.Warning!.Count);
            }
        }

        [Fact]
        public async Task QueryNeverMatchesOrExposesAPasswordBoxValue()
        {
            using (var ui = new ChartUi())
            using (var service = NewService())
            {
                ObjectRef form = await Resolve(service, ui.Form);
                QueryFindAllResult text = await service.FindAllAsync(Search(form, 256, Equal(new JsonStringNode("hunter2"), Property("Text"))), Deadline, 2000, null, None);
                Assert.Empty(text.Matches);
                Assert.Equal(1, text.Unreadable!.Reasons["redacted"]);
                QueryFindAllResult migrated = await service.FindAllAsync(Search(form, 256, Equal(new JsonStringNode("hunter2"), ObjectKey("Text"))), Deadline, 2000, null, None);
                Assert.Empty(migrated.Matches);
                QueryFindAllResult byName = await service.FindAllAsync(Search(form, 256, Equal(new JsonStringNode("secretBox"), Uia("automation_id"))), Deadline, 2000, null, None);
                Assert.Single(byName.Matches);
            }
        }

        [Fact]
        public async Task QueryFromAControlSearchesItsOwnChildrenOnly()
        {
            using (var ui = new ChartUi())
            using (var service = NewService())
            {
                ObjectRef side = (await service.FindAsync(Search(await Resolve(service, ui.Form), 256, Equal(new JsonStringNode("side"), Uia("automation_id"))), Deadline, 2000, None)).Match;
                QueryFindAllResult inside = await service.FindAllAsync(Search(side, 256, Equal(new JsonStringNode("SeriesChart"), TypeFacet("Name"))), Deadline, 2000, null, None);
                Assert.Equal(new[] { "chart2" }, await Names(service, inside));
            }
        }

        [Fact]
        public async Task WritesAndCallsOnWinFormsControlsFollowTheAllowlist()
        {
            using (var ui = new ChartUi())
            {
                string type = typeof(SeriesChart).FullName!;
                string key;
                using (var plain = NewService())
                {
                    ObjectRef chart = await Resolve(plain, ui.Chart);
                    key = "clrProperty|" + typeof(SeriesChart).Assembly.GetName().Name + "|" + type + "|Caption|";
                    var denied = await Assert.ThrowsAsync<ProtocolException>(() => plain.WriteAsync("setProperty", chart, key, new JsonNode[] { new JsonStringNode("x") }, Deadline, 2000, None));
                    Assert.Equal(ErrorCodes.WriteDenied, denied.Code);
                    var deniedCall = await Assert.ThrowsAsync<ProtocolException>(() => plain.WriteAsync("call", chart, "Refresh(System.Int32)", new JsonNode[] { TypedInt(7) }, Deadline, 2000, None));
                    Assert.Equal(ErrorCodes.WriteDenied, deniedCall.Code);
                }
                var allowlist = new WriteAllowlist(new[] { new PropertyAllowEntry(type, "Caption"), new PropertyAllowEntry("System.Windows.Forms.TextBox", "Text") }, new[] { new AllowEntry(type, "Refresh(System.Int32)") });
                using (var service = NewService(null, allowlist))
                {
                    ObjectRef chart = await Resolve(service, ui.Chart);
                    WriteCallResult written = await service.WriteAsync("setProperty", chart, key, new JsonNode[] { new JsonStringNode("updated") }, Deadline, 2000, None);
                    Assert.Equal("performed", written.Audit.Outcome);
                    Assert.Equal("allowlist", written.Audit.Authorization);
                    Assert.Equal("updated", Text(await Read(service, chart, Property("Caption"))));
                    WriteCallResult called = await service.WriteAsync("call", chart, "Refresh(System.Int32)", new JsonNode[] { TypedInt(7) }, Deadline, 2000, None);
                    Assert.Equal("refreshed:7", Text(called.Result!));
                    Assert.Equal("performed", called.Audit.Outcome);
                    Assert.Equal("7", ((JsonNumberNode)(await Read(service, chart, Property("SeriesCount"))).Scalar!).RawText);
                    ObjectRef password = await Resolve(service, ui.Password);
                    var protectedWrite = await Assert.ThrowsAsync<ProtocolException>(() => service.WriteAsync("setProperty", password, "clrProperty|System.Windows.Forms|System.Windows.Forms.TextBox|Text|", new JsonNode[] { new JsonStringNode("x") }, Deadline, 2000, None));
                    Assert.Equal(ErrorCodes.WriteDenied, protectedWrite.Code);
                }
            }
        }

        private static JsonNode TypedInt(int value)
        {
            var node = new JsonObjectNode();
            node.Add("type", new JsonStringNode("System.Int32"));
            node.Add("value", JsonNumberNode.From(value));
            return node;
        }

        [Fact]
        public async Task AQueryReachesAControlHostedInAWpfWindowsFormsHost()
        {
            using (var ui = new DispatcherThread())
            {
                var executor = new DispatcherExecutor();
                using (var registry = new ObjectRegistry("hosted", executor))
                {
                    System.Windows.DependencyObject root = await ui.Dispatcher.InvokeAsync(() =>
                    {
                        var host = new System.Windows.Forms.Integration.WindowsFormsHost { Name = "chartHost" };
                        var hostedChart = new SeriesChart { Name = "hostedChart", SeriesCount = 7 };
                        hostedChart.Controls.Add(new WinForms.Label { Name = "hostedLabel", Text = "inside" });
                        host.Child = hostedChart;
                        var grid = new Grid { Name = "root" };
                        grid.Children.Add(host);
                        grid.Children.Add(new Button { Name = "wpfButton" });
                        return (System.Windows.DependencyObject)grid;
                    }).Task;
                    ObjectRef rootRef = registry.Register(root, ui.Dispatcher, TypeInfoBuilder.Build(root.GetType()));
                    var engine = new QueryEngine(executor, registry);
                    foreach (string tree in new[] { "objects", "combined" })
                    {
                        Locator locator = Search(rootRef, 256, Equal(JsonNumberNode.From(7), Property("SeriesCount")));
                        locator.Tree = tree;
                        locator.DepthMode = tree == "objects" ? "tree" : "peers";
                        QueryFindAllResult found = await engine.FindAllAsync(locator, Deadline, CancellationToken.None);
                        ObjectRef match = Assert.Single(found.Matches);
                        Assert.Equal(typeof(SeriesChart).FullName, match.Type.FullName);

                        locator = Search(rootRef, 256, Equal(new JsonStringNode("hostedLabel"), Uia("automation_id")));
                        locator.Tree = tree;
                        locator.DepthMode = tree == "objects" ? "tree" : "peers";
                        Assert.Single((await engine.FindAllAsync(locator, Deadline, CancellationToken.None)).Matches);

                        locator = Search(rootRef, 256, Equal(new JsonStringNode("inside"), ObjectKey("Text")));
                        locator.Tree = tree;
                        locator.DepthMode = tree == "objects" ? "tree" : "peers";
                        Assert.Single((await engine.FindAllAsync(locator, Deadline, CancellationToken.None)).Matches);
                    }
                    // The WPF elements around the host are still found, and a depth that ends at the host does not reach into it.
                    Locator wpf = Search(rootRef, 256, Equal(new JsonStringNode("wpfButton"), Uia("automation_id")));
                    wpf.Tree = "objects"; wpf.DepthMode = "tree";
                    Assert.Single((await engine.FindAllAsync(wpf, Deadline, CancellationToken.None)).Matches);
                    Locator shallow = Search(rootRef, 1, Equal(JsonNumberNode.From(7), Property("SeriesCount")));
                    shallow.Tree = "objects"; shallow.DepthMode = "tree";
                    Assert.Empty((await engine.FindAllAsync(shallow, Deadline, CancellationToken.None)).Matches);
                }
            }
        }

        [Fact]
        public void TheHostedChildIsFoundByTypeNameWithoutLoadingWinFormsForOtherObjects()
        {
            Assert.Null(WinFormsNative.HostedChild(new object()));
            Assert.Null(WinFormsNative.HostedChild(new List<int>()));
        }

        [Fact]
        public void OrdinalsCountSiblingsOfTheSameRuntimeType()
        {
            var form = new WinForms.Form();
            var first = new WinForms.Button(); var label = new WinForms.Label(); var second = new WinForms.Button();
            form.Controls.AddRange(new WinForms.Control[] { first, label, second });
            Assert.Equal(1, WinFormsNative.Ordinal(first));
            Assert.Equal(1, WinFormsNative.Ordinal(label));
            Assert.Equal(2, WinFormsNative.Ordinal(second));
            Assert.Equal(1, WinFormsNative.Ordinal(form));
        }
    }
}
