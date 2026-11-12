"""Opt-in phase 6 checks against the owned WPF fixture."""

import os
import time

import pytest
from test_inspector_owned_integration import _control

from wintestkit import runtime
from wintestkit.config import load_config
from wintestkit.engine.locator import Locator
from wintestkit.engine.resolve import resolve
from wintestkit.errors import ConfigError, WriteDeniedError, WriteRateExceededError
from wintestkit.model import Element, Page
from wintestkit.report.html import write_report

pytest_plugins = ("test_wpf_query_gate_real",)


pytestmark = pytest.mark.skipif(
    os.name != "nt" or os.environ.get("WTK_INSPECTOR_REAL") != "1",
    reason="requires explicitly enabled owned Windows fixture",
)


class FixturePage(Page):
    control = Element(automation_id="FixtureControl")
    password = Element(automation_id="PasswordBox")


def configure(path, allow):
    entries = "\n".join(f"      - '{entry}'" for entry in allow)
    path.joinpath("wintestkit.yaml").write_text(
        "inspector:\n  enabled: true\n  attach: on-demand\n"
        + ("  writes:\n    allow:\n" + entries + "\n" if allow else ""),
        encoding="utf-8",
    )
    return load_config(path)


def test_writes_disabled(owned):
    scope, path = owned
    records = []
    unsubscribe = runtime.add_step_listener(records.append)
    try:
        with runtime.config_scope(configure(path, [])):
            page = FixturePage(scope.app)
            with pytest.raises(WriteDeniedError):
                page.control.set_property("DefaultValue", "denied-value-917")
            with pytest.raises(WriteDeniedError):
                page.control.call("RecordWrite", "denied-method-918", 4)
            assert _control(scope.app.pids[0]).get("RecordWrite", 0) == 0
            assert resolve(
                scope,
                Locator(automation_id="FixtureControl", where=(("clr:DefaultValue", "default"),)),
            )
            assert [r.audits[0]["outcome"] for r in records] == ["denied", "denied"]
    finally:
        unsubscribe()


def test_allowed_writes_and_report(owned):
    scope, path = owned
    prefix = "WinTestKit.Fixture.FixtureControl."
    cfg = configure(
        path,
        [
            prefix + "DefaultValue",
            prefix + "WritableText",
            prefix + "RecordWrite(System.String,System.Int64)",
            "System.Windows.Controls.PasswordBox.Password",
        ],
    )
    records = []
    unsubscribe = runtime.add_step_listener(records.append)
    try:
        with runtime.config_scope(cfg):
            page = FixturePage(scope.app)
            page.control.set_property("DefaultValue", "written-dp-781")
            page.control.set_property("WritableText", "written-clr-782")
            page.control.call("RecordWrite", "written-call-783", 9)
            assert _control(scope.app.pids[0]).get("RecordWrite", 0) == 1
            assert resolve(
                scope,
                Locator(
                    automation_id="FixtureControl", where=(("clr:WritableText", "written-clr-782"),)
                ),
            )
            assert resolve(
                scope,
                Locator(
                    automation_id="FixtureControl", where=(("clr:DefaultValue", "written-dp-781"),)
                ),
            )
            with pytest.raises(WriteDeniedError):
                page.control.set_property("LocalValue", "denied-784")
            with pytest.raises(WriteDeniedError):
                page.password.set_property("Password", "denied-password-785")
            time.sleep(1.1)
            for _ in range(10):
                page.control.call("RecordWrite", "rapid-786", 1)
            with pytest.raises(WriteRateExceededError):
                page.control.call("RecordWrite", "rapid-786", 1)
        steps = [record.to_dict() for record in records]
        assert all(step.get("audits") for step in steps)
        report = write_report(
            path / "report", {"version": 1, "tests": [{"name": "writes", "steps": steps}]}
        )
        html = report.read_text(encoding="utf-8")
        for value in (
            "written-dp-781",
            "written-clr-782",
            "written-call-783",
            "denied-784",
            "denied-password-785",
            "rapid-786",
        ):
            assert value not in html
    finally:
        unsubscribe()


def test_local_allowlist_rejected(tmp_path):
    (tmp_path / "wintestkit.yaml").write_text("{}", encoding="utf-8")
    (tmp_path / "wintestkit.local.yaml").write_text(
        "inspector:\n  writes:\n    allow: [Example.Control.Name]\n", encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="repository"):
        load_config(tmp_path)
