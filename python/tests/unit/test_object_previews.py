"""Paired preview safety, publication, intentional checks, and coordinate regressions."""

import contextlib
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

from wintestkit import model, object_previews, runtime, targets
from wintestkit.config import load_config
from wintestkit.engine.diagnose import Diagnostic
from wintestkit.engine.locator import ItemSelector
from wintestkit.errors import AmbiguousElementError, ElementNotFoundError, ElementTypeError
from wintestkit.model import (
    BoundControl,
    BoundElement,
    BoundElements,
    BoundWindow,
    Element,
    Elements,
    Window,
)
from wintestkit.pytest_plugin import _Controller
from wintestkit.uia import screenshot, win32
from wintestkit.uia.element import Rect


class Declaring:
    submit = Element(automation_id="Submit")
    rows = Elements(control_type="Button")
    main = Window(title="Example")


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
    monkeypatch.setattr(Declaring.main, "source", (str(source), 9))
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
    element.info = lambda: SimpleNamespace()
    element.iter_children = lambda: iter(())
    window.as_live = lambda: window
    window.info = lambda: SimpleNamespace()
    window.iter_children = lambda: iter((element,))
    bound = BoundElement(SimpleNamespace(), Inherited.submit)
    calls = []

    def frame(hwnd, expected_pid):
        calls.append((hwnd, expected_pid, threading.get_ident()))
        return window_bounds, bytes((18, 37, 57)) + bytes((17, 37, 57)) * (
            window_bounds.width * window_bounds.height - 1
        )

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
    assert targets.resolve_bound(preview.bound, 0, capture=True).uia is preview.element
    manifest = preview.directory / "manifest.json"
    return json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else None


def test_pair_contract_clean_crop_and_declaring_identity(preview, monkeypatch):
    monkeypatch.setattr(model, "_qualified_name", lambda page, definition: "Home.address.submit")
    manifest = capture(preview)
    assert manifest["schemaVersion"] == 2
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
        assert window.convert("RGB").getpixel((0, 0)) == (18, 37, 57)
    assert not (preview.root / "wtk-report").exists()
    assert not list(preview.directory.glob("*.png"))


@pytest.mark.parametrize("test_active", [False, True])
def test_resolution_and_test_actions_never_capture(preview, monkeypatch, test_active):
    capture_mock = Mock()
    monkeypatch.setattr(object_previews, "capture_bound", capture_mock)
    if test_active:
        runtime.begin_test("ordinary test")
    with runtime.config_scope(runtime.get_config()):
        preview.bound.resolve_once()
    worker = threading.Thread(target=preview.bound.resolve_once)
    worker.start()
    worker.join()
    preview.bound.perform(0, lambda element: None)
    capture_mock.assert_not_called()
    assert preview.calls == []


@pytest.mark.parametrize("valid_host", [True, False])
def test_hosted_app_capture_requires_verified_frame(preview, monkeypatch, valid_host):
    host = SimpleNamespace(**vars(preview.window))
    host.process_id = 456
    host.native_window_handle = 84
    host.class_name = "ApplicationFrameWindow"
    host.as_live = lambda: host
    host.iter_children = lambda: iter((preview.window,))
    preview.window.parent = lambda: host
    monkeypatch.setattr(win32, "root_window", lambda hwnd: 84)
    monkeypatch.setattr(win32, "window_pid", lambda hwnd: 456 if hwnd == 84 else 123)
    monkeypatch.setattr(win32, "window_class_name", lambda hwnd: "ApplicationFrameWindow")
    monkeypatch.setattr(win32, "top_level_windows", lambda pids: [84] if valid_host else [])
    manifest = capture(preview)
    if valid_host:
        assert manifest is not None
        assert preview.calls[0][:2] == (84, 456)
    else:
        assert manifest is None
        assert preview.calls == []


@pytest.mark.parametrize("sensitive", [False, True])
def test_unbounded_container_is_scanned_with_its_children(preview, sensitive):
    container = SimpleNamespace(**vars(preview.element))
    container.rect = None
    container.automation_id = "AccessToken" if sensitive else "Container"
    container.as_live = lambda: container
    container.iter_children = lambda: iter((preview.element,))
    preview.window.iter_children = lambda: iter((container,))
    assert capture(preview) is not None


def test_pytest_has_no_capture_call_wrapper():
    assert not hasattr(_Controller, "pytest_runtest_call")


