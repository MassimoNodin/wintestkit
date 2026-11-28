using System;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Contracts;
using WinTestKit.Inspector.Agent.Inspection;
using WinTestKit.Inspector.Protocol;
using Xunit;

namespace Agent.Session.Tests;

public class FocusTests
{
    private sealed class NumericSpinner : Control { }
    private sealed class Wrapper : Control { }

    [Fact]
    public async Task FocusTracksTemplatePartsAndScope()
    {
        var ready = new TaskCompletionSource<Dispatcher>();
        var thread = new Thread(() => { ready.SetResult(Dispatcher.CurrentDispatcher); Dispatcher.Run(); }) { IsBackground = true };
        thread.SetApartmentState(ApartmentState.STA); thread.Start();
        var dispatcher = await ready.Task;
        var service = (WpfInspectionService)new WpfInspectionServiceFactory().Create("session", Array.Empty<string>());
        var registry = (IObjectRegistry)typeof(WpfInspectionService).GetField("registry", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(service)!;
        var setup = await dispatcher.InvokeAsync(() =>
        {
            var spinner = new NumericSpinner { Template = new ControlTemplate(typeof(NumericSpinner)) { VisualTree = new FrameworkElementFactory(typeof(TextBox), "part") } };
            var wrapper = new Wrapper { Template = new ControlTemplate(typeof(Wrapper)) { VisualTree = new FrameworkElementFactory(typeof(PasswordBox), "part") } };
            var outside = new TextBox(); var panel = new StackPanel(); panel.Children.Add(spinner); panel.Children.Add(wrapper); panel.Children.Add(outside);
            var window = new Window { Width = 300, Height = 200, Content = panel, ShowInTaskbar = false }; window.Show(); window.UpdateLayout();
            var reference = registry.Register(spinner, dispatcher, new TypeInfoDto());
            return (window, spinner, wrapper, outside, scope: new FocusScope { ObjectId = reference.ObjectId, Generation = reference.Generation });
        }).Task;
        try
        {
            await dispatcher.InvokeAsync(() => { setup.window.Activate(); ((TextBox)setup.spinner.Template.FindName("part", setup.spinner)).Focus(); }, DispatcherPriority.ApplicationIdle).Task;
            var focus = await service.FocusedAsync(setup.scope, DateTime.UtcNow.AddSeconds(2), CancellationToken.None);
            Assert.NotNull(focus); Assert.True(focus!.WithinScope); Assert.False(focus.IsPassword); Assert.True(focus.Classified);
            var unscoped = await service.FocusedAsync(null, DateTime.UtcNow.AddSeconds(2), CancellationToken.None);
            Assert.NotNull(unscoped); Assert.False(unscoped!.WithinScope);
            await dispatcher.InvokeAsync(() => ((PasswordBox)setup.wrapper.Template.FindName("part", setup.wrapper)).Focus(), DispatcherPriority.ApplicationIdle).Task;
            focus = await service.FocusedAsync(setup.scope, DateTime.UtcNow.AddSeconds(2), CancellationToken.None);
            Assert.NotNull(focus); Assert.True(focus!.IsPassword); Assert.True(focus.Classified); Assert.False(focus.WithinScope);
            await dispatcher.InvokeAsync(() => setup.outside.Focus(), DispatcherPriority.ApplicationIdle).Task;
            focus = await service.FocusedAsync(setup.scope, DateTime.UtcNow.AddSeconds(2), CancellationToken.None);
            Assert.NotNull(focus); Assert.False(focus!.WithinScope);
            await dispatcher.InvokeAsync(() => Keyboard.ClearFocus(), DispatcherPriority.ApplicationIdle).Task;
            Assert.Null(await service.FocusedAsync(setup.scope, DateTime.UtcNow.AddSeconds(2), CancellationToken.None));
        }
        finally
        {
            await dispatcher.InvokeAsync(() => setup.window.Close()).Task;
            service.Dispose(); dispatcher.BeginInvokeShutdown(DispatcherPriority.Send); thread.Join();
        }
    }
}
