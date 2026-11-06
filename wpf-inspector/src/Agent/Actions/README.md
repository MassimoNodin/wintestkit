# Action implementation status

The agent advertises `actions` for all eleven non-realize verbs.
`realizeItem` searches the control's `Items` view rather than `ItemsSource`, preserving
filter and sort order. It realizes only the chosen item; a virtualizing panel may also
generate other containers in the viewport. It updates layout and yields at background
dispatcher priority while waiting for generation, bounded by the request deadline.
For other virtualizing controls it asks their items-host panel to bring the chosen
index into view; a ComboBox's dropdown must already be open.
Tree searches cover only the immediate items of the supplied TreeView or TreeViewItem;
callers must expand and search nested TreeViewItem containers separately.
Disabled elements fail with `actionUnsupported` because the protocol has no
disabled-element error code.
Deferred invocation catches provider failures, not separately dispatched application handler exceptions.
