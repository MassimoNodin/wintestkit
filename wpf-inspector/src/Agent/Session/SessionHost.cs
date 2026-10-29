using System;
using System.Diagnostics;
using System.Threading;
using WinTestKit.Inspector.Agent.Contracts;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Session
{
    public sealed class SessionHost : IDisposable
    {
        private readonly BootstrapSettings settings;
        private readonly IInspectionServiceFactory factory;
        private readonly IClientIdentityVerifier verifier;
        private readonly CancellationTokenSource cancellation = new CancellationTokenSource();
        private readonly object gate = new object();
        private Timer? timer;
        private PipeServer? pipe;
        private IInspectionService? service;
        private RequestScheduler? scheduler;
        private int disposed;
        public string State { get; private set; } = SessionState.Detached;

        public SessionHost(BootstrapSettings settings, IInspectionServiceFactory factory, IClientIdentityVerifier? verifier = null)
        {
            this.settings = settings; this.factory = factory; this.verifier = verifier ?? new ClientIdentityVerifier();
        }

        public void Run()
        {
            using (var mutex = new Mutex(false, @"Local\WinTestKit.Inspector.Agent." + settings.Process.Pid))
            {
                bool acquired;
                try { acquired = mutex.WaitOne(0); }
                catch (AbandonedMutexException) { acquired = true; }
                if (!acquired) { Trace.TraceWarning("Inspector agent already attached."); State = SessionState.Faulted; return; }
                try
                {
                    State = SessionState.Attaching;
                    lock (gate)
                    {
                        if (disposed != 0) return;
                        service = factory.Create(settings.SessionId);
                        scheduler = new RequestScheduler(settings.RequestTimeoutMs);
                        pipe = new PipeServer(settings, new RequestDispatcher(settings.SessionId, service, scheduler), verifier, factory.GetType().FullName == "WinTestKit.Inspector.Agent.Inspection.WpfInspectionServiceFactory", ResetIdle, (service as IExactMappingCapability)?.ExactMappingAvailable == true);
                        timer = new Timer(_ => { cancellation.Cancel(); pipe?.Dispose(); }, null, Math.Min(ProtocolLimits.IdleSessionMs, settings.IdleTimeoutMs), Timeout.Infinite);
                    }
                    State = SessionState.Ready;
                    pipe.RunAsync(cancellation.Token).GetAwaiter().GetResult();
                }
                catch (Exception error) when (error is OperationCanceledException || error is ObjectDisposedException || error is System.IO.IOException)
                {
                    if (!cancellation.IsCancellationRequested) State = SessionState.Faulted;
                }
                catch (Exception)
                {
                    State = SessionState.Faulted;
                    throw;
                }
                finally
                {
                    if (State != SessionState.Faulted) State = SessionState.Detaching;
                    Dispose();
                    mutex.ReleaseMutex();
                    if (State != SessionState.Faulted) State = SessionState.Detached;
                }
            }
        }
        private void ResetIdle() => timer?.Change(Math.Min(ProtocolLimits.IdleSessionMs, settings.IdleTimeoutMs), Timeout.Infinite);
        public void Dispose()
        {
            lock (gate)
            {
                if (Interlocked.Exchange(ref disposed, 1) != 0) return;
                cancellation.Cancel();
                scheduler?.Dispose();
                timer?.Dispose();
                pipe?.Dispose();
                service?.Dispose();
            }
        }
    }
}
