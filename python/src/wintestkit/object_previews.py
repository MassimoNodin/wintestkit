"""Best-effort paired previews of intentionally checked declared single elements."""

from __future__ import annotations

import contextlib
import ctypes
import hashlib
import json
import logging
import os
import re
import stat
import time
import uuid
from collections.abc import Generator, Iterator
from ctypes import wintypes
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

from PIL import Image, ImageDraw

from wintestkit import runtime
from wintestkit.backends.element import TargetElement, uia_of
from wintestkit.config import sync_object_previews_ignore
from wintestkit.uia import screenshot, win32
from wintestkit.uia.element import Rect, UIAElement
from wintestkit.uia.webp import encode_webp

if TYPE_CHECKING:
    from wintestkit.model import BoundControl

_GRACE_SECONDS = 60  # leftover staging from a crashed capture, and images from before pruning
_SCAN_NODES = 512
_SCAN_DEPTH = 64
_SCAN_SECONDS = 0.5
_REVISION = re.compile(r"[0-9a-f]{32}\.(?:(?:element|window)\.webp|manifest\.tmp)")
_SENSITIVE = re.compile(
    r"password|passwd|secret|token|credential|(?:^|[^a-z])pin(?:$|[^a-z])", re.I
)
log = logging.getLogger("wintestkit.object_previews")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _contains(outer: Rect, inner: Rect) -> bool:
    return not inner.is_empty() and screenshot.clip(inner, outer) == inner


def _native_path(path: Path) -> str:
    value = str(path.absolute())
    if value.startswith("\\\\?\\"):
        return value
    return "\\\\?\\UNC\\" + value[2:] if value.startswith("\\\\") else "\\\\?\\" + value


def _owning_window(element: UIAElement, bounds: Rect) -> tuple[int, UIAElement] | None:
    current: UIAElement | None = element
    process_id = element.process_id
    hosted_root = 0
    for _depth in range(64):
        if current is None:
            return None
        current = current.as_live()
        hwnd = current.native_window_handle
        if current.is_offscreen:
            return None
        if current.process_id != process_id and not (
            hwnd
            and hwnd == hosted_root
            and current.class_name == "ApplicationFrameWindow"
            and win32.window_class_name(hwnd) == "ApplicationFrameWindow"
            and hwnd in win32.top_level_windows({process_id})
        ):
            return None
        if current.get_property("IsPassword"):
            return None
        if _SENSITIVE.search(" ".join((current.automation_id, current.class_name, current.name))):
            return None
        parent_bounds = current.rect
        if parent_bounds is None or not _contains(parent_bounds, bounds):
            return None
        if hwnd:
            if win32.window_pid(hwnd) != current.process_id:
                return None
            root = win32.root_window(hwnd)
            if root == hwnd:
                return hwnd, current
            hosted_root = root
        current = current.parent()
    return None


def _safe_content(root: UIAElement, bounds: Rect) -> bool:
    deadline = time.monotonic() + _SCAN_SECONDS
    stack: list[tuple[int, Iterator[UIAElement]]] = [(0, iter((root,)))]
    count = 0
    while stack:
        if time.monotonic() >= deadline:
            return False
        depth, siblings = stack[-1]
        element = next(siblings, None)
        if element is None:
            stack.pop()
            continue
        count += 1
        if count > _SCAN_NODES or depth > _SCAN_DEPTH:
            return False
        element = element.as_live()
        if not element.is_offscreen:
            rect = element.rect
            if rect is None or screenshot.clip(rect, bounds) is not None:
                password = element.get_property("IsPassword")
                if type(password) not in (bool, int) or password:
                    return False
                if _SENSITIVE.search(
                    " ".join((element.automation_id, element.class_name, element.name))
                ):
                    return False
        stack.append((depth + 1, element.iter_children()))
    return time.monotonic() < deadline


