using System.Collections.Generic;
namespace WinTestKit.Inspector.Protocol
{
    public sealed class PointDto
    {
        public double X { get; set; } public double Y { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("x",JsonNumberNode.From(X)); o.Add("y",JsonNumberNode.From(Y)); FromJson(o); return o; }
        public static PointDto FromJson(JsonNode n) { var o = DtoHelpers.Object(n,"x","y"); return new PointDto { X = QueryHelpers.Number(o.Get("x")), Y = QueryHelpers.Number(o.Get("y")) }; }
    }
    public sealed class RectDto
    {
        public double X { get; set; } public double Y { get; set; } public double Width { get; set; } public double Height { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("x",JsonNumberNode.From(X)); o.Add("y",JsonNumberNode.From(Y)); o.Add("width",JsonNumberNode.From(Width)); o.Add("height",JsonNumberNode.From(Height)); FromJson(o); return o; }
        public static RectDto FromJson(JsonNode n) { var o = DtoHelpers.Object(n,"x","y","width","height"); var x = new RectDto { X = QueryHelpers.Number(o.Get("x")), Y = QueryHelpers.Number(o.Get("y")), Width = QueryHelpers.Number(o.Get("width")), Height = QueryHelpers.Number(o.Get("height")) }; if (x.Width < 0 || x.Height < 0) throw DtoHelpers.Invalid("Invalid bounds"); return x; }
    }
    public sealed class PartGeometry
    {
        public string Name { get; set; } = ""; public string Role { get; set; } = ""; public RectDto? Bounds { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); DtoHelpers.Add(o,"name",Name); DtoHelpers.Add(o,"role",Role); o.Add("bounds",(JsonNode?)Bounds?.ToJson() ?? JsonNullNode.Instance); FromJson(o); return o; }
        public static PartGeometry FromJson(JsonNode n) { var o = DtoHelpers.Object(n,"name","role","bounds"); var b = o.Get("bounds"); var x = new PartGeometry { Name = DtoHelpers.Required(o,"name"), Role = DtoHelpers.Required(o,"role"), Bounds = b is JsonNullNode ? null : RectDto.FromJson(b) }; DtoHelpers.OneOf(x.Role,"expanderToggle","comboDropDown","scrollThumb","scrollDecrement","scrollIncrement","scrollTrack","treeItemExpander","gridColumnHeader","templatePart"); return x; }
    }
    public sealed class ElementState
    {
        public ObjectRef Handle { get; set; } = new ObjectRef(); public long? WindowHandle { get; set; } public RectDto? Bounds { get; set; } public PointDto Dpi { get; set; } = new PointDto(); public bool Visible { get; set; } public bool Clipped { get; set; } public bool Offscreen { get; set; } public bool Enabled { get; set; } public bool Focused { get; set; } public bool IsKeyboardFocusable { get; set; } public IReadOnlyList<PartGeometry> Parts { get; set; } = new List<PartGeometry>();
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("handle",Handle.ToJson()); o.Add("windowHandle",WindowHandle.HasValue ? (JsonNode)JsonNumberNode.From(WindowHandle.Value) : JsonNullNode.Instance); o.Add("bounds",(JsonNode?)Bounds?.ToJson() ?? JsonNullNode.Instance); o.Add("dpi",Dpi.ToJson()); o.Add("visible",new JsonBoolNode(Visible)); o.Add("clipped",new JsonBoolNode(Clipped)); o.Add("offscreen",new JsonBoolNode(Offscreen)); o.Add("enabled",new JsonBoolNode(Enabled)); o.Add("focused",new JsonBoolNode(Focused)); o.Add("isKeyboardFocusable",new JsonBoolNode(IsKeyboardFocusable)); var a = new JsonArrayNode(); foreach (var p in Parts) a.Add(p.ToJson()); o.Add("parts",a); FromJson(o); return o; }
        public static ElementState FromJson(JsonNode n) { var o = DtoHelpers.Object(n,"handle","windowHandle","bounds","dpi","visible","clipped","offscreen","enabled","focused","isKeyboardFocusable","parts"); var w = o.Get("windowHandle"); var b = o.Get("bounds"); var ps = new List<PartGeometry>(); foreach (var p in DtoHelpers.Array(o.Get("parts"),int.MaxValue).Items) ps.Add(PartGeometry.FromJson(p)); var x = new ElementState { Handle = ObjectRef.FromJson(o.Get("handle")), WindowHandle = w is JsonNullNode ? (long?)null : DtoHelpers.Integer(w,long.MinValue), Bounds = b is JsonNullNode ? null : RectDto.FromJson(b), Dpi = PointDto.FromJson(o.Get("dpi")), Visible = DtoHelpers.Boolean(o.Get("visible")), Clipped = DtoHelpers.Boolean(o.Get("clipped")), Offscreen = DtoHelpers.Boolean(o.Get("offscreen")), Enabled = DtoHelpers.Boolean(o.Get("enabled")), Focused = DtoHelpers.Boolean(o.Get("focused")), IsKeyboardFocusable = DtoHelpers.Boolean(o.Get("isKeyboardFocusable")), Parts = ps }; if (x.Dpi.X <= 0 || x.Dpi.Y <= 0) throw DtoHelpers.Invalid("Invalid dpi"); return x; }
    }
    public sealed class StateGetResult
    {
        public ElementState State { get; set; } = new ElementState();
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("state",State.ToJson()); FromJson(o); return o; }
        public static StateGetResult FromJson(JsonNode n) { var o = DtoHelpers.Object(n,"state"); return new StateGetResult { State = ElementState.FromJson(o.Get("state")) }; }
    }
    public sealed class HitTestParams
    {
        public long NativeWindowHandle { get; set; } public PointDto Point { get; set; } = new PointDto(); public int TimeoutMs { get; set; }
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("nativeWindowHandle",JsonNumberNode.From(NativeWindowHandle)); o.Add("point",Point.ToJson()); o.Add("timeoutMs",JsonNumberNode.From(TimeoutMs)); FromJson(o); return o; }
        public static HitTestParams FromJson(JsonNode n) { var o = DtoHelpers.Object(n,"nativeWindowHandle","point","timeoutMs"); return new HitTestParams { NativeWindowHandle = DtoHelpers.Integer(o.Get("nativeWindowHandle"),long.MinValue), Point = PointDto.FromJson(o.Get("point")), TimeoutMs = (int)DtoHelpers.Integer(o.Get("timeoutMs"),1,2000) }; }
    }
    public sealed class HitTestResult
    {
        public ObjectRef Handle { get; set; } = new ObjectRef();
        public JsonObjectNode ToJson() { var o = new JsonObjectNode(); o.Add("handle",Handle.ToJson()); FromJson(o); return o; }
        public static HitTestResult FromJson(JsonNode n) { var o = DtoHelpers.Object(n,"handle"); return new HitTestResult { Handle = ObjectRef.FromJson(o.Get("handle")) }; }
    }
}
