# Action implementation status

The agent advertises `actions` for all eleven non-realize verbs.
`realizeItem` remains unsupported until P3c and belongs to the `virtualItems` feature.
Disabled elements fail with `actionUnsupported` because the protocol has no
disabled-element error code.
Deferred invocation catches provider failures, not separately dispatched application handler exceptions.
