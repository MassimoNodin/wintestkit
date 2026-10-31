"""Phase 1 live query gate, against the owned .NET 10 fixture."""

import os
import re
import statistics
import subprocess
import time
from dataclasses import replace

import pytest
from test_inspector_owned_integration import DOTNET, FIXTURE, PAYLOAD, _control

from wintestkit import runtime
from wintestkit.app import App
from wintestkit.config import load_config
from wintestkit.engine.actions import click
from wintestkit.engine.locator import Locator, WindowLocator
from wintestkit.engine.properties import resolve_where
from wintestkit.engine.query import query_all
from wintestkit.engine.resolve import Scope, resolve, resolve_all
from wintestkit.engine.wpf_query import translate
from wintestkit.errors import (
    AmbiguousElementError,
    InspectorError,
    InspectorLimitError,
    InspectorUnavailableError,
)
from wintestkit.inspector.models import Scope as WireScope
from wintestkit.inspector.probe import identify
from wintestkit.uia import win32

pytestmark = pytest.mark.skipif(
    os.name != "nt" or os.environ.get("WTK_INSPECTOR_REAL") != "1",
    reason="requires explicitly enabled owned Windows fixture",
)


@pytest.fixture
def owned(tmp_path, monkeypatch, request):
    runtime.reset()
    monkeypatch.syspath_prepend(str(PAYLOAD))
    env = os.environ.copy()
    env["DOTNET_ROOT_X64"] = DOTNET
    env["DOTNET_MULTILEVEL_LOOKUP"] = "0"
    target = subprocess.Popen(
        [str(FIXTURE / "WinTestKit.Fixture.exe")]
        + (
            ["--scenario", "openLarge"]
            if "large" in request.node.name
            else ["--scenario", "openPopup"]
            if "popup" in request.node.name
            else []
        ),
        cwd=FIXTURE,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        until = time.monotonic() + 30
        while True:
            assert target.poll() is None
            try:
                facts = identify(target.pid)
                if facts.wpf_loaded and len(win32.top_level_windows({target.pid})) >= (
                    2 if "large" in request.node.name else 1
                ):
                    _control(target.pid)
                    break
            except (OSError, InspectorUnavailableError):
                pass
            assert time.monotonic() < until
            time.sleep(0.1)
        yield Scope(App.attach(pid=target.pid)), tmp_path
    finally:
        runtime.reset()
        if target.poll() is None:
            target.terminate()
        target.wait(timeout=5)


def config(path, mode):
    return load_config(
        path, {"inspector.enabled": True, "inspector.attach": "on-demand", "inspector.query": mode}
    )


@pytest.mark.parametrize("backend", ["uia", "auto"])
def test_phase2_backend_parity(owned, backend):
    from wintestkit.expect import expect
    from wintestkit.model import Element, Elements, Page

    scope, path = owned

    class FixturePage(Page):
        button = Element(automation_id="FancyAutomationId")
        effect = Element(automation_id="ActionEffect")
        missing = Element(automation_id="NeverAppears")
        duplicates = Elements(automation_id="Duplicate")

    page = FixturePage(scope.app)
    with runtime.config_scope(replace(config(path, "agent"), backend=backend)):
        cases = [
            Locator(automation_id="FancyAutomationId"),
            Locator(name="Fancy action", control_type="Button"),
            Locator(class_name="Button", automation_id="FancyAutomationId"),
            Locator(control_type="Button", automation_id="FancyAutomationId"),
            Locator(automation_id=re.compile("^FancyAutomationId$")),
            Locator(automation_id="FancyAutomationId", where=(("clr:Tag", "fancy"),)),
            Locator(automation_id="NestedButton", within=Locator(automation_id="ParityGroup")),
        ]
        cases.extend(
            [
                Locator(automation_id=re.compile("Fancy(?=AutomationId)")),
                Locator(automation_id="FancyAutomationId", where=(("Name", "Fancy action"),)),
                Locator(automation_id="FancyAutomationId", where=(("IsEnabled", True),)),
                Locator(automation_id="FancyAutomationId", depth=20),
            ]
        )
        for locator in cases:
            assert len(resolve_all(scope, locator)) == 1
        assert len(resolve_all(scope, Locator(automation_id="Duplicate"))) == 2
        assert resolve(scope, Locator(automation_id="Duplicate", index=1)).name == "Duplicate"
        assert not resolve_all(scope, Locator(automation_id="NeverAppears"))
        with pytest.raises(AmbiguousElementError):
            resolve(scope, Locator(automation_id="Duplicate"))
        for state in ("attached", "visible", "enabled", "stable"):
            page.button.wait_for(state, timeout=5)
        for state in ("detached", "hidden"):
            page.missing.wait_for(state, timeout=5)
        expect(page.button, timeout=5).to_exist()
        expect(page.button, timeout=5).to_be_visible()
        expect(page.button, timeout=5).to_be_enabled()
        expect(page.button, timeout=5).not_.to_be_disabled()
        expect(page.missing, timeout=5).not_.to_exist()
        expect(page.duplicates, timeout=5).to_have_count(2)
        expect(page.button, timeout=5).to_have_text("Fancy action")
        expect(page.button, timeout=5).to_contain_text("Fancy")
        assert click(resolve(scope, Locator(automation_id="FancyAutomationId"))) == "invoke"
        expect(page.effect, timeout=5).to_have_text("Clicked 1")


def test_phase2_duplicate_order_matches(owned):
    from wintestkit.backends.element import uia_of

    scope, path = owned
    results = []
    for backend in ("uia", "auto"):
        with runtime.config_scope(replace(config(path, "agent"), backend=backend)):
            matches = resolve_all(scope, Locator(automation_id="Duplicate"))
            results.append([uia_of(element).runtime_id for element in matches])
    assert len(results[0]) == 2
    assert results[0] == results[1]


@pytest.mark.parametrize("backend", ["uia", "auto"])
def test_phase2_existing_expectations_and_input(owned, backend):
    from wintestkit.controls import TextBox
    from wintestkit.expect import expect
    from wintestkit.model import Element, Elements, Page

    scope, path = owned

    class FixturePage(Page):
        button = Element(automation_id="FancyAutomationId")
        source = TextBox(automation_id="BindingSource")
        duplicates = Elements(automation_id="Duplicate")

    page = FixturePage(scope.app)
    with runtime.config_scope(replace(config(path, "agent"), backend=backend)):
        expect(page.button, timeout=5).not_.to_be_hidden()
        expect(page.button, timeout=5).not_.to_have_text("wrong")
        expect(page.button, timeout=5).not_.to_contain_text("wrong")
        expect(page.button, timeout=5).to_have_property("IsEnabled", True)
        expect(page.button, timeout=5).not_.to_have_property("Name", "wrong")
        expect(page.duplicates, timeout=5).not_.to_have_count(3)
        expect(page.source, timeout=5).to_have_value("source")
        expect(page.source, timeout=5).not_.to_have_value("wrong")
        page.source.type("parity")
        expect(page.source, timeout=5).to_have_value("parity")
        page.source.clear()
        expect(page.source, timeout=5).to_have_value("")


def test_phase2_error_diagnostics_match(owned):
    from wintestkit.errors import LocatorError

    scope, path = owned
    locators = [
        Locator(automation_id="NeverAppears"),
        Locator(name="Never appears"),
        Locator(automation_id="Duplicate"),
        Locator(name="Duplicate", control_type="Button"),
        Locator(automation_id="Duplicate", index=10),
        Locator(name="Duplicate", control_type="Button", index=10),
        Locator(automation_id="NestedButton", within=Locator(automation_id="NeverAppears")),
        Locator(automation_id="NestedButton", within=Locator(name="Never appears")),
    ]
    messages = []
    for backend in ("uia", "auto"):
        results = []
        with runtime.config_scope(replace(config(path, "agent"), backend=backend)):
            for locator in locators:
                with pytest.raises(LocatorError) as error:
                    resolve(scope, locator)
                results.append((type(error.value), str(error.value)))
        messages.append(results)
    assert messages[0] == messages[1]


@pytest.mark.parametrize("backend", ["uia", "auto"])
def test_phase2_predicates_backend_parity(owned, backend):
    scope, path = owned
    predicates = [
        ("type:FullName", "WinTestKit.Fixture.FixtureControl"),
        ("clr:DataContext.Customer.Address.City", "Sydney"),
        ("field:PublicField", "public field"),
        ("dp:WinTestKit.Fixture|WinTestKit.Fixture.FixtureControl::DefaultValue", "default"),
        ("clr:CoercedValue", 10),
        ("IsEnabled", True),
        ("Name", re.compile("fixture control", re.IGNORECASE)),
        ("Name", re.compile("^Fixture control$", re.MULTILINE)),
        ("Name", re.compile("Fixture.*control", re.DOTALL)),
        ("Name", re.compile("Fixture(?= control)")),
    ]
    with runtime.config_scope(replace(config(path, "agent"), backend=backend)):
        for key, value in predicates:
            locator = Locator(automation_id="FixtureControl", where=((key, value),))
            assert len(resolve_all(scope, locator)) == 1, key


@pytest.mark.parametrize("backend", ["uia", "auto"])
def test_phase2_popup_backend_parity(owned, backend):
    scope, path = owned
    with runtime.config_scope(replace(config(path, "agent"), backend=backend)):
        assert resolve(scope, Locator(automation_id="PopupContent")).name == "Popup content"


def test_auto_backend_smoke(owned):
    scope, path = owned
    with runtime.config_scope(replace(config(path, "agent"), backend="auto")):
        assert (
            resolve(scope, Locator(automation_id="FixtureControl")).automation_id
            == "FixtureControl"
        )
        assert (
            resolve(
                scope, Locator(automation_id="FancyAutomationId", where=(("clr:Tag", "fancy"),))
            ).automation_id
            == "FancyAutomationId"
        )
        assert (
            resolve(
                scope,
                Locator(automation_id="NestedButton", within=Locator(automation_id="ParityGroup")),
            ).automation_id
            == "NestedButton"
        )
        peerless = resolve(
            scope, Locator(where=(("type:Is", "WinTestKit.Fixture.PeerlessMarker"),))
        )
        assert peerless.runtime_id.startswith("wpf:")
        assert click(resolve(scope, Locator(automation_id="FancyAutomationId"))) == "invoke"


def test_parity_and_features(owned):
    scope, path = owned
    where = (("type:FullName", "WinTestKit.Fixture.FixtureControl"),)
    cases = [
        Locator(automation_id="FixtureControl", where=where),
        Locator(automation_id="FixtureControl", name="Fixture control", where=where),
        Locator(name="Fixture control", where=where),
        Locator(automation_id="FixtureControl", class_name="Button", where=where),
        Locator(automation_id="FixtureControl", control_type="Button", where=where),
        Locator(automation_id=re.compile("^Fixture"), where=where),
        Locator(automation_id="FixtureControl", where=(("clr:LocalValue", "local"),)),
        Locator(automation_id="FixtureControl", where=(("clr:DefaultValue", "default"),)),
        Locator(automation_id="FixtureControl", where=(("clr:Overridden", "fixture"),)),
        Locator(
            automation_id="FixtureControl",
            where=(("clr:DataContext.Customer.Address.City", "Sydney"),),
        ),
        Locator(
            automation_id="FixtureControl", where=(("clr:DataContext.Label", re.compile("^fix")),)
        ),
        Locator(automation_id="FixtureControl", where=(("field:PublicField", "public field"),)),
        Locator(
            automation_id="FixtureControl",
            where=(
                (
                    "dp:WinTestKit.Fixture|WinTestKit.Fixture.FixtureControl::DefaultValue",
                    "default",
                ),
            ),
        ),
        Locator(automation_id="FancyAutomationId", where=(("clr:Tag", "fancy"),)),
        Locator(
            automation_id="Duplicate", where=(("type:FullName", "System.Windows.Controls.Button"),)
        ),
        Locator(
            automation_id="Duplicate",
            index=1,
            where=(("type:FullName", "System.Windows.Controls.Button"),),
        ),
        Locator(
            automation_id="NestedButton",
            where=(("clr:Tag", "nested"),),
            within=Locator(automation_id="ParityGroup"),
        ),
    ]
    for locator in cases:
        results = []
        for mode in ("agent", "postfilter"):
            with runtime.config_scope(config(path, mode)):
                if locator.index is not None:
                    found = [resolve(scope, locator)]
                else:
                    found = resolve_all(scope, locator)
                results.append([element.runtime_id for element in found])
        print("PARITY", locator.describe(), results)
        assert results[0] == results[1] and results[0]
    with runtime.config_scope(config(path, "agent")):
        fancy = resolve(
            scope,
            Locator(
                automation_id="FancyAutomationId",
                where=(("type:Is", "System.Windows.Controls.Button"),),
            ),
        )
        assert fancy.automation_id == "FancyAutomationId"
        assert not resolve_all(
            scope, Locator(automation_id="FancyXName", where=(("clr:Tag", "fancy"),))
        )
        assert not resolve_all(
            scope, Locator(where=(("type:Is", "WinTestKit.Fixture.PeerlessMarker"),))
        )
        assert click(fancy) == "invoke"
        assert resolve(scope, Locator(automation_id="ActionEffect")).name == "Clicked 1"
        assert click(fancy, mode="pattern") == "invoke"
        assert resolve(scope, Locator(automation_id="ActionEffect")).name == "Clicked 2"


def test_popup_parity(owned):
    scope, path = owned
    locator = Locator(
        automation_id="PopupContent", where=(("type:FullName", "System.Windows.Controls.Button"),)
    )
    results = []
    for mode in ("agent", "postfilter"):
        with runtime.config_scope(config(path, mode)):
            results.append([element.runtime_id for element in resolve_all(scope, locator)])
    print("PARITY popup", results)
    assert results[0] == results[1] and results[0]


def test_large_latency(owned):
    scope, path = owned
    with runtime.config_scope(config(path, "agent")):
        root = next(w for w in scope.app.top_level_windows() if w.automation_id == "LargeWindow")
        client = runtime.managed_client_for(
            root.process_id, deadline=time.monotonic() + 10, target_hwnd=root.native_window_handle
        )
        rid, hwnd = runtime.managed_element_identity(root)
        mapping = client.resolve(rid, hwnd, deadline=time.monotonic() + 10)
        assert mapping.object_ref is not None
        checks = []
        for label, target in (("unique", "Large1499"), ("missing", "NotPresent")):
            locator = Locator(
                automation_id=target, where=(("type:FullName", "WinTestKit.Fixture.LargeButton"),)
            )
            constraints = resolve_where(locator.where, locator.describe_link(), locator.taken())
            wire = replace(
                translate(locator, constraints, mapping.object_ref),
                scope=WireScope("object", mapping.object_ref),
            )
            samples = []
            outcomes = []
            for _ in range(30):
                start = time.perf_counter()
                try:
                    result = client.query_find(wire, timeout_ms=2000, deadline=time.monotonic() + 5)
                    elapsed = (time.perf_counter() - start) * 1000
                    outcomes.append("match")
                    client.release([result.match.object_id], deadline=time.monotonic() + 2)
                except InspectorError as error:
                    elapsed = (time.perf_counter() - start) * 1000
                    outcomes.append(error.code)
                samples.append(elapsed)
            median = statistics.median(samples)
            p95 = sorted(samples)[28]
            print(
                f"QUERY_FIND {label} median={median:.2f}ms p95={p95:.2f}ms outcomes={outcomes}",
                flush=True,
            )
            checks.append((median, set(outcomes), label))
        client.release([mapping.object_ref.object_id], deadline=time.monotonic() + 2)
        for median, outcomes, label in checks:
            assert outcomes == ({"match"} if label == "unique" else {"notFound"})
            assert median <= 100


def test_large_end_to_end(owned):
    scope, path = owned
    large = WindowLocator(automation_id="LargeWindow")
    unique = Locator(
        control_type="Button",
        where=(("clr:Group", "shared"), ("clr:Key", "Large 1499")),
        window=large,
    )
    root = next(w for w in scope.app.top_level_windows() if w.automation_id == "LargeWindow")
    measurements = {}
    for mode in ("postfilter", "agent"):
        with runtime.config_scope(config(path, mode)):
            for label, locator in (
                ("unique", unique),
                ("missing", replace(unique, where=(("clr:Group", "absent"),))),
            ):
                samples = []
                outcomes = []
                for _ in range(10 if mode == "agent" else 3):
                    start = time.perf_counter()
                    try:
                        outcomes.append(str(len(query_all(root, locator))))
                    except InspectorError as error:
                        outcomes.append(error.code)
                    samples.append((time.perf_counter() - start) * 1000)
                measurements[(mode, label)] = outcomes
                print(
                    f"QUERY_ALL {mode} {label} median={statistics.median(samples):.2f}ms p95={max(samples):.2f}ms outcomes={outcomes}",
                    flush=True,
                )

    assert measurements[("agent", "unique")] == ["1"] * 10
    assert measurements[("agent", "missing")] == ["0"] * 10


def test_large_cap(owned):
    scope, path = owned
    large = WindowLocator(automation_id="LargeWindow")
    shared = Locator(
        control_type="Button",
        where=(("type:FullName", "WinTestKit.Fixture.LargeButton"),),
        window=large,
    )
    unique = replace(shared, where=(*shared.where, ("clr:Key", "Large 1499")))
    with runtime.config_scope(config(path, "postfilter")):
        with pytest.raises(InspectorLimitError) as exc:
            resolve_all(scope, shared)
        assert exc.value.code == "limitExceeded"
    with runtime.config_scope(config(path, "agent")):
        assert resolve(scope, unique).automation_id == "Large1499"
        with pytest.raises(AmbiguousElementError):
            resolve(scope, shared)


def test_large_mapping_latency(owned):
    scope, path = owned
    locator = Locator(automation_id="Large100", window=WindowLocator(automation_id="LargeWindow"))
    root = next(w for w in scope.app.top_level_windows() if w.automation_id == "LargeWindow")
    assert win32.raise_window(root.native_window_handle)
    samples = []
    with runtime.config_scope(replace(config(path, "agent"), backend="auto")):
        for _ in range(10):
            start = time.perf_counter()
            element = resolve(scope, locator)
            assert not element.is_offscreen
            assert element.as_uia().runtime_id == element.runtime_id
            samples.append((time.perf_counter() - start) * 1000)
    print(
        f"WPF_RESOLVE_AS_UIA median={statistics.median(samples):.2f}ms p95={sorted(samples)[-1]:.2f}ms samples={samples}",
        flush=True,
    )


def test_auto_backend_waits_for_delayed_appearance(owned, monkeypatch):
    import ctypes
    import json
    import threading

    from wintestkit.expect import expect
    from wintestkit.inspector.client import InspectorClient
    from wintestkit.inspector.pipe import WindowsPipe, _api
    from wintestkit.model import Element, Page

    scope, path = owned

    class FixturePage(Page):
        dynamic = Element(automation_id="Dynamic73")

    page = FixturePage(scope.app)
    calls = []
    original = InspectorClient.wait_until

    def recorded(self, condition, *, timeout_ms, deadline):
        calls.append(condition.kind)
        return original(self, condition, timeout_ms=timeout_ms, deadline=deadline)

    monkeypatch.setattr(InspectorClient, "wait_until", recorded)

    def appear():
        time.sleep(0.5)
        handle = _api().CreateFileW(
            rf"\\.\pipe\WinTestKit.Fixture.{scope.app.pids[0]}",
            0xC0000000,
            0,
            None,
            3,
            0x40000000,
            None,
        )
        assert handle != ctypes.c_void_p(-1).value
        pipe = WindowsPipe(handle)
        try:
            deadline = time.monotonic() + 2
            pipe.write(
                json.dumps({"cmd": "scenario", "name": "addDynamic", "value": 73}).encode() + b"\n",
                deadline,
            )
            while pipe.read_exact(1, deadline) != b"\n":
                pass
        finally:
            pipe.close()

    with runtime.config_scope(replace(config(path, "agent"), backend="auto")):
        resolve(scope, Locator(automation_id="FixtureControl"))
        thread = threading.Thread(target=appear)
        thread.start()
        page.dynamic.wait_for("attached", timeout=10)
        thread.join()
        expect(page.dynamic, timeout=5).to_exist()
        expect(page.dynamic, timeout=5).to_be_enabled()
        assert "exists" in calls and "enabled" in calls


def test_auto_expect_missing_message_matches_uia(owned):
    from wintestkit.expect import expect
    from wintestkit.model import Element, Page

    scope, path = owned

    class FixturePage(Page):
        missing = Element(automation_id="NeverAppears")

    page = FixturePage(scope.app)
    messages = []
    for backend in ("uia", "auto"):
        with runtime.config_scope(replace(config(path, "agent"), backend=backend)):
            resolve(scope, Locator(automation_id="FixtureControl"))
            with pytest.raises(AssertionError) as error:
                expect(page.missing, timeout=2).to_exist()
            messages.append(str(error.value))
    assert messages[0] == messages[1]

    from wintestkit.errors import LocatorError

    diagnostics = []
    for backend in ("uia", "auto"):
        with runtime.config_scope(replace(config(path, "agent"), backend=backend)):
            with pytest.raises(LocatorError) as error:
                page.missing.wait_for("attached", timeout=2)
            diagnostics.append(str(error.value))
    assert diagnostics[0] == diagnostics[1]


@pytest.mark.parametrize("method", ["to_exist", "to_be_visible"])
def test_negated_expect_present_message_matches_uia(owned, method):
    from wintestkit.expect import expect
    from wintestkit.model import Element, Page

    scope, path = owned

    class FixturePage(Page):
        present = Element(automation_id="FixtureControl")

    page = FixturePage(scope.app)
    messages = []
    for backend in ("uia", "auto"):
        with runtime.config_scope(replace(config(path, "agent"), backend=backend)):
            resolve(scope, Locator(automation_id="FixtureControl"))
            with pytest.raises(AssertionError) as error:
                getattr(expect(page.present, timeout=1).not_, method)()
            messages.append(str(error.value))
    assert messages[0] == messages[1]
