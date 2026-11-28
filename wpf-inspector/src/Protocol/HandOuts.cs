using System.Collections.Generic;

namespace WinTestKit.Inspector.Protocol
{
    /// <summary>
    /// Finds every object handle a message hands out. The agent counts these before a response or notification is
    /// written, and the client counts the same shape in what it receives, so both sides agree on how many times an
    /// object ID was handed out. An object handle is a JSON object that has all of <c>sessionId</c>, <c>objectId</c>,
    /// <c>generation</c>, <c>type</c> and <c>dispatcherId</c>; no other message part has that shape.
    /// </summary>
    public static class HandOuts
    {
        /// <summary>The object ID and generation of each handle in <paramref name="message"/>, once per occurrence.</summary>
        public static IReadOnlyList<KeyValuePair<string, long>> Find(JsonNode message)
        {
            var found = new List<KeyValuePair<string, long>>();
            var pending = new Stack<JsonNode>();
            pending.Push(message);
            while (pending.Count > 0)
            {
                switch (pending.Pop())
                {
                    case JsonArrayNode array:
                        foreach (JsonNode item in array.Items) pending.Push(item);
                        break;
                    case JsonObjectNode obj:
                        if (obj.TryGet("sessionId", out _) && obj.TryGet("type", out _) && obj.TryGet("dispatcherId", out _) &&
                            obj.TryGet("objectId", out JsonNode id) && id is JsonStringNode text &&
                            obj.TryGet("generation", out JsonNode generation) && generation is JsonNumberNode number && number.TryGetInt64(out long value))
                        {
                            found.Add(new KeyValuePair<string, long>(text.Value, value));
                            break;
                        }
                        foreach (var member in obj.Members) pending.Push(member.Value);
                        break;
                }
            }
            return found;
        }
    }
}
