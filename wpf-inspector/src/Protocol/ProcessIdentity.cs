using System;
using System.Globalization;
using System.Text.RegularExpressions;

namespace WinTestKit.Inspector.Protocol
{
    public sealed class ProcessIdentity
    {
        public int Pid { get; set; }
        public string CreationTimeUtc { get; set; } = "";
        public JsonObjectNode ToJson()
        {
            var result = new JsonObjectNode(); result.Add("pid", JsonNumberNode.From(Pid)); result.Add("creationTimeUtc", new JsonStringNode(CreationTimeUtc));
            FromJson(result); return result;
        }
        public static ProcessIdentity FromJson(JsonNode node)
        {
            if (!(node is JsonObjectNode obj) || obj.Members.Count != 2 || !obj.TryGet("pid", out var pidNode) || !(pidNode is JsonNumberNode number) || !number.TryGetInt64(out long pid) || pid < 1 || pid > int.MaxValue || !obj.TryGet("creationTimeUtc", out var timeNode) || !(timeNode is JsonStringNode time) || time.Value.Length > 128 || !Regex.IsMatch(time.Value, @"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$") || !DateTimeOffset.TryParse(time.Value, CultureInfo.InvariantCulture, DateTimeStyles.None, out _)) throw new ProtocolException(ErrorCodes.InvalidParams, "Invalid process identity");
            return new ProcessIdentity { Pid = (int)pid, CreationTimeUtc = time.Value };
        }
    }
}
