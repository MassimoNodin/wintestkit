using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Media;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Inspection;
using WinTestKit.Inspector.Agent.Inspection.Members;
using WinTestKit.Inspector.Agent.Query;
using WinTestKit.Inspector.Protocol;
using Xunit;
using PathSegment = WinTestKit.Inspector.Protocol.PathSegment;

namespace WinTestKit.Inspector.Agent.Query.Tests
{
    [Collection("Wpf windows")]
    public sealed class ObjectTreeTests
    {
        private static void OnSta(Action action)
        {
            Exception? failure = null;
            var thread = new Thread(() => { try { action(); } catch (Exception error) { failure = error; } });
            thread.SetApartmentState(ApartmentState.STA);
            thread.Start();
            thread.Join();
            if (failure != null) System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(failure).Throw();
        }

        private static T Pump<T>(Task<T> task)
        {
            var frame = new DispatcherFrame();
            task.ContinueWith(_ => frame.Continue = false, TaskScheduler.Default);
            Dispatcher.PushFrame(frame);
            return task.GetAwaiter().GetResult();
        }

        private sealed class Labelled { public override string ToString() => "label"; }
        private sealed class Bare { }
        private sealed class Throws { public override string ToString() => throw new InvalidOperationException("boom"); }
        private sealed class ApiKeyHolder { public override string ToString() => "key-text"; }
        private sealed class ApiKeyBare { }

        // A control template of a border around one presenter, the way most controls are styled.
        private static ControlTemplate Chrome(Type control, Type presenter)
        {
            var border = new FrameworkElementFactory(typeof(Border));
            border.AppendChild(new FrameworkElementFactory(presenter));
            return new ControlTemplate(control) { VisualTree = border };
        }

        private static void Layout(FrameworkElement element)
        {
            element.ApplyTemplate();
            element.Measure(new Size(400, 400));
            element.Arrange(new Rect(0, 0, 400, 400));
        }

        private static IEnumerable<DependencyObject> Visual(DependencyObject root)
        {
            for (int index = 0; index < VisualTreeHelper.GetChildrenCount(root); index++)
            {
                DependencyObject child = VisualTreeHelper.GetChild(root, index);
                yield return child;
                foreach (DependencyObject descendant in Visual(child)) yield return descendant;
            }
        }

        private static ValueDto Value(object root, string name = "Text", RedactionPolicy? policy = null, CancellationToken token = default(CancellationToken))
        {
            using (var registry = new ObjectRegistry("text", new DispatcherExecutor()))
                return ObjectTreeValues.Read(root, name, policy ?? new RedactionPolicy(new string[0]), registry, Dispatcher.CurrentDispatcher, token, null);
        }

        private static string Text(object root, RedactionPolicy? policy = null)
        {
            ValueDto value = Value(root, "Text", policy);
            Assert.Equal("ok", value.Status);
            return ((JsonStringNode)value.Scalar!).Value;
        }

        // ------------------------------------------------------------------ the model

        [Trait("Category", "Unit")]
        [Fact]
        public void ControlTemplatePartsAreHiddenAndTheirContentIsKept()
        {
            OnSta(() =>
            {
                var button = new Button { Content = "content", Template = Chrome(typeof(Button), typeof(ContentPresenter)) };
                Layout(button);
                DependencyObject border = VisualTreeHelper.GetChild(button, 0);
                DependencyObject presenter = VisualTreeHelper.GetChild(border, 0);
                Assert.True(ObjectTree.Hidden(border));
                Assert.True(ObjectTree.Hidden(presenter));
                // The text the presenter generates belongs to the presenter (a data template), so it stays.
                var text = Assert.IsType<TextBlock>(Assert.Single(ObjectTree.Children(button)));
                Assert.False(ObjectTree.Hidden(text));
                Assert.Same(button, ObjectTree.Parent(text));
                Assert.Null(ObjectTree.Parent(button));
            });
        }

