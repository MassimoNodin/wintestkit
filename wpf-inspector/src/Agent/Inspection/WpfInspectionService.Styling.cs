using System.Threading;
using System.Threading.Tasks;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Inspection.Members;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Inspection
{
    public sealed partial class WpfInspectionService
    {
        /// <summary>The Style, templates and resources of an object; an empty, not applicable result for anything but a FrameworkElement or FrameworkContentElement.</summary>
        public Task<StylingResult> StylingAsync(string objectId, long generation, CancellationToken ct) => RunAsync(async token =>
        {
            object target = GetObject(objectId, generation, out Dispatcher dispatcher);
            return await executor.ExecuteAsync(dispatcher, () => new StylingReader(redaction, registry, dispatcher).Read(target), token).ConfigureAwait(false);
        }, ct);

        /// <summary>One resource value of the object's own dictionary or the application's. This is the only request that creates a resource.</summary>
        public Task<ResourceResult> ResourceAsync(string objectId, long generation, string scope, string key, string keyKind, int? index, CancellationToken ct) => RunAsync(async token =>
        {
            object target = GetObject(objectId, generation, out Dispatcher dispatcher);
            return await executor.ExecuteAsync(dispatcher, () => new StylingReader(redaction, registry, dispatcher).ReadResource(target, scope, key, keyKind, index), token).ConfigureAwait(false);
        }, ct);
    }
}