def test_setting_disables_explicit_capture(preview, monkeypatch):
    runtime.set_config(replace(runtime.get_config(), object_previews=False))
    capture_mock = Mock()
    monkeypatch.setattr(object_previews, "capture_bound", capture_mock)
    assert capture(preview) is None
    capture_mock.assert_not_called()
    assert preview.calls == []


@pytest.mark.parametrize("failure", [AmbiguousElementError, ElementNotFoundError, ElementTypeError])
def test_resolution_and_validation_failures_do_not_capture(preview, monkeypatch, failure):
    def fail(*args):
        if failure is not ElementTypeError:
            raise failure(
                Diagnostic("not_found", "not a validated unique element", "Button", "Demo", 0)
            )
        raise failure("not a validated unique element")

    if failure is not ElementTypeError:
        monkeypatch.setattr(model, "resolve", fail)
    else:
        monkeypatch.setattr(BoundControl, "check_type", fail)
    result = targets.resolve_bound(preview.bound, 0, capture=True)
    assert result.status in ("ambiguous", "not_found", "error")
    assert preview.calls == []


def test_collection_item_does_not_capture(preview):
    bound = BoundElement(SimpleNamespace(), Declaring.rows)
    assert targets.resolve_bound(bound, 0, capture=True).status == "found"
    assert preview.calls == []


def definition_directory(preview, qualname):
    definition_id = f"Pages/Shared.py::{qualname}"
    return preview.root / "object-previews" / hashlib.sha256(definition_id.encode()).hexdigest()


def check_window(preview, monkeypatch):
    monkeypatch.setattr(model, "resolve_window", lambda app, locator: preview.window)
    bound = BoundWindow(SimpleNamespace(app=SimpleNamespace(pids=[123])), Declaring.main)
    assert targets.resolve_bound(bound, 0, capture=True).uia is preview.window
    directory = definition_directory(preview, "Declaring.main")
    manifest = directory / "manifest.json"
    return directory, json.loads(manifest.read_text("utf-8")) if manifest.exists() else None


def test_window_check_saves_the_whole_window_twice_without_an_outline(preview, monkeypatch):
    directory, manifest = check_window(preview, monkeypatch)
    assert manifest["schemaVersion"] == 2
    assert manifest["definitionId"] == "Pages/Shared.py::Declaring.main"
    assert (manifest["width"], manifest["height"]) == (12, 10)
    assert "matchCount" not in manifest
    assert preview.calls == [(42, 123, threading.get_ident())]
    expected = bytes((18, 37, 57)) + bytes((17, 37, 57)) * 119
    for key in ("crop", "window"):
        with Image.open(directory / manifest[key]) as image:
            assert image.size == (12, 10)
            assert image.convert("RGB").tobytes() == expected
    assert not (directory / "status.json").exists()


@pytest.mark.parametrize("kind", ["password", "sensitive"])
def test_window_check_blacks_out_sensitive_controls_in_both_images(preview, monkeypatch, kind):
    preview.element.automation_id = "AccessToken" if kind == "sensitive" else "Other"
    preview.element.get_property = lambda name: kind == "password"
    directory, manifest = check_window(preview, monkeypatch)
    assert manifest is not None
    for key in ("crop", "window"):
        with Image.open(directory / manifest[key]) as image:
            rgb = image.convert("RGB")
            assert rgb.getpixel((3, 3)) == (0, 0, 0)  # inside the control (2, 2, 4x3)
            assert rgb.getpixel((0, 0)) == (18, 37, 57)
            assert rgb.getpixel((8, 8)) == (17, 37, 57)


def test_window_check_with_unsafe_content_saves_nothing_and_says_why(preview, monkeypatch):
    preview.element.get_property = lambda name: None
    directory, manifest = check_window(preview, monkeypatch)
    assert manifest is None
    status = json.loads((directory / "status.json").read_text("utf-8"))
    assert status["reason"] == "could not determine whether an element is a password field"
    assert status["definitionId"] == "Pages/Shared.py::Declaring.main"


def test_window_check_off_screen_reports_the_reason(preview, monkeypatch):
    monkeypatch.setattr(win32, "virtual_screen_rect", lambda: Rect(0, 0, 5, 5))
    directory, manifest = check_window(preview, monkeypatch)
    assert manifest is None
    assert "no on-screen rectangle" in (directory / "status.json").read_text("utf-8")