        [Trait("Category", "Unit")]
        [Fact]
        public void ItemsPanelElementsAreHiddenSoItemsAreChildrenOfTheControl()
        {
            OnSta(() =>
            {
                var list = new ItemsControl { Template = Chrome(typeof(ItemsControl), typeof(ItemsPresenter)) };
                var first = new Button(); var middle = new TextBlock(); var last = new Button();
                list.Items.Add(first); list.Items.Add(middle); list.Items.Add(last);
                Layout(list);
                Panel panel = Visual(list).OfType<Panel>().Single();
                Assert.True(ObjectTree.Hidden(panel));
                Assert.Equal(new DependencyObject[] { first, middle, last }, ObjectTree.Children(list).ToArray());
                Assert.Same(list, ObjectTree.Parent(middle));
                Assert.Equal(new[] { 1, 1, 2 }, new DependencyObject[] { first, middle, last }.Select(ObjectTree.Ordinal).ToArray());
            });
        }

        [Trait("Category", "Unit")]
        [Fact]
        public void DataTemplateContentIsKept()
        {
            OnSta(() =>
            {
                var content = new FrameworkElementFactory(typeof(Border));
                content.AppendChild(new FrameworkElementFactory(typeof(TextBlock)));
                var control = new ContentControl
                {
                    Template = Chrome(typeof(ContentControl), typeof(ContentPresenter)),
                    ContentTemplate = new DataTemplate { VisualTree = content },
                    Content = "x"
                };
                Layout(control);
                var border = Assert.IsType<Border>(Assert.Single(ObjectTree.Children(control)));
                Assert.IsType<TextBlock>(Assert.Single(ObjectTree.Children(border)));
                Assert.Same(control, ObjectTree.Parent(border));
            });
        }

        [Trait("Category", "Unit")]
        [Fact]
        public void VisibleDescendantsOfNestedHiddenElementsReparentInVisualOrder()
        {
            OnSta(() =>
            {
                // Border > StackPanel > (header presenter, content presenter): two hidden levels above both.
                var stack = new FrameworkElementFactory(typeof(StackPanel));
                var header = new FrameworkElementFactory(typeof(ContentPresenter));
                header.SetValue(ContentPresenter.ContentSourceProperty, "Header");
                stack.AppendChild(header);
                stack.AppendChild(new FrameworkElementFactory(typeof(ContentPresenter)));
                var border = new FrameworkElementFactory(typeof(Border));
                border.AppendChild(stack);
                var group = new GroupBox { Template = new ControlTemplate(typeof(GroupBox)) { VisualTree = border } };
                var headerButton = new Button(); var contentButton = new Button();
                group.Header = headerButton; group.Content = contentButton;
                Layout(group);
                Assert.Equal(new DependencyObject[] { headerButton, contentButton }, ObjectTree.Children(group).ToArray());
                Assert.Same(group, ObjectTree.Parent(contentButton));
                // Same type under one object-tree parent: one sequence, even across the hidden levels.
                Assert.Equal(1, ObjectTree.Ordinal(headerButton));
                Assert.Equal(2, ObjectTree.Ordinal(contentButton));
            });
        }

        [Trait("Category", "Unit")]
        [Fact]
        public void NestedTemplatedControlsKeepOneLevelEach()
        {
            OnSta(() =>
            {
                var inner = new Button { Content = "inner", Template = Chrome(typeof(Button), typeof(ContentPresenter)) };
                var outer = new Button { Content = inner, Template = Chrome(typeof(Button), typeof(ContentPresenter)) };
                Layout(outer);
                Assert.Same(inner, Assert.Single(ObjectTree.Children(outer)));
                Assert.IsType<TextBlock>(Assert.Single(ObjectTree.Children(inner)));
                Assert.Same(outer, ObjectTree.Parent(inner));
            });
        }

