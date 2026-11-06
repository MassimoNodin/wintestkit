# Action implementation status

The agent advertises `actions` for `focus`, `bringIntoView`, `scrollIntoView`,
`invoke`, `toggle`, `expand`, `collapse`, and `select` in this partial slice; `setValue`,
`setRange`, and `scroll` remain unsupported until the next slice.
`realizeItem` is also unsupported and belongs to the `virtualItems` feature.
Disabled elements fail with `actionUnsupported` because the protocol has no
disabled-element error code.
Deferred invocation catches provider failures, not separately dispatched application handler exceptions.
