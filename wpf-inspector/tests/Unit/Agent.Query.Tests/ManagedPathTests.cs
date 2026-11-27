using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Inspection;
using WinTestKit.Inspector.Agent.Inspection.Members;
using WinTestKit.Inspector.Agent.Query;
using WinTestKit.Inspector.Protocol;
using Xunit;
using Xunit.Abstractions;
using PathSegment = WinTestKit.Inspector.Protocol.PathSegment;

namespace WinTestKit.Inspector.Agent.Query.Tests
{
    /// <summary>Indexers, nested type metadata, loose text comparison, memoized and resumable queries over managed paths.</summary>
    [Collection("Wpf windows")]
    public sealed class ManagedPathTests
    {
        private readonly ITestOutputHelper output;
        public ManagedPathTests(ITestOutputHelper output) { this.output = output; }

        public enum Level { Low = 1, High = 2 }
        public sealed class Row { public string Value { get; set; } = ""; public int Id { get; set; } public Row? Next { get; set; } }
        /// <summary>A collection that only offers a default indexer with one int parameter.</summary>
        public sealed class IndexedBag
        {
            private readonly string[] items = { "a", "b", "c" };
            public string this[int index] => items[index];
        }
        /// <summary>A collection with only IReadOnlyList semantics, implemented explicitly.</summary>
        public sealed class Sequence : IEnumerable<int>
        {
            private readonly int count;
            public Sequence(int count) { this.count = count; }
            public IEnumerator<int> GetEnumerator() { for (int i = 0; i < count; i++) yield return i * 10; }
            IEnumerator IEnumerable.GetEnumerator() => GetEnumerator();
        }
        public class ViewModel
        {
            public string Status { get; set; } = "Ready";
            public int PersistId { get; set; } = 15;
            public bool Flag { get; set; } = true;
            public decimal Price { get; set; } = 1.50m;
            public double Ratio { get; set; } = 0.25;
            public Level Mode { get; set; } = Level.High;
            public string[] Names { get; } = { "zero", "one", "two" };
            public List<Row> Rows { get; } = new List<Row> { new Row { Value = "r0", Id = 7 }, new Row { Value = "r1", Id = 8, Next = new Row { Value = "deep" } } };
            public IList<Row> RowList => Rows;
            public IndexedBag Bag { get; } = new IndexedBag();
            public IEnumerable<int> Numbers { get; } = new Sequence(5);
            public IEnumerable<int> Huge { get; } = new Sequence(20000);
            public Dictionary<int, string> Map { get; } = new Dictionary<int, string> { [3] = "three" };
            public Row? NoRow => null;
            public List<Row>? NoRows => null;
            public string Text => "xyz";
            public int[,] Grid { get; } = new int[2, 2];
            public int Thrower => throw new InvalidOperationException("boom");
        }
        public sealed class OrderViewModel : ViewModel { }
        public sealed class ViewModelButton : Button { }

        private static PathSegment Prop(string name) => new PathSegment { Kind = "property", Name = name };
        private static PathSegment[] Path(string dotted) => dotted.Split('.').Select(Prop).ToArray();
        private static PathSegment[] TypeOf(string facet, string dotted = "") =>
            (dotted.Length == 0 ? new PathSegment[0] : Path(dotted)).Concat(new[] { new PathSegment { Kind = "type", Name = facet } }).ToArray();
        private static Predicate Eq(IReadOnlyList<PathSegment> path, JsonNode value, string kind = "equals") => new Predicate { Kind = kind, Path = path, Value = value };
        private static Predicate AsText(IReadOnlyList<PathSegment> path, string value) => Eq(path, new JsonStringNode(value), "equalsText");
        private static Predicate Regex(IReadOnlyList<PathSegment> path, string pattern) => new Predicate { Kind = "regex", Path = path, Pattern = pattern, Flags = new string[0] };