        [Trait("Category", "Unit")]
        [Fact]
        public void OrdinalsCountOnlySameRuntimeTypeInVisualOrder()
        {
            OnSta(() =>
            {
                var root = new StackPanel();
                var first = new Button(); var other = new TextBlock(); var second = new Button(); var subclass = new ToggleButton(); var third = new Button();
                foreach (UIElement child in new UIElement[] { first, other, second, subclass, third }) root.Children.Add(child);
                Assert.Equal(new object[] { first, other, second, subclass, third }, ObjectTree.Children(root).Cast<object>());
                Assert.Equal(new[] { 1, 1, 2, 1, 3 }, new DependencyObject[] { first, other, second, subclass, third }.Select(ObjectTree.Ordinal).ToArray());
                Assert.Equal(1, ObjectTree.Ordinal(root));
                var cache = new ObjectTreeCache();
                foreach (DependencyObject child in new DependencyObject[] { first, other, second, subclass, third, root }) Assert.Equal(ObjectTree.Ordinal(child), cache.Ordinal(child));
                cache.Clear();
                Assert.Equal(3, cache.Ordinal(third));
            });
        }

        [Trait("Category", "Unit")]
        [Fact]
        public void AHiddenElementCountsAmongItsOwnVisualSiblings()
        {
            OnSta(() =>
            {
                var button = new Button { Content = "x", Template = Chrome(typeof(Button), typeof(ContentPresenter)) };
                Layout(button);
                DependencyObject border = VisualTreeHelper.GetChild(button, 0);
                Assert.Equal(1, ObjectTree.Ordinal(border));
                Assert.Equal(1, new ObjectTreeCache().Ordinal(border));
            });
        }

        // ------------------------------------------------------------------ text (T3)

        [Trait("Category", "Unit")]
        [Fact]
        public void TextFollowsEachClassBranch()
        {
            OnSta(() =>
            {
                Assert.Equal("text", Text(new TextBlock { Text = "text" }));
                Assert.Equal("edit", Text(new TextBox { Text = "edit" }));
                Assert.Equal("", Text(new RichTextBox()));
                Assert.Equal("title", Text(new Window { Title = "title", Content = "ignored" }));
                // HeaderedContentControl: the first non-empty of Content and Header.
                Assert.Equal("content", Text(new GroupBox { Content = "content", Header = "header" }));
                Assert.Equal("header", Text(new GroupBox { Header = "header" }));
                Assert.Equal("header", Text(new Expander { Content = "", Header = "header" }));
                Assert.Equal("", Text(new TabItem()));
                // HeaderedItemsControl: only the header.
                Assert.Equal("menu", Text(new MenuItem { Header = "menu" }));
                Assert.Equal("node", Text(new TreeViewItem { Header = "node" }));
                // ContentControl and ContentPresenter: the content.
                Assert.Equal("button", Text(new Button { Content = "button" }));
                Assert.Equal("presented", Text(new ContentPresenter { Content = "presented" }));
                // Any other class has no text.
                Assert.Equal("", Text(new Border()));
                Assert.Equal("", Text(new StackPanel()));
                Assert.Equal("", Text(new ListBox { ItemsSource = new[] { "a" } }));
            });
        }

        [Trait("Category", "Unit")]
        [Fact]
        public void TextConvertsValuesLikeTheMigrationModel()
        {
            OnSta(() =>
            {
                // An element is read as an element (recursively), never by its ToString.
                Assert.Equal("nested", Text(new Button { Content = new TextBlock { Text = "nested" } }));
                Assert.Equal("deep", Text(new Button { Content = new Button { Content = new Button { Content = new TextBlock { Text = "deep" } } } }));
                Assert.Equal("", Text(new Button { Content = new Border() }));
                Assert.Equal("", Text(new Button { Content = null }));
                // Other objects: ToString only when the runtime type overrides it.
                Assert.Equal("label", Text(new Button { Content = new Labelled() }));
                Assert.Equal("", Text(new Button { Content = new Bare() }));
                Assert.Equal("42", Text(new Button { Content = 42 }));
                Assert.Equal("Monday", Text(new Button { Content = DayOfWeek.Monday }));
                // The root can be a plain value too (an item of an items control).
                Assert.Equal("label", Text(new Labelled()));
                Assert.Equal("", Text(new Bare()));
                Assert.Equal("raw", Text("raw"));
            });
        }

