using System;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Threading;

namespace WinTestKit.Inspector.Agent.Mapping.Tests
{
    public sealed class ApplicationDispatcherFixture : IDisposable
    {
        private readonly DispatcherThread ui = new DispatcherThread();
        private readonly Application application;
        internal Dispatcher Dispatcher => ui.Dispatcher;

        public ApplicationDispatcherFixture()
        {
            application = ui.Dispatcher.InvokeAsync(() => new Application { ShutdownMode = ShutdownMode.OnExplicitShutdown }).Task.GetAwaiter().GetResult();
        }

        public void Dispose()
        {
            try { ui.Dispatcher.InvokeAsync(application.Shutdown).Task.GetAwaiter().GetResult(); }
            finally { ui.Dispose(); }
        }
    }

    internal sealed class DispatcherThread : IDisposable
    {
        private readonly Thread thread;
        internal Dispatcher Dispatcher { get; }

        internal DispatcherThread()
        {
            var ready = new TaskCompletionSource<Dispatcher>(TaskCreationOptions.RunContinuationsAsynchronously);
            thread = new Thread(() =>
            {
                ready.SetResult(Dispatcher.CurrentDispatcher);
                Dispatcher.Run();
            }) { IsBackground = true };
            thread.SetApartmentState(ApartmentState.STA);
            thread.Start();
            Dispatcher = ready.Task.GetAwaiter().GetResult();
        }

        public void Dispose()
        {
            if (!Dispatcher.HasShutdownStarted) Dispatcher.BeginInvokeShutdown(DispatcherPriority.Send);
            if (!thread.Join(TimeSpan.FromSeconds(10))) throw new TimeoutException("Test Dispatcher did not shut down.");
        }
    }
}
