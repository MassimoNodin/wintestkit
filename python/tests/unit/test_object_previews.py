"""Paired preview safety, publication, test-call gating, and coordinate regressions."""

import hashlib
import json
import os
import subprocess
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from wintestkit import model, object_previews, runtime
from wintestkit.config import load_config
from wintestkit.engine.locator import ItemSelector
from wintestkit.errors import AmbiguousElementError, ElementTypeError
from wintestkit.model import BoundControl, BoundElement, Element, Elements
from wintestkit.pytest_plugin import _Controller
from wintestkit.uia import screenshot, win32
from wintestkit.uia.element import Rect


class Declaring:
    submit = Element(automation_id="Submit")
    rows = Elements(control_type="Button")


class Inherited(Declaring):
    pass


@pytest.fixture
def preview(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    runtime.reset()
    monkeypatch.delenv("WTK_OBJECT_PREVIEWS", raising=False)
    runtime.set_config(load_config(tmp_path))
    source = tmp_path / "Pages" / "Shared.py"
    monkeypatch.setattr(Declaring.submit, "source", (str(source), 7))
    monkeypatch.setattr(Declaring.rows, "source", (str(source), 8))
    bounds = Rect(-88, 212, 4, 3)
    window_bounds = Rect(-90, 210, 12, 10)
    window = SimpleNamespace(
        rect=window_bounds,
        process_id=123,
        is_offscreen=False,
        native_window_handle=42,
        automation_id="Main",
        class_name="Window",
        name="Example",
        get_property=lambda name: False,
    )
    element = SimpleNamespace(
        rect=bounds,
        process_id=123,
        is_offscreen=False,
        is_enabled=True,
        native_window_handle=0,
        automation_id="Submit",
        class_name="Button",
        name="Submit",
        get_property=lambda name: False,
        parent=lambda: window,
    )
    element.as_live = lambda: element
    element.iter_children = lambda: iter(())
    window.as_live = lambda: window
    window.iter_children = lambda: iter((element,))
    bound = BoundElement(SimpleNamespace(), Inherited.submit)
    calls = []

    def frame(hwnd, expected_pid):
        calls.append((hwnd, expected_pid, threading.get_ident()))
        return window_bounds, bytes((17, 37, 57)) * (window_bounds.width * window_bounds.height)

    monkeypatch.setattr(win32, "root_window", lambda hwnd: hwnd)
    monkeypatch.setattr(win32, "window_pid", lambda hwnd: 123)
    monkeypatch.setattr(win32, "virtual_screen_rect", lambda: Rect(-200, 0, 1000, 1000))
    monkeypatch.setattr(screenshot, "capture_window_frame", frame)
    monkeypatch.setattr(screenshot, "capture_element", Mock(side_effect=AssertionError("desktop")))
    monkeypatch.setattr(screenshot, "capture_screen", Mock(side_effect=AssertionError("desktop")))
    monkeypatch.setattr(model, "_scope", lambda page: None)
    monkeypatch.setattr(model, "_element_locator", lambda page, definition: definition.locator())
    monkeypatch.setattr(model, "resolve", lambda scope, locator: element)
    definition_id = "Pages/Shared.py::Declaring.submit"
    directory = (
        tmp_path / "object-previews" / hashlib.sha256(definition_id.encode("utf-8")).hexdigest()
    )
    yield SimpleNamespace(
        root=tmp_path,
        bound=bound,
        element=element,
        window=window,
        calls=calls,
        directory=directory,
        definition_id=definition_id,
    )
    runtime.reset()


def capture(preview):
    with runtime.object_preview_test_context():
        assert preview.bound.resolve_once() is preview.element
    manifest = preview.directory / "manifest.json"
    return json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else None


def test_pair_contract_clean_crop_and_declaring_identity(preview, monkeypatch):
    monkeypatch.setattr(model, "_qualified_name", lambda page, definition: "Home.address.submit")
    manifest = capture(preview)
    assert manifest["schemaVersion"] == 1
    assert manifest["definitionId"] == preview.definition_id
    assert manifest["context"] == "Home.address.submit"
    assert len(manifest["locatorFingerprint"]) == 64
    assert "Submit" not in json.dumps(manifest)
    assert "Example" not in json.dumps(manifest)
    assert manifest["capturedAt"].endswith("+00:00")
    assert manifest["width"] == 4 and manifest["height"] == 3
    assert preview.calls == [(42, 123, threading.get_ident())]
    for key in ("crop", "window"):
        assert (
            manifest[key] == f"{manifest['captureId']}.{key if key == 'window' else 'element'}.webp"
        )
    with Image.open(preview.directory / manifest["crop"]) as crop:
        assert crop.format == "WEBP"
        assert crop.size == (4, 3)
        assert crop.convert("RGB").tobytes() == bytes((17, 37, 57)) * 12
    with Image.open(preview.directory / manifest["window"]) as window:
        assert window.size == (12, 10)
        assert window.convert("RGB").getpixel((2, 2)) == (255, 0, 0)
        assert window.convert("RGB").getpixel((0, 0)) == (17, 37, 57)
    assert not (preview.root / "wtk-report").exists()
    assert not list(preview.directory.glob("*.png"))


def test_only_explicit_call_context_captures(preview):
    runtime.begin_test("setup is not the call phase")
    preview.bound.resolve_once()
    object_previews.capture_bound(preview.bound, preview.element)
    assert preview.calls == []
    with runtime.object_preview_test_context():
        with runtime.config_scope(runtime.get_config()):
            preview.bound.resolve_once()
        worker = threading.Thread(target=preview.bound.resolve_once)
        worker.start()
        worker.join()
        assert preview.calls == []
        preview.bound.resolve_once()
    preview.bound.resolve_once()
    assert len(preview.calls) == 1


def test_pytest_call_wrapper_restores_context_on_failure(preview):
    hook = _Controller.pytest_runtest_call(SimpleNamespace(report_enabled=True), SimpleNamespace())
    assert not runtime.object_previews_active()
    next(hook)
    assert runtime.object_previews_active()
    with pytest.raises(RuntimeError, match="test failed"):
        hook.throw(RuntimeError("test failed"))
    assert not runtime.object_previews_active()


def test_no_report_never_enters_preview_context_or_captures(preview, monkeypatch):
    monkeypatch.setattr(
        runtime,
        "object_preview_test_context",
        lambda: pytest.fail("no-report must not authorize preview capture"),
    )
    monkeypatch.setattr(
        object_previews,
        "_capture_bound",
        lambda *args: pytest.fail("no-report must not capture object previews"),
    )
    assert runtime.get_config().object_previews
    hook = _Controller.pytest_runtest_call(SimpleNamespace(report_enabled=False), SimpleNamespace())
    next(hook)
    assert not runtime.object_previews_active()
    preview.bound.resolve_once()
    object_previews.capture_bound(preview.bound, preview.element)
    with pytest.raises(StopIteration):
        next(hook)
    assert preview.calls == []


def test_setting_disables_capture_even_in_call_context(preview):
    runtime.set_config(replace(runtime.get_config(), object_previews=False))
    assert capture(preview) is None
    assert preview.calls == []


def test_capture_precedes_action_and_overlay(preview, monkeypatch):
    order = []
    monkeypatch.setattr(
        object_previews, "capture_bound", lambda bound, element: order.append("capture")
    )
    monkeypatch.setattr(
        BoundControl, "_maybe_highlight", lambda bound, element: order.append("overlay")
    )
    with runtime.object_preview_test_context():
        preview.bound.perform(0, lambda element: order.append("action"))
    assert order == ["capture", "overlay", "action"]


@pytest.mark.parametrize("failure", [AmbiguousElementError, ElementTypeError])
def test_resolution_and_validation_failures_do_not_capture(preview, monkeypatch, failure):
    def fail(*args):
        if failure is AmbiguousElementError:
            raise failure(SimpleNamespace(message="not a validated unique element"))
        raise failure("not a validated unique element")

    if failure is AmbiguousElementError:
        monkeypatch.setattr(model, "resolve", fail)
    else:
        monkeypatch.setattr(BoundControl, "check_type", fail)
    with runtime.object_preview_test_context(), pytest.raises(failure):
        preview.bound.resolve_once()
    assert preview.calls == []


def test_collection_item_does_not_capture(preview):
    bound = BoundElement(SimpleNamespace(), Declaring.rows)
    with runtime.object_preview_test_context():
        assert bound.resolve_once() is preview.element
    assert preview.calls == []


def test_preview_hook_failure_never_fails_resolution(preview, monkeypatch):
    monkeypatch.setattr(object_previews, "capture_bound", Mock(side_effect=OSError("disk full")))
    with runtime.object_preview_test_context():
        assert preview.bound.resolve_once() is preview.element


@pytest.mark.parametrize("reason", ["anonymous", "external-source", "password-locator"])
def test_undeclared_external_and_sensitive_locators_are_not_captured(preview, monkeypatch, reason):
    if reason == "anonymous":
        monkeypatch.setattr(Declaring.submit, "owner", None)
    elif reason == "external-source":
        monkeypatch.setattr(
            Declaring.submit, "source", (str(preview.root.parent / "external.py"), 1)
        )
    else:
        preview.bound = preview.bound._derive(model.Locator(class_name="PasswordBox"))
    assert capture(preview) is None
    assert preview.calls == []


@pytest.mark.parametrize(
    "reason",
    [
        "password",
        "sensitive",
        "hidden",
        "partial",
        "missing",
        "outside-screen",
        "wrong-process",
    ],
)
def test_unsafe_elements_never_capture(preview, reason):
    if reason == "password":
        preview.element.get_property = lambda name: True
    elif reason == "sensitive":
        preview.element.automation_id = "AccessToken"
    elif reason == "hidden":
        preview.element.is_offscreen = True
    elif reason == "partial":
        preview.window.rect = Rect(-86, 210, 12, 10)
    elif reason == "missing":
        preview.element.rect = None
    elif reason == "outside-screen":
        preview.element.rect = Rect(-201, 212, 4, 3)
    else:
        preview.window.process_id = 999
    assert capture(preview) is None
    assert preview.calls == []


@pytest.mark.parametrize("reason", ["unavailable", "partial", "moved", "exception", "black"])
def test_untrustworthy_capture_is_best_effort(preview, monkeypatch, reason):
    def frame(*args):
        if reason == "exception":
            raise OSError("renderer failed")
        if reason == "unavailable":
            return None
        if reason == "moved":
            preview.element.rect = Rect(-87, 212, 4, 3)
        origin = -87 if reason == "partial" else -90
        pixels = bytes(360) if reason == "black" else bytes((17, 37, 57)) * 120
        return Rect(origin, 210, 12, 10), pixels

    monkeypatch.setattr(screenshot, "capture_window_frame", frame)
    assert capture(preview) is None


def test_failed_publish_keeps_previous_pair(preview, monkeypatch):
    first = capture(preview)
    original = object_previews._replace_manifest

    def fail_manifest(path, target):
        if path.suffix == ".tmp":
            raise OSError("cannot publish")
        return original(path, target)

    monkeypatch.setattr(object_previews, "_replace_manifest", fail_manifest)
    assert capture(preview) == first
    assert {path.name for path in preview.directory.glob("*.webp")} == {
        first["crop"],
        first["window"],
    }
    assert not list(preview.directory.glob("*.tmp"))


def test_pair_is_complete_before_atomic_manifest_replacement(preview, monkeypatch):
    original = object_previews._replace_manifest
    observed = []

    def replace_manifest(path, target):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        assert (path.parent / manifest["crop"]).is_file()
        assert (path.parent / manifest["window"]).is_file()
        observed.append(manifest["captureId"])
        return original(path, target)

    monkeypatch.setattr(object_previews, "_replace_manifest", replace_manifest)
    first = capture(preview)
    second = capture(preview)
    assert observed == [first["captureId"], second["captureId"]]
    assert first["captureId"] != second["captureId"]
    assert (preview.directory / first["crop"]).exists()
    assert (preview.directory / first["window"]).exists()


def test_busy_definition_skips_without_capturing(preview):
    preview.directory.mkdir(parents=True)
    with object_previews._publication_lock(preview.directory) as acquired:
        assert acquired
        assert capture(preview) is None
    assert preview.calls == []


def test_old_current_pair_gets_reader_grace_when_superseded(preview):
    first = capture(preview)
    old = time.time() - object_previews._GRACE_SECONDS - 100
    for name in (first["crop"], first["window"]):
        os.utime(preview.directory / name, (old, old))
    second = capture(preview)
    assert second["captureId"] != first["captureId"]
    for name in (first["crop"], first["window"]):
        assert (preview.directory / name).stat().st_mtime > old + 100


def test_cleanup_retains_recent_staging_and_current_revision(preview):
    manifest = capture(preview)
    stale = preview.directory / f"{'a' * 32}.element.webp"
    staging = preview.directory / f"{'b' * 32}.window.webp"
    temporary = preview.directory / f"{'b' * 32}.manifest.tmp"
    for path in (stale, staging, temporary):
        path.write_bytes(b"staging")
    old = time.time() - object_previews._GRACE_SECONDS - 1
    os.utime(stale, (old, old))
    for name in (manifest["crop"], manifest["window"]):
        os.utime(preview.directory / name, (old, old))
    object_previews._cleanup(preview.directory, {manifest["crop"], manifest["window"]})
    assert not stale.exists()
    assert staging.exists() and temporary.exists()
    assert (preview.directory / manifest["crop"]).exists()
    assert (preview.directory / manifest["window"]).exists()


@pytest.mark.parametrize("location", ["sibling", "descendant"])
@pytest.mark.parametrize("kind", ["password", "sensitive", "unknown"])
def test_sensitive_window_content_prevents_pair_capture(preview, location, kind):
    child = SimpleNamespace(**vars(preview.element))
    child.as_live = lambda: child
    child.automation_id = "AccessToken" if kind == "sensitive" else "OtherField"
    child.get_property = lambda name: None if kind == "unknown" else kind == "password"
    if location == "sibling":
        preview.window.iter_children = lambda: iter((preview.element, child))
    else:
        preview.element.iter_children = lambda: iter((child,))
    assert capture(preview) is None
    assert preview.calls == []


@pytest.mark.parametrize("limit", ["nodes", "depth", "time", "enumeration"])
def test_incomplete_privacy_scan_prevents_capture(preview, monkeypatch, limit):
    if limit == "nodes":
        monkeypatch.setattr(object_previews, "_SCAN_NODES", 1)
    elif limit == "depth":
        monkeypatch.setattr(object_previews, "_SCAN_DEPTH", 0)
    elif limit == "time":
        monkeypatch.setattr(object_previews, "_SCAN_SECONDS", 0)
    else:
        preview.element.iter_children = Mock(side_effect=OSError("stale child"))
    assert capture(preview) is None
    assert preview.calls == []


def test_content_turning_sensitive_during_capture_keeps_previous_pair(preview, monkeypatch):
    first = capture(preview)
    frame = screenshot.capture_window_frame

    def became_sensitive(*args):
        pixels = frame(*args)
        preview.element.get_property = lambda name: True
        return pixels

    monkeypatch.setattr(screenshot, "capture_window_frame", became_sensitive)
    assert capture(preview) == first
    assert len(preview.calls) == 2


def test_derived_grid_item_does_not_replace_declaring_preview(preview):
    first = capture(preview)
    preview.bound = preview.bound._derive(
        preview.bound.locator.with_item(ItemSelector("cell", 0, 0))
    )
    assert capture(preview) == first
    assert len(preview.calls) == 1


@pytest.mark.skipif(os.name != "nt", reason="Windows junction protection")
@pytest.mark.parametrize("component", ["store", "definition"])
def test_redirected_output_directory_never_writes_external_files(preview, component):
    external = preview.root.parent / (preview.root.name + "-external")
    external.mkdir()
    link = preview.directory.parent if component == "store" else preview.directory
    link.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(external)],
        capture_output=True,
        check=False,
    )
    if result.returncode:
        pytest.skip("junction creation unavailable")
    try:
        assert capture(preview) is None
        assert list(external.iterdir()) == []
        assert preview.calls == []
    finally:
        link.rmdir()