        [Trait("Category", "Unit")]
        [Fact]
        public void TextIsSafeToReadFromApplicationCode()
        {
            OnSta(() =>
            {
                // A throwing ToString is an unreadable value that carries the sanitized error, not an exception.
                ValueDto thrown = Value(new Button { Content = new Throws() });
                Assert.Equal("exception", thrown.Status);
                Assert.Equal("System.InvalidOperationException", thrown.Message);
                Assert.Equal("boom", thrown.ErrorMessage);
                Assert.Null(thrown.Scalar);
                // Protected identities have no readable text, directly or nested in another element.
                ValueDto password = Value(new PasswordBox());
                Assert.Equal("redacted", password.Status);
                Assert.Equal("identity", password.RedactionRule);
                Assert.Equal("redacted", Value(new Button { Content = new PasswordBox() }).Status);
                // Redacted member names and type names follow the policy of any managed read.
                var policy = new RedactionPolicy(new[] { "Title" });
                ValueDto title = Value(new Window { Title = "secret title" }, "Text", policy);
                Assert.Equal("redacted", title.Status);
                Assert.Equal("Title", title.RedactionRule);
                Assert.Equal("redacted", Value(new Button { Content = "x" }, "Text", new RedactionPolicy(new[] { "Content" })).Status);
                ValueDto type = Value(new Button { Content = new ApiKeyHolder() });
                Assert.Equal("redacted", type.Status);
                Assert.Equal("apikey", type.RedactionRule);
                // A type without text to show reveals nothing and is not redacted.
                Assert.Equal("", Text(new Button { Content = new ApiKeyBare() }));
                // Long text is shortened like any value, and a read that runs past the request is stopped.
                Assert.Equal("truncated", Value(new TextBlock { Text = new string('a', ProtocolLimits.MaxScalarChars + 1) }).Status);
                using (var cancelled = new CancellationTokenSource())
                {
                    cancelled.Cancel();
                    Assert.Throws<OperationCanceledException>(() => Value(new Button(), "Text", null, cancelled.Token));
                }
            });
        }

        // ------------------------------------------------------------------ both keys as reads

        [Trait("Category", "Unit")]
        [Fact]
        public void BothKeysReadThroughThePathReader()
        {
            OnSta(() =>
            {
                var panel = new StackPanel();
                var first = new Button { Content = "one" }; var second = new Button { Content = "two" };
                panel.Children.Add(first); panel.Children.Add(second);
                using (var registry = new ObjectRegistry("read", new DispatcherExecutor()))
                {
                    var inspector = new ObjectInspector();
                    ValueDto Read(object target, string name) =>
                        inspector.ReadPath(target, new[] { new PathSegment { Kind = "object", Name = name } }, registry, Dispatcher.CurrentDispatcher, CancellationToken.None);
                    ValueDto text = Read(second, "Text");
                    Assert.Equal("ok", text.Status);
                    Assert.Equal("two", ((JsonStringNode)text.Scalar!).Value);
                    ValueDto ordinal = Read(second, "Ordinal");
                    Assert.Equal("integer", ordinal.Kind);
                    Assert.Equal("2", ((JsonNumberNode)ordinal.Scalar!).RawText);
                    Assert.Equal("1", ((JsonNumberNode)Read(first, "Ordinal").Scalar!).RawText);
                    Assert.Equal("unavailable", Read("not an element", "Ordinal").Status);
                    // A password field has an ordinal but no text.
                    Assert.Equal("redacted", Read(new PasswordBox(), "Text").Status);
                    Assert.Equal("ok", Read(new PasswordBox(), "Ordinal").Status);
                    Assert.Equal(ErrorCodes.InvalidParams, Assert.Throws<ProtocolException>(() => inspector.ReadPath(first,
                        new[] { new PathSegment { Kind = "object", Name = "Text" }, new PathSegment { Kind = "property", Name = "Length" } }, registry, Dispatcher.CurrentDispatcher, CancellationToken.None)).Code);
                    Assert.Throws<ProtocolException>(() => Read(first, "Other"));
                }
            });
        }

