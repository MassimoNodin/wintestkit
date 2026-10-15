"""UI test automation for Windows WPF applications."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

__version__ = "0.1.0"

if TYPE_CHECKING:
    from wintestkit import errors as errors
    from wintestkit.app import App as App
    from wintestkit.config import WtkConfig as WtkConfig
    from wintestkit.config import load_config as load_config
    from wintestkit.expect import expect as expect
    from wintestkit.model import BoundElement as BoundElement
    from wintestkit.model import BoundElements as BoundElements
    from wintestkit.model import BoundWindow as BoundWindow
    from wintestkit.model import Element as Element
    from wintestkit.model import Elements as Elements
    from wintestkit.model import Page as Page
    from wintestkit.model import Window as Window

__all__ = [
    "App",
    "BoundElement",
    "BoundElements",
    "BoundWindow",
    "Element",
    "Elements",
    "Page",
    "Window",
    "WtkConfig",
    "__version__",
    "errors",
    "expect",
    "load_config",
]

# Public names are imported lazily so that merely loading the pytest plugin (which happens in
# every pytest run once wintestkit is installed) does not initialise COM or import UI Automation.
_LAZY: dict[str, tuple[str, str]] = {
    "App": ("wintestkit.app", "App"),
    "BoundElement": ("wintestkit.model", "BoundElement"),
    "BoundElements": ("wintestkit.model", "BoundElements"),
    "BoundWindow": ("wintestkit.model", "BoundWindow"),
    "Element": ("wintestkit.model", "Element"),
    "Elements": ("wintestkit.model", "Elements"),
    "Page": ("wintestkit.model", "Page"),
    "Window": ("wintestkit.model", "Window"),
    "WtkConfig": ("wintestkit.config", "WtkConfig"),
    "expect": ("wintestkit.expect", "expect"),
    "load_config": ("wintestkit.config", "load_config"),
}


def __getattr__(name: str) -> Any:
    if name == "errors":
        return importlib.import_module("wintestkit.errors")
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module 'wintestkit' has no attribute {name!r}")
    value = getattr(importlib.import_module(target[0]), target[1])
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(__all__)