        private static void OnSta(Action action)
        {
            Exception? failure = null;
            var thread = new Thread(() => { try { action(); } catch (Exception error) { failure = error; } });
            thread.SetApartmentState(ApartmentState.STA); thread.Start(); thread.Join();
            if (failure != null) System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(failure).Throw();
        }
        private static T Pump<T>(Task<T> task)
        {
            var frame = new DispatcherFrame();
            task.ContinueWith(_ => frame.Continue = false, TaskScheduler.Default);
            Dispatcher.PushFrame(frame);
            return task.GetAwaiter().GetResult();
        }
        private static ValueDto Read(object root, IReadOnlyList<PathSegment> path, ObjectInspector? inspector = null)
        {
            ValueDto? result = null;
            OnSta(() =>
            {
                using (var registry = new ObjectRegistry("paths", new DispatcherExecutor()))
                    result = (inspector ?? new ObjectInspector()).ReadPath(root, path, registry, Dispatcher.CurrentDispatcher, CancellationToken.None);
            });
            return result!;
        }
        private static string Scalar(ValueDto value) => value.Scalar is JsonStringNode text ? text.Value : value.Scalar is JsonNumberNode number ? number.RawText : value.Scalar is JsonBoolNode flag ? (flag.Value ? "true" : "false") : "";

        [Trait("Category", "Unit")]
        [Theory]
        [InlineData("Names[0]", "zero")]
        [InlineData("Names[2]", "two")]
        [InlineData("Rows[0].Value", "r0")]
        [InlineData("Rows[1].Next.Value", "deep")]
        [InlineData("RowList[1].Id", "8")]
        [InlineData("Bag[1]", "b")]
        [InlineData("Numbers[3]", "30")]
        [InlineData("Map[3]", "three")]
        [InlineData("Text[1]", "y")]
        public void IndexersReadArraysListsDefaultIndexersAndSequences(string path, string expected)
        {
            ValueDto value = Read(new ViewModel(), Path(path));
            Assert.Equal("ok", value.Status);
            Assert.Equal(expected, Scalar(value));
        }

        [Trait("Category", "Unit")]
        [Theory]
        [InlineData("Names[3]")]
        [InlineData("Names[-1]")]
        [InlineData("Rows[2].Value")]
        [InlineData("RowList[5]")]
        [InlineData("Bag[3]")]
        [InlineData("Numbers[5]")]
        [InlineData("Map[4]")]
        public void OutOfRangeIndexesReportAClearReadError(string path)
        {
            ValueDto value = Read(new ViewModel(), Path(path));
            Assert.Equal("exception", value.Status);
            Assert.Equal("System.IndexOutOfRangeException", value.Message);
            Assert.Equal("index out of range", value.ErrorMessage);
        }

        [Trait("Category", "Unit")]
        [Fact]
        public void IndexingEnumerationIsBoundedAndNullCannotBeIndexed()
        {
            var model = new ViewModel();
            ValueDto limit = Read(model, Path("Huge[10000]"));
            Assert.Equal("exception", limit.Status);
            Assert.Contains("enumeration limit", limit.ErrorMessage);
            Assert.Equal("ok", Read(model, Path("Huge[9999]")).Status);
            Assert.Equal("nullIntermediate", Read(model, Path("NoRows[0]")).Status);
            Assert.Equal("nullIntermediate", Read(model, Path("NoRow.Value")).Status);
            Assert.Equal("exception", Read(model, Path("Grid[0]")).Status);
        }

        [Trait("Category", "Unit")]
        [Fact]
        public void IndexersKeepRedaction()
        {
            var model = new ViewModel();
            ValueDto redacted = Read(model, Path("Names[0]"), new ObjectInspector(new[] { "names" }));
            Assert.Equal("redacted", redacted.Status);
            Assert.Equal("redacted", Read(model, Path("Rows[0].Value"), new ObjectInspector(new[] { "rows" })).Status);
        }

