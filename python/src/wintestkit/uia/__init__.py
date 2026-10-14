"""Low-level UI Automation access (COM bootstrap, element wrappers, input)."""

from wintestkit.uia import dpi as _dpi

_dpi.ensure_per_monitor_aware()