@pytest.mark.parametrize("filename", [".lock", "manifest.json"])
def test_hardlinked_output_files_are_not_modified(preview, filename):
    preview.directory.mkdir(parents=True)
    external = preview.root.parent / (preview.root.name + "-external.txt")
    external.write_text("private", encoding="utf-8")
    (preview.directory / filename).hardlink_to(external)
    with runtime.object_preview_test_context():
        assert preview.bound.resolve_once() is preview.element
    assert external.read_text(encoding="utf-8") == "private"
    assert not list(preview.directory.glob("*.webp"))


def test_output_directory_cannot_be_replaced_during_publication(preview):
    with (
        object_previews._output_directory(preview.root, preview.directory.name),
        pytest.raises(OSError),
    ):
        preview.directory.parent.rename(preview.root / "moved-previews")


def test_manifest_publication_supports_non_bmp_project_paths(tmp_path):
    directory = tmp_path / "capture-\U0001f9ea"
    directory.mkdir()
    temporary = directory / "next.tmp"
    manifest = directory / "manifest.json"
    temporary.write_text("new", encoding="utf-8")
    manifest.write_text("old", encoding="utf-8")
    object_previews._replace_manifest(temporary, manifest)
    assert manifest.read_text(encoding="utf-8") == "new"
    assert not temporary.exists()


