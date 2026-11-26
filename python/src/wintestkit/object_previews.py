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
from wintestkit.backends.element import TargetElement, WpfElement, uia_of
from wintestkit.config import sync_object_previews_ignore
from wintestkit.inspector.client import InspectorClient
from wintestkit.uia import screenshot, win32
from wintestkit.uia.element import Rect, UIAElement
from wintestkit.uia.webp import encode_webp

if TYPE_CHECKING:
    from wintestkit.model import BoundControl, BoundElements, BoundWindow

_GRACE_SECONDS = 60  # leftover staging from a crashed capture, and images from before pruning
_SCAN_NODES = 512
_SCAN_DEPTH = 64
_SCAN_SECONDS = 0.5
# A saved window image is the whole window, so its content check gets a larger budget.
_WINDOW_SCAN_NODES = 4096
_WINDOW_SCAN_SECONDS = 4.0
_TOO_MANY = "too many elements to check"
_REVISION = re.compile(r"[0-9a-f]{32}\.(?:(?:element|window)\.webp|manifest\.tmp)")
_SENSITIVE = re.compile(
    r"password|passwd|secret|token|credential|(?:^|[^a-z])pin(?:$|[^a-z])", re.I
)
log = logging.getLogger("wintestkit.object_previews")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _contains(outer: Rect, inner: Rect) -> bool:
    return not inner.is_empty() and screenshot.clip(inner, outer) == inner


def picture_target_is_safe(element: UIAElement, bounds: Rect) -> bool:
    """Check a picture target and its visible contents before capture."""
    return _owning_window(element, bounds) is not None and _safe_content(element, bounds)


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


def _scan(
    root: UIAElement,
    bounds: Rect,
    *,
    redact: bool = False,
    skip_root: bool = False,
    whole_window: bool = False,
) -> tuple[str | None, list[Rect]]:
    deadline = time.monotonic() + (_WINDOW_SCAN_SECONDS if whole_window else _SCAN_SECONDS)
    limit = _WINDOW_SCAN_NODES if whole_window else _SCAN_NODES
    stack: list[tuple[int, Iterator[UIAElement]]] = [(0, iter((root,)))]
    count = 0
    rectangles: list[Rect] = []
    while stack:
        if time.monotonic() >= deadline:
            return _TOO_MANY, rectangles
        depth, siblings = stack[-1]
        element = next(siblings, None)
        if element is None:
            stack.pop()
            continue
        count += 1
        if count > limit or depth > _SCAN_DEPTH:
            return _TOO_MANY, rectangles
        element = element.as_live()
        if not element.is_offscreen and not (skip_root and depth == 0):
            rect = element.rect
            if rect is None or screenshot.clip(rect, bounds) is not None:
                password = element.get_property("IsPassword")
                sensitive = _SENSITIVE.search(
                    " ".join((element.automation_id, element.class_name, element.name))
                )
                if type(password) not in (bool, int):
                    return "could not determine whether an element is a password field", rectangles
                if password or sensitive:
                    if not redact:
                        return (
                            "element contains a password field"
                            if password
                            else "element looks sensitive"
                        ), rectangles
                    if rect is None:
                        return "sensitive element has no rectangle", rectangles
                    rectangles.append(rect)
        stack.append((depth + 1, element.iter_children()))
    return None, rectangles


def _wpf_passwords(root: WpfElement) -> list[WpfElement]:
    """Query the scoped WPF tree without creating UI Automation peers."""
    from wintestkit.inspector.models import Locator, Predicate, Scope

    deadline = time.monotonic() + 2.0
    locator = Locator(
        Scope("object", root.ref),
        "combined",
        (Predicate("assignableTo", full_name="System.Windows.Controls.PasswordBox"),),
        256,
        200,
        "tree",
    )
    result = root.client.query_find_all(locator, timeout_ms=2000, deadline=deadline)
    if not result.complete:
        raise RuntimeError("inspector query did not complete")
    return [WpfElement(root.client, ref, root.process_id) for ref in result.matches]


def _wpf_crop_reason(root: WpfElement) -> str | None:
    try:
        if _wpf_passwords(root):
            return "element contains a password field"
    except Exception as exc:
        return f"could not check the element's contents for password fields: {exc}"
    return None


def _crop_reason(element: TargetElement, owner: UIAElement, bounds: Rect) -> str | None:
    """Why the element's own crop must not be saved; a window is redacted instead."""
    if isinstance(element, WpfElement):
        return _wpf_crop_reason(element)
    return _scan(owner, bounds)[0]


def _attached_client(process_id: int) -> InspectorClient | None:
    """The ready inspector session of an already attached process; never attaches one."""
    try:
        if not runtime.get_config().inspector.enabled:
            return None
        from wintestkit.inspector import probe

        return runtime.inspector_sessions().get(probe.current_identity(process_id))
    except Exception:
        return None


