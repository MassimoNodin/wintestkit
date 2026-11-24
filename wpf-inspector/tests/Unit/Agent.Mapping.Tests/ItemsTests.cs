using System;
using System.Collections;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Controls;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Inspection;
using WinTestKit.Inspector.Agent.Inspection.Members;
using WinTestKit.Inspector.Protocol;
using Xunit;

namespace WinTestKit.Inspector.Agent.Mapping.Tests
{
    [Collection("WPF dispatchers")]
    [Trait("Category", "Unit")]
    public sealed class ItemsTests
    {
        private sealed class Sequence : IEnumerable { public IEnumerator GetEnumerator() { yield return 7; yield return 8; } }
        private sealed class Broken : IEnumerable { public IEnumerator GetEnumerator() { yield return 1; throw new InvalidOperationException("bad\nvalue"); } }
        [Fact]
        public async Task CollectionsPagingAndErrors()
        {
            var ready = new TaskCompletionSource<Dispatcher>();
            var thread = new Thread(() => { var dispatcher = Dispatcher.CurrentDispatcher; ready.SetResult(dispatcher); Dispatcher.Run(); });
            thread.SetApartmentState(ApartmentState.STA); thread.Start();
            var dispatcher = await ready.Task;
            try
            {
                using (var service = new WpfInspectionService("items", new ObjectInspector()))
                {
                    var registry = (ObjectRegistry)typeof(WpfInspectionService).GetField("registry", BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(service)!;
                    async Task<ItemsResult> Read(object target, string expected)
                    {
                        var handle = registry.Register(target, dispatcher, new ObjectInspector().DescribeType(target.GetType()));
                        var first = await service.ItemsAsync(handle.ObjectId, handle.Generation, 1, null, CancellationToken.None);
                        Assert.Equal(expected, first.Kind);
                        if (first.NextPageToken != null) { var second = await service.ItemsAsync(handle.ObjectId, handle.Generation, 1, first.NextPageToken, CancellationToken.None); Assert.Single(second.Items); }
                        var error = await Assert.ThrowsAsync<ProtocolException>(() => service.ItemsAsync(handle.ObjectId, handle.Generation + 1, 1, null, CancellationToken.None)); Assert.Equal(ErrorCodes.ObjectStale, error.Code);
                        return first;
                    }
                    Assert.NotNull((await Read(new[] { 1, 2 }, "array")).NextPageToken);
                    await Read(new List<int> { 1, 2 }, "list");
                    Assert.NotNull(Assert.Single((await Read(new Dictionary<string, int> { ["a"] = 1, ["b"] = 2 }, "dictionary")).Items).Key);
                    await Read(new ObservableCollection<int> { 1, 2 }, "list");
                    var listBox = await dispatcher.InvokeAsync(() => { var control = new ListBox(); control.Items.Add(1); control.Items.Add(2); return control; });
                    await Read(listBox.Items, "list");
                    await Read(new Sequence(), "enumerable");
                    Assert.Equal("System.InvalidOperationException", (await Read(new Broken(), "enumerable")).ErrorType);
                    Assert.Empty((await Read("text", "notEnumerable")).Items);
                }
            }
            finally { dispatcher.InvokeShutdown(); thread.Join(); }
        }
    }
}
