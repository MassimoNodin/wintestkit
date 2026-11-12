"""Run from an isolated installed environment against the published owned fixture."""

import sys
from pathlib import Path

import wintestkit_inspector

import wintestkit
from wintestkit import runtime
from wintestkit.app import App
from wintestkit.backends import WpfElement
from wintestkit.config import load_config
from wintestkit.engine.actions import click
from wintestkit.engine.locator import Locator
from wintestkit.engine.resolve import Scope, resolve
from wintestkit.inspector.payload import load_payload

fixture = Path(sys.argv[1]).resolve()
repo = Path(sys.argv[2]).resolve()
assert not any(Path(p).resolve() == repo or repo in Path(p).resolve().parents for p in sys.path)
print(f"Installed: {wintestkit.__file__}; {wintestkit_inspector.__file__}")
payload = load_payload()
payload.verify()
assert not payload.signed
cfg = load_config(
    Path.cwd(),
    {
        "backend": "auto",
        "inspector.enabled": True,
        "inspector.attach": "on-launch",
    },
)
app = None
try:
    with runtime.config_scope(cfg):
        app = App.launch(fixture, cwd=fixture.parent, owned_only=True)
        target = resolve(Scope(app), Locator(automation_id="NestedButton"))
        assert isinstance(target, WpfElement)
        print(f"WPF click: {click(target, mode='pattern')}")
        app.close()
        app = None
        assert not runtime.inspector_sessions()._entries
finally:
    if app is not None:
        app.close()
    runtime.reset()
print("Installed inspector smoke passed; no sessions remain.")