def _wpf_window_redactions(
    client: InspectorClient, process_id: int, window: UIAElement
) -> list[Rect]:
    deadline = time.monotonic() + 2.0
    rid, hwnd = runtime.managed_element_identity(window)
    mapping = client.resolve(rid, hwnd, deadline=deadline)
    if mapping.status != "exact" or mapping.object_ref is None:
        raise RuntimeError(f"window mapping is {mapping.status}")
    root = WpfElement(client, mapping.object_ref, process_id)
    rectangles: list[Rect] = []
    for password in _wpf_passwords(root):
        if not password.is_offscreen:
            rect = password.rect
            if rect is None:
                raise RuntimeError("password field has no rectangle")
            rectangles.append(rect)
    return rectangles


def _window_redactions(
    element: TargetElement, window: UIAElement, window_bounds: Rect
) -> tuple[str | None, list[Rect]]:
    """Why the window context cannot be saved, and the rectangles to black out in it.

    With an attached .NET inspector the password query over the whole window is
    authoritative, so the UI Automation name scan is best effort: it adds what it finds
    within its budget but running out of budget no longer drops the context.
    """
    inspector: list[Rect] | None = None
    if isinstance(element, WpfElement):
        inspector = _wpf_window_redactions(element.client, element.process_id, window)
    else:
        client = _attached_client(window.process_id)
        if client is not None:
            with contextlib.suppress(Exception):
                inspector = _wpf_window_redactions(client, window.process_id, window)
    reason, found = _scan(window, window_bounds, redact=True, skip_root=True, whole_window=True)
    if inspector is None:
        return reason, found
    return (None if reason == _TOO_MANY else reason), [*inspector, *found]


def _safe_content(root: UIAElement, bounds: Rect) -> bool:
    return _scan(root, bounds)[0] is None


def _blackout(image: Image.Image, rectangles: list[Rect], window_bounds: Rect) -> None:
    """Paint sensitive rectangles (screen coordinates) black on a window-sized image."""
    for rect in rectangles:
        clipped = screenshot.clip(rect, window_bounds)
        if clipped:
            left, top = clipped.left - window_bounds.left, clipped.top - window_bounds.top
            ImageDraw.Draw(image).rectangle(
                (left, top, left + clipped.width - 1, top + clipped.height - 1), fill="black"
            )


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


class _SkipPreview(Exception):
    pass


def _definition_id(bound: BoundControl | BoundElements | BoundWindow) -> str | None:
    definition = bound.definition
    if definition.owner is None or definition.name is None or definition.source is None:
        return None
    relative = (
        Path(definition.source[0])
        .resolve()
        .relative_to(runtime.get_config().root.resolve())
        .as_posix()
    )
    return f"{relative}::{definition.owner.__qualname__}.{definition.name}"


def _status(bound: BoundControl | BoundElements | BoundWindow, reason: str) -> None:
    log.info("Preview not saved for %s: %s", bound.qualname, reason)
    try:
        definition_id = _definition_id(bound)
        if definition_id is None:
            return
        config = runtime.get_config()
        sync_object_previews_ignore(config.root, config.object_previews_share)
        with (
            _output_directory(config.root, _digest(definition_id)) as directory,
            _publication_lock(directory) as acquired,
        ):
            if not acquired:
                return
            temporary = directory / (uuid.uuid4().hex + ".manifest.tmp")
            try:
                data = {
                    "schemaVersion": 1,
                    "definitionId": definition_id,
                    "reason": reason[:2048],
                    "at": datetime.now(UTC).isoformat(),
                }
                with temporary.open("xb") as output:
                    output.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
                _replace_manifest(temporary, directory / "status.json")
            finally:
                temporary.unlink(missing_ok=True)
    except Exception:
        log.info("Could not persist preview status for %s", bound.qualname, exc_info=True)


def capture_bound(
    bound: BoundControl | BoundElements | BoundWindow, element: TargetElement
) -> None:
    """Save an explicitly checked element; failures must never affect its result."""
    try:
        if not runtime.get_config().object_previews:
            raise _SkipPreview("object previews are disabled")
        _capture_bound(bound, element)
    except _SkipPreview as exc:
        _status(bound, str(exc))
    except Exception as exc:
        _status(bound, f"capture failed: {exc}")