def test_window_check_with_a_sensitive_title_locator_is_skipped(preview, monkeypatch):
    monkeypatch.setattr(Declaring.main, "locator", Window(title="Enter password").locator)
    directory, manifest = check_window(preview, monkeypatch)
    assert manifest is None
    assert "locator looks sensitive" in (directory / "status.json").read_text("utf-8")


def check_collection(preview, monkeypatch, matches=3):
    monkeypatch.setattr(model, "resolve_all", lambda scope, locator: [preview.element] * matches)
    bound = BoundElements(SimpleNamespace(), Declaring.rows)
    assert targets.resolve_bound(bound, 0, capture=True).uia is preview.element
    directory = definition_directory(preview, "Declaring.rows")
    manifest = directory / "manifest.json"
    return directory, json.loads(manifest.read_text("utf-8")) if manifest.exists() else None


def test_collection_check_saves_the_first_match_with_its_count(preview, monkeypatch):
    directory, manifest = check_collection(preview, monkeypatch)
    assert manifest["definitionId"] == "Pages/Shared.py::Declaring.rows"
    assert manifest["matchCount"] == 3
    assert (manifest["width"], manifest["height"]) == (4, 3)
    with Image.open(directory / manifest["crop"]) as crop:
        assert crop.size == (4, 3)
    with Image.open(directory / manifest["window"]) as window:
        assert window.size == (12, 10)
        assert window.convert("RGB").getpixel((2, 2)) == (255, 0, 0)  # the outline


def test_collection_check_of_a_single_match_records_one(preview, monkeypatch):
    _, manifest = check_collection(preview, monkeypatch, matches=1)
    assert manifest["matchCount"] == 1


def test_collection_check_with_a_password_match_says_why(preview, monkeypatch):
    preview.element.get_property = lambda name: True
    directory, manifest = check_collection(preview, monkeypatch)
    assert manifest is None
    assert "element contains a password field" in (directory / "status.json").read_text("utf-8")


def test_preview_failure_never_fails_check(preview, monkeypatch):
    capture_mock = Mock(side_effect=OSError("disk full"))
    monkeypatch.setattr(object_previews, "capture_bound", capture_mock)
    assert targets.resolve_bound(preview.bound, 0, capture=True).status == "found"
    capture_mock.assert_called_once_with(preview.bound, preview.element)


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
        pixels = (
            bytes(360) if reason == "black" else bytes((18, 37, 57)) + bytes((17, 37, 57)) * 119
        )
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
    assert not (preview.directory / first["crop"]).exists()
    assert not (preview.directory / first["window"]).exists()


def test_busy_definition_skips_without_capturing(preview):
    preview.directory.mkdir(parents=True)
    with object_previews._publication_lock(preview.directory) as acquired:
        assert acquired
        assert capture(preview) is None
    assert preview.calls == []


def test_new_capture_replaces_the_previous_pair_instead_of_piling_up(preview):
    first = capture(preview)
    second = capture(preview)
    third = capture(preview)
    assert len({first["captureId"], second["captureId"], third["captureId"]}) == 3
    images = sorted(path.name for path in preview.directory.glob("*.webp"))
    assert images == sorted([third["crop"], third["window"]])


def test_superseded_image_held_open_by_a_reader_is_removed_later(preview, monkeypatch):
    first = capture(preview)
    real = object_previews._pinned
    held = preview.directory / first["crop"]

    @contextlib.contextmanager
    def pinned(path, *, directory=False):
        if path == held:
            raise PermissionError("in use")
        with real(path, directory=directory) as handle:
            yield handle

    monkeypatch.setattr(object_previews, "_pinned", pinned)
    second = capture(preview)
    monkeypatch.undo()
    assert held.exists()
    assert not (preview.directory / first["window"]).exists()
    old = time.time() - object_previews._GRACE_SECONDS - 1
    os.utime(held, (old, old))
    object_previews._cleanup(preview.directory, {second["crop"], second["window"]})
    assert not held.exists()


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
    result = capture(preview)
    if location == "descendant":
        assert result is None
    else:
        assert result is not None
        with Image.open(preview.directory / result["window"]) as image:
            if kind != "unknown":
                assert image.convert("RGB").getpixel((3, 3)) == (0, 0, 0)