        [Trait("Category", "Unit")]
        [Fact]
        public void TooLongIndexedPathsAndBadIndexersAreInvalid()
        {
            Assert.Throws<ProtocolException>(() => Read(new ViewModel(), Path("Names[x]")));
            Assert.Throws<ProtocolException>(() => Read(new ViewModel(), Path("[0]")));
            Assert.Throws<ProtocolException>(() => Read(new ViewModel(), Path("Names[99999999999]")));
            Assert.Throws<ProtocolException>(() => Read(new ViewModel(), Path("A.B.C.D.E.F.G.H.I")));
        }

        [Trait("Category", "Unit")]
        [Theory]
        [InlineData("Name", "OrderViewModel")]
        [InlineData("FullName", "WinTestKit.Inspector.Agent.Query.Tests.ManagedPathTests+OrderViewModel")]
        [InlineData("AssemblyName", "Agent.Query.Tests")]
        public void NestedTypeReadsTheRuntimeTypeOfAValue(string facet, string expected)
        {
            var holder = new Row();
            ValueDto direct = Read(new Holder { Context = new OrderViewModel() }, TypeOf(facet, "Context"));
            Assert.Equal(expected, Scalar(direct));
            Assert.Equal("Row", Scalar(Read(holder, TypeOf("Name"))));
            // A runtime type, not the declared one.
            Assert.Equal("OrderViewModel", Scalar(Read(new Holder { Context = new OrderViewModel() }, TypeOf("Name", "Context"))));
            Assert.Equal("Row", Scalar(Read(new ViewModel(), TypeOf("Name", "Rows[0]"))));
            Assert.Equal("Int32", Scalar(Read(new ViewModel(), TypeOf("Name", "PersistId"))));
        }
        public sealed class Holder { public object? Context { get; set; } }

        [Trait("Category", "Unit")]
        [Fact]
        public void NestedTypeOfNullIsNotAValue()
        {
            Assert.Equal("nullIntermediate", Read(new Holder(), TypeOf("Name", "Context")).Status);
            Assert.Equal("nullIntermediate", Read(new ViewModel(), TypeOf("Name", "NoRow")).Status);
            Assert.Throws<ProtocolException>(() => Read(new Holder { Context = 1 }, new[] { Prop("Context"), new PathSegment { Kind = "type", Name = "Nope" } }));
            Assert.Throws<ProtocolException>(() => Read(new Holder(), new[] { new PathSegment { Kind = "type", Name = "Name" }, Prop("Context") }));
        }

        [Trait("Category", "Unit")]
        [Fact]
        public void NestedTypeKeepsRedaction()
        {
            var holder = new Holder { Context = new ViewModel() };
            Assert.Equal("redacted", Read(holder, TypeOf("Name", "Context"), new ObjectInspector(new[] { "context" })).Status);
        }

        private static IEnumerable<ViewModelButton> Buttons(int count, object? context = null, Action<ViewModelButton, int>? each = null)
        {
            for (int i = 0; i < count; i++)
            {
                var button = new ViewModelButton { DataContext = context };
                each?.Invoke(button, i);
                yield return button;
            }
        }

        private static bool Matches(Predicate predicate, DependencyObject target)
        {
            bool result = false;
            using (var registry = new ObjectRegistry("match", new DispatcherExecutor()))
            using (var context = new QueryPredicateContext(DateTime.UtcNow.AddSeconds(60)))
                result = PredicateFactory.Create(predicate, new ObjectInspector(), registry).Matches(target, context);
            return result;
        }

