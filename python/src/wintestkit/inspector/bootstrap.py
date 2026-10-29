"""Create and dispose the private, one-use agent bootstrap file."""

from __future__ import annotations

import base64
import ctypes
import json
import os
import secrets
import stat
import uuid
from contextlib import suppress
from ctypes import wintypes
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from wintestkit.errors import InspectorUnavailableError
from wintestkit.inspector.models import ProcessIdentity
from wintestkit.inspector.probe import win_libraries as _libraries


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [
        ("length", wintypes.DWORD),
        ("descriptor", ctypes.c_void_p),
        ("inherit", wintypes.BOOL),
    ]


class _AclSize(ctypes.Structure):
    _fields_ = [("count", wintypes.DWORD), ("used", wintypes.DWORD), ("free", wintypes.DWORD)]


def _api() -> tuple[Any, Any]:
    kernel, security = _libraries()
    security.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.DWORD),
    ]
    security.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    kernel.CreateDirectoryW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(_SecurityAttributes)]
    kernel.CreateDirectoryW.restype = wintypes.BOOL
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(_SecurityAttributes),
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.WriteFile.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    kernel.WriteFile.restype = wintypes.BOOL
    security.GetSecurityInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    security.GetSecurityInfo.restype = wintypes.DWORD
    security.GetSecurityDescriptorControl.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.WORD),
        ctypes.POINTER(wintypes.DWORD),
    ]
    security.GetSecurityDescriptorControl.restype = wintypes.BOOL
    security.GetAclInformation.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_int,
    ]
    security.GetAclInformation.restype = wintypes.BOOL
    security.GetAce.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    security.GetAce.restype = wintypes.BOOL
    return kernel, security


def _error(message: str) -> InspectorUnavailableError:
    return InspectorUnavailableError(
        f"{message} (Windows error {ctypes.get_last_error()})", code="accessDenied"
    )


def _descriptor(sid: str, *, directory: bool) -> ctypes.c_void_p:
    if not sid.startswith("S-") or any(char not in "S-0123456789" for char in sid):
        raise InspectorUnavailableError("Invalid user SID", code="accessDenied")
    _, security = _api()
    descriptor = ctypes.c_void_p()
    inheritance = "OICI" if directory else ""
    if not security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        f"O:{sid}D:P(A;{inheritance};FA;;;{sid})", 1, ctypes.byref(descriptor), None
    ):
        raise _error("Cannot create bootstrap security descriptor")
    return descriptor


def _sid_text(pointer: Any) -> str:
    kernel, security = _api()
    text = wintypes.LPWSTR()
    if not security.ConvertSidToStringSidW(pointer, ctypes.byref(text)):
        raise _error("Cannot inspect bootstrap SID")
    try:
        return str(text.value)
    finally:
        kernel.LocalFree(text)


def _verify_acl(handle: Any, sid: str) -> None:
    kernel, security = _api()
    owner, dacl, descriptor = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
    status = security.GetSecurityInfo(
        handle,
        1,
        0x5,
        ctypes.byref(owner),
        None,
        ctypes.byref(dacl),
        None,
        ctypes.byref(descriptor),
    )
    if status:
        raise InspectorUnavailableError(
            f"Cannot inspect bootstrap ACL (Windows error {status})", code="accessDenied"
        )
    try:
        control, revision = wintypes.WORD(), wintypes.DWORD()
        size = _AclSize()
        if not owner.value or _sid_text(owner) != sid or not dacl.value:
            raise InspectorUnavailableError(
                "Bootstrap owner or ACL is not private", code="accessDenied"
            )
        if (
            not security.GetSecurityDescriptorControl(
                descriptor, ctypes.byref(control), ctypes.byref(revision)
            )
            or not control.value & 0x1000
        ):
            raise InspectorUnavailableError("Bootstrap ACL is not protected", code="accessDenied")
        if (
            not security.GetAclInformation(dacl, ctypes.byref(size), ctypes.sizeof(size), 2)
            or size.count != 1
        ):
            raise InspectorUnavailableError("Bootstrap ACL is not user-only", code="accessDenied")
        ace = ctypes.c_void_p()
        if not security.GetAce(dacl, 0, ctypes.byref(ace)) or not ace.value:
            raise _error("Cannot inspect bootstrap ACL")
        ace_type = ctypes.c_ubyte.from_address(ace.value).value
        mask = wintypes.DWORD.from_address(ace.value + 4).value
        if ace_type != 0 or mask & 0x1F01FF != 0x1F01FF or _sid_text(ace.value + 8) != sid:
            raise InspectorUnavailableError("Bootstrap ACL is not user-only", code="accessDenied")
    finally:
        kernel.LocalFree(descriptor)