@pytest.mark.parametrize("limit", ["nodes", "depth", "time", "enumeration"])
def test_incomplete_privacy_scan_prevents_capture(preview, monkeypatch, limit):
    if limit == "nodes":
        monkeypatch.setattr(object_previews, "_WINDOW_SCAN_NODES", 1)
    elif limit == "depth":
        monkeypatch.setattr(object_previews, "_SCAN_DEPTH", 0)
    elif limit == "time":
        monkeypatch.setattr(object_previews, "_SCAN_SECONDS", 0)
    else:
        preview.element.iter_children = Mock(side_effect=OSError("stale child"))
    result = capture(preview)
    if limit in ("nodes", "depth"):
        assert result is not None
        assert "window context not saved" in (preview.directory / "status.json").read_text()
    else:
        assert result is None


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
    assert targets.resolve_bound(preview.bound, 0, capture=True).uia is preview.element
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


@pytest.mark.parametrize("mapped", [False, True])
def test_wpf_capture_uses_agent_bounds_and_fails_closed_without_peer(preview, monkeypatch, mapped):
    from wintestkit.backends.element import WpfElement
    from wintestkit.errors import NoUiaPeerError

    node = object.__new__(WpfElement)
    bounds = Rect(-87, 213, 2, 2)
    monkeypatch.setattr(WpfElement, "as_live", lambda self: self)
    monkeypatch.setattr(WpfElement, "rect", property(lambda self: bounds))
    monkeypatch.setattr(WpfElement, "process_id", property(lambda self: 123))
    monkeypatch.setattr(WpfElement, "is_offscreen", property(lambda self: False))
    monkeypatch.setattr(WpfElement, "automation_id", property(lambda self: "Panel"))
    monkeypatch.setattr(WpfElement, "class_name", property(lambda self: "DockPanel"))
    monkeypatch.setattr(WpfElement, "name", property(lambda self: ""))
    monkeypatch.setattr(WpfElement, "state", lambda self: SimpleNamespace(window_handle=42))
    monkeypatch.setattr("wintestkit.uia.element.from_handle", lambda hwnd: preview.window)

    def as_uia(self):
        if not mapped:
            raise NoUiaPeerError("no peer")
        return preview.element

    monkeypatch.setattr(WpfElement, "as_uia", as_uia)
    monkeypatch.setattr(object_previews, "_wpf_passwords", lambda root: [])
    monkeypatch.setattr(object_previews, "_wpf_window_redactions", lambda *args: [])
    object_previews.capture_bound(preview.bound, node)
    manifest = preview.directory / "manifest.json"
    assert manifest.exists()
    if mapped:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        assert (data["width"], data["height"]) == (2, 2)
    else:
        assert preview.calls


def test_status_logged_and_cleared_after_success(preview, caplog):
    import logging

    preview.element.rect = None
    with caplog.at_level(logging.INFO, logger="wintestkit.object_previews"):
        assert capture(preview) is None
    status = json.loads((preview.directory / "status.json").read_text())
    assert status["reason"] == "element has no on-screen rectangle"
    assert "element has no on-screen rectangle" in caplog.text
    preview.element.rect = Rect(-88, 212, 4, 3)
    assert capture(preview) is not None
    assert not (preview.directory / "status.json").exists()


def test_large_window_saves_crop_and_ancestor_name_is_allowed(preview):
    preview.window.name = "Token settings"
    preview.window.iter_children = lambda: iter([preview.element] * 5000)
    result = capture(preview)
    assert result is not None
    assert (
        "window context not saved: too many elements to check"
        in (preview.directory / "status.json").read_text()
    )
    with Image.open(preview.directory / result["window"]) as image:
        assert image.size == (4, 3)


@pytest.mark.parametrize(
    "reason",
    [
        "object previews are disabled",
        "definition is a collection",
        "definition has no declared source",
        "definition refers to a collection item",
        "locator looks sensitive",
        "element has no on-screen rectangle",
        "element has no owned on-screen window",
        "element looks sensitive",
        "element contains a password field",
        "too many elements to check",
        "could not determine whether an element is a password field",
        "could not check the element's contents for password fields: limit exceeded",
        "another capture is publishing",
        "window capture failed",
        "element is outside the window or the window is blank",
        "element or window changed during capture",
        "capture failed: unexpected error",
    ],
)
def test_each_skip_reason_is_persisted_and_logged(preview, monkeypatch, caplog, reason):
    import logging

    def skip(bound, element):
        raise object_previews._SkipPreview(reason)

    monkeypatch.setattr(object_previews, "_capture_bound", skip)
    with caplog.at_level(logging.INFO, logger="wintestkit.object_previews"):
        object_previews.capture_bound(preview.bound, preview.element)
    status = json.loads((preview.directory / "status.json").read_text(encoding="utf-8"))
    assert status["schemaVersion"] == 1
    assert status["definitionId"] == preview.definition_id
    assert status["reason"] == reason
    assert reason in caplog.text


