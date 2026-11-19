"""Native window facts for UIA nodes that own an HWND: class, styles, ids, text, geometry.

Reading is split in two so the decoding is testable without a desktop: a ``NativeWindowBackend``
returns raw numbers (the ctypes one lives in ``win32.py``), and ``NativeWindowReader`` turns them
into the JSON shape the Spy shows (``NativeWindowInfo`` in ``schemas/rpc.schema.json``).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from wintestkit.uia.element import Rect

__all__ = [
    "NativeWindowBackend",
    "NativeWindowReader",
    "RawWindow",
    "StyleBit",
    "decode_ex_style",
    "decode_style",
    "default_reader",
]

#: Window text is cut to this many characters (an edit control can hold megabytes).
MAX_TEXT = 2000

WS_POPUP = 0x80000000
WS_CHILD = 0x40000000
WS_DISABLED = 0x08000000
WS_EX_TOPMOST = 0x00000008
ES_PASSWORD = 0x20


@dataclass(frozen=True)
class StyleBit:
    """A named style: it applies when ``style & mask == value`` (a flag has mask == value)."""

    name: str
    mask: int
    value: int


def _flags(*pairs: tuple[str, int]) -> tuple[StyleBit, ...]:
    return tuple(StyleBit(name, bit, bit) for name, bit in pairs)


def _enum(mask: int, *pairs: tuple[str, int]) -> tuple[StyleBit, ...]:
    return tuple(StyleBit(name, mask, value) for name, value in pairs)


# Composite names come first so they claim their bits before the single-bit names would.
_WS_COMMON = _flags(
    ("WS_POPUP", 0x80000000),
    ("WS_CHILD", 0x40000000),
    ("WS_MINIMIZE", 0x20000000),
    ("WS_VISIBLE", 0x10000000),
    ("WS_DISABLED", 0x08000000),
    ("WS_CLIPSIBLINGS", 0x04000000),
    ("WS_CLIPCHILDREN", 0x02000000),
    ("WS_MAXIMIZE", 0x01000000),
    ("WS_CAPTION", 0x00C00000),
    ("WS_BORDER", 0x00800000),
    ("WS_DLGFRAME", 0x00400000),
    ("WS_VSCROLL", 0x00200000),
    ("WS_HSCROLL", 0x00100000),
    ("WS_SYSMENU", 0x00080000),
    ("WS_THICKFRAME", 0x00040000),
)
# Bits 16 and 17 mean different things on a control and on a top-level window.
_WS_CONTROL = _flags(("WS_GROUP", 0x00020000), ("WS_TABSTOP", 0x00010000))
_WS_TOP_LEVEL = _flags(("WS_MINIMIZEBOX", 0x00020000), ("WS_MAXIMIZEBOX", 0x00010000))

_WS_EX = _flags(
    ("WS_EX_DLGMODALFRAME", 0x00000001),
    ("WS_EX_NOPARENTNOTIFY", 0x00000004),
    ("WS_EX_TOPMOST", 0x00000008),
    ("WS_EX_ACCEPTFILES", 0x00000010),
    ("WS_EX_TRANSPARENT", 0x00000020),
    ("WS_EX_MDICHILD", 0x00000040),
    ("WS_EX_TOOLWINDOW", 0x00000080),
    ("WS_EX_WINDOWEDGE", 0x00000100),
    ("WS_EX_CLIENTEDGE", 0x00000200),
    ("WS_EX_CONTEXTHELP", 0x00000400),
    ("WS_EX_RIGHT", 0x00001000),
    ("WS_EX_RTLREADING", 0x00002000),
    ("WS_EX_LEFTSCROLLBAR", 0x00004000),
    ("WS_EX_CONTROLPARENT", 0x00010000),
    ("WS_EX_STATICEDGE", 0x00020000),
    ("WS_EX_APPWINDOW", 0x00040000),
    ("WS_EX_LAYERED", 0x00080000),
    ("WS_EX_NOINHERITLAYOUT", 0x00100000),
    ("WS_EX_NOREDIRECTIONBITMAP", 0x00200000),
    ("WS_EX_LAYOUTRTL", 0x00400000),
    ("WS_EX_COMPOSITED", 0x02000000),
    ("WS_EX_NOACTIVATE", 0x08000000),
)

_BUTTON = (
    *_enum(
        0xF,
        ("BS_PUSHBUTTON", 0),
        ("BS_DEFPUSHBUTTON", 1),
        ("BS_CHECKBOX", 2),
        ("BS_AUTOCHECKBOX", 3),
        ("BS_RADIOBUTTON", 4),
        ("BS_3STATE", 5),
        ("BS_AUTO3STATE", 6),
        ("BS_GROUPBOX", 7),
        ("BS_USERBUTTON", 8),
        ("BS_AUTORADIOBUTTON", 9),
        ("BS_PUSHBOX", 10),
        ("BS_OWNERDRAW", 11),
    ),
    *_flags(("BS_LEFTTEXT", 0x20), ("BS_ICON", 0x40), ("BS_BITMAP", 0x80)),
    *_enum(0x300, ("BS_LEFT", 0x100), ("BS_RIGHT", 0x200), ("BS_CENTER", 0x300)),
    *_enum(0xC00, ("BS_TOP", 0x400), ("BS_BOTTOM", 0x800), ("BS_VCENTER", 0xC00)),
    *_flags(("BS_PUSHLIKE", 0x1000), ("BS_MULTILINE", 0x2000), ("BS_NOTIFY", 0x4000)),
    *_flags(("BS_FLAT", 0x8000)),
)
_EDIT = (
    *_enum(3, ("ES_LEFT", 0), ("ES_CENTER", 1), ("ES_RIGHT", 2)),
    *_flags(
        ("ES_MULTILINE", 0x4),
        ("ES_UPPERCASE", 0x8),
        ("ES_LOWERCASE", 0x10),
        ("ES_PASSWORD", 0x20),
        ("ES_AUTOVSCROLL", 0x40),
        ("ES_AUTOHSCROLL", 0x80),
        ("ES_NOHIDESEL", 0x100),
        ("ES_OEMCONVERT", 0x400),
        ("ES_READONLY", 0x800),
        ("ES_WANTRETURN", 0x1000),
        ("ES_NUMBER", 0x2000),
    ),
)
_STATIC = (
    *_enum(
        0x1F,
        ("SS_LEFT", 0),
        ("SS_CENTER", 1),
        ("SS_RIGHT", 2),
        ("SS_ICON", 3),
        ("SS_BLACKRECT", 4),
        ("SS_GRAYRECT", 5),
        ("SS_WHITERECT", 6),
        ("SS_BLACKFRAME", 7),
        ("SS_GRAYFRAME", 8),
        ("SS_WHITEFRAME", 9),
        ("SS_USERITEM", 10),
        ("SS_SIMPLE", 11),
        ("SS_LEFTNOWORDWRAP", 12),
        ("SS_OWNERDRAW", 13),
        ("SS_BITMAP", 14),
        ("SS_ENHMETAFILE", 15),
        ("SS_ETCHEDHORZ", 16),
        ("SS_ETCHEDVERT", 17),
        ("SS_ETCHEDFRAME", 18),
    ),
    *_flags(
        ("SS_REALSIZECONTROL", 0x40),
        ("SS_NOPREFIX", 0x80),
        ("SS_NOTIFY", 0x100),
        ("SS_CENTERIMAGE", 0x200),
        ("SS_RIGHTJUST", 0x400),
        ("SS_REALSIZEIMAGE", 0x800),
        ("SS_SUNKEN", 0x1000),
        ("SS_EDITCONTROL", 0x2000),
    ),
    *_enum(
        0xC000, ("SS_ENDELLIPSIS", 0x4000), ("SS_PATHELLIPSIS", 0x8000), ("SS_WORDELLIPSIS", 0xC000)
    ),
)
_COMBOBOX = (
    *_enum(3, ("CBS_SIMPLE", 1), ("CBS_DROPDOWN", 2), ("CBS_DROPDOWNLIST", 3)),
    *_flags(
        ("CBS_OWNERDRAWFIXED", 0x10),
        ("CBS_OWNERDRAWVARIABLE", 0x20),
        ("CBS_AUTOHSCROLL", 0x40),
        ("CBS_OEMCONVERT", 0x80),
        ("CBS_SORT", 0x100),
        ("CBS_HASSTRINGS", 0x200),
        ("CBS_NOINTEGRALHEIGHT", 0x400),
        ("CBS_DISABLENOSCROLL", 0x800),
        ("CBS_UPPERCASE", 0x2000),
        ("CBS_LOWERCASE", 0x4000),
    ),
)
_LISTBOX = _flags(
    ("LBS_NOTIFY", 0x1),
    ("LBS_SORT", 0x2),
    ("LBS_NOREDRAW", 0x4),
    ("LBS_MULTIPLESEL", 0x8),
    ("LBS_OWNERDRAWFIXED", 0x10),
    ("LBS_OWNERDRAWVARIABLE", 0x20),
    ("LBS_HASSTRINGS", 0x40),
    ("LBS_USETABSTOPS", 0x80),
    ("LBS_NOINTEGRALHEIGHT", 0x100),
    ("LBS_MULTICOLUMN", 0x200),
    ("LBS_WANTKEYBOARDINPUT", 0x400),
    ("LBS_EXTENDEDSEL", 0x800),
    ("LBS_DISABLENOSCROLL", 0x1000),
    ("LBS_NODATA", 0x2000),
    ("LBS_NOSEL", 0x4000),
)
_DIALOG = _flags(
    ("DS_ABSALIGN", 0x1),
    ("DS_SYSMODAL", 0x2),
    ("DS_3DLOOK", 0x4),
    ("DS_FIXEDSYS", 0x8),
    ("DS_NOFAILCREATE", 0x10),
    ("DS_LOCALEDIT", 0x20),
    ("DS_SETFONT", 0x40),
    ("DS_MODALFRAME", 0x80),
    ("DS_NOIDLEMSG", 0x100),
    ("DS_SETFOREGROUND", 0x200),
    ("DS_CONTROL", 0x400),
    ("DS_CENTER", 0x800),
    ("DS_CENTERMOUSE", 0x1000),
    ("DS_CONTEXTHELP", 0x2000),
)
_LISTVIEW = (
    *_enum(3, ("LVS_ICON", 0), ("LVS_REPORT", 1), ("LVS_SMALLICON", 2), ("LVS_LIST", 3)),
    *_flags(
        ("LVS_SINGLESEL", 0x4),
        ("LVS_SHOWSELALWAYS", 0x8),
        ("LVS_SORTASCENDING", 0x10),
        ("LVS_SORTDESCENDING", 0x20),
        ("LVS_SHAREIMAGELISTS", 0x40),
        ("LVS_NOLABELWRAP", 0x80),
        ("LVS_AUTOARRANGE", 0x100),
        ("LVS_EDITLABELS", 0x200),
        ("LVS_OWNERDRAWFIXED", 0x400),
        ("LVS_ALIGNLEFT", 0x800),
        ("LVS_OWNERDATA", 0x1000),
        ("LVS_NOSCROLL", 0x2000),
        ("LVS_NOCOLUMNHEADER", 0x4000),
        ("LVS_NOSORTHEADER", 0x8000),
    ),
)
_TREEVIEW = _flags(
    ("TVS_HASBUTTONS", 0x1),
    ("TVS_HASLINES", 0x2),
    ("TVS_LINESATROOT", 0x4),
    ("TVS_EDITLABELS", 0x8),
    ("TVS_DISABLEDRAGDROP", 0x10),
    ("TVS_SHOWSELALWAYS", 0x20),
    ("TVS_RTLREADING", 0x40),
    ("TVS_NOTOOLTIPS", 0x80),
    ("TVS_CHECKBOXES", 0x100),
    ("TVS_TRACKSELECT", 0x200),
    ("TVS_SINGLEEXPAND", 0x400),
    ("TVS_INFOTIP", 0x800),
    ("TVS_FULLROWSELECT", 0x1000),
    ("TVS_NOSCROLL", 0x2000),
    ("TVS_NONEVENHEIGHT", 0x4000),
    ("TVS_NOHSCROLL", 0x8000),
)
_TAB = _flags(
    ("TCS_SCROLLOPPOSITE", 0x1),
    ("TCS_BOTTOM", 0x2),
    ("TCS_MULTISELECT", 0x4),
    ("TCS_FLATBUTTONS", 0x8),
    ("TCS_FORCEICONLEFT", 0x10),
    ("TCS_FORCELABELLEFT", 0x20),
    ("TCS_HOTTRACK", 0x40),
    ("TCS_VERTICAL", 0x80),
    ("TCS_BUTTONS", 0x100),
    ("TCS_MULTILINE", 0x200),
    ("TCS_FIXEDWIDTH", 0x400),
    ("TCS_RAGGEDRIGHT", 0x800),
    ("TCS_FOCUSONBUTTONDOWN", 0x1000),
    ("TCS_OWNERDRAWFIXED", 0x2000),
    ("TCS_TOOLTIPS", 0x4000),
    ("TCS_FOCUSNEVER", 0x8000),
)

_CLASS_STYLES: dict[str, tuple[StyleBit, ...]] = {
    "button": _BUTTON,
    "edit": _EDIT,
    "static": _STATIC,
    "combobox": _COMBOBOX,
    "listbox": _LISTBOX,
    "#32770": _DIALOG,
    "syslistview32": _LISTVIEW,
    "systreeview32": _TREEVIEW,
    "systabcontrol32": _TAB,
}

# WinForms wraps a system class and names its own after it: WindowsForms10.EDIT.app.0.141b42a_r8.
_WINFORMS = re.compile(r"^WindowsForms\d+\.([^.]+)\.app\.", re.IGNORECASE)


def class_style_table(class_name: str) -> tuple[StyleBit, ...]:
    """The class-specific style names (BS_*, ES_*, ...) for a window class, or none."""
    key = class_name.lower()
    wrapped = _WINFORMS.match(class_name)
    if wrapped is not None:
        key = wrapped.group(1).lower()
    return _CLASS_STYLES.get(key, ())


def _decode(value: int, table: Sequence[StyleBit]) -> tuple[list[tuple[str, int]], int]:
    value &= 0xFFFFFFFF
    claimed = 0
    found: list[tuple[str, int]] = []
    for bit in table:
        if bit.mask & claimed or value & bit.mask != bit.value:
            continue
        claimed |= bit.mask
        found.append((bit.name, bit.value))
    return found, value & ~claimed


def decode_style(style: int, class_name: str) -> tuple[list[tuple[str, int]], int]:
    """Names for a ``GWL_STYLE`` value, then the bits no name covers.

    Returns ``([(name, bits), ...], remainder)``: window styles first, then the styles of the
    window class (a button's ``BS_*``, an edit's ``ES_*``...). ``bits`` is what the name stands
    for, so an enumeration such as ``BS_AUTOCHECKBOX`` reports ``3``.
    """
    child = bool(style & WS_CHILD)
    table = (
        *_WS_COMMON,
        *(_WS_CONTROL if child else _WS_TOP_LEVEL),
        *class_style_table(class_name),
    )
    return _decode(style, table)


def decode_ex_style(ex_style: int) -> tuple[list[tuple[str, int]], int]:
    """Names for a ``GWL_EXSTYLE`` value, then the bits no name covers."""
    return _decode(ex_style, _WS_EX)


@dataclass(frozen=True)
class RawWindow:
    """What the system reports for one HWND; ``None`` marks a value that could not be read."""

    class_name: str = ""
    style: int = 0
    ex_style: int = 0
    text: str | None = None
    control_id: int | None = None
    process_id: int | None = None
    thread_id: int | None = None
    owner: int = 0
    parent: int = 0
    rect: tuple[int, int, int, int] | None = None  # left, top, right, bottom (screen)
    client_rect: tuple[int, int, int, int] | None = None  # left, top, right, bottom (client)
    visible: bool | None = None
    enabled: bool | None = None
    dpi: int | None = None


class NativeWindowBackend(Protocol):
    """Reads one window; ``None`` means the handle is not (or is no longer) a window."""

    def read(self, hwnd: int) -> RawWindow | None: ...


def _rect(box: tuple[int, int, int, int] | None) -> dict[str, int] | None:
    if box is None:
        return None
    left, top, right, bottom = box
    return Rect(left, top, max(0, right - left), max(0, bottom - top)).to_dict()


def _entries(found: list[tuple[str, int]]) -> list[dict[str, Any]]:
    return [{"name": name, "value": value} for name, value in found]


class NativeWindowReader:
    """Builds the ``NativeWindowInfo`` payload for a window handle."""

    def __init__(self, backend: NativeWindowBackend) -> None:
        self._backend = backend

    def read(self, hwnd: int) -> dict[str, Any] | None:
        """The window facts for ``hwnd``, or ``None`` for a zero or stale handle."""
        if not hwnd:
            return None
        raw = self._backend.read(hwnd)
        if raw is None:
            return None
        styles, unknown = decode_style(raw.style, raw.class_name)
        ex_styles, unknown_ex = decode_ex_style(raw.ex_style)
        child = bool(raw.style & WS_CHILD)
        result: dict[str, Any] = {
            "handle": hwnd,
            "className": raw.class_name,
            "styles": _entries(styles),
            "rawStyle": raw.style & 0xFFFFFFFF,
            "exStyles": _entries(ex_styles),
            "rawExStyle": raw.ex_style & 0xFFFFFFFF,
            "owner": raw.owner,
            "parent": raw.parent,
            "topmost": bool(raw.ex_style & WS_EX_TOPMOST),
            "enabled": raw.enabled if raw.enabled is not None else not raw.style & WS_DISABLED,
        }
        if unknown:
            result["unknownStyle"] = unknown
        if unknown_ex:
            result["unknownExStyle"] = unknown_ex
        # A password box hands out its secret to WM_GETTEXT; never read it back.
        hidden = bool(raw.style & ES_PASSWORD) and "edit" in raw.class_name.lower()
        if raw.text is not None and not hidden:
            result["text"] = raw.text[:MAX_TEXT] + ("…" if len(raw.text) > MAX_TEXT else "")
        if raw.control_id is not None and child:
            result["controlId"] = raw.control_id
        if raw.process_id is not None:
            result["processId"] = raw.process_id
        if raw.thread_id is not None:
            result["threadId"] = raw.thread_id
        if raw.visible is not None:
            result["visible"] = raw.visible
        if raw.dpi:
            result["dpi"] = raw.dpi
        for key, box in (("rect", raw.rect), ("clientRect", raw.client_rect)):
            shaped = _rect(box)
            if shaped is not None:
                result[key] = shaped
        return result


def default_reader() -> NativeWindowReader:
    """A reader backed by the real Win32 API (the import is deferred so tests need no desktop)."""
    from wintestkit.uia import win32

    return NativeWindowReader(win32.Win32WindowBackend())
