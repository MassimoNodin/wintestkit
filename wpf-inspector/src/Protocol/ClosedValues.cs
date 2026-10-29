namespace WinTestKit.Inspector.Protocol
{
    public static class EventKind { public const string WindowOpened = "windowOpened", WindowClosed = "windowClosed", TreeChanged = "treeChanged", Overflow = "overflow"; }
    public static class ActionOutcome { public const string Performed = "performed", NoChange = "noChange"; }
    public static class ValueStatus { public const string Ok = "ok", NotRead = "notRead", NotReadable = "notReadable", NullIntermediate = "nullIntermediate", Exception = "exception", Stale = "stale", Redacted = "redacted", Truncated = "truncated", Cycle = "cycle", Timeout = "timeout", Unsupported = "unsupported"; }
    public static class ValueKind { public const string Null = "null", String = "string", Boolean = "boolean", Integer = "integer", Number = "number", Enum = "enum", Object = "object", Array = "array", Type = "type", Unavailable = "unavailable"; }
    public static class MemberCategory { public const string TypeMetadata = "typeMetadata", ClrProperty = "clrProperty", ClrField = "clrField", DependencyProperty = "dependencyProperty", AttachedProperty = "attachedProperty"; }
    public static class Visibility { public const string Public = "public", Protected = "protected", Internal = "internal", Private = "private", ProtectedInternal = "protectedInternal", PrivateProtected = "privateProtected"; }
    public static class UnreadableReason { public const string NonPublic = "nonPublic", WriteOnly = "writeOnly", Indexer = "indexer", Static = "static", UnsupportedType = "unsupportedType", Ambiguous = "ambiguous"; }
    public static class MappingStatus { public const string Exact = "exact", NotFound = "notFound", Ambiguous = "ambiguous", UnsupportedPeer = "unsupportedPeer", Stale = "stale", LimitExceeded = "limitExceeded"; }
    public static class BindingKind { public const string None = "none", Binding = "binding", MultiBinding = "multiBinding", PriorityBinding = "priorityBinding"; }
    public static class SessionState { public const string Detached = "detached", Probing = "probing", Attaching = "attaching", Ready = "ready", Detaching = "detaching", Faulted = "faulted", Exited = "exited"; }
    public static class TreeKind { public const string Visual = "visual", Logical = "logical"; }
    public static class SegmentKind { public const string Property = "property", Field = "field", Dependency = "dependency", Type = "type"; }
}
