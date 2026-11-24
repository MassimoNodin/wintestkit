using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Inspection.Members;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Inspection
{
    public sealed partial class WpfInspectionService
    {
        /// <summary>Where the events request finds handlers; tests replace it to simulate a framework whose private state cannot be read.</summary>
        internal IEventStores EventStores { get; set; } = new ReflectedEventStores();

        /// <summary>
        /// The routed and CLR events of an object, each with its handlers or subscribers. Events somebody handles come first, then the rest by name.
        /// Only metadata and delegate lists are read: no handler runs.
        /// </summary>
        public Task<PageDto<MemberEventDto>> EventsAsync(string objectId, long generation, int? pageSize, string? pageToken, CancellationToken ct) => RunAsync(async token =>
        {
            int size = PageSize(pageSize);
            object target = GetObject(objectId, generation, out Dispatcher dispatcher);
            if (pageToken != null) return Page<MemberEventDto>(objectId, generation, "members.events", "", size, pageToken);
            IEventStores stores = EventStores;
            IReadOnlyList<MemberEventDto> events = await executor.ExecuteAsync(dispatcher, () => new EventsReader(stores).Read(target), token).ConfigureAwait(false);
            MemberEventDto[] sorted = events.OrderBy(item => item.Count > 0 ? 0 : 1)
                .ThenBy(item => item.Name, StringComparer.Ordinal)
                .ThenBy(item => item.DeclaringType, StringComparer.Ordinal)
                .ThenBy(item => item.Kind, StringComparer.Ordinal).ToArray();
            return NewPage(objectId, generation, "members.events", "", sorted, Array.Empty<Diagnostic>(), size, token);
        }, ct);
    }
}