def test_manifest_publication_supports_long_project_paths(tmp_path):
    padding = max(75, 260 - len(str(tmp_path)))
    directory = tmp_path.joinpath("part-" + "a" * padding, "part-" + "b" * 75)
    directory.mkdir(parents=True)
    temporary = directory / "next.tmp"
    manifest = directory / "manifest.json"
    assert len(str(manifest)) > 260
    temporary.write_text("new", encoding="utf-8")
    manifest.write_text("old", encoding="utf-8")
    object_previews._replace_manifest(temporary, manifest)
    assert manifest.read_text(encoding="utf-8") == "new"
    assert not temporary.exists()


def test_cleanup_preserves_unowned_filenames(preview):
    manifest = capture(preview)
    custom = preview.directory / "customer.webp"
    custom.write_bytes(b"private")
    old = time.time() - object_previews._GRACE_SECONDS - 100
    os.utime(custom, (old, old))
    object_previews._cleanup(preview.directory, {manifest["crop"], manifest["window"]})
    assert custom.read_bytes() == b"private"


def test_window_frame_keeps_dwm_and_black_trim_offsets(monkeypatch):
    def get_rect(hwnd, pointer):
        pointer._obj.left, pointer._obj.top = -100, 200
        pointer._obj.right, pointer._obj.bottom = -80, 220
        return 1

    monkeypatch.setattr(win32.user32, "GetWindowRect", get_rect)
    monkeypatch.setattr(win32, "window_pid", lambda hwnd: 123)
    monkeypatch.setattr(win32, "IsWindowVisible", lambda hwnd: True)
    monkeypatch.setattr(win32, "IsIconic", lambda hwnd: False)
    monkeypatch.setattr(screenshot, "_visible_frame", lambda hwnd, rect: Rect(2, 3, 6, 5))
    grey, black = bytes((20, 30, 40)), bytes(3)
    pixels = black * 6 + (black + grey * 4 + black) * 3 + black * 6
    calls = []

    def capture_pixels(rect, hwnd, crop):
        calls.append((rect, hwnd, crop))
        return 6, 5, pixels

    monkeypatch.setattr(screenshot, "_capture_pixels", capture_pixels)
    assert screenshot.capture_window_frame(42, 123) == (Rect(-97, 204, 4, 3), grey * 12)
    assert calls == [(Rect(-100, 200, 20, 20), 42, Rect(2, 3, 6, 5))]
