using System.Collections.Generic;
namespace WinTestKit.Inspector.Protocol
{
    public sealed class ItemDto
    {
        public int? Index { get; set; }
        public ValueDto? Key { get; set; }
        public ValueDto Value { get; set; } = new ValueDto();
        public JsonObjectNode ToJson() { var obj = new JsonObjectNode(); obj.Add("index", Index.HasValue ? (JsonNode)JsonNumberNode.From(Index.Value) : JsonNullNode.Instance); obj.Add("key", Key == null ? (JsonNode)JsonNullNode.Instance : Key.ToJson()); obj.Add("value", Value.ToJson()); return obj; }
        public static ItemDto FromJson(JsonNode node) { var obj = DtoHelpers.Object(node, "index", "key", "value"); var index = obj.Get("index"); var key = obj.Get("key"); return new ItemDto { Index = index is JsonNullNode ? (int?)null : (int)DtoHelpers.Integer(index, 0, int.MaxValue), Key = key is JsonNullNode ? null : ValueDto.FromJson(key), Value = ValueDto.FromJson(obj.Get("value")) }; }
    }
    public sealed class ItemsResult
    {
        public string Kind { get; set; } = "notEnumerable";
        public int? Count { get; set; }
        public IReadOnlyList<ItemDto> Items { get; set; } = new List<ItemDto>();
        public string? NextPageToken { get; set; }
        public bool Complete { get; set; }
        public string? ErrorType { get; set; }
        public string? ErrorMessage { get; set; }
        public JsonObjectNode ToJson() { var obj = new JsonObjectNode(); obj.Add("kind", new JsonStringNode(Kind)); obj.Add("count", Count.HasValue ? (JsonNode)JsonNumberNode.From(Count.Value) : JsonNullNode.Instance); var items = new JsonArrayNode(); foreach (var item in Items) items.Add(item.ToJson()); obj.Add("items", items); obj.Add("nextPageToken", NextPageToken == null ? (JsonNode)JsonNullNode.Instance : new JsonStringNode(NextPageToken)); obj.Add("complete", new JsonBoolNode(Complete)); if (ErrorType != null) { var error = new JsonObjectNode(); error.Add("type", new JsonStringNode(ErrorType)); error.Add("message", ErrorMessage == null ? (JsonNode)JsonNullNode.Instance : new JsonStringNode(ErrorMessage)); obj.Add("error", error); } return obj; }
        public static ItemsResult FromJson(JsonNode node) { var obj = DtoHelpers.Object(node, "kind", "count", "items", "nextPageToken", "complete", "error"); var kind = DtoHelpers.Required(obj, "kind"); DtoHelpers.OneOf(kind, "array", "list", "dictionary", "enumerable", "notEnumerable"); var count = obj.Get("count"); var next = obj.Get("nextPageToken"); var items = new List<ItemDto>(); foreach (var item in DtoHelpers.Array(obj.Get("items")).Items) items.Add(ItemDto.FromJson(item)); var result = new ItemsResult { Kind = kind, Count = count is JsonNullNode ? (int?)null : (int)DtoHelpers.Integer(count, 0, int.MaxValue), Items = items, NextPageToken = next is JsonNullNode ? null : DtoHelpers.String(next), Complete = DtoHelpers.Boolean(obj.Get("complete")) }; if (obj.TryGet("error", out var errorNode)) { var error = DtoHelpers.Object(errorNode, "type", "message"); result.ErrorType = DtoHelpers.Required(error, "type"); var message = error.Get("message"); result.ErrorMessage = message is JsonNullNode ? null : DtoHelpers.String(message, 512, true); } if (result.Complete && result.NextPageToken != null) throw DtoHelpers.Invalid("Complete page cannot have next token"); return result; }
    }
}
