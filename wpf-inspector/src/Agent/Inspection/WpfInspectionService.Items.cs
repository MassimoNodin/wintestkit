using System;
using System.Collections;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Inspection.Members;
using WinTestKit.Inspector.Protocol;

namespace WinTestKit.Inspector.Agent.Inspection
{
    public sealed partial class WpfInspectionService
    {
        public Task<ItemsResult> ItemsAsync(string objectId, long generation, int? pageSize, string? pageToken, CancellationToken ct) => RunAsync(async token =>
        {
            int size = PageSize(pageSize);
            object target = GetObject(objectId, generation, out Dispatcher dispatcher);
            int offset = 0;
            if (pageToken != null)
            {
                int separator = pageToken.IndexOf('.');
                if (separator <= 0) throw InvalidPage();
                var snapshot = snapshots.Get<Snapshot<int>>(pageToken.Substring(0, separator), objectId, generation, "members.items", "")[0];
                lock (snapshot) if (!snapshot.Offsets.TryGetValue(pageToken.Substring(separator + 1), out offset)) throw InvalidPage();
            }
            var result = await executor.ExecuteAsync(dispatcher, () => ReadItems(target, dispatcher, offset, size), token).ConfigureAwait(false);
            if (!result.Complete && result.ErrorType == null)
            {
                var snapshot = new Snapshot<int>();
                string cursor = Guid.NewGuid().ToString("N");
                snapshot.Offsets.Add(cursor, checked(offset + result.Items.Count));
                string id = snapshots.Create(objectId, generation, "members.items", "", new[] { snapshot }, Comparer<Snapshot<int>>.Create((first, second) => 0));
                result.NextPageToken = id + "." + cursor;
            }
            return result;
        }, ct);

        private ItemsResult ReadItems(object target, Dispatcher dispatcher, int offset, int size)
        {
            var result = new ItemsResult();
            var items = new List<ItemDto>();
            result.Items = items;
            if (target == null || target is string || !(target is IEnumerable enumerable)) { result.Complete = true; return result; }
            if (RedactionPolicy.IsProtectedIdentity(target)) { result.Complete = true; return result; }
            result.Kind = target is Array array && array.Rank == 1 ? "array" : target is IDictionary ? "dictionary" : target is IList && !(target is Array) ? "list" : "enumerable";
            try
            {
                if (target is Array values) result.Count = values.Length;
                else if (target is ICollection collection) result.Count = collection.Count;
                if (result.Kind == "array" || result.Kind == "list")
                {
                    var list = (IList)target;
                    int end = (int)Math.Min((long)result.Count!.Value, (long)offset + size);
                    for (int index = offset; index < end; index++) items.Add(new ItemDto { Index = index, Value = ValueSerializer.Serialize(list[index], typeof(object), registry, dispatcher) });
                    result.Complete = end >= result.Count.Value;
                }
                else
                {
                    IEnumerator iterator = target is IDictionary dictionary ? dictionary.GetEnumerator() : enumerable.GetEnumerator();
                    try
                    {
                        // Reaching a later page costs O(offset) for an enumerator.
                        for (int index = 0; index < offset; index++) if (!iterator.MoveNext()) { result.Complete = true; return result; }
                        while (items.Count < size && iterator.MoveNext())
                        {
                            if (result.Kind == "dictionary")
                            {
                                var entry = (DictionaryEntry)iterator.Current;
                                items.Add(new ItemDto { Key = ValueSerializer.Serialize(entry.Key, typeof(object), registry, dispatcher), Value = ValueSerializer.Serialize(entry.Value, typeof(object), registry, dispatcher) });
                            }
                            else items.Add(new ItemDto { Index = offset + items.Count, Value = ValueSerializer.Serialize(iterator.Current, typeof(object), registry, dispatcher) });
                        }
                        result.Complete = items.Count < size || (result.Count.HasValue ? (long)offset + items.Count >= result.Count.Value : !iterator.MoveNext());
                    }
                    finally { (iterator as IDisposable)?.Dispose(); }
                }
            }
            catch (Exception exception) { result.ErrorType = exception.GetType().FullName ?? exception.GetType().Name; result.ErrorMessage = ValueSerializer.ErrorMessage(exception); result.Complete = false; }
            return result;
        }
    }
}