def test_wpf_password_query_fails_closed_on_incomplete_or_error(monkeypatch):
    from wintestkit.backends.element import WpfElement

    node = object.__new__(WpfElement)
    node.client = SimpleNamespace(query_find_all=Mock(return_value=SimpleNamespace(complete=False)))
    node.ref = object()
    assert "inspector query did not complete" in object_previews._wpf_crop_reason(node)
    node.client.query_find_all.side_effect = RuntimeError("deadline")
    assert object_previews._wpf_crop_reason(node) == (
        "could not check the element's contents for password fields: deadline"
    )
    monkeypatch.setattr(object_previews, "_wpf_passwords", lambda root: [object()])
    assert object_previews._wpf_crop_reason(node) == "element contains a password field"


def test_element_in_a_window_over_the_crop_budget_still_gets_its_context(preview):
    # more than the 512 nodes an element crop may scan, within the whole-window budget
    preview.window.iter_children = lambda: iter([preview.element] * 2000)
    result = capture(preview)
    assert result is not None
    assert not (preview.directory / "status.json").exists()
    with Image.open(preview.directory / result["window"]) as image:
        assert image.size == (12, 10)


def _wpf_node(preview, monkeypatch, *, passwords=()):
    from wintestkit.backends.element import WpfElement

    node = object.__new__(WpfElement)
    node.client = SimpleNamespace()
    node.ref = object()
    bounds = preview.element.rect
    monkeypatch.setattr(WpfElement, "as_live", lambda self: self)
    monkeypatch.setattr(WpfElement, "rect", property(lambda self: bounds))
    monkeypatch.setattr(WpfElement, "process_id", property(lambda self: 123))
    monkeypatch.setattr(WpfElement, "is_offscreen", property(lambda self: False))
    monkeypatch.setattr(WpfElement, "automation_id", property(lambda self: "Panel"))
    monkeypatch.setattr(WpfElement, "class_name", property(lambda self: "DockPanel"))
    monkeypatch.setattr(WpfElement, "name", property(lambda self: ""))
    monkeypatch.setattr(WpfElement, "as_uia", lambda self: preview.element)
    monkeypatch.setattr(object_previews, "_wpf_passwords", lambda root: [])
    redactions = Mock(return_value=list(passwords))
    monkeypatch.setattr(object_previews, "_wpf_window_redactions", redactions)
    return node, redactions


def _password_child(rect):
    secret = SimpleNamespace(
        rect=rect,
        is_offscreen=False,
        automation_id="Password",
        class_name="PasswordBox",
        name="",
        get_property=lambda name: True,
        iter_children=lambda: iter(()),
    )
    secret.as_live = lambda: secret
    return secret


def test_managed_window_over_the_uia_budget_keeps_its_context_with_inspector_redactions(
    preview, monkeypatch
):
    node, redactions = _wpf_node(preview, monkeypatch, passwords=[Rect(-89, 211, 2, 2)])
    preview.window.iter_children = lambda: iter([preview.element] * 5000)
    object_previews.capture_bound(preview.bound, node)
    data = json.loads((preview.directory / "manifest.json").read_text(encoding="utf-8"))
    redactions.assert_called_once()
    assert not (preview.directory / "status.json").exists()
    with Image.open(preview.directory / data["window"]) as image:
        assert image.size == (12, 10)
        assert image.convert("RGB").getpixel((1, 1)) == (0, 0, 0)
        assert image.convert("RGB").getpixel((11, 9)) != (0, 0, 0)


def test_managed_window_blacks_out_what_the_uia_scan_finds_before_its_budget_runs_out(
    preview, monkeypatch
):
    node, _ = _wpf_node(preview, monkeypatch)
    secret = _password_child(Rect(-90, 210, 2, 2))
    preview.window.iter_children = lambda: iter([secret, *[preview.element] * 5000])
    object_previews.capture_bound(preview.bound, node)
    data = json.loads((preview.directory / "manifest.json").read_text(encoding="utf-8"))
    with Image.open(preview.directory / data["window"]) as image:
        assert image.size == (12, 10)
        assert image.convert("RGB").getpixel((0, 0)) == (0, 0, 0)