        [Trait("Category", "Unit")]
        [Fact]
        public void IndexedAndNestedTypePredicatesMatchOrSilentlyDoNot()
        {
            OnSta(() =>
            {
                var button = new ViewModelButton { DataContext = new OrderViewModel() };
                Assert.True(Matches(Eq(Path("DataContext.Rows[1].Next.Value"), new JsonStringNode("deep")), button));
                Assert.False(Matches(Eq(Path("DataContext.Rows[0].Value"), new JsonStringNode("other")), button));
                // Out of range, negative and indexing a null value are non-matches rather than errors.
                Assert.False(Matches(Eq(Path("DataContext.Rows[9].Value"), new JsonStringNode("r0")), button));
                Assert.False(Matches(Eq(Path("DataContext.Rows[-1].Value"), new JsonStringNode("r0")), button));
                Assert.False(Matches(Eq(Path("DataContext.NoRows[0]"), new JsonStringNode("r0")), button));
                Assert.False(Matches(Eq(Path("DataContext.Numbers[5]"), new JsonNumberNode("0")), button));
                Assert.True(Matches(Eq(Path("DataContext.Numbers[4]"), new JsonNumberNode("40")), button));
                Assert.True(Matches(Eq(TypeOf("Name", "DataContext"), new JsonStringNode("OrderViewModel")), button));
                Assert.False(Matches(Eq(TypeOf("Name", "DataContext"), new JsonStringNode("ViewModel")), button));
                Assert.True(Matches(Eq(TypeOf("FullName", "DataContext"), new JsonStringNode(typeof(OrderViewModel).FullName!)), button));
                Assert.True(Matches(Regex(TypeOf("Name", "DataContext"), "^Order"), button));
                Assert.False(Matches(Regex(TypeOf("Name", "DataContext"), "^Invoice"), button));
                // A null DataContext is a non-match for any type condition.
                Assert.False(Matches(Eq(TypeOf("Name", "DataContext"), new JsonStringNode("OrderViewModel")), new ViewModelButton()));
                Assert.False(Matches(Regex(TypeOf("Name", "DataContext"), ".*"), new ViewModelButton()));
                // A getter that throws is still unreadable, not a silent non-match.
                Assert.Equal(ErrorCodes.ValueUnreadable, Assert.Throws<ProtocolException>(() => Matches(Eq(Path("DataContext.Thrower"), new JsonNumberNode("1")), button)).Code);
            });
        }

        [Trait("Category", "Unit")]
        [Theory]
        [InlineData("PersistId", "15", true)]
        [InlineData("PersistId", "16", false)]
        [InlineData("PersistId", "015", false)]
        [InlineData("Flag", "True", true)]
        [InlineData("Flag", "true", true)]
        [InlineData("Flag", "False", false)]
        [InlineData("Price", "1.5", true)]
        [InlineData("Price", "1.50", true)]
        [InlineData("Ratio", "0.25", true)]
        [InlineData("Status", "Ready", true)]
        [InlineData("Status", "ready", false)]
        [InlineData("Mode", "High", true)]
        [InlineData("Mode", "2", true)]
        [InlineData("Mode", "Low", false)]
        [InlineData("NoRow", "x", false)]
        public void EqualsTextComparesTheInvariantTextOfAValue(string property, string expected, bool match)
        {
            OnSta(() =>
            {
                var button = new ViewModelButton { DataContext = new ViewModel() };
                Assert.Equal(match, Matches(AsText(Path("DataContext." + property), expected), button));
                // Exact comparison stays typed.
                if (property == "PersistId") Assert.False(Matches(Eq(Path("DataContext.PersistId"), new JsonStringNode("15")), button));
            });
        }

        [Trait("Category", "Unit")]
        [Fact]
        public void EqualsTextRejectsStructuredValuesAndIndexedElements()
        {
            OnSta(() =>
            {
                var button = new ViewModelButton { DataContext = new ViewModel() };
                Assert.Equal(ErrorCodes.ValueUnreadable, Assert.Throws<ProtocolException>(() => Matches(AsText(Path("DataContext.Rows"), "x"), button)).Code);
                Assert.True(Matches(AsText(Path("DataContext.Rows[0].Id"), "7"), button));
                Assert.True(Matches(AsText(Path("DataContext.Names[1]"), "one"), button));
            });
        }

        // ------------------------------------------------------------------ memoization