@contextlib.contextmanager
def _pinned(path: Path, *, directory: bool = False) -> Generator[int]:
    if os.name != "nt":
        raise OSError("object preview publication requires Windows path guards")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create.restype = wintypes.HANDLE
    handle = create(_native_path(path), 0x80, 3, None, 3, 0x02200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    try:

        class AttributeTag(ctypes.Structure):
            _fields_ = [("attributes", wintypes.DWORD), ("tag", wintypes.DWORD)]

        info = AttributeTag()
        query = kernel.GetFileInformationByHandleEx
        query.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        query.restype = wintypes.BOOL
        if not query(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        metadata = path.lstat()
        if (
            info.attributes & 0x400
            or bool(info.attributes & 0x10) != directory
            or (not directory and (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1))
        ):
            raise OSError("redirected object preview output")
        yield cast("int", handle)
    finally:
        close(handle)


def _replace_manifest(source: Path, target: Path) -> None:
    if source.parent != target.parent:
        raise OSError("object preview manifest must stay in its definition directory")
    with _pinned(target.parent, directory=True):
        os.replace(_native_path(source), _native_path(target))


@contextlib.contextmanager
def _output_directory(root: Path, key: str) -> Generator[Path]:
    root = root.resolve()
    with contextlib.ExitStack() as guards:
        guards.enter_context(_pinned(root, directory=True))
        directory = root
        for component in ("object-previews", key):
            directory = directory / component
            directory.mkdir(exist_ok=True)
            guards.enter_context(_pinned(directory, directory=True))
            if not directory.resolve().is_relative_to(root):
                raise OSError("object preview output escaped the project")
        yield directory


@contextlib.contextmanager
def _publication_lock(directory: Path) -> Generator[bool]:
    path = directory / ".lock"
    try:
        with path.open("xb"):
            pass
    except FileExistsError:
        pass
    with _pinned(path), path.open("a+b") as handle:
        import msvcrt

        if not handle.seek(0, os.SEEK_END):
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def _cleanup(directory: Path, keep: set[str]) -> None:
    cutoff = time.time() - _GRACE_SECONDS
    for candidate in directory.iterdir():
        if candidate.name in keep or _REVISION.fullmatch(candidate.name) is None:
            continue
        with contextlib.suppress(OSError):
            with _pinned(candidate):
                stale = candidate.stat().st_mtime < cutoff
            if stale:
                candidate.unlink()


def _previous_images(directory: Path) -> list[str]:
    """The image names the current manifest points at, before a new capture replaces them."""
    try:
        manifest = directory / "manifest.json"
        with _pinned(manifest):
            previous = json.loads(manifest.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return []
    if not isinstance(previous, dict):
        return []
    names = (cast("dict[str, object]", previous).get(key) for key in ("crop", "window"))
    return [
        name
        for name in names
        if isinstance(name, str) and re.fullmatch(r"[0-9a-f]{32}\.(?:element|window)\.webp", name)
    ]


def _discard(directory: Path, names: list[str]) -> None:
    """Delete superseded images now; one a reader still holds open is left for ``_cleanup``."""
    for name in names:
        with contextlib.suppress(OSError):
            with _pinned(directory / name):
                pass
            (directory / name).unlink()


def capture_bound(bound: BoundControl, element: TargetElement) -> None:
    """Save an explicitly checked element; failures must never affect its result."""
    try:
        if runtime.get_config().object_previews:
            _capture_bound(bound, uia_of(element))
    except Exception:
        log.debug("Could not save object preview", exc_info=True)


def _capture_bound(bound: BoundControl, element: UIAElement) -> None:
    from wintestkit.model import Element, Elements, is_password_locator

    definition = bound.definition
    if not isinstance(definition, Element) or isinstance(definition, Elements):
        return
    if (
        definition.ad_hoc
        or definition.owner is None
        or definition.name is None
        or definition.source is None
    ):
        return
    config = runtime.get_config()
    relative = Path(definition.source[0]).resolve().relative_to(config.root.resolve()).as_posix()
    definition_id = f"{relative}::{definition.owner.__qualname__}.{definition.name}"
    locator = bound.locator
    if (
        locator.item is not None
        or is_password_locator(locator)
        or _SENSITIVE.search(locator.describe())
    ):
        return
    element = element.as_live()
    bounds = element.rect
    if bounds is None or not _contains(win32.virtual_screen_rect(), bounds):
        return
    owner = _owning_window(element, bounds)
    if owner is None:
        return
    hwnd, window = owner
    if not _safe_content(window, window.rect or bounds):
        return
    sync_object_previews_ignore(config.root, config.object_previews_share)
    with (
        _output_directory(config.root, _digest(definition_id)) as directory,
        _publication_lock(directory) as acquired,
    ):
        if not acquired:
            return
        frame = screenshot.capture_window_frame(hwnd, window.process_id)
        if frame is None:
            return
        window_bounds, pixels = frame
        if not _contains(window_bounds, bounds) or not any(pixels):
            return
        owner = _owning_window(element, bounds)
        if (
            element.rect != bounds
            or owner is None
            or owner[0] != hwnd
            or not _safe_content(owner[1], window_bounds)
        ):
            return
        captured_at = datetime.now(UTC).isoformat()
        capture_id = uuid.uuid4().hex
        crop_path = directory / f"{capture_id}.element.webp"
        window_path = directory / f"{capture_id}.window.webp"
        temporary = directory / f"{capture_id}.manifest.tmp"
        left, top = bounds.left - window_bounds.left, bounds.top - window_bounds.top
        with Image.frombytes("RGB", (window_bounds.width, window_bounds.height), pixels) as image:
            with image.crop((left, top, left + bounds.width, top + bounds.height)) as crop:
                crop_bytes = encode_webp(crop.width, crop.height, crop.tobytes())
            with image.copy() as outlined:
                ImageDraw.Draw(outlined).rectangle(
                    (left, top, left + bounds.width - 1, top + bounds.height - 1),
                    outline="red",
                    width=2,
                )
                window_bytes = encode_webp(outlined.width, outlined.height, outlined.tobytes())
        manifest = {
            "schemaVersion": 2,
            "definitionId": definition_id,
            "captureId": capture_id,
            "capturedAt": captured_at,
            "locatorFingerprint": _digest(
                json.dumps(locator.to_dict(), sort_keys=True, ensure_ascii=False)
            ),
            "crop": crop_path.name,
            "window": window_path.name,
            "width": bounds.width,
            "height": bounds.height,
        }
        context = bound.qualname
        if len(context) <= 240 and re.fullmatch(r"[A-Za-z_][A-Za-z_0-9.]*", context):
            manifest["context"] = context
        published = False
        owned: list[Path] = []
        try:
            with contextlib.ExitStack() as files:
                for path, content in (
                    (crop_path, crop_bytes),
                    (window_path, window_bytes),
                    (temporary, json.dumps(manifest, ensure_ascii=False).encode("utf-8")),
                ):
                    with path.open("xb") as output:
                        owned.append(path)
                        output.write(content)
                        output.flush()
                        if path != temporary:
                            files.enter_context(_pinned(path))
                superseded = _previous_images(directory)
                _replace_manifest(temporary, directory / "manifest.json")
                published = True
                _discard(
                    directory,
                    [name for name in superseded if name not in (crop_path.name, window_path.name)],
                )
        finally:
            for path in (temporary,) if published else owned:
                with contextlib.suppress(OSError):
                    path.unlink(missing_ok=True)
        _cleanup(directory, {crop_path.name, window_path.name})
