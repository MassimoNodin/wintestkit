using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Runtime.InteropServices;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Threading;
using System.Windows.Interop;
using Visual = System.Windows.Media.Visual;
using VisualTreeHelper = System.Windows.Media.VisualTreeHelper;
using WinTestKit.Inspector.Agent.Contracts;
using WinTestKit.Inspector.Agent.Actions;
using WinTestKit.Inspector.Agent.Mapping;
using WinTestKit.Inspector.Agent.Query;
using WinTestKit.Inspector.Agent.State;
using WinTestKit.Inspector.Agent.Wait;
using WinTestKit.Inspector.Agent.Writes;
using WinTestKit.Inspector.Agent.Inspection.Members;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Inspection
{
    public sealed partial class WpfInspectionService : IInspectionService, IItemsInspectionService, IStylingInspectionService, IResourceInspectionService, IMemberEventsInspectionService, IParentInspectionService, ISpyFieldInspectionService, ISpyMethodInspectionService, IExactMappingCapability, IQueryInspectionService, IStateInspectionService, IWaitInspectionService, IActionInspectionService, IRealizeInspectionService, IHitTestInspectionService, IWriteInspectionService, ISpyInvokeInspectionService, Events.IEventInspectionService
    {
        private readonly DispatcherExecutor executor;
        private readonly ObjectRegistry registry;
        private readonly PageSnapshotStore snapshots;
        private readonly IPeerRuntimeIdAdapter adapter;
        private readonly ElementMapper mapper;
        private readonly IObjectInspector inspector;
        private readonly TreeWalker walker;
        private readonly QueryEngine query;
        private readonly WriteEngine writes;
        private readonly MethodInvocationExecutor invocations;
        private readonly RedactionPolicy redaction;
        private readonly string sessionId;
        private readonly CancellationTokenSource lifetime = new CancellationTokenSource();
        private int disposed;
        private Events.WpfEventHooks? eventHooks;

        public void SetEventSubscriptions(Events.SubscriptionStore subscriptions)
        {
            eventHooks = new Events.WpfEventHooks(subscriptions, executor, registry, inspector);
        }

        internal WpfInspectionService(string sessionId, IObjectInspector inspector,
            PageSnapshotStore? snapshots = null, IPeerRuntimeIdAdapter? adapter = null, WriteAllowlist? allowlist = null, IReadOnlyList<string>? redactNames = null)
        {
            this.sessionId = sessionId;
            this.inspector = inspector ?? throw new ArgumentNullException(nameof(inspector));
            executor = new DispatcherExecutor();
            registry = new ObjectRegistry(sessionId, executor);
            this.snapshots = snapshots ?? new PageSnapshotStore();
            this.adapter = adapter ?? new PeerRuntimeIdAdapter();
            walker = new TreeWalker(executor);
            mapper = new ElementMapper(executor, this.adapter, registry, walker);
            query = new QueryEngine(executor, registry, inspector as ObjectInspector);
            writes = new WriteEngine(executor, allowlist ?? new WriteAllowlist(), redactNames ?? Array.Empty<string>());
            invocations = new MethodInvocationExecutor(executor, redactNames ?? Array.Empty<string>());
            redaction = new RedactionPolicy(redactNames ?? Array.Empty<string>());
        }

        public bool ExactMappingAvailable => mapper.IsAvailable;

        public Task<WriteCallResult> WriteAsync(string operation, ObjectRef handle, string memberKey, IReadOnlyList<JsonNode> values, DateTime deadline, int timeoutMs, CancellationToken ct) => RunAsync(async token =>
        {
            object target = GetObject(handle.ObjectId, handle.Generation, out Dispatcher dispatcher);
            ObjectRef actual = registry.Register(target, dispatcher, inspector.DescribeType(target.GetType()));
            if (actual.SessionId != handle.SessionId || actual.DispatcherId != handle.DispatcherId)
                throw new ProtocolException(ErrorCodes.ObjectStale, "Unknown or stale object handle.");
            return await writes.ExecuteWithResultAsync(dispatcher, target, operation, memberKey, values, deadline, timeoutMs, token, registry).ConfigureAwait(false);
        }, ct);

        public Task<WriteCallResult> InvokeAsync(ObjectRef handle, string memberKey, IReadOnlyList<JsonNode> values, DateTime deadline, CancellationToken ct) => RunAsync(async token =>
        {
            if (handle.SessionId != sessionId) throw new ProtocolException(ErrorCodes.SessionStale, "Session mismatch.");
            object target = GetObject(handle.ObjectId, handle.Generation, out Dispatcher dispatcher);
            ObjectRef actual = registry.Register(target, dispatcher, inspector.DescribeType(target.GetType()));
            if (actual.DispatcherId != handle.DispatcherId) throw new ProtocolException(ErrorCodes.ObjectStale, "Unknown or stale object handle.");
            return await invocations.ExecuteAsync(target, dispatcher, memberKey, values, deadline, token, registry).ConfigureAwait(false);
        }, ct);

        [DllImport("user32.dll")]
        private static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint processId);

        internal static int? VisualSiblingIndex(DependencyObject node)
        {
            if (!(node is Visual) && !(node is System.Windows.Media.Media3D.Visual3D)) return null;
            var parent = VisualTreeHelper.GetParent(node);
            if (parent == null) return null;
            int index = 0;
            for (int i = 0; i < VisualTreeHelper.GetChildrenCount(parent); i++)
            {
                var child = VisualTreeHelper.GetChild(parent, i);
                if (ReferenceEquals(child, node)) return index;
                if (child.GetType() == node.GetType()) index++;
            }
            return null;
        }

        internal static DependencyObject? VisualHost(DependencyObject? node)
        {
            while (node != null && !(node is Visual) && !(node is System.Windows.Media.Media3D.Visual3D))
                node = LogicalTreeHelper.GetParent(node) ?? (node as FrameworkContentElement)?.Parent;
            return node;
        }

        public Task<Protocol.HitTestResult> HitTestAsync(long nativeWindowHandle, PointDto point, DateTime deadline, int timeoutMs, CancellationToken ct, bool includePath = false) => RunAsync(async token =>
        {
            IntPtr hwnd;
            try { hwnd = new IntPtr(nativeWindowHandle); }
            catch (OverflowException) { throw new ProtocolException(ErrorCodes.MappingFailed, "Invalid window handle."); }
            if (GetWindowThreadProcessId(hwnd, out uint processId) == 0 || processId != (uint)Process.GetCurrentProcess().Id)
                throw new ProtocolException(ErrorCodes.MappingFailed, "Invalid window handle.");
            HwndSource? source = HwndSource.FromHwnd(hwnd);
            if (source == null) return await HitTestWinFormsAsync(hwnd, point, deadline, timeoutMs, includePath, token).ConfigureAwait(false);
            DateTime end = DateTime.UtcNow.AddMilliseconds(timeoutMs);
            if (deadline < end) end = deadline;
            int remaining = (int)Math.Max(0, (end - DateTime.UtcNow).TotalMilliseconds);
            if (remaining == 0) throw new ProtocolException(ErrorCodes.Timeout, "Request deadline elapsed.");
            using (var timed = CancellationTokenSource.CreateLinkedTokenSource(token))
            {
                timed.CancelAfter(remaining);
                try
                {
                    return await executor.ExecuteAsync(source.Dispatcher, () =>
                    {
                        Visual? root = source.RootVisual;
                        if (root == null) throw new ProtocolException(ErrorCodes.MappingFailed, "Window has no WPF root.");
                        Point local = root.PointFromScreen(ScreenCoordinates.Convert(hwnd, new Point(point.X, point.Y), false));
                        if (root is UIElement rootElement && !new Rect(rootElement.RenderSize).Contains(local))
                            throw new ProtocolException(ErrorCodes.NotFound, "No hit.");
                        DependencyObject? target = null;
                        VisualTreeHelper.HitTest(root, candidate =>
                            candidate is UIElement element && (!element.IsVisible || !element.IsHitTestVisible)
                                ? System.Windows.Media.HitTestFilterBehavior.ContinueSkipSelfAndChildren
                                : System.Windows.Media.HitTestFilterBehavior.Continue,
                            result => { target = result.VisualHit; return System.Windows.Media.HitTestResultBehavior.Stop; },
                            new System.Windows.Media.PointHitTestParameters(local));
                        while (target != null && !(target is UIElement) && !(target is ContentElement))
                            target = VisualTreeHelper.GetParent(target);
                        if (target == null) throw new ProtocolException(ErrorCodes.NotFound, "No hit.");
                        Protocol.InnerElementDto? inner = null;
                        if (root is UIElement inputRoot && inputRoot.InputHitTest(local) is ContentElement content)
                        {
                            DependencyObject? host = VisualHost(content);
                            if (host != null)
                            {
                                string? text = content is System.Windows.Documents.Run run ? run.Text : content is System.Windows.Documents.TextElement element ? new System.Windows.Documents.TextRange(element.ContentStart, element.ContentEnd).Text : null;
                                if (RedactionPolicy.IsProtectedIdentity(host) || redaction.Match("Text") != null || (host is FrameworkElement named && redaction.Match(named.Name) != null) || redaction.Match(System.Windows.Automation.AutomationProperties.GetAutomationId(host)) != null || (text != null && redaction.Match(text) != null)) text = null;
                                if (text != null && text.Length > 128) text = text.Substring(0, 128);
                                inner = new Protocol.InnerElementDto { Type = content.GetType().Name, Text = text };
                                target = host;
                            }
                        }
                        var hit = new Protocol.HitTestResult { Handle = registry.Register(target, source.Dispatcher, inspector.DescribeType(target.GetType())), InnerElement = inner };
                        if (includePath)
                        {
                            var path = new List<ManagedNodeDto>();
                            DependencyObject? current = target;
                            while (current != null)
                            {
                                timed.Token.ThrowIfCancellationRequested();
                                if (path.Count >= 256) throw new ProtocolException(ErrorCodes.LimitExceeded, "Hit test path limit reached.");
                                AddNode(path, current);
                                var identity = new NodeIdentityDto { SiblingIndex = VisualSiblingIndex(current) };
                                if (current is FrameworkElement || current is FrameworkContentElement)
                                {
                                    string declaringType = current is FrameworkElement ? "System.Windows.FrameworkElement" : "System.Windows.FrameworkContentElement";
                                    identity.XName = ReadIdentity(current, new PathSegment { Kind = "property", Name = "Name", DeclaringType = declaringType }, source.Dispatcher, timed.Token);
                                }
                                identity.AutomationId = ReadIdentity(current, new PathSegment { Kind = "uia", Name = "automation_id" }, source.Dispatcher, timed.Token);
                                path[path.Count - 1].Identity = identity;
                                if (ReferenceEquals(current, root)) break;
                                current = current is Visual || current is System.Windows.Media.Media3D.Visual3D ? VisualTreeHelper.GetParent(current) : LogicalTreeHelper.GetParent(current);
                            }
                            if (current == null) throw new ProtocolException(ErrorCodes.MappingFailed, "Hit is not connected to the window root.");
                            path.Reverse();
                            hit.Path = path;
                        }
                        return hit;
                    }, timed.Token).ConfigureAwait(false);
                }
                catch (OperationCanceledException) when (!token.IsCancellationRequested) { throw new ProtocolException(ErrorCodes.Timeout, "Request deadline elapsed."); }
            }
        }, ct);

        public Task<ActRealizeItemResult> RealizeItemAsync(ItemSearch search, DateTime deadline, int timeoutMs, CancellationToken ct) => RunAsync(async token =>
        {
            ObjectRef handle = search.Container;
            object target = GetObject(handle.ObjectId, handle.Generation, out Dispatcher dispatcher);
            ObjectRef actual = registry.Register(target, dispatcher, inspector.DescribeType(target.GetType()));
            if (actual.SessionId != handle.SessionId || actual.DispatcherId != handle.DispatcherId)
                throw new ProtocolException(ErrorCodes.ObjectStale, "Unknown or stale object handle.");
            return await RealizeItemEngine.ExecuteAsync(executor, dispatcher, target, search, registry,
                inspector as ObjectInspector ?? new ObjectInspector(), deadline, timeoutMs, token).ConfigureAwait(false);
        }, ct);

        public Task<ActResult> ActAsync(string method, ObjectRef handle, DateTime deadline, int timeoutMs, CancellationToken ct, object? parameters = null) => RunAsync(async token =>
        {
            object target = GetObject(handle.ObjectId, handle.Generation, out Dispatcher dispatcher);
            ObjectRef actual = registry.Register(target, dispatcher, inspector.DescribeType(target.GetType()));
            if (actual.SessionId != handle.SessionId || actual.DispatcherId != handle.DispatcherId)
                throw new ProtocolException(ErrorCodes.ObjectStale, "Unknown or stale object handle.");
            return await ActionEngine.ExecuteAsync(executor, dispatcher, target, actual, method, deadline, timeoutMs, token, parameters).ConfigureAwait(false);
        }, ct);

        public Task<WaitUntilResult> WaitUntilAsync(WaitCondition condition, DateTime deadline, int timeoutMs, CancellationToken ct) =>
            RunAsync(token => new WaitEngine(query, executor, registry, inspector as ObjectInspector ?? new ObjectInspector(), adapter).UntilAsync(condition, deadline, timeoutMs, token), ct);

        public Task<StateGetResult> GetStateAsync(ObjectRef handle, DateTime deadline, int timeoutMs, CancellationToken ct) => RunAsync(async token =>
        {
            object target = GetObject(handle.ObjectId, handle.Generation, out Dispatcher dispatcher);
            ObjectRef actual = registry.Register(target, dispatcher, inspector.DescribeType(target.GetType()));
            if (actual.SessionId != handle.SessionId || actual.DispatcherId != handle.DispatcherId)
                throw new ProtocolException(ErrorCodes.ObjectStale, "Unknown or stale object handle.");
            DateTime end = DateTime.UtcNow.AddMilliseconds(timeoutMs);
            if (deadline < end) end = deadline;
            int remaining = (int)Math.Max(0, (end - DateTime.UtcNow).TotalMilliseconds);
            if (remaining == 0) throw new ProtocolException(ErrorCodes.Timeout, "Request deadline elapsed.");
            using (var timed = CancellationTokenSource.CreateLinkedTokenSource(token))
            {
                timed.CancelAfter(remaining);
                try { return new StateGetResult { State = await executor.ExecuteAsync(dispatcher, () => StateReader.Read(target, actual, adapter), timed.Token).ConfigureAwait(false) }; }
                catch (OperationCanceledException) when (!token.IsCancellationRequested) { throw new ProtocolException(ErrorCodes.Timeout, "Request deadline elapsed."); }
            }
        }, ct);

        public Task<QueryFindResult> FindAsync(Locator locator, DateTime deadline, int timeoutMs, CancellationToken ct) =>
            RunAsync(token => query.FindAsync(locator, deadline, timeoutMs, token), ct);

        public Task<QueryFindAllResult> FindAllAsync(Locator locator, DateTime deadline, int timeoutMs, string? continuation, CancellationToken ct) =>
            RunAsync(token => query.FindAllAsync(locator, deadline, timeoutMs, continuation, token), ct);

        public Task<MappingDto> ResolveAsync(int[] runtimeId, long? nativeWindowHandle, CancellationToken ct) =>
            RunAsync(async token => await TryResolveWinFormsAsync(runtimeId, nativeWindowHandle, token).ConfigureAwait(false)
                ?? await mapper.ResolveAsync(runtimeId, nativeWindowHandle, token).ConfigureAwait(false), ct);

        public Task<ReadBatchResult> ReadBatchAsync(IReadOnlyList<CandidateRequest> candidates,
            IReadOnlyList<IReadOnlyList<PathSegment>> paths, CancellationToken ct) => RunAsync(async token =>
        {
            CheckCount(candidates.Count, ProtocolLimits.MaxBatchCandidates);
            CheckPaths(paths);
            IReadOnlyList<MappingDto> mappings = await mapper.ResolveBatchAsync(candidates, token).ConfigureAwait(false);
            var results = new List<CandidateResult>();
            foreach (MappingDto mapping in mappings)
            {
                token.ThrowIfCancellationRequested();
                IReadOnlyList<PathValue> values = Array.Empty<PathValue>();
                if (mapping.Status == MappingStatus.Exact && mapping.Object != null)
                    values = await ReadValuesAsync(mapping.Object.ObjectId, mapping.Object.Generation, paths, token).ConfigureAwait(false);
                results.Add(new CandidateResult { RuntimeId = mapping.RuntimeId, Mapping = mapping, Values = values });
            }
            return new ReadBatchResult { Candidates = results };
        }, ct);

        public Task<PageDto<ManagedNodeDto>> RootsAsync(int? pageSize, string? pageToken, CancellationToken ct) => RunAsync(async token =>
        {
            int size = PageSize(pageSize);
            if (pageToken != null) return Page<ManagedNodeDto>("", 0, "roots", "", size, pageToken);
            var nodes = new List<ManagedNodeDto>();
            var seen = new HashSet<object>(ReferenceComparer.Instance);
            IReadOnlyList<Dispatcher> dispatchers = await executor.DiscoverDispatchersAsync(token).ConfigureAwait(false);
            ScanBudget budget = walker.NewBudget();
            foreach (Dispatcher dispatcher in dispatchers)
                await CollectNodesAsync(dispatcher, () => TreeWalker.EnumerateRoots(dispatcher), nodes, seen, budget, token).ConfigureAwait(false);
            await CollectWinFormsRootsAsync(nodes, token).ConfigureAwait(false);
            nodes.Sort(CompareNodes);
            return NewPage("", 0, "roots", "", nodes, Array.Empty<Diagnostic>(), size, token);
        }, ct);

        public Task<ParentResult> ParentAsync(string objectId, long generation, CancellationToken ct) => RunAsync(async token =>
        {
            object target = GetObject(objectId, generation, out Dispatcher dispatcher);
            return await executor.ExecuteAsync(dispatcher, () =>
            {
                object? parent = target is DependencyObject dependency ? TreeWalker.Parent(dependency) : WinFormsNative.ParentOf(target);
                return new ParentResult { Handle = parent == null ? null : registry.Register(parent, dispatcher, inspector.DescribeType(parent.GetType())) };
            }, token).ConfigureAwait(false);
        }, ct);

        public Task<PageDto<ManagedNodeDto>> ChildrenAsync(string objectId, long generation, string tree,
            int? pageSize, string? pageToken, CancellationToken ct) => RunAsync(async token =>
        {
            int size = PageSize(pageSize);
            if (tree != TreeKind.Visual && tree != TreeKind.Logical)
                throw new ProtocolException(ErrorCodes.InvalidParams, "Unknown tree kind.");
            object target = GetObject(objectId, generation, out Dispatcher dispatcher);
            PageDto<ManagedNodeDto> page;
            if (pageToken != null)
            {
                page = Page<ManagedNodeDto>(objectId, generation, "children", tree, size, pageToken);
                return await AddPageIdentityAsync(page, dispatcher, token).ConfigureAwait(false);
            }
            var nodes = new List<ManagedNodeDto>();
            if (target is DependencyObject dependencyObject)
                await CollectNodesAsync(dispatcher, () => TreeWalker.EnumerateChildren(dependencyObject, tree),
                    nodes, new HashSet<object>(ReferenceComparer.Instance), walker.NewBudget(), token).ConfigureAwait(false);
            else if (WinFormsNative.IsWinFormsObject(target))
                await CollectWinFormsChildrenAsync(target, dispatcher, nodes, token).ConfigureAwait(false);
            page = NewPage(objectId, generation, "children", tree, nodes, Array.Empty<Diagnostic>(), size, token);
            return await AddPageIdentityAsync(page, dispatcher, token).ConfigureAwait(false);
        }, ct);

        public Task<PageDto<MemberInfo>> MembersAsync(string objectId, long generation, int? pageSize,
            string? pageToken, CancellationToken ct) => RunAsync(async token =>
        {
            int size = PageSize(pageSize);
            object target = GetObject(objectId, generation, out Dispatcher dispatcher);
            if (pageToken != null) return Page<MemberInfo>(objectId, generation, "members", "", size, pageToken);
            var diagnostics = new List<Diagnostic>();
            IReadOnlyList<MemberInfo> members = await executor.ExecuteAsync(dispatcher,
                () => inspector.GetMembers(target, diagnostics), token).ConfigureAwait(false);
            var sorted = members.OrderBy(member => member.Category, StringComparer.Ordinal)
                .ThenBy(member => member.Name, StringComparer.Ordinal)
                .ThenBy(member => member.DeclaringType, StringComparer.Ordinal)
                .ThenBy(member => member.MemberKey, StringComparer.Ordinal).ToArray();
            return NewPage(objectId, generation, "members", "", sorted, diagnostics.ToArray(), size, token);
        }, ct);

        public Task<PageDto<MethodMetadataDto>> SpyMethodsAsync(string objectId, long generation, int? pageSize, string? pageToken, CancellationToken ct) => RunAsync(async token =>
        {
            int size = PageSize(pageSize);
            object target = GetObject(objectId, generation, out Dispatcher dispatcher);
            if (pageToken != null) return Page<MethodMetadataDto>(objectId, generation, "spy.methods", "", size, pageToken);
            MethodMetadataDto[] methods = await executor.ExecuteAsync(dispatcher, () => MethodCatalog.Get(target.GetType()).Select(method => new MethodMetadataDto
            {
                Key = method.Key, Name = method.Name, DeclaringType = method.DeclaringType.FullName ?? method.DeclaringType.ToString(),
                ReturnType = method.ReturnType.FullName ?? method.ReturnType.ToString(), Visibility = method.Visibility == "protected internal" ? "protectedInternal" : method.Visibility == "private protected" ? "privateProtected" : method.Visibility, IsStatic = method.IsStatic,
                Parameters = method.Parameters.Select(parameter => new MethodParameterDto { Name = parameter.Name, Type = parameter.ParameterType.FullName ?? parameter.ParameterType.ToString(), IsOut = parameter.IsOut }).ToArray(),
                UnsupportedReason = method.UnsupportedReason
            }).ToArray(), token).ConfigureAwait(false);
            return NewPage(objectId, generation, "spy.methods", "", methods, Array.Empty<Diagnostic>(), size, token);
        }, ct);

        public Task<ReadResult> ReadAsync(string objectId, long generation,
            IReadOnlyList<IReadOnlyList<PathSegment>> paths, CancellationToken ct) => RunAsync(async token =>
        {
            CheckPaths(paths);
            return new ReadResult
            {
                Values = await ReadValuesAsync(objectId, generation, paths, token).ConfigureAwait(false),
                ReadId = Guid.NewGuid().ToString("N")
            };
        }, ct);

        public Task<ReadResult> ReadSpyFieldAsync(string objectId, long generation, IReadOnlyList<IReadOnlyList<PathSegment>> paths, CancellationToken ct) => RunAsync(async token =>
        {
            if (paths.Count != 1 || paths[0].Count != 1 || paths[0][0].Kind != "field" || string.IsNullOrEmpty(paths[0][0].MemberKey) || string.IsNullOrEmpty(paths[0][0].DeclaringType))
                throw new ProtocolException(ErrorCodes.InvalidParams, "Spy field reads require one exact field");
            if (!(inspector is ObjectInspector spyInspector)) throw new ProtocolException(ErrorCodes.UnsupportedTarget, "Spy field reads unavailable");
            object target = GetObject(objectId, generation, out Dispatcher dispatcher);
            ValueDto value = await executor.ExecuteAsync(dispatcher, t => spyInspector.ReadSpyField(target, paths[0], registry, dispatcher, t), token).ConfigureAwait(false);
            return new ReadResult { Values = new[] { new PathValue { Path = paths[0], Value = value } }, ReadId = Guid.NewGuid().ToString("N") };
        }, ct);

        public Task<IReadOnlyList<BindingInfoDto>> BindingsAsync(string objectId, long generation,
            IReadOnlyList<string> memberKeys, CancellationToken ct) => RunAsync(async token =>
        {
            CheckCount(memberKeys.Count, ProtocolLimits.MaxBindingKeys, true);
            object target = GetObject(objectId, generation, out Dispatcher dispatcher);
            return await executor.ExecuteAsync(dispatcher, () => inspector.GetBindings(target, memberKeys, registry, dispatcher), token).ConfigureAwait(false);
        }, ct);

        public Task<int> ReleaseAsync(IReadOnlyList<string> objectIds, CancellationToken ct) => RunAsync(token =>
        {
            CheckCount(objectIds.Count, ProtocolLimits.MaxReleaseIds, true);
            token.ThrowIfCancellationRequested();
            return Task.FromResult(registry.Release(objectIds));
        }, ct);

        private async Task<IReadOnlyList<PathValue>> ReadValuesAsync(string objectId, long generation,
            IReadOnlyList<IReadOnlyList<PathSegment>> paths, CancellationToken ct)
        {
            object target = GetObject(objectId, generation, out Dispatcher dispatcher);
            var values = new List<PathValue>();
            foreach (IReadOnlyList<PathSegment> path in paths)
            {
                ValueDto value = await executor.ExecuteAsync(dispatcher,
                    token => inspector.ReadPath(target, path, registry, dispatcher, token), ct).ConfigureAwait(false);
                values.Add(new PathValue { Path = path, Value = value });
            }
            return values;
        }

        private object GetObject(string objectId, long generation, out Dispatcher dispatcher)
        {
            if (!registry.TryGet(objectId, generation, out object target, out dispatcher))
                throw new ProtocolException(ErrorCodes.ObjectStale, "Unknown or stale object handle.");
            return target;
        }

        private async Task<PageDto<ManagedNodeDto>> AddPageIdentityAsync(PageDto<ManagedNodeDto> page, Dispatcher dispatcher, CancellationToken ct)
        {
            int index = 0;
            while (index < page.Items.Count)
            {
                await executor.ExecuteAsync(dispatcher, token =>
                {
                    Stopwatch slice = Stopwatch.StartNew();
                    for (int count = 0; index < page.Items.Count && count < ProtocolLimits.TraversalSliceObjects &&
                        slice.ElapsedMilliseconds < ProtocolLimits.TraversalSliceMs; count++, index++)
                    {
                        token.ThrowIfCancellationRequested();
                        long itemStart = Stopwatch.GetTimestamp();
                        ManagedNodeDto node = page.Items[index];
                        if (registry.TryGetWeak(node.Object.ObjectId, node.Object.Generation, out object target))
                        {
                            if (WinFormsNative.IsWinFormsObject(target)) node.Identity = WinFormsIdentity(target);
                            else
                            {
                                var identity = new NodeIdentityDto { SiblingIndex = target is DependencyObject dependency ? VisualSiblingIndex(dependency) : null };
                                if (target is FrameworkElement || target is FrameworkContentElement)
                                {
                                    string declaringType = target is FrameworkElement ? "System.Windows.FrameworkElement" : "System.Windows.FrameworkContentElement";
                                    identity.XName = ReadIdentity(target, new PathSegment { Kind = "property", Name = "Name", DeclaringType = declaringType }, dispatcher, token);
                                }
                                identity.AutomationId = ReadIdentity(target, new PathSegment { Kind = "uia", Name = "automation_id" }, dispatcher, token);
                                node.Identity = identity;
                            }
                        }
                        if ((Stopwatch.GetTimestamp() - itemStart) * 1000.0 / Stopwatch.Frequency > DispatcherExecutor.TraversalItemLimitMs)
                        {
                            page.Diagnostics = page.Diagnostics.Concat(new[] { new Diagnostic { Code = "identityCutShort", Message = "Identity collection stopped after a slow item.", Category = "identity" } }).ToArray();
                            index = page.Items.Count;
                            break;
                        }
                    }
                    return true;
                }, ct).ConfigureAwait(false);
            }
            return page;
        }

        private string? ReadIdentity(object target, PathSegment segment, Dispatcher dispatcher, CancellationToken ct)
        {
            try
            {
                ValueDto value;
                // Tree identity reads x:Name straight from the element: the generic path builds the object's whole member catalog,
                // about 7 ms per element, which froze the UI thread for ~0.4 s on a pick path through 60 Ribbon template levels.
                if (segment.Kind == "property" && segment.Name == "Name" && segment.MemberKey == null && inspector is ObjectInspector names &&
                    (segment.DeclaringType == "System.Windows.FrameworkElement" && target is FrameworkElement || segment.DeclaringType == "System.Windows.FrameworkContentElement" && target is FrameworkContentElement))
                    return names.IdentityName(target);
                if (segment.Kind != "uia" && inspector is ObjectInspector objectInspector)
                {
                    bool protectedTarget = RedactionPolicy.IsProtectedIdentity(target);
                    if (protectedTarget) return null;
                    value = objectInspector.ReadPath(target, new[] { segment }, registry, dispatcher, ct, protectedTarget);
                }
                else value = inspector.ReadPath(target, new[] { segment }, registry, dispatcher, ct);
                return value.Status == ValueStatus.Ok && value.Scalar is JsonStringNode text && text.Value.Length != 0 ? text.Value : null;
            }
            catch (OperationCanceledException) { throw; }
            catch (Exception) { return null; }
        }

        private void AddNode(List<ManagedNodeDto> nodes, DependencyObject target)
        {
            if (nodes.Count >= ProtocolLimits.ScanMaxObjects)
                throw new ProtocolException(ErrorCodes.LimitExceeded, "Tree scan limit reached.");
            var peer = PeerRuntimeIdAdapter.ExistingPeer(target);
            int[]? runtimeId = peer == null || !adapter.IsAvailable ? null : adapter.GetRuntimeId(peer);
            nodes.Add(new ManagedNodeDto
            {
                Object = registry.Register(target, target.Dispatcher, inspector.DescribeType(target.GetType())),
                Label = target.GetType().Name,
                HasVisualChildren = TreeWalker.EnumerateChildren(target, TreeKind.Visual).Any(),
                HasLogicalChildren = TreeWalker.EnumerateChildren(target, TreeKind.Logical).Any(),
                RuntimeId = runtimeId == null ? null : (int[])runtimeId.Clone()
            });
        }

        private async Task CollectNodesAsync(Dispatcher dispatcher, Func<IEnumerable<DependencyObject>> enumerate,
            List<ManagedNodeDto> nodes, HashSet<object> seen, ScanBudget budget, CancellationToken ct)
        {
            IEnumerator<DependencyObject> iterator = await executor.ExecuteAsync(dispatcher, () => enumerate().GetEnumerator(), ct).ConfigureAwait(false);
            try
            {
                bool complete;
                do
                {
                    complete = await executor.ExecuteAsync(dispatcher, token =>
                    {
                        Stopwatch slice = Stopwatch.StartNew();
                        for (int count = 0; count < ProtocolLimits.TraversalSliceObjects &&
                            slice.ElapsedMilliseconds < ProtocolLimits.TraversalSliceMs; count++)
                        {
                            token.ThrowIfCancellationRequested();
                            if (budget.Expired) throw new ProtocolException(ErrorCodes.LimitExceeded, "Tree scan limit reached.");
                            if (!iterator.MoveNext()) return true;
                            DependencyObject current = iterator.Current;
                            if (!seen.Add(current)) continue;
                            if (!budget.Take()) throw new ProtocolException(ErrorCodes.LimitExceeded, "Tree scan limit reached.");
                            AddNode(nodes, current);
                        }
                        return false;
                    }, ct).ConfigureAwait(false);
                } while (!complete);
            }
            finally
            {
                if (!dispatcher.HasShutdownStarted)
                    await executor.ExecuteAsync(dispatcher, () => { iterator.Dispose(); return true; }, CancellationToken.None).ConfigureAwait(false);
            }
        }

        private static int CompareNodes(ManagedNodeDto first, ManagedNodeDto second)
        {
            int label = StringComparer.Ordinal.Compare(first.Label, second.Label);
            return label != 0 ? label : StringComparer.Ordinal.Compare(first.Object.ObjectId, second.Object.ObjectId);
        }

        private sealed class Snapshot<T>
        {
            internal IReadOnlyList<T> Items = Array.Empty<T>();
            internal IReadOnlyList<Diagnostic> Diagnostics = Array.Empty<Diagnostic>();
            internal readonly Dictionary<string, int> Offsets = new Dictionary<string, int>(StringComparer.Ordinal);
            internal readonly Dictionary<int, string> Tokens = new Dictionary<int, string>();
        }

        private PageDto<T> NewPage<T>(string objectId, long generation, string operation, string tree,
            IReadOnlyList<T> items, IReadOnlyList<Diagnostic> diagnostics, int size, CancellationToken ct)
        {
            ct.ThrowIfCancellationRequested();
            var snapshot = new Snapshot<T> { Items = items.ToArray(), Diagnostics = diagnostics };
            if (items.Count <= size)
                return Slice(snapshot, Guid.NewGuid().ToString("N"), 0, size);
            string id = snapshots.Create(objectId, generation, operation, tree, new[] { snapshot },
                Comparer<Snapshot<T>>.Create((first, second) => 0));
            return Slice(snapshot, id, 0, size);
        }

        private PageDto<T> Page<T>(string objectId, long generation, string operation, string tree, int size, string token)
        {
            int separator = token.IndexOf('.');
            if (separator <= 0) throw InvalidPage();
            string id = token.Substring(0, separator);
            Snapshot<T> snapshot = snapshots.Get<Snapshot<T>>(id, objectId, generation, operation, tree)[0];
            lock (snapshot)
            {
                snapshots.Get<Snapshot<T>>(id, objectId, generation, operation, tree);
                if (!snapshot.Offsets.TryGetValue(token.Substring(separator + 1), out int offset)) throw InvalidPage();
                PageDto<T> page = Slice(snapshot, id, offset, size);
                if (page.NextToken == null) snapshots.Remove(id);
                return page;
            }
        }

        private static PageDto<T> Slice<T>(Snapshot<T> snapshot, string id, int offset, int size)
        {
            var items = new List<T>();
            int end = Math.Min(snapshot.Items.Count, offset + size);
            for (int index = offset; index < end; index++) items.Add(snapshot.Items[index]);
            string? nextToken = null;
            lock (snapshot)
            {
                if (end < snapshot.Items.Count)
                {
                    if (!snapshot.Tokens.TryGetValue(end, out string? cursor))
                    {
                        cursor = Guid.NewGuid().ToString("N");
                        snapshot.Tokens.Add(end, cursor);
                        snapshot.Offsets.Add(cursor, end);
                    }
                    nextToken = id + "." + cursor;
                }
            }
            return new PageDto<T>
            {
                Items = items, SnapshotId = id, Diagnostics = snapshot.Diagnostics,
                Complete = end == snapshot.Items.Count && snapshot.Diagnostics.Count == 0,
                NextToken = nextToken
            };
        }

        private static int PageSize(int? size)
        {
            int result = size ?? ProtocolLimits.DefaultPageSize;
            CheckCount(result, ProtocolLimits.MaxPageSize);
            return result;
        }

        private static void CheckPaths(IReadOnlyList<IReadOnlyList<PathSegment>> paths)
        {
            CheckCount(paths.Count, ProtocolLimits.MaxBatchPaths);
            foreach (IReadOnlyList<PathSegment> path in paths)
            {
                CheckCount(path.Count, ProtocolLimits.MaxPathSegments);
                var json = new JsonArrayNode();
                foreach (PathSegment segment in path) json.Add(segment.ToJson());
                if (StrictJson.Serialize(json).Length > ProtocolLimits.MaxPathBytes)
                    throw new ProtocolException(ErrorCodes.LimitExceeded, "Path byte limit reached.");
                // Type metadata describes the object a path reaches, so it can only end a path (type:Name@DataContext).
                if (path.Count > 1 && path.Take(path.Count - 1).Any(segment => segment.Kind == SegmentKind.Type))
                    throw new ProtocolException(ErrorCodes.InvalidParams, "Type metadata must be the final path segment.");
            }
        }

        private static void CheckCount(int count, int maximum, bool allowEmpty = false)
        {
            if (count > maximum) throw new ProtocolException(ErrorCodes.LimitExceeded, "Request limit reached.");
            if (!allowEmpty && count < 1) throw new ProtocolException(ErrorCodes.InvalidParams, "Empty request.");
        }

        private static ProtocolException InvalidPage() => new ProtocolException(ErrorCodes.InvalidPageToken, "Invalid or expired page token.");

        private async Task<T> RunAsync<T>(Func<CancellationToken, Task<T>> action, CancellationToken ct)
        {
            CancellationTokenSource cancellation;
            lock (lifetime)
            {
                if (Volatile.Read(ref disposed) != 0) throw new ObjectDisposedException(nameof(WpfInspectionService));
                cancellation = CancellationTokenSource.CreateLinkedTokenSource(ct, lifetime.Token);
            }
            using (cancellation)
            {
                cancellation.Token.ThrowIfCancellationRequested();
                T result = await action(cancellation.Token).ConfigureAwait(false);
                cancellation.Token.ThrowIfCancellationRequested();
                return result;
            }
        }

        public void Dispose()
        {
            if (Interlocked.Exchange(ref disposed, 1) != 0) return;
            eventHooks?.Dispose();
            lock (lifetime) { lifetime.Cancel(); lifetime.Dispose(); }
            mapper.Invalidate();
            snapshots.Dispose();
            registry.Dispose();
        }
    }
}