        public sealed class CountingModel
        {
            public int Calls;
            public string Status { get { Interlocked.Increment(ref Calls); return "Ready"; } }
            public Row[] Rows { get { Interlocked.Increment(ref Calls); return new[] { new Row { Value = "v" } }; } }
        }

        private static Task<QueryFindAllResult> FindAll(QueryEngine engine, Locator locator, string? continuation = null) =>
            engine.FindAllAsync(locator, DateTime.UtcNow.AddSeconds(120), 2000, continuation, CancellationToken.None);

        private static Locator Scoped(ObjectRegistry registry, DependencyObject root, params Predicate[] predicates)
        {
            ObjectRef handle = registry.Register(root, root.Dispatcher, TypeInfoBuilder.Build(root.GetType()));
            return new Locator { Scope = new Scope { Kind = "object", Handle = handle }, Tree = "logical", DepthMode = "tree", Depth = 256, Limit = 200, Predicates = predicates };
        }

        private static StackPanel Tree(int elements, int models, out CountingModel[] contexts, int groups = 1)
        {
            contexts = Enumerable.Range(0, models).Select(_ => new CountingModel()).ToArray();
            var root = new StackPanel();
            for (int group = 0; group < models; group++)
            {
                var panel = new StackPanel { DataContext = contexts[group] };
                for (int i = 0; i < elements / models; i++) panel.Children.Add(new ViewModelButton());
                root.Children.Add(panel);
            }
            return root;
        }

        [Trait("Category", "Unit")]
        [Fact]
        public void ASharedDataContextIsReadOnceForAThousandsOfElements()
        {
            OnSta(() =>
            {
                CountingModel[] contexts;
                StackPanel root = Tree(6000, 3, out contexts);
                var executor = new DispatcherExecutor();
                using (var registry = new ObjectRegistry("memo", executor))
                {
                    var engine = new QueryEngine(executor, registry);
                    Locator locator = Scoped(registry, root, Eq(Path("DataContext.Status"), new JsonStringNode("Ready")));
                    QueryFindAllResult result = Pump(FindAll(engine, locator));
                    // 6,000 buttons plus 3 panels inherit or hold a DataContext; the root has none.
                    Assert.False(result.Complete);          // 200-match limit
                    Assert.All(contexts, model => Assert.Equal(1, model.Calls));
                    GC.KeepAlive(root);
                }
            });
        }

        [Trait("Category", "Unit")]
        [Fact]
        public void EveryPathStepIsSharedWhenTheSameObjectIsReachedTwice()
        {
            OnSta(() =>
            {
                CountingModel[] contexts;
                StackPanel root = Tree(2000, 2, out contexts);
                var executor = new DispatcherExecutor();
                using (var registry = new ObjectRegistry("memo2", executor))
                {
                    var engine = new QueryEngine(executor, registry);
                    Locator locator = Scoped(registry, root, Eq(Path("DataContext.Rows[0].Value"), new JsonStringNode("v")));
                    QueryFindAllResult result = Pump(FindAll(engine, locator));
                    Assert.Equal(200, result.Matches.Count);
                    // Rows is a getter that returns a new array: it must still run once per model.
                    Assert.All(contexts, model => Assert.Equal(1, model.Calls));
                    GC.KeepAlive(root);
                }
            });
        }

        [Trait("Category", "Unit")]
        [Fact]
        public void CheapPredicatesRunBeforeManagedReads()
        {
            OnSta(() =>
            {
                CountingModel[] contexts;
                StackPanel root = Tree(1000, 1, out contexts);
                var executor = new DispatcherExecutor();
                using (var registry = new ObjectRegistry("order", executor))
                {
                    var engine = new QueryEngine(executor, registry);
                    // No element has this type: the member is never read.
                    Locator locator = Scoped(registry, root,
                        Eq(Path("DataContext.Status"), new JsonStringNode("Ready")),
                        Eq(new[] { new PathSegment { Kind = "type", Name = "FullName" } }, new JsonStringNode("No.Such.Type")));
                    QueryFindAllResult result = Pump(FindAll(engine, locator));
                    Assert.True(result.Complete);
                    Assert.Empty(result.Matches);
                    Assert.Equal(0, contexts[0].Calls);
                    GC.KeepAlive(root);
                }
            });
        }