def _capture_bound(
    bound: BoundControl | BoundElements | BoundWindow, element: TargetElement
) -> None:
    from wintestkit.engine.locator import Locator
    from wintestkit.errors import NoUiaPeerError
    from wintestkit.model import BoundElements, Element, Elements, Window, is_password_locator
    from wintestkit.uia.element import from_handle

    definition = bound.definition
    is_window = isinstance(definition, Window)
    if isinstance(definition, Elements) and not isinstance(bound, BoundElements):
        raise _SkipPreview("definition refers to a collection item")
    if not isinstance(definition, (Element, Window)):
        raise _SkipPreview("definition is not a declared object")
    if (
        (isinstance(definition, Element) and definition.ad_hoc)
        or definition.owner is None
        or definition.name is None
        or definition.source is None
    ):
        raise _SkipPreview("definition has no declared source")
    config = runtime.get_config()
    definition_id = _definition_id(bound)
    assert definition_id is not None
    locator = bound.locator
    if isinstance(locator, Locator):
        if locator.item is not None:
            raise _SkipPreview("definition refers to a collection item")
        if is_password_locator(locator):
            raise _SkipPreview("locator looks sensitive")
    if _SENSITIVE.search(locator.describe()):
        raise _SkipPreview("locator looks sensitive")
    element = element.as_live()
    if element.is_offscreen:
        raise _SkipPreview(
            "element is scrolled out of view or hidden; scroll it into view and check again"
        )
    bounds = element.rect
    if bounds is None or not _contains(win32.virtual_screen_rect(), bounds):
        raise _SkipPreview("element has no on-screen rectangle")
    peerless = False
    hwnd = 0
    try:
        owner_element = uia_of(element)
    except NoUiaPeerError:
        if not isinstance(element, WpfElement):
            raise
        peerless = True
        hwnd = win32.root_window(element.state().window_handle or 0)
        if not hwnd or win32.window_pid(hwnd) != element.process_id or element.is_offscreen:
            raise _SkipPreview("element has no owned on-screen window") from None
        owner_element = from_handle(hwnd)
    if peerless:
        window = owner_element
        if _SENSITIVE.search(" ".join((element.automation_id, element.class_name, element.name))):
            raise _SkipPreview("element looks sensitive")
        reason = None if is_window else _crop_reason(element, owner_element, bounds)
    else:
        owner = _owning_window(owner_element, bounds)
        if owner is None:
            raise _SkipPreview("element has no owned on-screen window")
        hwnd, window = owner
        reason = None if is_window else _crop_reason(element, owner_element, bounds)
    if reason:
        raise _SkipPreview(reason)
    sync_object_previews_ignore(config.root, config.object_previews_share)
    with (
        _output_directory(config.root, _digest(definition_id)) as directory,
        _publication_lock(directory) as acquired,
    ):
        if not acquired:
            raise _SkipPreview("another capture is publishing")
        frame = screenshot.capture_window_frame(hwnd, window.process_id)
        if frame is None:
            raise _SkipPreview("window capture failed")
        window_bounds, pixels = frame
        if (not is_window and not _contains(window_bounds, bounds)) or not any(pixels):
            raise _SkipPreview("element is outside the window or the window is blank")
        with Image.frombytes(
            "RGB", (window_bounds.width, window_bounds.height), pixels
        ) as frame_image:
            extrema = cast("tuple[tuple[int, int], ...]", frame_image.getextrema())
            if all(low == high for low, high in extrema):
                raise _SkipPreview(
                    "The window rendered as a single colour; it may not be painted yet"
                )
        if element.as_live().rect != bounds or win32.window_pid(hwnd) != window.process_id:
            raise _SkipPreview("element or window changed during capture")
        reason = None if is_window else _crop_reason(element, owner_element, bounds)
        if reason:
            raise _SkipPreview(reason)
        try:
            window_reason, redactions = _window_redactions(element, window, window_bounds)
        except Exception:
            window_reason, redactions = "window elements could not be checked", []
        if is_window:
            if window_reason:
                raise _SkipPreview(window_reason)
            bounds = window_bounds
        captured_at = datetime.now(UTC).isoformat()
        capture_id = uuid.uuid4().hex
        crop_path = directory / f"{capture_id}.element.webp"
        window_path = directory / f"{capture_id}.window.webp"
        temporary = directory / f"{capture_id}.manifest.tmp"
        left, top = bounds.left - window_bounds.left, bounds.top - window_bounds.top
        with Image.frombytes("RGB", (window_bounds.width, window_bounds.height), pixels) as image:
            if is_window:
                # a window's crop and its context are the same image, so black out first
                _blackout(image, redactions, window_bounds)
            with image.crop((left, top, left + bounds.width, top + bounds.height)) as crop:
                crop_bytes = encode_webp(crop.width, crop.height, crop.tobytes())
            with (
                image.crop((left, top, left + bounds.width, top + bounds.height))
                if window_reason
                else image.copy()
            ) as outlined:
                if not window_reason and not is_window:
                    ImageDraw.Draw(outlined).rectangle(
                        (left, top, left + bounds.width - 1, top + bounds.height - 1),
                        outline="red",
                        width=2,
                    )
                    _blackout(outlined, redactions, window_bounds)
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
        if isinstance(bound, BoundElements):
            try:
                count = len(bound.resolve_all())
                if count:
                    manifest["matchCount"] = count
            except Exception:
                pass
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
        status = directory / "status.json"
        if not window_reason:
            with contextlib.suppress(FileNotFoundError):
                with _pinned(status):
                    pass
                status.unlink()
        _cleanup(directory, {crop_path.name, window_path.name})
    if window_reason:
        _status(bound, "window context not saved: " + window_reason)