        // ------------------------------------------------------------------ queries

        private static Predicate Equal(string key, JsonNode value, string kind = "equals") =>
            new Predicate { Kind = kind, Path = new[] { new PathSegment { Kind = "object", Name = key } }, Value = value };
        private static Predicate Regex(string key, string pattern) =>
            new Predicate { Kind = "regex", Path = new[] { new PathSegment { Kind = "object", Name = key } }, Pattern = pattern, Flags = new string[0] };
        private static Predicate OfType<T>() => new Predicate { Kind = "assignableTo", FullName = typeof(T).FullName };

        private static Locator ObjectScope(ObjectRegistry registry, DependencyObject root, int depth = 256, params Predicate[] predicates)
        {
            ObjectRef handle = registry.Register(root, root.Dispatcher, TypeInfoBuilder.Build(root.GetType()));
            return new Locator { Scope = new Scope { Kind = "object", Handle = handle }, Tree = "objects", DepthMode = "tree", Depth = depth, Limit = 200, Predicates = predicates };
        }

        private static Task<QueryFindAllResult> FindAll(QueryEngine engine, Locator locator, string? continuation = null) =>
            engine.FindAllAsync(locator, DateTime.UtcNow.AddSeconds(120), 2000, continuation, CancellationToken.None);

        private static string[] Ids(ObjectRegistry registry, params DependencyObject[] items) =>
            items.Select(item => registry.Register(item, item.Dispatcher, TypeInfoBuilder.Build(item.GetType())).ObjectId).ToArray();

        // A window-like tree: a templated group box (header and content re-parented) holding a templated button.
        private sealed class Tree
        {
            internal GroupBox Group; internal Button Header; internal Button Content; internal TextBlock Caption; internal StackPanel Root;
            internal Tree()
            {
                var stack = new FrameworkElementFactory(typeof(StackPanel));
                var header = new FrameworkElementFactory(typeof(ContentPresenter));
                header.SetValue(ContentPresenter.ContentSourceProperty, "Header");
                stack.AppendChild(header);
                stack.AppendChild(new FrameworkElementFactory(typeof(ContentPresenter)));
                var border = new FrameworkElementFactory(typeof(Border));
                border.AppendChild(stack);
                Group = new GroupBox { Template = new ControlTemplate(typeof(GroupBox)) { VisualTree = border } };
                Header = new Button { Content = "head", Template = Chrome(typeof(Button), typeof(ContentPresenter)) };
                Content = new Button { Content = "body", Template = Chrome(typeof(Button), typeof(ContentPresenter)) };
                Group.Header = Header; Group.Content = Content;
                Caption = new TextBlock { Text = "caption" };
                Root = new StackPanel();
                Root.Children.Add(Group); Root.Children.Add(Caption);
                Layout(Header); Layout(Content); Layout(Group);
            }
        }