def _no_reparse(path: Path, root: Path) -> None:
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise InspectorUnavailableError(
            "Bootstrap path is outside local application data", code="accessDenied"
        ) from error
    current = root
    for part in (None, *relative.parts):
        if part is not None:
            current /= part
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise InspectorUnavailableError(
                "Bootstrap path contains a reparse point", code="accessDenied"
            )


def _local_app_data() -> Path:
    if os.name != "nt":
        raise InspectorUnavailableError(
            "The WPF inspector requires Windows", code="unsupportedTarget"
        )
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    shell.SHGetFolderPathW.argtypes = [
        wintypes.HWND,
        ctypes.c_int,
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
    ]
    shell.SHGetFolderPathW.restype = ctypes.c_long
    buffer = ctypes.create_unicode_buffer(32768)
    if shell.SHGetFolderPathW(None, 0x1C, None, 0, buffer) != 0 or not buffer.value:
        raise InspectorUnavailableError("Cannot locate local application data", code="accessDenied")
    return Path(buffer.value)


@dataclass
class Bootstrap:
    session_id: str
    pipe_name: str
    path: Path
    directory: Path
    root: Path
    token: str = field(repr=False)

    def cleanup(self) -> None:
        try:
            _no_reparse(self.directory, self.root)
            try:
                self.path.unlink(missing_ok=True)
            finally:
                self.directory.rmdir()
        except FileNotFoundError:
            pass


def create_bootstrap(
    identity: ProcessIdentity,
    sid: str,
    agent_version: str,
    *,
    request_timeout_ms: int = 2000,
    idle_timeout_ms: int = 300000,
) -> Bootstrap:
    if not 1 <= request_timeout_ms <= 2000 or not 1 <= idle_timeout_ms <= 300000:
        raise InspectorUnavailableError("Invalid bootstrap timeout", code="invalidParams")
    kernel, _ = _api()
    local = _local_app_data()
    _no_reparse(local, local)
    root = local
    for part in ("WinTestKit", "inspector", "bootstrap"):
        root /= part
        with suppress(FileExistsError):
            root.mkdir()
        _no_reparse(root, local)
        if not root.is_dir():
            raise InspectorUnavailableError("Invalid bootstrap directory", code="accessDenied")
    session_id = str(uuid.uuid4())
    directory = root / session_id
    path = directory / (secrets.token_hex(16) + ".json")
    token = base64.b64encode(secrets.token_bytes(32)).decode("ascii")
    pipe_name = f"WinTestKit.Inspector.{identity.pid}.{session_id}"
    bootstrap = Bootstrap(session_id, pipe_name, path, directory, local, token)
    descriptor = _descriptor(sid, directory=True)
    try:
        attributes = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), descriptor, False)
        if not kernel.CreateDirectoryW(str(directory), ctypes.byref(attributes)):
            raise _error("Cannot create private bootstrap directory")
    finally:
        kernel.LocalFree(descriptor)
    try:
        _no_reparse(directory, local)
        handle = kernel.CreateFileW(str(directory), 0x00020000, 7, None, 3, 0x02200000, None)
        if handle == ctypes.c_void_p(-1).value:
            raise _error("Cannot open bootstrap directory")
        try:
            _verify_acl(handle, sid)
        finally:
            kernel.CloseHandle(handle)
        settings = {
            "schemaVersion": 1,
            "protocolMajor": 1,
            "protocolMinor": 0,
            "sessionId": session_id,
            "process": identity.to_json(),
            "pipeName": pipe_name,
            "token": token,
            "clientSid": sid,
            "expiresUtc": (datetime.now(UTC) + timedelta(seconds=30))
            .isoformat()
            .replace("+00:00", "Z"),
            "requestTimeoutMs": request_timeout_ms,
            "idleTimeoutMs": idle_timeout_ms,
            "agentVersion": agent_version,
        }
        payload = json.dumps(settings, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if len(payload) > 16384:
            raise InspectorUnavailableError("Bootstrap exceeds size limit", code="limitExceeded")
        descriptor = _descriptor(sid, directory=False)
        try:
            attributes = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), descriptor, False)
            handle = kernel.CreateFileW(
                str(path), 0x40020000, 0, ctypes.byref(attributes), 1, 0x00200080, None
            )
            if handle == ctypes.c_void_p(-1).value:
                raise _error("Cannot create bootstrap file")
        finally:
            kernel.LocalFree(descriptor)
        try:
            _verify_acl(handle, sid)
            written = wintypes.DWORD()
            data = ctypes.create_string_buffer(payload)
            if not kernel.WriteFile(
                handle, data, len(payload), ctypes.byref(written), None
            ) or written.value != len(payload):
                raise _error("Cannot write bootstrap file")
        finally:
            kernel.CloseHandle(handle)
        _no_reparse(path, local)
        return bootstrap
    except BaseException:
        bootstrap.cleanup()
        raise
