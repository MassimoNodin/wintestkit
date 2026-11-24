using System.Reflection;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
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
    public sealed class StylingServiceTests
    {
        [Fact]
        public async Task StylingRunsOnTheTargetDispatcherAndAppliesTheRedactionPolicy()
        {
            var ready = new TaskCompletionSource<Dispatcher>();
            var thread = new Thread(() => { var dispatcher = Dispatcher.CurrentDispatcher; ready.SetResult(dispatcher); Dispatcher.Run(); });
            thread.SetApartmentState(ApartmentState.STA); thread.Start();
            var dispatcher = await ready.Task;
            try
            {
                using (var service = new WpfInspectionService("styling", new ObjectInspector(new[] { "tag" }), redactNames: new[] { "tag" }))
                {
                    var registry = (ObjectRegistry)typeof(WpfInspectionService).GetField("registry", BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(service)!;
                    ObjectRef Register(object target) => registry.Register(target, dispatcher, new ObjectInspector().DescribeType(target.GetType()));

                    var button = await dispatcher.InvokeAsync(() =>
                    {
                        var style = new Style(typeof(Button));
                        style.Setters.Add(new Setter(FrameworkElement.TagProperty, "hunter2"));
                        style.Setters.Add(new Setter(Control.PaddingProperty, new Thickness(2)));
                        var trigger = new Trigger { Property = UIElement.IsEnabledProperty, Value = false };
                        trigger.Setters.Add(new Setter(UIElement.OpacityProperty, 0.5));
                        style.Triggers.Add(trigger);
                        var control = new Button { Style = style, IsEnabled = false };
                        control.Resources.Add("Title", "Hello");
                        return control;
                    });
                    var handle = Register(button);
                    var result = await service.StylingAsync(handle.ObjectId, handle.Generation, CancellationToken.None);
                    Assert.True(result.Applicable);
                    Assert.Equal(ValueStatus.Redacted, result.Style!.Setters[0].Value!.Status);
                    Assert.Equal("ok", result.Style.Setters[1].Value!.Status);
                    Assert.Equal("active", Assert.Single(result.Style.Triggers).Active);
                    Assert.Equal("Title", Assert.Single(result.Resources!.Entries).Key);
                    byte[] json = StrictJson.Serialize(result.ToJson());
                    Assert.Equal(json, StrictJson.Serialize(StylingResult.FromJson(StrictJson.Parse(json, 0, json.Length)).ToJson()));

                    var plain = Register("text");
                    Assert.False((await service.StylingAsync(plain.ObjectId, plain.Generation, CancellationToken.None)).Applicable);
                    var stale = await Assert.ThrowsAsync<ProtocolException>(() => service.StylingAsync(handle.ObjectId, handle.Generation + 1, CancellationToken.None));
                    Assert.Equal(ErrorCodes.ObjectStale, stale.Code);
                }
            }
            finally { dispatcher.InvokeShutdown(); thread.Join(); }
        }
    }
}
