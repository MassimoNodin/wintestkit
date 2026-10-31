using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Automation.Peers;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Inspection;
using WinTestKit.Inspector.Agent.Inspection.Members;
using WinTestKit.Inspector.Agent.Query;
using WinTestKit.Inspector.Protocol;
using PathSegment = WinTestKit.Inspector.Protocol.PathSegment;
using Xunit;

namespace WinTestKit.Inspector.Agent.Query.Tests
{
    [Trait("Category", "Unit")]
    public sealed class ValuePredicateTests
    {
        public enum Sample { First = 1, Second = 2 }
        public sealed class Model : Button
        {
            public string TextValue => "Hello\nWorld";
            public bool BoolValue => true;
            public int IntValue => 1;
            public double DoubleValue => 1.0;
            public Sample EnumValue => Sample.Second;
            public object? EmptyValue => null;
            public object BrokenValue => throw new InvalidOperationException();
            public Brush BrushValue => Brushes.Red;
            public string SecretValue => "not disclosed";
            public string LongValue => new string('a', 4000) + "!";
        }
        private sealed class ProtectedButton : Button
        {
            protected override AutomationPeer OnCreateAutomationPeer() => new ProtectedPeer(this);
        }
        private sealed class ProtectedPeer : ButtonAutomationPeer
        {
            internal ProtectedPeer(Button owner) : base(owner) { }
            protected override bool IsPasswordCore() => true;
        }
        private static PathSegment Segment(string name, string kind = "property") => new PathSegment { Kind = kind, Name = name };
        private static Predicate Equal(string name, JsonNode value, string kind = "property") => new Predicate { Kind = "equals", Path = new[] { Segment(name, kind) }, Value = value };
        private static Predicate Regex(string name, string pattern, params string[] flags) => new Predicate { Kind = "regex", Path = new[] { Segment(name) }, Pattern = pattern, Flags = flags };
        private static void OnSta(Action action)
        {
            Exception? failure = null;
            var thread = new Thread(() => { try { action(); } catch (Exception error) { failure = error; } });
            thread.SetApartmentState(ApartmentState.STA); thread.Start(); thread.Join();
            if (failure != null) System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(failure).Throw();
        }
        private static void WithPredicate(Action<ObjectInspector, ObjectRegistry, QueryPredicateContext> action)
        {
            OnSta(() =>
            {
                var executor = new DispatcherExecutor();
                using (var registry = new ObjectRegistry("values", executor))
                    action(new ObjectInspector(), registry, new QueryPredicateContext(DateTime.UtcNow.AddSeconds(2)));
            });
        }
        public sealed class LargeButton : Button
        {
            public string Group => "shared";
            public string Key { get; set; } = "";
        }
        [Fact]
        public void LargeManagedQueriesComplete()
        {
            OnSta(() =>
            {
                var executor = new DispatcherExecutor();
                using (var registry = new ObjectRegistry("large", executor))
                {
                    var panel = new StackPanel();
                    for (int i = 0; i < 1500; i++) panel.Children.Add(new LargeButton { Key = "Large " + i });
                    for (int i = 0; i < 3500; i++) panel.Children.Add(i % 2 == 0 ? (UIElement)new Border() : new TextBlock());
                    var window = new Window { Content = panel };
                    var handle = registry.Register(window, window.Dispatcher, TypeInfoBuilder.Build(window.GetType()));
                    foreach (bool typed in new[] { false, true })
                    {
                        var locator = new Locator
                        {
                            Scope = new Scope { Kind = "window", Handle = handle },
                            Tree = "logical", DepthMode = "tree",
                            Depth = 10,
                            Limit = 2,
                            Predicates = typed ? new[] { Equal("FullName", new JsonStringNode(typeof(LargeButton).FullName!), "type"), Equal("Key", new JsonStringNode("Large 1499")) } :
                                new[] { Equal("Group", new JsonStringNode("shared")), Equal("Key", new JsonStringNode("Large 1499")) }
                        };
                        var samples = new List<long>();
                        for (int iteration = 0; iteration < 11; iteration++)
                        {
                            var watch = System.Diagnostics.Stopwatch.StartNew();
                            var task = new QueryEngine(executor, registry).FindAllAsync(locator, DateTime.UtcNow.AddSeconds(2), CancellationToken.None);
                            var frame = new DispatcherFrame(); task.ContinueWith(_ => frame.Continue = false, TaskScheduler.Default); Dispatcher.PushFrame(frame);
                            var result = task.GetAwaiter().GetResult();
                            if (iteration > 0) samples.Add(watch.ElapsedMilliseconds);
                            Assert.True(result.Complete); Assert.Single(result.Matches);
                        }
                        samples.Sort();
                        Console.WriteLine("Large managed typed={0}: median={1} ms, p95={2} ms", typed, (samples[4] + samples[5]) / 2.0, samples[9]);
#if !NET48
                        Assert.True((samples[4] + samples[5]) / 2.0 <= 100);
#endif
                    }
                }
            });
        }
        [Fact]
        public void ScalarEqualityAndRegexUseReaderValues()
        {
            WithPredicate((inspector, registry, context) =>
            {
                var model = new Model();
                bool Match(Predicate predicate) => PredicateFactory.Create(predicate, inspector, registry).Matches(model, context);
                Assert.True(Match(Equal("TextValue", new JsonStringNode("Hello\nWorld"))));
                Assert.True(Match(Equal("BoolValue", new JsonBoolNode(true))));
                Assert.True(Match(Equal("IntValue", new JsonNumberNode("1.0"))));
                Assert.True(Match(Equal("DoubleValue", new JsonNumberNode("1"))));
                Assert.True(Match(Equal("EnumValue", new JsonNumberNode("2"))));
                Assert.True(Match(Equal("EnumValue", new JsonStringNode("Second"))));
                Assert.False(Match(Equal("BoolValue", new JsonNumberNode("1"))));
                Assert.False(Match(Equal("IntValue", new JsonBoolNode(true))));
                Assert.False(Match(Equal("IntValue", new JsonStringNode("1"))));
                Assert.False(Match(Equal("EnumValue", new JsonNumberNode("2.0"))));
                Assert.True(Match(Regex("TextValue", "^world$", "ignoreCase", "multiline")));
                Assert.True(Match(Regex("TextValue", "Hello.World", "singleline")));
                Assert.True(Match(Regex("EnumValue", "^second$", "ignoreCase")));
                Assert.False(Match(Regex("IntValue", "1")));
                Assert.False(Match(Equal("EmptyValue", new JsonStringNode("anything"))));
                var nested = Equal("EmptyValue", new JsonStringNode("anything"));
                nested.Path = new[] { Segment("EmptyValue"), Segment("Name") };
                Assert.False(Match(nested));
            });
        }
        [Fact]
        public void ErrorsAndRedactedPathsNeverLeakValues()
        {
            WithPredicate((inspector, registry, context) =>
            {
                var model = new Model();
                void Check(Predicate predicate, string status, bool hasPath, DependencyObject? target = null, ObjectInspector? reader = null)
                {
                    var error = Assert.Throws<ProtocolException>(() => PredicateFactory.Create(predicate, reader ?? inspector, registry).Matches(target ?? model, context));
                    Assert.Equal(ErrorCodes.ValueUnreadable, error.Code);
                    Assert.Equal(status, ((JsonStringNode)error.Details!.Get("status")).Value);
                    Assert.Equal(hasPath, error.Details.TryGet("path", out _));
                    Assert.DoesNotContain("not disclosed", error.Message);
                }
                Check(Equal("BrokenValue", new JsonStringNode("x")), "exception", true);
                Check(Equal("BrushValue", new JsonStringNode("x")), "unsupported", true);
                Check(Equal("SecretValue", new JsonStringNode("x")), "redacted", false);
                Check(Equal("Content", new JsonStringNode("x")), "redacted", true, new ProtectedButton());
                Check(Equal("TextValue", new JsonStringNode("x")), "redacted", false, reader: new ObjectInspector(new[] { "TextValue" }));
                var predicate = (ValuePredicate)PredicateFactory.Create(Equal("TextValue", new JsonStringNode("x")), inspector, registry);
                Assert.False(predicate.MatchesValue(new ValueDto { Status = "stale", Kind = "unavailable" }, context));
            });
        }
        [Fact]
        public void UiaPathsAndControlTypes()
        {
            WithPredicate((inspector, registry, context) =>
            {
                var button = new Button { Name = "Named", Content = "Caption" };
                bool Match(DependencyObject target, string name, string value) => PredicateFactory.Create(Equal(name, new JsonStringNode(value), "uia"), inspector, registry).Matches(target, context);
                Assert.True(Match(button, "automation_id", "Named"));
                AutomationProperties.SetAutomationId(button, "explicit");
                Assert.True(Match(button, "automation_id", "explicit"));
                Assert.True(Match(button, "class_name", "Button"));
                Assert.True(Match(button, "name", "Caption"));
                Assert.True(Match(button, "control_type", "Button"));
                var border = new Border { Name = "BorderName" };
                Assert.False(Match(border, "automation_id", "BorderName"));
                Assert.False(Match(border, "class_name", "Border"));
                Assert.False(Match(border, "name", "anything"));
                Assert.False(Match(border, "control_type", "Custom"));
                Assert.False(PredicateFactory.Create(Equal("name", new JsonStringNode("x"), "uia"), new ObjectInspector(new[] { "name" }), registry).Matches(border, context));
                var uiaRegex = new Predicate { Kind = "regex", Path = new[] { Segment("name", "uia") }, Pattern = "^caption$", Flags = new[] { "ignoreCase" } };
                Assert.True(PredicateFactory.Create(uiaRegex, inspector, registry).Matches(button, context));
                Assert.False(Match(new Border(), "automation_id", ""));
                string[] names = { "Button", "Calendar", "CheckBox", "ComboBox", "Edit", "Hyperlink", "Image", "ListItem", "List", "Menu", "MenuBar", "MenuItem", "ProgressBar", "RadioButton", "ScrollBar", "Slider", "Spinner", "StatusBar", "Tab", "TabItem", "Text", "ToolBar", "ToolTip", "Tree", "TreeItem", "Custom", "Group", "Thumb", "DataGrid", "DataItem", "Document", "SplitButton", "Window", "Pane", "Header", "HeaderItem", "Table", "TitleBar", "Separator", "SemanticZoom", "AppBar" };
                Assert.All(Enum.GetValues(typeof(AutomationControlType)).Cast<AutomationControlType>(), type => Assert.Contains(ValuePredicate.ControlTypeName(type), names));
            });
        }
        [Fact]
        public void RegexTimeoutIsReported()
        {
            WithPredicate((inspector, registry, context) =>
            {
                var predicate = PredicateFactory.Create(Regex("LongValue", "(a+)+$"), inspector, registry);
                Assert.Equal(ErrorCodes.RegexTimeout, Assert.Throws<ProtocolException>(() => predicate.Matches(new Model(), context)).Code);
            });
        }
        [Fact]
        public void UiaClassNameUsesTheAutomationPeer()
        {
            WithPredicate((inspector, registry, context) =>
            {
                var model = new Model();
                Assert.True(PredicateFactory.Create(Equal("class_name", new JsonStringNode("Button"), "uia"), inspector, registry).Matches(model, context));
                Assert.False(PredicateFactory.Create(Equal("class_name", new JsonStringNode("Model"), "uia"), inspector, registry).Matches(model, context));
            });
        }
        [Fact]
        public void UiaMismatchSkipsManagedReadsEvenWhenListedSecond()
        {
            OnSta(() =>
            {
                var executor = new DispatcherExecutor();
                using (var registry = new ObjectRegistry("query", executor))
                {
                    var model = new Model();
                    ObjectRef handle = registry.Register(model, model.Dispatcher, TypeInfoBuilder.Build(model.GetType()));
                    var locator = new Locator
                    {
                        Scope = new Scope { Kind = "object", Handle = handle },
                        Tree = "logical", DepthMode = "tree",
                        Depth = 0,
                        Limit = 1,
                        Predicates = new[] { Equal("SecretValue", new JsonStringNode("x")), Equal("automation_id", new JsonStringNode("other"), "uia") }
                    };
                    var task = new QueryEngine(executor, registry).FindAllAsync(locator, DateTime.UtcNow.AddSeconds(2), CancellationToken.None);
                    var frame = new DispatcherFrame();
                    task.ContinueWith(_ => frame.Continue = false, TaskScheduler.Default);
                    Dispatcher.PushFrame(frame);
                    Assert.Empty(task.GetAwaiter().GetResult().Matches);
                }
            });
        }
        [Fact]
        public void MismatchDoesNotHideUnreadablePredicate()
        {
            OnSta(() =>
            {
                var executor = new DispatcherExecutor();
                using (var registry = new ObjectRegistry("query", executor))
                {
                    var model = new Model();
                    ObjectRef handle = registry.Register(model, model.Dispatcher, TypeInfoBuilder.Build(model.GetType()));
                    var locator = new Locator
                    {
                        Scope = new Scope { Kind = "object", Handle = handle },
                        Tree = "logical", DepthMode = "tree",
                        Depth = 0,
                        Limit = 1,
                        Predicates = new[] { Equal("TextValue", new JsonStringNode("mismatch")), Equal("SecretValue", new JsonStringNode("x")) }
                    };
                    var task = new QueryEngine(executor, registry).FindAsync(locator, DateTime.UtcNow.AddSeconds(2), CancellationToken.None);
                    var frame = new DispatcherFrame();
                    task.ContinueWith(_ => frame.Continue = false, TaskScheduler.Default);
                    Dispatcher.PushFrame(frame);
                    var error = Assert.Throws<ProtocolException>(() => task.GetAwaiter().GetResult());
                    Assert.Equal(ErrorCodes.ValueUnreadable, error.Code);
                }
            });
        }
    }
}