        // ------------------------------------------------------------------ large trees and continuation

        private static StackPanel LargeTree(int elements, int models, CountingModel[] contexts)
        {
            var root = new StackPanel();
            int perModel = elements / models;
            for (int group = 0; group < models; group++)
            {
                var panel = new StackPanel { DataContext = contexts[group] };
                for (int i = 0; i < perModel; i++) panel.Children.Add(new ViewModelButton());
                root.Children.Add(panel);
            }
            return root;
        }

        [Trait("Category", "Unit")]
        [Fact]
        public void ALargeTreeScanContinuesAcrossRequestsAndCountsEverything()
        {
            OnSta(() =>
            {
                var contexts = Enumerable.Range(0, 5).Select(_ => new CountingModel()).ToArray();
                StackPanel root = LargeTree(24000, 5, contexts);
                var executor = new DispatcherExecutor();
                using (var registry = new ObjectRegistry("large", executor))
                {
                    var engine = new QueryEngine(executor, registry);
                    // Matches nothing: the query must visit all ~24,000 elements, which takes three requests.
                    Locator locator = Scoped(registry, root, Eq(Path("DataContext.Status"), new JsonStringNode("Missing")));
                    int requests = 0;
                    QueryFindAllResult result = Pump(FindAll(engine, locator)); requests++;
                    Assert.False(result.Complete);
                    Assert.NotNull(result.Continuation);
                    Assert.Empty(result.Matches);
                    Assert.Equal(1, engine.SuspendedCount);
                    while (!result.Complete && result.Continuation != null)
                    {
                        result = Pump(FindAll(engine, locator, result.Continuation)); requests++;
                    }
                    Assert.True(result.Complete);
                    Assert.Equal(0, result.Count);
                    Assert.True(requests >= 3, "requests: " + requests);
                    Assert.Equal(0, engine.SuspendedCount);
                    Assert.All(contexts, model => Assert.Equal(1, model.Calls));
                    GC.KeepAlive(root);
                }
            });
        }

        [Trait("Category", "Unit")]
        [Fact]
        public void AContinuedScanReturnsEveryMatchAtTheEnd()
        {
            OnSta(() =>
            {
                var contexts = Enumerable.Range(0, 5).Select(_ => new CountingModel()).ToArray();
                StackPanel root = LargeTree(24000, 5, contexts);
                // The last panel's buttons are the only ones with a different DataContext type.
                var special = new ViewModelButton { DataContext = new ViewModel() };
                ((StackPanel)root.Children[4]).Children.Add(special);
                var executor = new DispatcherExecutor();
                using (var registry = new ObjectRegistry("large-match", executor))
                {
                    var engine = new QueryEngine(executor, registry);
                    Locator locator = Scoped(registry, root, Eq(TypeOf("Name", "DataContext"), new JsonStringNode("ViewModel")));
                    QueryFindAllResult result = Pump(FindAll(engine, locator));
                    int guard = 0;
                    while (result.Continuation != null && guard++ < 20) result = Pump(FindAll(engine, locator, result.Continuation));
                    Assert.True(result.Complete);
                    Assert.Single(result.Matches);
                    Assert.Equal(1, result.Count);
                    Assert.True(registry.TryGet(result.Matches[0].ObjectId, result.Matches[0].Generation, out object found, out _));
                    Assert.Same(special, found);
                    GC.KeepAlive(root);
                }
            });
        }