        [Trait("Category", "Unit")]
        [Fact]
        public void QueriesVisitTheObjectTreeInPreOrderAndCountItsLevels()
        {
            OnSta(() =>
            {
                var tree = new Tree();
                var executor = new DispatcherExecutor();
                using (var registry = new ObjectRegistry("objects", executor))
                {
                    var engine = new QueryEngine(executor, registry);
                    // Depth-first: a node, then everything below it, before its next sibling.
                    QueryFindAllResult all = Pump(FindAll(engine, ObjectScope(registry, tree.Root)));
                    TextBlock headText = (TextBlock)ObjectTree.Children(tree.Header).Single(), bodyText = (TextBlock)ObjectTree.Children(tree.Content).Single();
                    Assert.Equal(Ids(registry, tree.Root, tree.Group, tree.Header, headText, tree.Content, bodyText, tree.Caption), all.Matches.Select(match => match.ObjectId).ToArray());
                    Assert.True(all.Complete);
                    // Levels of the object tree: the template parts do not count.
                    Assert.Equal(Ids(registry, tree.Root), Pump(FindAll(engine, ObjectScope(registry, tree.Root, 0))).Matches.Select(match => match.ObjectId).ToArray());
                    Assert.Equal(Ids(registry, tree.Root, tree.Group, tree.Caption), Pump(FindAll(engine, ObjectScope(registry, tree.Root, 1))).Matches.Select(match => match.ObjectId).ToArray());
                    Assert.Equal(Ids(registry, tree.Root, tree.Group, tree.Header, tree.Content, tree.Caption), Pump(FindAll(engine, ObjectScope(registry, tree.Root, 2))).Matches.Select(match => match.ObjectId).ToArray());
                    // The first match is the pre-order one; Index counts in that order.
                    Locator buttons = ObjectScope(registry, tree.Root, 256, OfType<Button>());
                    Assert.Equal(Ids(registry, tree.Header)[0], Pump(engine.FindAsync(buttons, DateTime.UtcNow.AddSeconds(60), CancellationToken.None)).Match.ObjectId);
                    buttons.Index = 1;
                    Assert.Equal(Ids(registry, tree.Content)[0], Pump(engine.FindAsync(buttons, DateTime.UtcNow.AddSeconds(60), CancellationToken.None)).Match.ObjectId);
                    GC.KeepAlive(tree);
                }
            });
        }

        [Trait("Category", "Unit")]
        [Fact]
        public void TheDefaultTreesAreUnchanged()
        {
            OnSta(() =>
            {
                var tree = new Tree();
                var executor = new DispatcherExecutor();
                using (var registry = new ObjectRegistry("default", executor))
                {
                    var engine = new QueryEngine(executor, registry);
                    Locator visual = ObjectScope(registry, tree.Root);
                    visual.Tree = "visual";
                    // The visual tree still contains the template parts, so it has more elements than the object tree.
                    int visualCount = Pump(FindAll(engine, visual)).Matches.Count;
                    int objectCount = Pump(FindAll(engine, ObjectScope(registry, tree.Root))).Matches.Count;
                    Assert.True(visualCount > objectCount);
                    GC.KeepAlive(tree);
                }
            });
        }

        [Trait("Category", "Unit")]
        [Fact]
        public void TextAndOrdinalMatchAsPredicates()
        {
            OnSta(() =>
            {
                var tree = new Tree();
                var executor = new DispatcherExecutor();
                using (var registry = new ObjectRegistry("predicates", executor))
                {
                    var engine = new QueryEngine(executor, registry);
                    string[] Found(params Predicate[] predicates) => Pump(FindAll(engine, ObjectScope(registry, tree.Root, 256, predicates))).Matches.Select(match => match.ObjectId).ToArray();
                    Assert.Equal(Ids(registry, tree.Content), Found(OfType<Button>(), Equal("Text", new JsonStringNode("body"))));
                    Assert.Equal(Ids(registry, tree.Caption), Found(Equal("Text", new JsonStringNode("caption"))));
                    // The group box takes its content's text (the content is an element, read as an element).
                    Assert.Equal(Ids(registry, tree.Group, tree.Content, (TextBlock)ObjectTree.Children(tree.Content).Single()), Found(Equal("Text", new JsonStringNode("body"))));
                    // Regular expressions use the shared grammar.
                    Assert.Equal(Ids(registry, tree.Group, tree.Content, (TextBlock)ObjectTree.Children(tree.Content).Single()), Found(Regex("Text", "^body$")));
                    Assert.Equal(Ids(registry, tree.Header, tree.Content), Found(OfType<Button>(), Regex("Text", "^(head|body)$")));
                    // The ordinal is the position among same-type siblings, whatever the text.
                    Assert.Equal(Ids(registry, tree.Root, tree.Group, tree.Header, (TextBlock)ObjectTree.Children(tree.Header).Single(), (TextBlock)ObjectTree.Children(tree.Content).Single(), tree.Caption), Found(Equal("Ordinal", JsonNumberNode.From(1))));
                    Assert.Equal(Ids(registry, tree.Content), Found(Equal("Ordinal", JsonNumberNode.From(2))));
                    Assert.Equal(Ids(registry, tree.Content), Found(Equal("Ordinal", new JsonStringNode("2"), "equalsText")));
                    Assert.Equal(Ids(registry, tree.Content), Found(OfType<Button>(), Equal("Ordinal", JsonNumberNode.From(2)), Equal("Text", new JsonStringNode("body"))));
                    Assert.Empty(Found(OfType<Button>(), Equal("Ordinal", JsonNumberNode.From(3))));
                    GC.KeepAlive(tree);
                }
            });
        }