def test_managed_window_still_stops_on_a_password_it_cannot_black_out(preview, monkeypatch):
    node, _ = _wpf_node(preview, monkeypatch)
    preview.window.iter_children = lambda: iter([_password_child(None)])
    object_previews.capture_bound(preview.bound, node)
    data = json.loads((preview.directory / "manifest.json").read_text(encoding="utf-8"))
    assert "sensitive element has no rectangle" in (preview.directory / "status.json").read_text()
    with Image.open(preview.directory / data["window"]) as image:
        assert image.size == (4, 3)


def test_managed_window_without_inspector_redactions_saves_only_the_crop(preview, monkeypatch):
    node, redactions = _wpf_node(preview, monkeypatch)
    redactions.side_effect = RuntimeError("window mapping is ambiguous")
    object_previews.capture_bound(preview.bound, node)
    data = json.loads((preview.directory / "manifest.json").read_text(encoding="utf-8"))
    assert (
        "window context not saved: window elements could not be checked"
        in (preview.directory / "status.json").read_text()
    )
    with Image.open(preview.directory / data["window"]) as image:
        assert image.size == (4, 3)


def test_uia_element_in_an_attached_process_uses_the_inspector_for_passwords(preview, monkeypatch):
    client = SimpleNamespace()
    monkeypatch.setattr(object_previews, "_attached_client", lambda pid: client)
    redactions = Mock(return_value=[Rect(-89, 211, 2, 2)])
    monkeypatch.setattr(object_previews, "_wpf_window_redactions", redactions)
    preview.window.iter_children = lambda: iter([preview.element] * 5000)
    result = capture(preview)
    redactions.assert_called_once_with(client, 123, preview.window)
    assert result is not None
    assert not (preview.directory / "status.json").exists()
    with Image.open(preview.directory / result["window"]) as image:
        assert image.size == (12, 10)
        assert image.convert("RGB").getpixel((1, 1)) == (0, 0, 0)


def test_uia_element_falls_back_to_the_uia_scan_when_the_inspector_query_fails(
    preview, monkeypatch
):
    monkeypatch.setattr(object_previews, "_attached_client", lambda pid: SimpleNamespace())
    monkeypatch.setattr(
        object_previews, "_wpf_window_redactions", Mock(side_effect=RuntimeError("mapping"))
    )
    preview.window.iter_children = lambda: iter([preview.element] * 5000)
    result = capture(preview)
    assert result is not None
    assert "too many elements to check" in (preview.directory / "status.json").read_text()


def test_attached_client_requires_enabled_inspector_and_never_attaches(monkeypatch):
    from wintestkit.inspector import probe

    runtime.reset()
    assert object_previews._attached_client(123) is None
    registry = Mock()
    registry.get.return_value = "client"
    config = SimpleNamespace(inspector=SimpleNamespace(enabled=True))
    monkeypatch.setattr(runtime, "get_config", lambda: config)
    monkeypatch.setattr(runtime, "inspector_sessions", lambda: registry)
    monkeypatch.setattr(probe, "current_identity", lambda pid: ("identity", pid))
    assert object_previews._attached_client(123) == "client"
    registry.get.assert_called_once_with(("identity", 123))
    monkeypatch.setattr(probe, "current_identity", Mock(side_effect=OSError("gone")))
    assert object_previews._attached_client(123) is None


def test_single_colour_and_offscreen_skip_reasons(preview, monkeypatch):
    monkeypatch.setattr(
        screenshot,
        "capture_window_frame",
        lambda *args: (Rect(-90, 210, 12, 10), bytes((255, 255, 255)) * 120),
    )
    assert capture(preview) is None
    status = json.loads((preview.directory / "status.json").read_text())
    assert "single colour" in status["reason"]
    preview.element.is_offscreen = True
    assert capture(preview) is None
    status = json.loads((preview.directory / "status.json").read_text())
    assert "scrolled out of view or hidden" in status["reason"]


def test_a_page_check_scans_each_window_for_sensitive_controls_once(preview, monkeypatch):
    scans = Mock(wraps=object_previews._window_redactions)
    monkeypatch.setattr(object_previews, "_window_redactions", scans)
    with object_previews.shared_window_scans():
        assert capture(preview) is not None
        assert capture(preview) is not None
    assert scans.call_count == 1
    # Outside a page check every preview scans again.
    assert capture(preview) is not None
    assert scans.call_count == 2