        [Trait("Category", "Unit")]
        [Fact]
        public void ContinuationTokensAreBoundToTheirLocatorAndAreSingleUse()
        {
            OnSta(() =>
            {
                var contexts = Enumerable.Range(0, 5).Select(_ => new CountingModel()).ToArray();
                StackPanel root = LargeTree(24000, 5, contexts);
                var executor = new DispatcherExecutor();
                using (var registry = new ObjectRegistry("tokens", executor))
                {
                    var engine = new QueryEngine(executor, registry);
                    Locator locator = Scoped(registry, root, Eq(Path("DataContext.Status"), new JsonStringNode("Missing")));
                    QueryFindAllResult first = Pump(FindAll(engine, locator));
                    string token = first.Continuation!;
                    Locator other = Scoped(registry, root, Eq(Path("DataContext.Status"), new JsonStringNode("Other")));
                    // Another locator cannot use the token, and a refused attempt does not consume it.
                    Assert.Equal(ErrorCodes.InvalidPageToken, Assert.Throws<ProtocolException>(() => Pump(FindAll(engine, other, token))).Code);
                    QueryFindAllResult resumed = Pump(FindAll(engine, locator, token));
                    // Resuming consumes the token: it works once.
                    Assert.Equal(ErrorCodes.InvalidPageToken, Assert.Throws<ProtocolException>(() => Pump(FindAll(engine, locator, token))).Code);
                    Assert.Equal(ErrorCodes.InvalidPageToken, Assert.Throws<ProtocolException>(() => Pump(FindAll(engine, locator, "unknown"))).Code);
                    Assert.NotNull(resumed);
                    GC.KeepAlive(root);
                }
            });
        }

        [Trait("Category", "Unit")]
        [Fact]
        public void OnlyAFewTraversalsStaySuspended()
        {
            OnSta(() =>
            {
                var contexts = Enumerable.Range(0, 5).Select(_ => new CountingModel()).ToArray();
                StackPanel root = LargeTree(12000, 5, contexts);
                var executor = new DispatcherExecutor();
                using (var registry = new ObjectRegistry("suspended", executor))
                {
                    var engine = new QueryEngine(executor, registry);
                    Locator locator = Scoped(registry, root, Eq(Path("DataContext.Status"), new JsonStringNode("Missing")));
                    string? oldest = null;
                    for (int i = 0; i <= ProtocolLimits.MaxContinuations; i++)
                    {
                        QueryFindAllResult result = Pump(FindAll(engine, locator));
                        oldest = oldest ?? result.Continuation;
                    }
                    Assert.Equal(ProtocolLimits.MaxContinuations, engine.SuspendedCount);
                    Assert.Equal(ErrorCodes.InvalidPageToken, Assert.Throws<ProtocolException>(() => Pump(FindAll(engine, locator, oldest))).Code);
                    GC.KeepAlive(root);
                }
            });
        }

        [Trait("Category", "Unit")]
        [Fact]
        public void WholeWindowScanOfTwentyThousandElementsIsFastWithASharedDataContext()
        {
            long elapsed = 0; int calls = 0, requests = 0;
            OnSta(() =>
            {
                var contexts = Enumerable.Range(0, 4).Select(_ => new CountingModel()).ToArray();
                StackPanel root = LargeTree(20000, 4, contexts);
                var executor = new DispatcherExecutor();
                using (var registry = new ObjectRegistry("bench", executor))
                {
                    var engine = new QueryEngine(executor, registry);
                    Locator locator = Scoped(registry, root, Eq(Path("DataContext.Status"), new JsonStringNode("Missing")));
                    var watch = Stopwatch.StartNew();
                    QueryFindAllResult result = Pump(FindAll(engine, locator)); requests++;
                    while (!result.Complete && result.Continuation != null) { result = Pump(FindAll(engine, locator, result.Continuation)); requests++; }
                    elapsed = watch.ElapsedMilliseconds;
                    Assert.True(result.Complete);
                    calls = contexts.Sum(model => model.Calls);
                    GC.KeepAlive(root);
                }
            });
            output.WriteLine("20,001 elements, 4 distinct DataContexts: {0} ms in {1} requests, getter calls: {2}", elapsed, requests, calls);
            Assert.Equal(4, calls);
        }
    }
}