        [Trait("Category", "Unit")]
        [Fact]
        public void APasswordFieldNeverMatchesTextAndABrokenToStringIsReported()
        {
            OnSta(() =>
            {
                var root = new StackPanel();
                var password = new PasswordBox(); var match = new Button { Content = "ok" };
                root.Children.Add(password); root.Children.Add(match);
                var executor = new DispatcherExecutor();
                using (var registry = new ObjectRegistry("unreadable", executor))
                {
                    var engine = new QueryEngine(executor, registry);
                    // The password field is skipped instead of failing the whole search.
                    Assert.Equal(Ids(registry, match), Pump(FindAll(engine, ObjectScope(registry, root, 256, Equal("Text", new JsonStringNode("ok"))))).Matches.Select(item => item.ObjectId).ToArray());
                    root.Children.Add(new Button { Content = new Throws() });
                    var error = Assert.Throws<ProtocolException>(() => Pump(FindAll(engine, ObjectScope(registry, root, 256, Equal("Text", new JsonStringNode("ok"))))));
                    Assert.Equal(ErrorCodes.ValueUnreadable, error.Code);
                    GC.KeepAlive(root);
                }
            });
        }

        [Trait("Category", "Unit")]
        [Fact]
        public void ObjectModeScansContinueAcrossRequestsAndEndCompletely()
        {
            OnSta(() =>
            {
                // 24,000 elements need three requests; the continuation keeps pre-order and the per-request cap.
                var root = new StackPanel();
                for (int group = 0; group < 4; group++)
                {
                    var panel = new StackPanel();
                    for (int index = 0; index < 6000; index++) panel.Children.Add(new Button());
                    root.Children.Add(panel);
                }
                var special = new Button { Content = "needle" };
                ((StackPanel)root.Children[3]).Children.Add(special);
                var executor = new DispatcherExecutor();
                using (var registry = new ObjectRegistry("continue", executor))
                {
                    var engine = new QueryEngine(executor, registry);
                    Locator locator = ObjectScope(registry, root, 256, Equal("Text", new JsonStringNode("needle")));
                    QueryFindAllResult result = Pump(FindAll(engine, locator));
                    int requests = 1;
                    Assert.False(result.Complete);
                    Assert.NotNull(result.Continuation);
                    Assert.Equal(1, engine.SuspendedCount);
                    while (result.Continuation != null && requests < 20) { result = Pump(FindAll(engine, locator, result.Continuation)); requests++; }
                    Assert.True(requests >= 3, "requests: " + requests);
                    Assert.True(result.Complete);
                    Assert.Equal(1, result.Count);
                    Assert.True(registry.TryGet(result.Matches[0].ObjectId, result.Matches[0].Generation, out object found, out _));
                    Assert.Same(special, found);
                    Assert.Equal(0, engine.SuspendedCount);
                    // A token belongs to its locator in object mode too.
                    QueryFindAllResult first = Pump(FindAll(engine, locator));
                    Locator other = ObjectScope(registry, root, 256, Equal("Text", new JsonStringNode("other")));
                    Assert.Equal(ErrorCodes.InvalidPageToken, Assert.Throws<ProtocolException>(() => Pump(FindAll(engine, other, first.Continuation))).Code);
                    GC.KeepAlive(root);
                }
            });
        }
    }
}
